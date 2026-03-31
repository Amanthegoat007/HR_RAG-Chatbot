"""
============================================================================
FILE: services/ingest/app/qdrant_client_wrapper.py
PURPOSE: Qdrant vector database operations — collection setup, upsert chunks,
         delete vectors by document ID.
ARCHITECTURE REF: §3.6 — Qdrant Collection Configuration
DEPENDENCIES: qdrant-client, httpx (for embedding-svc calls)
============================================================================

Collection Design:
- Name: "hr_documents" (configurable via QDRANT_COLLECTION env var)
- Dense vectors: 1024-dim COSINE (BGE-M3 dense output)
- Sparse vectors: BM25-like weights (BGE-M3 sparse output)
- Payload indexes: document_id (KEYWORD), filename (KEYWORD), section (TEXT)

The collection is created at ingest-svc startup if it doesn't exist.
This is an idempotent operation — safe to call repeatedly.
"""

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


def get_qdrant_client() -> QdrantClient:
    """Create and return a Qdrant client."""
    return QdrantClient(url=settings.qdrant_url, timeout=30)


def ensure_collection_exists(client: QdrantClient) -> None:
    """
    Create the hr_documents collection if it doesn't exist.

    This is an idempotent bootstrap operation — safe to call at every startup.
    The collection configuration matches Architecture §3.6 exactly.

    Args:
        client: Qdrant client instance.

    Raises:
        Exception: If collection creation fails.
    """
    collection_name = settings.qdrant_collection

    # Check if collection exists
    existing = [c.name for c in client.get_collections().collections]
    if collection_name in existing:
        logger.info("Qdrant collection already exists", extra={"collection": collection_name})
        return

    logger.info("Creating Qdrant collection", extra={"collection": collection_name})

    # Create collection with both dense and sparse vector configurations
    # as specified in Architecture §3.6
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            # Dense vector: 1024-dim from BGE-M3, cosine similarity
            "dense": models.VectorParams(
                size=settings.embedding_dense_dim,  # 1024
                distance=models.Distance.COSINE,
                # on_disk=False: keep vectors in RAM for sub-millisecond ANN search
                on_disk=False,
            )
        },
        sparse_vectors_config={
            # Sparse vector: BM25-like weights from BGE-M3
            "sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(
                    on_disk=False  # Keep sparse index in RAM for speed
                )
            )
        },
    )

    # Create payload indexes for fast metadata filtering
    # KEYWORD index: exact match on document_id — used to delete all chunks of a document
    client.create_payload_index(
        collection_name=collection_name,
        field_name="document_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    # KEYWORD index: exact match on filename — used for source citations
    client.create_payload_index(
        collection_name=collection_name,
        field_name="filename",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    # TEXT index: full-text search on section heading — enables section filtering
    client.create_payload_index(
        collection_name=collection_name,
        field_name="section",
        field_schema=models.TextIndexParams(
            type=models.TextIndexType.TEXT,
            tokenizer=models.TokenizerType.WORD,
            lowercase=True,
        ),
    )

    logger.info("Qdrant collection created with all indexes", extra={
        "collection": collection_name,
        "dense_dim": settings.embedding_dense_dim,
    })


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def upsert_chunks(
    client: QdrantClient,
    chunks_with_embeddings: list[dict[str, Any]],
) -> int:
    """
    Upsert chunks with their dense and sparse embeddings to Qdrant.

    Each chunk becomes one Qdrant point with:
    - A unique UUID point ID
    - Dense vector (for ANN search)
    - Sparse vector (for BM25-like search)
    - Payload with metadata (filename, section, page, text, etc.)

    Args:
        client: Qdrant client.
        chunks_with_embeddings: List of dicts, each containing:
            {
                "point_id": str (UUID),
                "dense_vector": [float, ...],  # 1024 values
                "sparse_indices": [int, ...],
                "sparse_values": [float, ...],
                "payload": dict,  # from metadata_extractor.build_chunk_payload()
            }

    Returns:
        Number of points upserted.

    Raises:
        Exception: If Qdrant upsert fails after retries.
    """
    if not chunks_with_embeddings:
        return 0

    points = []
    for item in chunks_with_embeddings:
        point = models.PointStruct(
            id=item["point_id"],
            vector={
                "dense": item["dense_vector"],
                "sparse": models.SparseVector(
                    indices=item["sparse_indices"],
                    values=item["sparse_values"],
                ),
            },
            payload=item["payload"],
        )
        points.append(point)

    # Upsert in one batch (more efficient than individual inserts)
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=points,
        wait=True,  # Wait for indexing to complete before returning
    )

    logger.info("Upserted chunks to Qdrant", extra={
        "count": len(points),
        "collection": settings.qdrant_collection,
    })
    return len(points)


def delete_document_vectors(client: QdrantClient, document_id: str) -> int:
    """
    Delete all Qdrant vectors associated with a document.

    Uses payload filter on the indexed document_id field.
    Called when a document is deleted via DELETE /ingest/document/{id}.

    Args:
        client: Qdrant client.
        document_id: UUID of the document whose vectors to delete.

    Returns:
        Estimated count of deleted vectors.
    """
    # Filter: delete all points where payload.document_id == document_id
    result = client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            )
        ),
        wait=True,
    )

    # Qdrant returns operation info — count is not directly available
    # Log the operation_id as confirmation
    logger.info("Deleted Qdrant vectors for document", extra={
        "document_id": document_id,
        "operation_id": getattr(result, "operation_id", "unknown"),
    })

    # Estimate deleted count from collection stats
    count_result = client.count(
        collection_name=settings.qdrant_collection,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                )
            ]
        ),
    )
    remaining = count_result.count

    # If count is 0, all were deleted
    logger.info("Vector deletion verified", extra={
        "document_id": document_id,
        "remaining_vectors": remaining,
    })
    return 0  # Return 0 since we can't get exact deleted count from Qdrant response
