"""
============================================================================
FILE: services/rerank/app/models.py
PURPOSE: Pydantic schemas for the reranker service API.
ARCHITECTURE REF: §4.2 — Reranking
DEPENDENCIES: pydantic
============================================================================
"""

from pydantic import BaseModel, Field


class RerankPair(BaseModel):
    """A single (query, document) pair to score."""
    document_id: str = Field(description="Unique ID for this document/chunk")
    text: str = Field(description="Document chunk text to score against the query")
    # Pass-through metadata — returned unchanged in response for convenience
    metadata: dict = Field(default_factory=dict, description="Arbitrary metadata to pass through")


class RerankRequest(BaseModel):
    """
    Request body for POST /rerank.

    The cross-encoder scores each (query, document) pair independently —
    unlike bi-encoders (embedding models) which encode query and document separately.
    This gives higher quality relevance scores at the cost of more computation.

    Typical usage: send top-20 candidates from hybrid retrieval, get back top-5 sorted by score.
    """
    query: str = Field(..., description="The user's question text")
    documents: list[RerankPair] = Field(
        ...,
        min_length=1,
        max_length=50,   # Cross-encoders are slower; limit to 50 pairs per call
        description="Documents to score. Typically 20 candidates from hybrid retrieval.",
    )
    top_n: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Return only the top-N highest-scoring documents.",
    )


class RerankResult(BaseModel):
    """A single document with its relevance score."""
    document_id: str
    text: str
    score: float = Field(description="Cross-encoder relevance score (higher = more relevant)")
    rank: int = Field(description="1-based rank position (1 = most relevant)")
    metadata: dict


class RerankResponse(BaseModel):
    """Response from POST /rerank — sorted by relevance score descending."""
    results: list[RerankResult] = Field(description="Top-N documents sorted by relevance")
    query: str
    model: str
    processing_time_ms: float


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float
    model_loaded: bool
