from pydantic import BaseModel, Field


class LLMPrediction(BaseModel):
    answer: str = Field(
        description="Synthesized summary or response answering the user query."
    )
    relevant_chunk_ids: list[int] = Field(
        description="The candidate index numbers (0, 1, 2...) that support this answer."
    )