"""
============================================================================
FILE: services/query/app/models.py
PURPOSE: Pydantic schemas for the query service API.
ARCHITECTURE REF: §4 — RAG Query Pipeline
============================================================================
"""

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request body for POST /query."""
    question: str = Field(..., min_length=1, max_length=2000, description="The user's question")
    # Optional: filter results to a specific document
    document_id_filter: str | None = Field(
        default=None,
        description="Optional: limit search to chunks from a specific document UUID"
    )


class SourceCitation(BaseModel):
    """A source citation attached to the response."""
    filename: str = Field(description="Original document filename")
    section: str = Field(description="Section heading where this chunk came from")
    page_number: int = Field(description="Page number in the original document")
    relevance_score: float = Field(description="Cross-encoder relevance score (0-1)")
    chunk_excerpt: str = Field(description="First 200 chars of the chunk text")


class QueryResponse(BaseModel):
    """
    Non-streaming response (for clients that don't support SSE).
    The streaming SSE response uses a different format (see sse_handler.py).
    """
    answer: str
    sources: list[SourceCitation]
    cache_hit: bool = Field(description="True if answer was returned from semantic cache")
    processing_time_ms: float


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float
    dependencies: dict[str, str]
