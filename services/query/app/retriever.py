"""
============================================================================
FILE: services/query/app/retriever.py
PURPOSE: Hybrid retrieval from Qdrant — dense ANN + sparse BM25 in parallel,
         merged using Reciprocal Rank Fusion (RRF).
ARCHITECTURE REF: §3.5 — Hybrid Retrieval with RRF
DEPENDENCIES: qdrant-client, asyncio
============================================================================

Hybrid Retrieval Strategy:
━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Dense ANN search: finds semantically similar chunks (embedding similarity)
   → Good for paraphrase matching and conceptual queries
   → "How many vacation days do I get?" finds "annual leave entitlement" chunks

2. Sparse BM25-like search: finds keyword-matching chunks (term overlap)
   → Good for exact term queries and proper nouns
   → "Article 23 of UAE Labour Law" finds chunks mentioning that exact term

3. RRF Fusion: merges the two ranked lists into a unified ranking
   → Formula: score(doc) = Σ 1/(k + rank_in_list)  where k=60
   → Gives documents a bonus if they appear in both lists
   → k=60 is the standard constant (dampens the effect of rank position)

4. Result: Top-20 unified candidates sent to reranker for final scoring

OPTIMIZATION: Uses Qdrant's native hybrid query API (prefetch + fusion).
This is a SINGLE Qdrant API call, not two separate calls.
Internally Qdrant executes both searches in parallel and applies RRF.
"""

import asyncio
import logging
from typing import Any, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.config import settings

logger = logging.getLogger(__name__)


async def hybrid_search(
    qdrant_client: AsyncQdrantClient,
    dense_vector: list[float],
    sparse_indices: list[int],
    sparse_values: list[float],
    top_k: int,
    document_id_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Execute hybrid search (dense + sparse) in Qdrant and return fused results.

    Uses Qdrant's native prefetch + query fusion API for efficiency.
    Both searches run in parallel inside Qdrant, then RRF is applied.

    Architecture Reference: §3.5 — Hybrid Retrieval with RRF

    Pipeline position: Step 3 in the RAG pipeline (after cache check fails).

    Args:
        qdrant_client: Async Qdrant client (initialized at service startup).
        dense_vector: Query dense embedding (1024-dim from embedding-svc).
        sparse_indices: Query sparse token indices (from embedding-svc).
        sparse_values: Query sparse token weights (from embedding-svc).
        top_k: Number of results to return (typically 20, sent to reranker).
        document_id_filter: Optional UUID to limit search to one document.

    Returns:
        List of dicts, each containing chunk data from Qdrant payload:
        {
            "point_id": str,
            "score": float,    # RRF-fused score
            "text": str,
            "filename": str,
            "section": str,
            "page_number": int,
            "document_id": str,
            "chunk_index": int,
        }
    """
    # Build optional payload filter for document-scoped search
    search_filter = None
    if document_id_filter:
        search_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id_filter),
                )
            ]
        )

    # Qdrant client 1.9.1 doesn't have AsyncQdrantClient.query_points.
    # We use search_batch to run dense and sparse searches in parallel, then apply RRF manually.
    try:
        batch_results = await qdrant_client.search_batch(
            collection_name=settings.qdrant_collection,
            requests=[
                # Dense ANN search
                models.SearchRequest(
                    vector=models.NamedVector(
                        name="dense",
                        vector=dense_vector,
                    ),
                    limit=settings.retrieval_dense_top_k,
                    filter=search_filter,
                    with_payload=True,
                ),
                # Sparse BM25-like search
                models.SearchRequest(
                    vector=models.NamedSparseVector(
                        name="sparse",
                        vector=models.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values,
                        ),
                    ),
                    limit=settings.retrieval_sparse_top_k,
                    filter=search_filter,
                    with_payload=True,
                ),
            ],
        )
    except Exception as exc:
        logger.error("Qdrant search_batch failed", extra={"error": str(exc)})
        raise

    dense_results = batch_results[0]
    sparse_results = batch_results[1]

    # Manual Reciprocal Rank Fusion (RRF)
    k = 60
    rrf_scores: dict[str, float] = {}
    fused_points: dict[str, Any] = {}

    for rank, point in enumerate(dense_results):
        point_id = str(point.id)
        rrf_scores[point_id] = rrf_scores.get(point_id, 0.0) + 1.0 / (k + rank + 1)
        fused_points[point_id] = point

    for rank, point in enumerate(sparse_results):
        point_id = str(point.id)
        rrf_scores[point_id] = rrf_scores.get(point_id, 0.0) + 1.0 / (k + rank + 1)
        fused_points[point_id] = point

    # Sort by descending RRF score and take top_k
    sorted_ids = sorted(rrf_scores.keys(), key=lambda pid: rrf_scores[pid], reverse=True)[:top_k]

    chunks = []
    for pid in sorted_ids:
        point = fused_points[pid]
        payload = point.payload or {}
        chunks.append({
            "point_id": pid,
            "score": rrf_scores[pid],
            "text": payload.get("text", ""),
            "filename": payload.get("filename", ""),
            "section": payload.get("section", ""),
            "page_number": payload.get("page_number", 1),
            "document_id": payload.get("document_id", ""),
            "chunk_index": payload.get("chunk_index", 0),
            "heading_path": payload.get("heading_path", ""),
        })

    logger.info("Hybrid search complete", extra={
        "results_count": len(chunks),
        "top_score": round(chunks[0]["score"], 4) if chunks else 0,
        "document_filter": document_id_filter,
    })

    return chunks
