# app/api/v1/endpoints/search.py
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from app.core.database import AsyncSessionLocal
from app.schemas.searchQueryRequest import SearchQueryRequest
from app.services.retrieval.hybrid_search import HybridSearchService
from fastapi.responses import StreamingResponse
from app.services.retrieval.hybrid_search import HybridSearchService

router = APIRouter()

async def event_generator(service: HybridSearchService) -> AsyncGenerator[str, None]:
    """Streams search status, references, and LLM tokens formatted for SSE."""
    try:
        # Assuming execute_search_stream() yields dicts or token strings
        async for chunk in service.execute_search_stream():
            if isinstance(chunk, dict): # type: ignore
                yield f"data: {json.dumps(chunk)}\n\n"
            else:
                yield f"data: {json.dumps({'token': chunk})}\n\n"
        
        # Standard SSE completion event
        yield "data: [DONE]\n\n"
    except Exception as exc:
        yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"


# https://github.com/fastapi/fastapi/discussions/15839
# @router.api_route("/search", methods=["QUERY"])
#  python -m fastapi dev main.py 
@router.get('/search')
async def hybrid_search(
    payload: SearchQueryRequest = Depends()
) -> StreamingResponse:
    service = HybridSearchService(session_factory=AsyncSessionLocal, payload=payload)
    
    return StreamingResponse(
        event_generator(service),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disables response buffering in Nginx reverse proxies
        },
    )