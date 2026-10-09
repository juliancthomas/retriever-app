from pydantic import BaseModel, ConfigDict, Field

class SearchQueryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description="Search query or compliance question.",
        examples=["What is the deadline for submitting a dispute claim?"],
    )
    
    # Standard top_k validation (must be at least 1, defaults to 10)
    # top-k validation checks if the correct label is present anywhere within the model's top k highest-probability predictions
    # Top-5 Validation: The model is considered correct if the true label is among its top 5 highest-probability predictions.
    top_k: int = Field(
        default=10, 
        ge=1, 
        description="The number of top results to return."
    )
    
    alpha: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight balance: 1.0 = pure vector search, 0.0 = pure keyword/BM25 search.",
        examples=[0.7],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "query": "What is the deadline for submitting a dispute claim?",
                    "top_k": 5,
                    "alpha": 0.7,
                }
            ]
        }
    )