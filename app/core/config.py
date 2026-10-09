# Pydantic Settings (.env, DB URL, model configs)

import os

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://rag_user:rag_password@localhost:5432/rag_db"
)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")