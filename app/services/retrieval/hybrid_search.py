# Parallel execution: pgvector + tsvector
from collections import defaultdict
import logging
import asyncio
import uuid

from sentence_transformers import CrossEncoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.schemas.citation import Citation
from app.schemas.llm_prediction import LLMPrediction
from app.schemas.ragresponse import RAGResponse
from app.schemas.searchQueryRequest import SearchQueryRequest
from app.models.chunk import Chunk
from ollama import AsyncClient
import sqlalchemy as sa
from sqlalchemy.orm import joinedload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s"
)
logger = logging.getLogger("ingestion")

EMBEDDING_MODEL_NAME = "all-minilm:l6-v2"
BATCH_SIZE = 64

reranker_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device="cpu")

class HybridSearchService():
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
    def _reciprocal_rank_fusion(ranked_lists: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
        """
        Fuses multiple ranked lists using the Reciprocal Rank Fusion (RRF) algorithm.
        
        :param ranked_lists: List of lists, where each inner list contains chunks 
                            ordered by relevance (index 0 is rank 1).
        :param k: Smoothing constant (default: 60).
        :return: A list of tuples containing (chunk_id, rrf_score), sorted descending by score.
        """
        rrf_scores: dict[int, float] = defaultdict(float)
        
        # Iterate through each retrieval system's ranked list
        for rank_list in ranked_lists:
            for index, chunk_id in enumerate(rank_list):
                # Convert 0-based Python index to 1-based rank
                rank = index + 1  
                # Accumulate the RRF score
                rrf_scores[chunk_id] += 1.0 / (k + rank)
                
        # Sort chunks based on their accumulated RRF score in descending order
        return sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
        
    # Generate a dense embedding vector from the query text
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
        ts_query = sa.func.websearch_to_tsquery("english", self.query)
        rank = sa.func.ts_rank(Chunk.search_vector, ts_query).label("rank")

        return (
            select(Chunk, rank)
            .options(joinedload(Chunk.document))
            .where(Chunk.search_vector.op("@@")(ts_query))
            .order_by(rank.desc())
            .limit(60)
        )

    async def execute_search(self) -> RAGResponse:
        dense_results = []
        sparse_results = []
        
        dense_stmt = await self.dense_embed_query()
        sparse_stmt = self.sparse_search()

        async with self.session_factory() as session:
            await session.execute(sa.text("SET LOCAL hnsw.ef_search = 100"))

            dense_task = session.execute(dense_stmt)
            sparse_task = session.execute(sparse_stmt)
            dense_resp, sparse_resp = await asyncio.gather(dense_task, sparse_task)

            dense_results = dense_resp.scalars().all()
            sparse_results = [row[0] for row in sparse_resp.all()]

        chunks_by_id = {}
        
        dense_ids: list[int] = []
        for chunk in dense_results:
            chunks_by_id[chunk.id] = chunk
            dense_ids.append(chunk.id)

        sparse_ids: list[int] = []
        for chunk in sparse_results:
            chunks_by_id[chunk.id] = chunk
            sparse_ids.append(chunk.id)

        # 2. RRF Fusion
        fused_results = self._reciprocal_rank_fusion([dense_ids, sparse_ids], k=60)

        fused_results_dict: dict[int, float] = {}
        for result in fused_results:
            fused_results_dict[result[0]] = result[1]

        # 3. Slice candidate pool for the reranker (top 25)
        candidate_ids: list[int] = [chunk_id for chunk_id, _ in fused_results[:25]]
        candidate_chunks: list[Chunk] = [chunks_by_id[cid] for cid in candidate_ids]

        # 4. Prepare pairs for cross-encoder
        pairs: list[list[str]] = [[self.query, chunk.text] for chunk in candidate_chunks]

        # # 5. Compute scores
        scores = await asyncio.to_thread(reranker_model.predict, pairs) # type: ignore

        # # 6. Rank by cross-encoder score and slice final context (top 5)
        reranked = sorted(
            zip(candidate_chunks, scores),
            key=lambda item: item[1],
            reverse=True
        )
        final_context_chunks = [chunk for chunk, _ in reranked[:5]]

        context_blocks: list[str] = []
        for idx, chunk in enumerate(final_context_chunks):
            context_blocks.append(f"[{idx}] {chunk.text}")

        llm_context_str = "\n".join(context_blocks)

        SYSTEM_PROMPT = """
        You are a medical data assistant. Answer the user's question using the provided patient condition records.
        Return the answer and list the candidate indices [0, 1, 2...] that support your answer.
        """

        USER_PROMPT = f"""
        Query: {self.query}

        Records:
        {llm_context_str}
        """

        response = await self.client.chat( # type: ignore
            model='llama3.2', 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT}
            ], 
            format=LLMPrediction.model_json_schema(),
            options={"temperature": 0.0},
        )

        prediction = LLMPrediction.model_validate_json(response.message.content or '')

        citations: list[Citation] = []
        for idx in prediction.relevant_chunk_ids:
            if 0 <= idx < len(final_context_chunks):
                c = final_context_chunks[idx]
                citations.append(
                    Citation(
                        citation_chunk_id=uuid.UUID(int=c.id),  # True DB UUID
                        document_id=uuid.UUID(int=c.document_id),  # True Doc ID
                        document_name=c.document.filename,  # True filename
                        page_number=c.page,  # True CSV row number
                        quote_text=c.text,  # Verbatim serialized text
                        relevance_score=fused_results_dict.get(c.id),
                        metadata=c.metadata_ or {},  # Full CSV row dictionary
                    )
                )
    
        return RAGResponse(
            query=self.query,
            answer=prediction.answer,
            citations=citations,
        )
