# app/models/chunk.py
from typing import TYPE_CHECKING, Any, Optional
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document import Document

class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)  # Stores raw text block / CSV row
    story_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # LLM narrative summary
    extraction_quality: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Confidence score

    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )

    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(384), nullable=True
    )

    # Full-text search now indexes story_context (falling back to text if summary is null)
    search_vector: Mapped[Optional[str]] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(story_context, text))", 
            persisted=True
        ),
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_metadata", metadata_, postgresql_using="gin")
    )