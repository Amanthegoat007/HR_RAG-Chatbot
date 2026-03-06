"""
============================================================================
FILE: services/rag-pipeline/app/main.py
PURPOSE: FastAPI application for the unified RAG Pipeline.
         Combines Query Orchestrator, Embedding, and Reranking.
============================================================================
"""

# Monkey-patch FlagEmbedding 1.2.10 bug: Optional not imported in BGE_M3/trainer.py
# Inject Optional into builtins so it's available when the module evaluates its class definition
import builtins
from typing import Optional as _Optional
if not hasattr(builtins, "Optional"):
    builtins.Optional = _Optional

import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import httpx
import redis.asyncio as aioredis

from fastapi import FastAPI, Request, HTTPException
from starlette.responses import StreamingResponse
from prometheus_fastapi_instrumentator import Instrumentator

sys.path.insert(0, "/app")

from app.config import settings
from app.models import QueryRequest, HealthResponse
from app.embedding_service import embedding_service
from app.reranker_service import reranker_service
from app.model_prefetch import prefetch_required_models
from app.pipeline import run_query_pipeline
from app.cache import SemanticCache
from app.qdrant_client_wrapper import get_qdrant_client

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Prefetch models into shared HF cache before model initialization.
    # This enables faster restarts and avoids slow/unstable runtime downloads.
    try:
        embedding_model_path, reranker_model_path = prefetch_required_models()
    except Exception as exc:
        raise RuntimeError(f"Could not prefetch required models: {exc}") from exc

    # Load Embedding Model
    try:
        embedding_service.load_model(embedding_model_path)
    except Exception as exc:
        raise RuntimeError(f"Could not load embedding model: {exc}") from exc

    # Load Reranker Model
    try:
        reranker_service.load_model(reranker_model_path)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Could not load reranker model. Reranking will be disabled: {exc}")

    # Initialize Redis client for semantic cache
    redis_client = aioredis.from_url(
        settings.redis_url,
        decode_responses=False,
    )
    app.state.redis_client = redis_client

    # Initialize external clients
    app.state.qdrant_client = get_qdrant_client()
    app.state.cache = SemanticCache(
        redis_client=redis_client,
        similarity_threshold=settings.cache_similarity_threshold,
        ttl_seconds=settings.cache_ttl_seconds,
    )

    # Shared HTTP client for talking to llama.cpp
    # Timeout is large because local LLM generation can be slow
    app.state.http_client = httpx.AsyncClient(timeout=300.0)

    yield

    await app.state.qdrant_client.close()
    await app.state.cache._client.close()
    await app.state.http_client.aclose()


app = FastAPI(
    title="HR RAG — Unified Pipeline",
    description="RAG orchestrator with in-process BGE-M3 and BGE-Reranker.",
    version=settings.service_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

_start_time = time.time()
Instrumentator().instrument(app).expose(app)


# ---------- Embed endpoint (used by backend Celery worker for document ingestion) ----------

from pydantic import BaseModel as PydanticBaseModel
from typing import List

class EmbedRequest(PydanticBaseModel):
    texts: List[str]

@app.post("/embed", summary="Generate embeddings for texts")
async def embed_texts(request: EmbedRequest):
    """Generate dense and sparse embeddings for a list of texts."""
    if not embedding_service.is_loaded:
        raise HTTPException(status_code=503, detail="Embedding model not loaded yet")

    results = embedding_service.embed_texts(request.texts)
    return {"results": results}


@app.post(
    "/query",
    summary="Query the RAG pipeline",
)
async def query(request: QueryRequest, req: Request):
    if not (embedding_service.is_loaded and reranker_service.is_loaded):
        raise HTTPException(status_code=503, detail="Models not loaded yet")

    document_id = getattr(request, "document_id", None)
    
    event_generator = run_query_pipeline(
        query=request.query,
        document_id=document_id,
        http_client=req.app.state.http_client,
        qdrant_client=req.app.state.qdrant_client,
        cache=req.app.state.cache,
    )

    if request.stream:
        async def sse_stream():
            async for sse_event in event_generator:
                yield sse_event.encode()

        return StreamingResponse(
            sse_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        raise HTTPException(status_code=400, detail="Use stream=True")

@app.get("/health", response_model=HealthResponse)
async def health(request: Request):
    models_loaded = embedding_service.is_loaded and reranker_service.is_loaded
    statuses = {}
    
    # Qdrant
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{settings.qdrant_url}/healthz")
            statuses["qdrant"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        statuses["qdrant"] = "unhealthy"
        
    # Local LLM Supervised Process
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{settings.llm_server_url}/health")
            statuses["llama-server"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        statuses["llama-server"] = "unhealthy"

    overall = "healthy" if all(v == "healthy" for v in statuses.values()) and models_loaded else "degraded"
    
    return HealthResponse(
        status=overall,
        service=settings.service_name,
        version=settings.service_version,
        uptime_seconds=round(time.time() - _start_time, 1),
        dependencies=statuses,
        models_loaded=models_loaded
    )
