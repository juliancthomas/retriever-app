# app/api/v1/endpoints/search.py
from fastapi import APIRouter, Depends
from app.core.database import AsyncSessionLocal
from app.schemas.searchQueryRequest import SearchQueryRequest
from app.schemas.ragresponse import RAGResponse
from app.services.retrieval.hybrid_search import HybridSearchService

router = APIRouter()

# https://github.com/fastapi/fastapi/discussions/15839
# @router.api_route("/search", methods=["QUERY"])
@router.get('/search')
async def hybrid_search(
    payload: SearchQueryRequest = Depends() 
) -> RAGResponse:
    service = HybridSearchService(session_factory=AsyncSessionLocal, payload=payload)
    results = await service.execute_search()
    return results