"""
============================================================================
FILE: services/query/app/reranker_client.py
PURPOSE: HTTP client for the reranker microservice (reranker-svc).
         Takes retrieved chunks and re-scores them using cross-encoder.
ARCHITECTURE REF: §3.6 — Cross-Encoder Reranking
DEPENDENCIES: httpx, tenacity
============================================================================

Reranking in the RAG Pipeline:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
After hybrid retrieval returns top-20 candidates (fast, approximate),
cross-encoder reranking re-scores them using the actual query text + doc text
together as input. This catches cases where:
  - ANN search missed a highly relevant document (low embedding similarity)
  - The exact keywords of the question match critical document sections
  - Semantic embeddings over-generalised and retrieved off-topic content

Cross-encoder (BGE-Reranker-v2-m3) reads both query and document as one
input sequence. This is much more accurate but slower, so we only rerank
the top-20 candidates, not the full corpus.

Result: Top-5 (or configured top_k) chunks are sent to the LLM as context.

HTTP Contract with reranker-svc (POST /rerank):
  Request:  { "query": str, "documents": [{"id": str, "text": str}], "top_k": int }
  Response: { "results": [{"id": str, "score": float, "rank": int}] }
"""

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def rerank_chunks(
    client: httpx.AsyncClient,
    query: str,
    chunks: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """
    Call the reranker service to re-score and re-sort retrieved chunks.

    Sends the query + all chunk texts to BGE-Reranker-v2-m3 (cross-encoder),
    which scores each query-document pair jointly for much higher precision
    than embedding similarity alone.

    Architecture Reference: §3.6 — Cross-Encoder Reranking

    Pipeline position: Step 5 (after hybrid retrieval, before LLM generation).

    Tenacity retry: 3 attempts, exponential backoff (1s → 2s → 4s).
    Retries only on network errors (timeout, connection refused) not on
    HTTP 4xx/5xx (those indicate a bug, not a transient failure).

    Args:
        client: Shared httpx.AsyncClient (connection-pooled, injected at startup).
        query: The user's natural-language question.
        chunks: List of chunk dicts from hybrid_search() — each has at minimum:
                {"point_id": str, "text": str, ...}
        top_k: How many top-scoring chunks to keep (typically 5).

    Returns:
        List of up to top_k chunk dicts, re-ordered by reranker score descending.
        Each dict is the original chunk dict with two extra fields:
            "rerank_score": float  — cross-encoder score (higher = more relevant)
            "rerank_rank":  int    — final rank (1 = most relevant)

    Raises:
        httpx.HTTPStatusError: If the reranker service returns 4xx/5xx.
        httpx.TimeoutException: If the reranker does not respond within timeout.
    """
    if not chunks:
        logger.warning("rerank_chunks called with empty chunk list — returning empty")
        return []

    # Build request payload for reranker-svc
    # Each document needs a stable ID so we can merge scores back into chunks
    documents = [
        {"id": chunk["point_id"], "text": chunk["text"]}
        for chunk in chunks
    ]

    payload = {
        "query": query,
        "documents": documents,
        "top_k": top_k,
    }

    logger.debug(
        "Sending rerank request",
        extra={
            "doc_count": len(documents),
            "top_k": top_k,
            "query_len": len(query),
        },
    )

    response = await client.post(
        f"{settings.reranker_svc_url}/rerank",
        json=payload,
        timeout=settings.reranker_timeout_seconds,
    )
    response.raise_for_status()

    data = response.json()
    reranked = data.get("results", [])

    # Build a lookup map: point_id → original chunk dict
    # This allows us to reconstruct the full chunk objects with reranker scores
    chunk_by_id = {chunk["point_id"]: chunk for chunk in chunks}

    # Merge reranker scores back into the original chunk dicts
    # Only include chunks that appear in the reranker's top_k results
    result_chunks = []
    for ranked_item in reranked:
        doc_id = ranked_item["id"]
        original_chunk = chunk_by_id.get(doc_id)
        if original_chunk is None:
            # Should never happen — reranker echoes back IDs we sent
            logger.warning("Reranker returned unknown document ID", extra={"doc_id": doc_id})
            continue

        # Merge: original chunk dict + reranker-specific scores
        enriched_chunk = {
            **original_chunk,
            "rerank_score": ranked_item.get("score", 0.0),
            "rerank_rank": ranked_item.get("rank", 0),
        }
        result_chunks.append(enriched_chunk)

    logger.info(
        "Reranking complete",
        extra={
            "input_count": len(chunks),
            "output_count": len(result_chunks),
            "top_score": round(result_chunks[0]["rerank_score"], 4) if result_chunks else 0,
        },
    )

    return result_chunks
