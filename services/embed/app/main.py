"""
============================================================================
FILE: services/embed/app/main.py
PURPOSE: FastAPI application for the embedding service.
         Exposes POST /embed for dense+sparse vector generation,
         and GET /health for container health checks.
ARCHITECTURE REF: §3.3 — BGE-M3 Optimization for CPU
DEPENDENCIES: FastAPI, embedding_service.py, Prometheus instrumentation
============================================================================
"""

import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

# Add shared directory to path (copied into image at build time)
sys.path.insert(0, "/app")
from shared.logging_config import setup_logging, get_logger

from app.config import settings
from app.embedding_service import embedding_service
from app.models import EmbedRequest, EmbedResponse, EmbedResult, DenseVector, SparseVector, HealthResponse

# Initialize structured logging before creating the app
setup_logging(
    service_name=settings.service_name,
    log_level=settings.log_level,
    log_format=settings.log_format,
)
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# LIFESPAN — model loading at startup, cleanup at shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Startup: Load the BGE-M3 model into RAM (takes 30-60 seconds).
    Shutdown: Clean up (Python GC handles memory; nothing explicit needed).

    The lifespan pattern replaces deprecated @app.on_event("startup") decorators.
    """
    # STARTUP
    logger.info("Embedding service starting up...")
    try:
        # This is a blocking call — it loads ~1.1 GB model into RAM
        # FastAPI waits for this to complete before accepting requests
        embedding_service.load_model()
        logger.info("Embedding service startup complete — ready to accept requests")
    except Exception as exc:
        logger.error("FATAL: Failed to load embedding model", extra={"error": str(exc)})
        raise RuntimeError(f"Could not load embedding model: {exc}") from exc

    yield  # Application runs here

    # SHUTDOWN
    logger.info("Embedding service shutting down...")


# ---------------------------------------------------------------------------
# FASTAPI APPLICATION
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HR RAG — Embedding Service",
    description="BGE-M3 embedding service providing dense (1024-dim) and sparse vectors",
    version=settings.service_version,
    lifespan=lifespan,
    # Disable OpenAPI docs in production (optional — enables them for debugging)
    docs_url="/docs",
    redoc_url=None,
)

# Expose Prometheus metrics at /metrics endpoint
# Automatically tracks: request count, latency histograms, error rates
Instrumentator().instrument(app).expose(app)


# ---------------------------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------------------------

@app.post(
    "/embed",
    response_model=EmbedResponse,
    summary="Generate embeddings",
    description="Embed one or more texts using BGE-M3. Returns dense (1024-dim) + sparse vectors."
)
async def embed(request: EmbedRequest) -> EmbedResponse:
    """
    Generate dense and sparse embeddings for a list of texts.

    Architecture Reference: §3.3 — BGE-M3 Optimization for CPU

    Both vector types are computed in a SINGLE forward pass through BGE-M3.
    The dense vectors are used for ANN (nearest-neighbor) search in Qdrant.
    The sparse vectors are used for BM25-like keyword search in Qdrant.
    Together they enable the hybrid retrieval strategy described in §4.1.

    Args:
        request: EmbedRequest with list of texts and optional batch_size override.

    Returns:
        EmbedResponse with one EmbedResult per input text.

    Raises:
        HTTPException(503): If the model is not loaded.
        HTTPException(500): If inference fails unexpectedly.
    """
    if not embedding_service.is_loaded:
        raise HTTPException(
            status_code=503,
            detail="Embedding model not loaded yet. Please retry in a few seconds."
        )

    start_time = time.time()

    try:
        # Run inference (blocking CPU operation — FastAPI handles this in threadpool)
        raw_results = embedding_service.embed_texts(
            texts=request.texts,
            batch_size=request.batch_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Embedding inference failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Embedding failed: {exc}")

    processing_time_ms = (time.time() - start_time) * 1000

    # Convert raw results to response schema
    results = [
        EmbedResult(
            dense=DenseVector(values=r["dense"]["values"]),
            sparse=SparseVector(
                indices=r["sparse"]["indices"],
                values=r["sparse"]["values"],
            ),
        )
        for r in raw_results
    ]

    return EmbedResponse(
        results=results,
        model=settings.embedding_model_name,
        processing_time_ms=round(processing_time_ms, 2),
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service health status and model load state."
)
async def health() -> HealthResponse:
    """
    Health check endpoint — called by Docker healthcheck and Prometheus.

    Returns 200 when the model is loaded and ready.
    Returns 503 if the model is still loading (Docker will retry).
    """
    if not embedding_service.is_loaded:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded yet"
        )

    return HealthResponse(
        status="healthy",
        service=settings.service_name,
        version=settings.service_version,
        uptime_seconds=round(embedding_service.uptime_seconds, 1),
        model_loaded=True,
    )
