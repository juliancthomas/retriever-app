import csv
import logging
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Iterator, Mapping
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


class Ingestion:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        batch_size: int = BATCH_SIZE,
        model_name: str = EMBEDDING_MODEL_NAME,
    ):
        self.session_factory = session_factory
        self.model_name = model_name
        self.client = AsyncClient()
        self.batch_size = batch_size

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
        """Converts key-value row pairs into structured natural text for the embedder."""
        items = [
            f"{str(k).strip()}: {str(v).strip()}"
            for k, v in row.items()
            if v is not None and str(v).strip()
        ]
        return " | ".join(items)

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
        raw_claims_dir = base_dir.parent / "data" / "sample_cases"
        files = [str(file_path) for file_path in raw_claims_dir.glob("*.csv")]
        logger.info("Found %d CSV files to process in %s", len(files), raw_claims_dir)
        return files

    async def _process_file(
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
        csv_files = self._gather_all_files()
        if not csv_files:
            logger.warning("No CSV files located. Exiting pipeline.")
            return

        pipeline_start = time.perf_counter()

        for file_path in csv_files:
            path_obj = Path(file_path)
            file_size_kb = path_obj.stat().st_size / 1024
            logger.info("Starting processing: %s (%.1f KB)", path_obj.name, file_size_kb)

            doc_start = time.perf_counter()
            doc_id = await self._insert_document(filename=file_path)
            logger.info("Created Document record with ID=%s", doc_id)

            total_chunks = 0
            async for chunk_batch in self._process_file(document_id=doc_id, file_path=file_path):
                db_start = time.perf_counter()
                await self._bulk_insert_chunks(chunks=chunk_batch)
                db_duration = time.perf_counter() - db_start
                total_chunks += len(chunk_batch)
                logger.info("Saved batch of %d chunks to DB in %.2fs", len(chunk_batch), db_duration)

            total_file_duration = time.perf_counter() - doc_start
            logger.info(
                "Completed %s: %d total chunks in %.2fs",
                path_obj.name,
                total_chunks,
                total_file_duration,
            )

        total_elapsed = time.perf_counter() - pipeline_start
        logger.info("Pipeline completed all files in %.2fs", total_elapsed)