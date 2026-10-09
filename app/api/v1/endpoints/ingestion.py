# Upload/parse documents
# The FastAPI endpoint validates that the path exists, creates a tracking record 
# (e.g., an IngestionJob in PostgreSQL with status PENDING), 
# and kicks off the processing in the background 
# (using FastAPI's BackgroundTasks for this practice project, or Celery / ARQ with Redis for production systems).

# The endpoint immediately returns a 202 Accepted response with a job_id

from fastapi import APIRouter

from app.core.database import AsyncSessionLocal
from app.services.ingestion.ingestion import Ingestion

router = APIRouter()

@router.get('/embedDocs')
async def embedDocs():
    pipeline = Ingestion(session_factory=AsyncSessionLocal)
    await pipeline.run_pipeline()