# app/schemas/citation.py
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field

class Citation(BaseModel):
    """Represents a specific verified passage supporting an answer."""

    citation_chunk_id: UUID = Field(
        ...,
        description="Unique identifier of the exact database chunk referenced",
        examples=["a3b8e7c1-841f-4b0d-9b5e-4c7fa43ef210"],
    )
    document_id: UUID = Field(
        ...,
        description="Parent document identifier",
        examples=["d1c2b3a4-1111-2222-3333-444455556666"],
    )
    document_name: str = Field(
        ...,
        description="Filename or title of the original source document",
        examples=["compliance_policy_2026.pdf"],
    )
    page_number: int | None = Field(
        default=None,
        ge=1,
        description="1-based page number where the quote appears",
        examples=[4],
    )
    # section_header: str | None = Field(
    #     default=None,
    #     description="Preserved section header or title hierarchy context",
    #     examples=["Section 4.2: Billing Dispute Resolution"],
    # )
    quote_text: str = Field(
        ...,
        min_length=1,
        description="Exact quote or snippet excerpted from the chunk",
        examples=[
            "Claims filed exceeding the 90-day window must undergo secondary compliance review."
        ],
    )
    relevance_score: float | None = Field(
        default=None,
        description="Re-ranked fusion score (e.g., RRF or cross-encoder confidence)",
        examples=[0.894],
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional contextual metadata (table identifiers, offsets, etc.)",
    )


