from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.ingestion import router as ingestion_router
from app.api.v1.endpoints.search import router as search_router

app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for dev
    allow_credentials=False,  # Note: cannot use allow_credentials=True when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get('/')
def main():
    return 'hello world'

app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")


