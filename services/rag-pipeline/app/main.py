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
from app.cache import ContextResolutionCache, SemanticCache
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
    app.state.context_resolution_cache = ContextResolutionCache(
        redis_client=redis_client,
        ttl_seconds=settings.context_resolution_cache_ttl_seconds,
    )

    # Shared HTTP client for talking to llama.cpp
    # Timeout is large because local LLM generation can be slow
    app.state.http_client = httpx.AsyncClient(timeout=300.0)

    yield

    await app.state.qdrant_client.close()
    await app.state.cache._client.aclose()
    await app.state.http_client.aclose()
    embedding_service.close()
    reranker_service.close()


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

    results = await embedding_service.embed_texts_async(request.texts)
    return {"results": results}


@app.post(
    "/query",
    summary="Query the RAG pipeline",
)
async def query(request: QueryRequest, req: Request):
    if not (embedding_service.is_loaded and reranker_service.is_loaded):
        raise HTTPException(status_code=503, detail="Models not loaded yet")

    document_id = getattr(request, "document_id", None)
    session_id = request.conversation_id if request.conversation_id and request.conversation_id != "temp" and request.conversation_id != "new" else None
    
    event_generator = run_query_pipeline(
        query=request.query,
        document_id=document_id,
        http_client=req.app.state.http_client,
        qdrant_client=req.app.state.qdrant_client,
        cache=req.app.state.cache,
        context_resolution_cache=req.app.state.context_resolution_cache,
        conversation_history=request.conversation_history,
        conversation_id=request.conversation_id,
        user_role=getattr(request, "user_role", "employee"),
        session_id=session_id,
        session_scope_active=getattr(request, "session_scope_active", False),
        conversation_working_set=getattr(request, "conversation_working_set", None),
        reasoning_mode=getattr(request, "reasoning_mode", None),
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

async def _http_dependency_status(client: httpx.AsyncClient, url: str, timeout: float = 2.0) -> str:
    try:
        response = await client.get(url, timeout=timeout)
        return "healthy" if response.status_code < 400 else "unhealthy"
    except Exception:
        return "unhealthy"


async def _rag_dependency_statuses(request: Request) -> tuple[dict[str, str], bool]:
    http_client: httpx.AsyncClient = request.app.state.http_client
    statuses: dict[str, str] = {}

    try:
        pong = await request.app.state.redis_client.ping()
        statuses["redis"] = "healthy" if pong else "unhealthy"
    except Exception:
        statuses["redis"] = "unhealthy"

    statuses["qdrant"] = await _http_dependency_status(
        http_client,
        f"{settings.qdrant_url}/healthz",
    )
    statuses["llama-server"] = await _http_dependency_status(
        http_client,
        f"{settings.llm_server_url}/health",
    )
    models_loaded = embedding_service.is_loaded and reranker_service.is_loaded
    return statuses, models_loaded


def _health_response(statuses: dict[str, str], models_loaded: bool) -> HealthResponse:
    overall = "healthy" if all(value == "healthy" for value in statuses.values()) and models_loaded else "degraded"
    return HealthResponse(
        status=overall,
        service=settings.service_name,
        version=settings.service_version,
        uptime_seconds=round(time.time() - _start_time, 1),
        dependencies=statuses,
        models_loaded=models_loaded,
    )


@app.get("/live")
async def live():
    return {
        "status": "live",
        "service": settings.service_name,
        "version": settings.service_version,
        "uptime_seconds": round(time.time() - _start_time, 1),
    }


@app.get("/ready", response_model=HealthResponse)
async def ready(request: Request):
    statuses, models_loaded = await _rag_dependency_statuses(request)
    return _health_response(statuses, models_loaded)


@app.get("/health", response_model=HealthResponse)
async def health(request: Request):
    return await ready(request)
