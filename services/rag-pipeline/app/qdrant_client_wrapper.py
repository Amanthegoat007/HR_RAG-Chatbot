"""
============================================================================
FILE: services/rag-pipeline/app/qdrant_client_wrapper.py
PURPOSE: Async Qdrant client factory for the RAG pipeline.
         Uses AsyncQdrantClient for non-blocking vector search.
============================================================================
"""

import logging
from qdrant_client import AsyncQdrantClient
from app.config import settings

logger = logging.getLogger(__name__)


def get_qdrant_client() -> AsyncQdrantClient:
    """Create and return an async Qdrant client for the RAG pipeline."""
    logger.info("Creating AsyncQdrantClient", extra={"url": settings.qdrant_url})
    return AsyncQdrantClient(
        url=settings.qdrant_url,
        timeout=30,
    )
