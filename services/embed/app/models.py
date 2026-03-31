"""
============================================================================
FILE: services/embed/app/models.py
PURPOSE: Pydantic request/response schemas for the embedding service API.
ARCHITECTURE REF: §3.3 — BGE-M3 Optimization for CPU
DEPENDENCIES: pydantic
============================================================================
"""

from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    """
    Request body for the POST /embed endpoint.

    Attributes:
        texts: List of text strings to embed. Can be a single item or a batch.
               Batch processing (multiple texts) is more efficient due to GPU/CPU
               vectorization, so clients should batch texts when possible.
        batch_size: Optional override for batch size (useful for very long texts
                   that might OOM at the default batch size of 32).
    """
    texts: list[str] = Field(
        ...,
        min_length=1,
        description="List of text strings to embed. Min 1, Max 128 items.",
        max_length=128,  # Prevent memory exhaustion from huge batches
    )
    batch_size: int | None = Field(
        default=None,
        ge=1,
        le=128,
        description="Override batch size for this request. Default: service-level setting.",
    )


class DenseVector(BaseModel):
    """Dense embedding vector from BGE-M3 (1024-dimensional float list)."""
    values: list[float] = Field(description="1024-dimensional dense vector")


class SparseVector(BaseModel):
    """
    Sparse embedding vector from BGE-M3's BM25-like sparse encoder.

    Sparse vectors store only non-zero elements as (index, value) pairs,
    making them memory-efficient for large vocabularies.
    These are used for the BM25-like sparse search in Qdrant.
    """
    indices: list[int] = Field(description="Non-zero vocabulary indices")
    values: list[float] = Field(description="Corresponding non-zero weights")


class EmbedResult(BaseModel):
    """Embedding result for a single text input."""
    dense: DenseVector = Field(description="Dense 1024-dim vector for ANN search")
    sparse: SparseVector = Field(description="Sparse vector for BM25-like search")


class EmbedResponse(BaseModel):
    """
    Response body from POST /embed.

    Returns one EmbedResult per input text, in the same order as the request.
    """
    results: list[EmbedResult] = Field(description="Embedding results, one per input text")
    model: str = Field(description="Model name used for embedding")
    processing_time_ms: float = Field(description="Total inference time in milliseconds")


class HealthResponse(BaseModel):
    """Standard health check response for all services."""
    status: str
    service: str
    version: str
    uptime_seconds: float
    model_loaded: bool
