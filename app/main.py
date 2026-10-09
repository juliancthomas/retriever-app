from typing import Annotated

from fastapi import FastAPI, Query

from app.api.v1.endpoints.ingestion import router as ingestion_router
from app.api.v1.endpoints.search import router as search_router

app = FastAPI()

@app.get('/')
def main():
    return 'hello world'

app.include_router(ingestion_router)
app.include_router(search_router)


