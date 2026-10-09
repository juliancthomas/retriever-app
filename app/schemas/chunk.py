from typing import Any, Sequence
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ChunkBase(BaseModel):
    text: str
    page: int | None = None
    # Reads from either 'metadata_' (ORM attribute) or 'metadata' (JSON key)
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
        serialization_alias="metadata",
    )
    embedding: Sequence[float]


class ChunkCreate(ChunkBase):
    """Payload for inserting a new chunk into the database."""

    document_id: int


class ChunkUpdate(BaseModel):
    """Payload for partial updates (e.g. after generating embeddings)."""

    text: str | None = None
    page: int | None = None
    metadata_: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_", "metadata"),
        serialization_alias="metadata",
    )
    embedding: list[float] | None = None


class ChunkRead(ChunkBase):
    """Schema returned to API clients or downstream services."""

    id: int
    document_id: int
    search_vector: str | None = None

    model_config = ConfigDict(
        from_attributes=True,  # Enables ChunkRead.model_validate(orm_chunk)
        populate_by_name=True,
    )