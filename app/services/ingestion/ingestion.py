import asyncio
import csv
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Iterator, Mapping, TypedDict
from sentence_transformers import SentenceTransformer
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
NUM_WORKERS = 4


class SummaryAndConfidenceDictionary(TypedDict):
    summary: str
    confidence: float


class ProcessedItem(TypedDict):
    page: int
    raw_claim: str
    summary: str
    confidence: float
    metadata: dict[str, Any]


class Ingestion:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        batch_size: int = BATCH_SIZE,
        model_name: str = EMBEDDING_MODEL_NAME,
        use_narration: bool = False,
        num_workers: int = NUM_WORKERS,
    ):
        self.session_factory = session_factory
        self.model_name = model_name
        self.client = AsyncClient()
        self.batch_size = batch_size
        self.use_narration = use_narration
        self.num_workers = num_workers
        self.embed_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

    EXCLUDE_PATTERNS = re.compile(
        r"(id|uuid|_pk|_fk|hash|duplicate|created_at|updated_at|timestamp)",
        re.IGNORECASE
    )

    CLAIM_SPLIT_PATTERN = re.compile(
        r"=== RAW CLAIM RECORD ===\s*(.*?)\s*========================", re.DOTALL
    )

    PRIORITY_PATTERNS = [
        re.compile(r"(type|category|kind|class|specialty|role)", re.IGNORECASE),
        re.compile(r"(name|title|label|facility|organization|company)", re.IGNORECASE),
        re.compile(r"(city|state|region|county|address|location)", re.IGNORECASE),
        re.compile(r"(desc|summary|notes|diagnosis|condition)", re.IGNORECASE),
    ]

    def _stream_text_claims(self, file_path: str | Path) -> Iterator[str]:
        """Streams raw claim blocks chunk-by-chunk without loading full files into memory."""
        current_block: list[str] = []

        with open(file_path, mode="r", encoding="utf-8") as f:
            for line in f:
                if "=== RAW CLAIM RECORD ===" in line:
                    if current_block:
                        claim_text = "".join(current_block).strip()
                        if claim_text:
                            yield claim_text
                    current_block = [line]
                else:
                    current_block.append(line)

            if current_block:
                claim_text = "".join(current_block).strip()
                if claim_text:
                    yield claim_text

    def _extract_claim_metadata(self, raw_claim: str, filename: str, confidence: float) -> dict[str, Any]:
        """Extract basic structural metadata from raw claim text."""
        return {
            "source_file": filename,
            "raw_length": len(raw_claim),
            "confidence": confidence,
        }

    async def _process_large_text_file(
        self, file_path: str | Path, document_id: int
    ) -> AsyncGenerator[list[ChunkCreate], None]:
        path_obj = Path(file_path)

        # Queues bounded at 100 items for backpressure
        raw_queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue(maxsize=100)
        processed_queue: asyncio.Queue[ProcessedItem | None] = asyncio.Queue(maxsize=100)

        # 1. Producer task: Stream claims from disk into raw_queue
        async def _producer():
            # Asynchronous producer without thread-blocking calls
            for idx, claim_text in enumerate(self._stream_text_claims(path_obj)):
                await raw_queue.put((idx, claim_text))

            for _ in range(self.num_workers):
                await raw_queue.put(None)

        # 2. Stage 1 Workers: Executed in parallel across OLLAMA_NUM_PARALLEL slots
        async def _worker():
            while True:
                item = await raw_queue.get()
                if item is None:
                    raw_queue.task_done()
                    break

                idx, raw_claim = item
                try:
                    # Summarize & score via llama3.2:3b
                    res = await self._summarize_and_score_claim_chunk(raw_claim)
                    meta = self._extract_claim_metadata(raw_claim, path_obj.name, res["confidence"])

                    processed_item: ProcessedItem = {
                        "page": idx,
                        "raw_claim": raw_claim,
                        "summary": res["summary"],
                        "confidence": res["confidence"],
                        "metadata": meta,
                    }
                    await processed_queue.put(processed_item)
                except Exception as err:
                    logger.error("Error generating summary for claim %d: %s", idx, err)
                finally:
                    raw_queue.task_done()

        # Launch producer and summarization workers
        producer_task = asyncio.create_task(_producer())
        worker_tasks = [asyncio.create_task(_worker()) for _ in range(self.num_workers)]

        # Signal completed summarizations
        async def _monitor_workers():
            await asyncio.gather(*worker_tasks)
            await processed_queue.put(None)

        monitor_task = asyncio.create_task(_monitor_workers())

        # 3. Stage 2 (Vectorized Batch Embedding): Accumulate items and send a single bulk array to /api/embed
        async def _encode_processed_batch(batch: list[ProcessedItem]) -> list[ChunkCreate]:
            summaries = [item["summary"] for item in batch]
            
            vectors = self.embed_model.encode( # type: ignore
                summaries,
                show_progress_bar=False,
                convert_to_numpy=True
            ).tolist()

            return [
                ChunkCreate(
                    document_id=document_id,
                    page=item["page"],
                    text=item["raw_claim"],
                    story_context=item["summary"],
                    extraction_quality=item["confidence"],
                    embedding=vec,
                    metadata_=item["metadata"],
                )
                for item, vec in zip(batch, vectors)
            ]

        batch_buffer: list[ProcessedItem] = []

        while True:
            item = await processed_queue.get()
            if item is None:
                processed_queue.task_done()
                break

            batch_buffer.append(item)
            processed_queue.task_done()

            if len(batch_buffer) >= self.batch_size:
                chunks = await _encode_processed_batch(batch_buffer)
                yield chunks
                batch_buffer = []

        if batch_buffer:
            chunks = await _encode_processed_batch(batch_buffer)
            yield chunks

        await producer_task
        await monitor_task

    async def _summarize_and_score_claim_chunk(self, raw_claim_text: str) -> SummaryAndConfidenceDictionary:
        """Generates a narrative summary and assigns an extraction confidence score."""
        prompt = (
            "Summarize the claim in 1 short sentence and evaluate data completeness.\n"
            "Required fields: Name, Dates, ICD-10, CPT, Charges.\n"
            "Respond ONLY in JSON with keys 'summary' (string) and 'confidence' (float 0.0 to 1.0).\n\n"
            f"Claim:\n{raw_claim_text}"
        )

        try:
            response = await self.client.generate(
                model="llama3.2:3b",
                prompt=prompt,
                format="json",
                keep_alive="60m",
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
        if not claims:
            claims = [c.strip() for c in text_content.split("\n\n") if c.strip()]
        return claims

    def _get_column_priority(self, col_name: str) -> int:
        """Assigns an integer priority to column names based on heuristic match."""
        for rank, pattern in enumerate(self.PRIORITY_PATTERNS):
            if pattern.search(col_name):
                return rank
        return len(self.PRIORITY_PATTERNS)

    async def _insert_document(self, filename: str) -> int:
        """Creates the parent document record and returns its ID."""
        async with self.session_factory() as session:
            statement = insert(Document).values(filename=filename).returning(Document.id)
            res = await session.execute(statement)
            doc_id = res.scalar_one()
            await session.commit()
            return doc_id

    async def _bulk_insert_chunks(self, chunks: list[ChunkCreate]) -> None:
        """Bulk-inserts accumulated ChunkCreate objects into PostgreSQL in batches."""
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

            if self.EXCLUDE_PATTERNS.fullmatch(k_clean):
                continue

            entry = f"{k_clean}: {v_str}"
            priority = self._get_column_priority(k_clean)

            if priority < len(self.PRIORITY_PATTERNS):
                priority_items.append((priority, entry))
            else:
                regular_items.append(entry)

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

        target_dirs = [
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
                keep_alive="60m",
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

        # Limit total parallel processing tasks across files
        semaphore = asyncio.Semaphore(self.num_workers)

        async def _process_single_file(file_path: str):
            async with semaphore:
                path_obj = Path(file_path)
                file_size_kb = path_obj.stat().st_size / 1024
                logger.info("Starting processing: %s (%.1f KB)", path_obj.name, file_size_kb)

                doc_id = await self._insert_document(filename=file_path)

                if path_obj.suffix.lower() == ".txt":
                    chunk_generator = self._process_large_text_file(file_path=file_path, document_id=doc_id)
                else:
                    chunk_generator = self._process_csv_file(file_path=file_path, document_id=doc_id)

                async for chunk_batch in chunk_generator:
                    await self._bulk_insert_chunks(chunks=chunk_batch)

        # Fire all file processing tasks concurrently
        await asyncio.gather(*[_process_single_file(f) for f in all_files])

        total_elapsed = time.perf_counter() - pipeline_start
        logger.info("Pipeline completed all files in %.2fs", total_elapsed)