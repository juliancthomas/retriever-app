import asyncio
import csv
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Iterator, Mapping, TypedDict
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ollama import AsyncClient

from app.models.chunk import Chunk
from app.models.document import Document
from app.schemas.chunk import ChunkCreate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s"
)
logger = logging.getLogger("ingestion")

EMBEDDING_MODEL_NAME = "all-minilm:l6-v2"
BATCH_SIZE = 64


class SummaryAndConfidenceDictionary(TypedDict):
    summary: str
    confidence: float

class Ingestion:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        batch_size: int = BATCH_SIZE,
        model_name: str = EMBEDDING_MODEL_NAME,
        use_narration: bool = False,
    ):
        self.session_factory = session_factory
        self.model_name = model_name
        self.client = AsyncClient()
        self.batch_size = batch_size
        self.use_narration = use_narration

    EXCLUDE_PATTERNS = re.compile(
        r"(id|uuid|_pk|_fk|hash|duplicate|created_at|updated_at|timestamp)",
        re.IGNORECASE
    )

    CLAIM_SPLIT_PATTERN = re.compile(
        r"=== RAW CLAIM RECORD ===\s*(.*?)\s*========================", re.DOTALL
    )

    # Patterns for fields that carry primary semantic weight
    PRIORITY_PATTERNS = [
        # Tier 1: Categories and classifications (e.g., Location_Type, Category, Specialty)
        re.compile(r"(type|category|kind|class|specialty|role)", re.IGNORECASE),
        # Tier 2: Entity names and titles (e.g., Facility_Name, Title, Provider)
        re.compile(r"(name|title|label|facility|organization|company)", re.IGNORECASE),
        # Tier 3: Geographical locations (e.g., City, State, Region)
        re.compile(r"(city|state|region|county|address|location)", re.IGNORECASE),
        # Tier 4: Descriptions and summaries
        re.compile(r"(desc|summary|notes|diagnosis|condition)", re.IGNORECASE),
    ]



    async def _process_text_file(
        self, file_path: str | Path, document_id: int
    ) -> AsyncGenerator[list[ChunkCreate], None]:
        path_obj = Path(file_path)
        text_content = path_obj.read_text(encoding="utf-8")
        raw_claims = self._split_text_into_claims(text_content)

        batch_indices: list[int] = []
        batch_texts: list[str] = []
        batch_metadata: list[dict[str, Any]] = []

        # Limit concurrent LLM calls to 2 or 4 instead of firing 64 at once
        semaphore = asyncio.Semaphore(4)

        async def _summarize_with_limit(claim_text: str):
            async with semaphore:
                return await self._summarize_and_score_claim_chunk(claim_text)

        async def _encode_batch() -> list[ChunkCreate]:
            # Generate mini-LM summaries and confidence scores in parallel for the current batch
            summary_results = await asyncio.gather(
                *(_summarize_with_limit(claim_text) for claim_text in batch_texts)
            )

            # Update metadata items in the batch with their corresponding confidence scores
            for meta, res in zip(batch_metadata, summary_results):
                meta["extraction_confidence"] = res["confidence"]

            # Prepend the narrative summary to the raw text for semantic embedding
            texts_to_embed = [
                f"Summary: {res['summary']}\n\nRaw Record:\n{raw}"
                for res, raw in zip(summary_results, batch_texts)
            ]

            # Generate vector embeddings
            response = await self.client.embed(
                model=self.model_name,
                input=texts_to_embed,
                truncate=True,
                keep_alive="60m",  # Keeps embedding model pinned in VRAM
            )

            return [
                ChunkCreate(
                    document_id=document_id,
                    page=idx,
                    text=txt,
                    embedding=vec,
                    metadata_=meta,
                )
                for idx, txt, vec, meta in zip(
                    batch_indices, texts_to_embed, response.embeddings, batch_metadata
                )
            ]

        for idx, raw_claim in enumerate(raw_claims):
            # Extract primary key-value fields directly from the raw record string
            claim_id_match = re.search(r"CLAIM_ID:\s*(\S+)", raw_claim)
            encounter_id_match = re.search(r"ENCOUNTER_ID:\s*(\S+)", raw_claim)
            payer_match = re.search(r"PAYER:\s*(.+)", raw_claim)
            patient_match = re.search(r"PATIENT_NAME:\s*(.+)", raw_claim)
            patient_raw = patient_match.group(1).strip() if patient_match else None
            last_name, first_name = None, None

            if patient_raw and "," in patient_raw:
                parts = [p.strip() for p in patient_raw.split(",", 1)]
                last_name, first_name = parts[0], parts[1]

            # Build metadata payload per record (extraction_confidence populated during batch encoding)
            meta = {
                "claim_id": claim_id_match.group(1) if claim_id_match else None,
                "encounter_id": encounter_id_match.group(1) if encounter_id_match else None,
                "payer": payer_match.group(1).strip() if payer_match else None,
                "patient_name": patient_raw,
                "patient_first_name": first_name,
                "patient_last_name": last_name,
                "file_type": "txt",
                "source_file": path_obj.name,
                "extraction_confidence": None,
            }

            batch_indices.append(idx)
            batch_texts.append(raw_claim)
            batch_metadata.append(meta)

            if len(batch_texts) >= self.batch_size:
                yield await _encode_batch()
                batch_indices, batch_texts, batch_metadata = [], [], []

        if batch_texts:
            yield await _encode_batch()

    async def _summarize_and_score_claim_chunk(self, raw_claim_text: str) -> SummaryAndConfidenceDictionary:
        """Generates a narrative summary and assigns an extraction confidence score."""
        prompt = (
            "You are an expert medical billing AI evaluator.\n"
            "1. Summarize the key claim details into a single concise sentence.\n"
            "2. Check if the following required fields exist in the raw record: Name, Dates, ICD-10, CPT, Charges.\n"
            "3. Set 'confidence' to 1.0 if all exist cleanly, or reduce confidence proportionally for each missing or ambiguous entity.\n\n"
            "Respond strictly in JSON format with keys: 'summary' and 'confidence'.\n\n"
            f"Claim Text:\n{raw_claim_text}"
        )

        try:
            response = await self.client.generate(
                model="llama3.2:3b",
                prompt=prompt,
                format="json",  # Force Ollama to output structured JSON
                keep_alive="60m",  # Keeps model pinned in VRAM
                options={
                    "temperature": 0.1,
                    "num_predict": 128,
                },
            )
            data: SummaryAndConfidenceDictionary = json.loads(response.get("response", "{}"))
            return {
                "summary": data.get("summary", raw_claim_text),
                "confidence": float(data.get("confidence", 1.0)),
            }
        except Exception as e:
            logger.warning("LLM summarization/scoring failed (%s); defaulting to fallback.", e)
            return {"summary": "Unsummarized claim record.", "confidence": 0.0}

    def _split_text_into_claims(self, text_content: str) -> list[str]:
        """Extracts raw claim text blocks delimited by the record header/footer."""
        claims = self.CLAIM_SPLIT_PATTERN.findall(text_content)
        # Fallback if delimiter isn't present: split by double newlines or whole text
        if not claims:
            claims = [c.strip() for c in text_content.split("\n\n") if c.strip()]
        return claims

    def _get_column_priority(self, col_name: str) -> int:
        """Assigns an integer priority to column names based on heuristic match."""
        for rank, pattern in enumerate(self.PRIORITY_PATTERNS):
            if pattern.search(col_name):
                return rank
        return len(self.PRIORITY_PATTERNS)  # All other custom columns come after

    async def _insert_document(self, filename: str) -> int:
        """Creates the parent document record and returns its ID."""
        async with self.session_factory() as session:
            statement = insert(Document).values(filename=filename).returning(Document.id)
            res = await session.execute(statement)
            doc_id = res.scalar_one()
            await session.commit()
            return doc_id

    async def _bulk_insert_chunks(self, chunks: list[ChunkCreate]) -> None:
        if not chunks:
            return

        payload = [chunk.model_dump(by_alias=True) for chunk in chunks]

        async with self.session_factory() as session:
            statement = insert(Chunk).values(payload)
            await session.execute(statement)
            await session.commit()

    def _serialize_row(self, row: Mapping[str, Any]) -> str:
        """
        Dynamically prioritizes high-signal semantic columns to the front
        and strips noisy metadata IDs.
        """
        priority_items: list[tuple[int, str]] = []
        regular_items: list[str] = []

        for k, v in row.items():
            if v is None:
                continue
            v_str = str(v).strip()
            if not v_str:
                continue

            k_clean = str(k).strip()

            # 1. Skip pure IDs, hashes, and binary flags
            if self.EXCLUDE_PATTERNS.fullmatch(k_clean):
                continue

            entry = f"{k_clean}: {v_str}"
            priority = self._get_column_priority(k_clean)

            if priority < len(self.PRIORITY_PATTERNS):
                priority_items.append((priority, entry))
            else:
                regular_items.append(entry)

        # Sort semantic fields by their detected priority rank
        priority_items.sort(key=lambda x: x[0])
        ordered_entries = [entry for _, entry in priority_items] + regular_items

        return " | ".join(ordered_entries)

    def _stream_csv_rows(
        self, file_path: str | Path
    ) -> Iterator[tuple[int, str, dict[str, Any]]]:
        """Streams a CSV file row by row to prevent loading massive files into memory."""
        with open(file_path, mode="r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                serialized = self._serialize_row(row)
                if serialized:
                    yield idx, serialized, dict(row)

    def _gather_all_files(self) -> list[str]:
        base_dir = Path(__file__).resolve().parent.parent.parent
        data_dir = base_dir.parent / "data"

        # Folders to inspect for input files
        target_dirs = [
            # data_dir / "sample_cases",
            data_dir / "sample_claims",
        ]

        files: list[str] = []
        for directory in target_dirs:
            if not directory.exists():
                logger.warning("Directory does not exist: %s", directory)
                continue
                
            for file_path in directory.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in [".csv", ".txt"]:
                    files.append(str(file_path))

        logger.info("Found %d files to process across target directories.", len(files))
        return files

    async def _process_csv_file(
        self, file_path: str | Path, document_id: int
    ) -> AsyncGenerator[list[ChunkCreate], None]:
        batch_indices: list[int] = []
        batch_texts: list[str] = []
        batch_metadata: list[dict[str, Any]] = []
        total_rows = 0

        async def _encode_batch() -> list[ChunkCreate]:
            start_embed = time.perf_counter()
            response = await self.client.embed(
                model=self.model_name,
                input=batch_texts,
                truncate=True,
                keep_alive="60m",  # Keeps embedding model pinned in VRAM
            )
            embed_duration = time.perf_counter() - start_embed
            logger.info(
                "Embedded %d rows in %.2fs (%.1f rows/sec)",
                len(batch_texts),
                embed_duration,
                len(batch_texts) / embed_duration if embed_duration > 0 else 0,
            )

            vectors = response.embeddings
            return [
                ChunkCreate(
                    document_id=document_id,
                    page=idx,
                    text=txt,
                    embedding=vec,
                    metadata_=meta,
                )
                for idx, txt, vec, meta in zip(
                    batch_indices, batch_texts, vectors, batch_metadata
                )
            ]

        for row_idx, text, raw_row in self._stream_csv_rows(file_path):
            total_rows += 1
            batch_indices.append(row_idx)
            batch_texts.append(text)
            batch_metadata.append(raw_row)

            if len(batch_texts) >= self.batch_size:
                yield await _encode_batch()
                batch_indices, batch_texts, batch_metadata = [], [], []

        if batch_texts:
            yield await _encode_batch()

        logger.info("Finished streaming %d total rows from %s", total_rows, Path(file_path).name)

    async def run_pipeline(self):
        all_files = self._gather_all_files()
        if not all_files:
            logger.warning("No CSV or TXT files located. Exiting pipeline.")
            return

        pipeline_start = time.perf_counter()

        for file_path in all_files:
            path_obj = Path(file_path)
            file_size_kb = path_obj.stat().st_size / 1024
            logger.info("Starting processing: %s (%.1f KB)", path_obj.name, file_size_kb)

            doc_id = await self._insert_document(filename=file_path)
            logger.info("Created Document record with ID=%s", doc_id)

            if path_obj.suffix.lower() == ".txt":
                chunk_generator = self._process_text_file(file_path=file_path, document_id=doc_id)
            else:
                chunk_generator = self._process_csv_file(file_path=file_path, document_id=doc_id)

            total_chunks = 0
            async for chunk_batch in chunk_generator:
                await self._bulk_insert_chunks(chunks=chunk_batch)
                total_chunks += len(chunk_batch)

            total_elapsed = time.perf_counter() - pipeline_start

        total_elapsed = time.perf_counter() - pipeline_start
        logger.info("Pipeline completed all files in %.2fs", total_elapsed)