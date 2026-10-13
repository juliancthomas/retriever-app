# app/services/retrieval/hybrid_search.py
from collections import defaultdict
import logging
import asyncio
import uuid
from typing import AsyncGenerator, Any
import math

from sentence_transformers import CrossEncoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.schemas.citation import Citation
from app.schemas.searchQueryRequest import SearchQueryRequest
from app.models.chunk import Chunk
from ollama import AsyncClient
import sqlalchemy as sa
from sqlalchemy.orm import joinedload



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s"
)
logging.getLogger("hybrid_search")

EMBEDDING_MODEL_NAME = "all-minilm:l6-v2"
BATCH_SIZE = 64

reranker_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device="cpu")

def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

class HybridSearchService:
    def __init__(
        self,
        payload: SearchQueryRequest,
        session_factory: async_sessionmaker[AsyncSession],
        batch_size: int = BATCH_SIZE,
        model_name: str = EMBEDDING_MODEL_NAME,
    ):
        self.session_factory = session_factory
        self.model_name = model_name
        self.client = AsyncClient()
        self.batch_size = batch_size
        self.query = payload.query
        self.top_k = payload.top_k
        self.alpha = payload.alpha

    @staticmethod
    def _reciprocal_rank_fusion(
        ranked_lists: list[list[int]],
        weights: list[float] | None = None, 
        k: int = 60
    ) -> list[tuple[int, float]]:
        rrf_scores: dict[int, float] = defaultdict(float)
        if weights is None:
            weights = [1.0] * len(ranked_lists)

        for rank_list, weight in zip(ranked_lists, weights):
            for index, chunk_id in enumerate(rank_list):
                rank = index + 1
                rrf_scores[chunk_id] += weight * (1.0 / (k + rank))
        return sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)

    async def dense_embed_query(self):
        response = await self.client.embed(
            model=self.model_name,
            input=[self.query],
            truncate=True,
        )
        return (
            select(Chunk)
            .options(joinedload(Chunk.document))
            .order_by(Chunk.embedding.cosine_distance(response.embeddings[0]))
            .limit(60)
        )

    def sparse_search(self):
        ts_query = sa.func.websearch_to_tsquery("simple", self.query)
        rank = sa.func.ts_rank(Chunk.search_vector, ts_query).label("rank")

        return (
            select(Chunk, rank)
            .options(joinedload(Chunk.document))
            .where(Chunk.search_vector.op("@@")(ts_query))
            .order_by(rank.desc())
            .limit(60)
        )

    async def _retrieve_and_rerank(self) -> tuple[list[Chunk], dict[int, float]]:
        """Executes hybrid retrieval, RRF, and cross-encoder reranking."""
        dense_stmt = await self.dense_embed_query()
        sparse_stmt = self.sparse_search()

        async with self.session_factory() as session:
            await session.execute(sa.text("SET LOCAL hnsw.ef_search = 100"))

            dense_task = session.execute(dense_stmt)
            sparse_task = session.execute(sparse_stmt)
            dense_resp, sparse_resp = await asyncio.gather(dense_task, sparse_task)

            dense_results = dense_resp.scalars().all()
            sparse_results = [row[0] for row in sparse_resp.all()]

        chunks_by_id: dict[int, Chunk] = {}
        dense_ids: list[int] = []
        for chunk in dense_results:
            chunks_by_id[chunk.id] = chunk
            dense_ids.append(chunk.id)

        sparse_ids: list[int] = []
        for chunk in sparse_results:
            chunks_by_id[chunk.id] = chunk
            sparse_ids.append(chunk.id)

        fused_results = self._reciprocal_rank_fusion([dense_ids, sparse_ids], weights=[1.0 - self.alpha, self.alpha], k=60)

        # Candidate pool for reranker (top 25)
        candidate_ids = [cid for cid, _ in fused_results[:25]]
        candidate_chunks = [chunks_by_id[cid] for cid in candidate_ids]

        pairs = [[self.query, chunk.text] for chunk in candidate_chunks]
        scores = await asyncio.to_thread(reranker_model.predict, pairs) # type: ignore

        reranked = sorted(
            zip(candidate_chunks, scores),
            key=lambda item: item[1],
            reverse=True
        )

        final_context_chunks = [chunk for chunk, _ in reranked[:self.top_k]]

        # Map top-k chunks to their reranker scores
        rerank_score_map = {
            chunk.id: float(score)
            for chunk, score in reranked[:self.top_k]
        }

        return final_context_chunks, rerank_score_map

    async def execute_search_stream(self) -> AsyncGenerator[dict[str, Any], None]:
        """
        Retrieves context, yields citations event first, then streams LLM tokens.
        """
        final_context_chunks, rerank_score_map = await self._retrieve_and_rerank()

        # Build citations for the top candidate chunks
        citations = [
            Citation(
                citation_chunk_id=uuid.uuid5(uuid.NAMESPACE_DNS, str(c.id)),
                document_id=uuid.uuid5(uuid.NAMESPACE_DNS, str(c.document_id)),
                document_name=c.document.filename,
                page_number=(c.page + 1) if c.page is not None else None,
                quote_text=c.text,
                relevance_score=rerank_score_map.get(c.id),
                metadata=c.metadata_ or {},
            ).model_dump(mode="json")
            for c in final_context_chunks
        ]

        # 1. Yield citations as the first SSE payload
        yield {
            "type": "citations",
            "data": citations,
        }

        # 2. Format LLM prompt
        context_blocks = [f"[{idx}] {chunk.text}" for idx, chunk in enumerate(final_context_chunks)]
        llm_context_str = "\n".join(context_blocks)

        system_prompt = (
            "You are an expert medical data retrieval assistant. "
            "Answer the user's question accurately based only on the provided records. "
            "Cite the record index inline (e.g., [0], [1]) whenever referring to specific information."
        )
        user_prompt = f"Query: {self.query}\n\nRecords:\n{llm_context_str}"

        # 3. Stream LLM tokens directly via Ollama
        stream = await self.client.chat( # type: ignore
            model="llama3.2:3b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
            options={"temperature": 0.0},
        )

        async for chunk in stream:
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield {
                    "type": "token",
                    "data": content,
                }