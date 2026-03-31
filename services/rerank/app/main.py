"""
============================================================================
FILE: services/rerank/app/main.py
PURPOSE: FastAPI application for the reranker service.
         Exposes POST /rerank for cross-encoder scoring and ranking.
ARCHITECTURE REF: §4.2 — Reranking
DEPENDENCIES: FastAPI, reranker_service.py
============================================================================
"""

import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

sys.path.insert(0, "/app")
from shared.logging_config import setup_logging, get_logger

from app.config import settings
from app.reranker_service import reranker_service
from app.models import (
    RerankRequest, RerankResponse, RerankResult, HealthResponse
)

setup_logging(
    service_name=settings.service_name,
    log_level=settings.log_level,
    log_format=settings.log_format,
)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Load the reranker model at startup."""
    logger.info("Reranker service starting up...")
    try:
        reranker_service.load_model()
        logger.info("Reranker service ready")
    except Exception as exc:
        logger.error("FATAL: Failed to load reranker model", extra={"error": str(exc)})
        raise RuntimeError(f"Could not load reranker model: {exc}") from exc

    yield

    logger.info("Reranker service shutting down...")


app = FastAPI(
    title="HR RAG — Reranker Service",
    description="BGE-Reranker-v2-m3 cross-encoder for query-document relevance scoring",
    version=settings.service_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

Instrumentator().instrument(app).expose(app)


@app.post(
    "/rerank",
    response_model=RerankResponse,
    summary="Rerank documents by relevance",
    description="Score query-document pairs using BGE-Reranker-v2-m3 cross-encoder. Returns top-N sorted by relevance."
)
async def rerank(request: RerankRequest) -> RerankResponse:
    """
    Score all (query, document) pairs and return the top-N most relevant.

    Architecture Reference: §4.2 — Reranking

    Pipeline position: Called AFTER hybrid retrieval (which returns 20 candidates),
    and BEFORE LLM generation. Takes 20 candidates, returns top-5.

    This is a blocking CPU-intensive operation. FastAPI runs it in a thread pool
    to avoid blocking the event loop.

    Args:
        request: RerankRequest with query, list of documents, and top_n.

    Returns:
        RerankResponse with documents sorted by cross-encoder score descending.
    """
    if not reranker_service.is_loaded:
        raise HTTPException(status_code=503, detail="Reranker model not loaded yet")

    start_time = time.time()

    # Convert request documents to plain dicts for the service layer
    docs = [
        {
            "document_id": doc.document_id,
            "text": doc.text,
            "metadata": doc.metadata,
        }
        for doc in request.documents
    ]

    try:
        ranked = reranker_service.rerank(
            query=request.query,
            documents=docs,
            top_n=request.top_n,
        )
    except Exception as exc:
        logger.error("Reranking failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Reranking failed: {exc}")

    processing_time_ms = (time.time() - start_time) * 1000

    results = [
        RerankResult(
            document_id=r["document_id"],
            text=r["text"],
            score=r["score"],
            rank=r["rank"],
            metadata=r["metadata"],
        )
        for r in ranked
    ]

    return RerankResponse(
        results=results,
        query=request.query,
        model=settings.reranker_model_name,
        processing_time_ms=round(processing_time_ms, 2),
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    if not reranker_service.is_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded yet")

    return HealthResponse(
        status="healthy",
        service=settings.service_name,
        version=settings.service_version,
        uptime_seconds=round(reranker_service.uptime_seconds, 1),
        model_loaded=True,
    )
