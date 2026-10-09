from pydantic import BaseModel, Field

from .citation import Citation


class RAGResponse(BaseModel):
    """Final API response returning the synthesized answer with backing citations."""

    query: str = Field(
        ...,
        min_length=1,
        description="Search query or compliance question.",
        examples=["What is the deadline for submitting a dispute claim?"],
    )
    answer: str = Field(
        ...,
        description="Generated synthesized answer incorporating the citations",
        examples=[
            "Dispute claims must be submitted within 90 days. Claims filed after this window require a secondary compliance audit."
        ],
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="List of verified source citations backing the synthesized text",
    )