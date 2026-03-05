"""
============================================================================
FILE: services/query/app/embedding_client.py
PURPOSE: HTTP client to call embedding-svc for query embedding.
         Used by the RAG pipeline to embed the user's question.
ARCHITECTURE REF: §4 — RAG Query Pipeline (Step 1: Embed query)
DEPENDENCIES: httpx
============================================================================
"""

import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def embed_query(
    http_client: httpx.AsyncClient,
    question: str,
) -> dict[str, Any]:
    """
    Embed a single query text using the embedding service.

    Returns both dense and sparse vectors for use in hybrid search.
    The dense vector is also used for semantic cache lookup.

    Args:
        http_client: Shared httpx.AsyncClient (connection pooling).
        question: The user's question text.

    Returns:
        Dict with {"dense": {"values": [...]}, "sparse": {"indices": [...], "values": [...]}}

    Raises:
        httpx.HTTPStatusError: If embedding service returns error.
        httpx.ConnectError: If embedding service is unreachable (triggers retry).
    """
    response = await http_client.post(
        f"{settings.embedding_svc_url}/embed",
        json={"texts": [question]},
        timeout=30.0,
    )
    response.raise_for_status()

    data = response.json()
    # Single text → single result
    result = data["results"][0]

    logger.debug("Query embedded", extra={
        "dense_dim": len(result["dense"]["values"]),
        "sparse_terms": len(result["sparse"]["indices"]),
    })

    return (
        result["dense"]["values"],
        result["sparse"]["indices"],
        result["sparse"]["values"],
    )
