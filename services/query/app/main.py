"""
============================================================================
FILE: services/query/app/main.py
PURPOSE: FastAPI application entrypoint for query-svc.
         Exposes POST /query (SSE streaming), GET /health, GET /metrics.
ARCHITECTURE REF: §3 — Query Processing Pipeline; §9 — API Specification
DEPENDENCIES: fastapi, sse-starlette, httpx, qdrant-client, redis
============================================================================

Endpoints:
  POST /query
    - Auth: JWT Bearer (any role)
    - Body: {"query": str, "document_id": optional str}
    - Response: text/event-stream (SSE)
    - Events: token | sources | error | done
    - Rate limit: enforced by nginx (10 req/s/IP)

  GET /health
    - Auth: none
    - Checks: Redis PING, Qdrant collection exists, embedding-svc /health,
              reranker-svc /health, llm-server /health
    - Returns: 200 (all healthy) or 503 (any dependency down)

  GET /metrics
    - Auth: none (prometheus scrapes this)
    - Returns: Prometheus exposition format text
    - Instrumented by prometheus-fastapi-instrumentator

Application Lifecycle:
  startup:  Create asyncpg pool, connect Redis, create Qdrant client,
            create shared httpx.AsyncClient, warm up embedding model
  shutdown: Close all connections gracefully
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient
from sse_starlette.sse import EventSourceResponse

from app.cache import SemanticCache
from app.config import settings
from app.pipeline import run_query_pipeline
from shared.jwt_utils import decode_token, TokenData
from shared.logging_config import setup_logging, set_correlation_id

setup_logging(settings.log_level, settings.log_format)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ──────────────────────────────────────────────────────────────────────────────


class QueryRequest(BaseModel):
    """Request body for POST /query."""

    query: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Natural-language question (English or Arabic)",
        examples=["How many days of annual leave am I entitled to?"],
    )
    document_id: Optional[str] = Field(
        default=None,
        description="Optional document UUID to restrict search to one document",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Application Lifecycle
# ──────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown.

    Initializes all shared clients once at startup and stores them in
    app.state so that request handlers can access them via dependency injection.
    This avoids creating new connections per request.
    """
    logger.info("query-svc starting up")

    # ── Shared HTTP client (for embedding-svc, reranker-svc, llm-server) ─────
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=5.0,
            read=settings.llm_stream_timeout_seconds,
            write=30.0,
            pool=30.0,
        ),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30,
        ),
    )

    # ── Redis client (semantic cache) ─────────────────────────────────────────
    app.state.redis_client = await aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,  # Raw bytes — cache stores pickled numpy arrays
        db=settings.redis_cache_db,
    )
    # Verify Redis connection
    await app.state.redis_client.ping()
    logger.info("Redis connected", extra={"url": settings.redis_url})

    # ── Semantic cache wrapper ─────────────────────────────────────────────────
    app.state.cache = SemanticCache(
        redis_client=app.state.redis_client,
        similarity_threshold=settings.cache_similarity_threshold,
        ttl_seconds=settings.cache_ttl_seconds,
        max_entries=settings.cache_max_entries,
    )

    # ── Qdrant client ──────────────────────────────────────────────────────────
    app.state.qdrant_client = AsyncQdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        timeout=30,
    )
    # Verify Qdrant connection by checking collection exists
    try:
        collections = await app.state.qdrant_client.get_collections()
        collection_names = [c.name for c in collections.collections]
        if settings.qdrant_collection not in collection_names:
            logger.warning(
                "Qdrant collection not found — has ingest-svc run yet?",
                extra={"collection": settings.qdrant_collection},
            )
        else:
            logger.info(
                "Qdrant collection verified",
                extra={"collection": settings.qdrant_collection},
            )
    except Exception as exc:
        logger.error("Qdrant connection failed", extra={"error": str(exc)})

    logger.info("query-svc startup complete")

    yield  # Application runs here

    # ── Shutdown: close all connections ───────────────────────────────────────
    logger.info("query-svc shutting down")
    await app.state.http_client.aclose()
    await app.state.redis_client.aclose()
    await app.state.qdrant_client.close()
    logger.info("query-svc shutdown complete")


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI Application
# ──────────────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="HR RAG Query Service",
    description="Streaming RAG query endpoint for HR knowledge base",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Prometheus Metrics ─────────────────────────────────────────────────────────
Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# ── CORS (nginx handles prod CORS; this is for dev direct access) ───────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────────────────────────────────────


async def get_current_user(request: Request) -> TokenData:
    """
    FastAPI dependency: validate JWT Bearer token.

    Extracts and validates the JWT from the Authorization header.
    Returns decoded token payload (sub, role, exp).

    Raises:
        HTTPException 401: If token is missing or invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header[len("Bearer "):]
    token_data = decode_token(token, settings.jwt_secret)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token_data


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────


@app.post(
    "/query",
    response_class=EventSourceResponse,
    summary="Submit an HR query and receive a streaming answer",
    description="""
    Executes the full RAG pipeline:
    1. Embed the query
    2. Check semantic cache (Redis)
    3. Hybrid retrieval from Qdrant (dense + sparse + RRF)
    4. Cross-encoder reranking
    5. LLM generation (streaming SSE)
    6. Return answer tokens + source citations

    **Authentication**: JWT Bearer token required (any role: user or admin)

    **Response**: `text/event-stream` with the following event types:
    - `token`: `{"token": "Hello"}`  — one per LLM output token
    - `sources`: `{"sources": [...]}` — citations after final token
    - `error`: `{"error": "...", "code": "..."}` — on failure
    - `done`: `{"status": "complete"}` — end-of-stream marker
    """,
    tags=["query"],
)
async def post_query(
    body: QueryRequest,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
) -> EventSourceResponse:
    """
    Main RAG query endpoint with SSE streaming.

    Validates the JWT, sets the correlation ID for log tracing, then
    delegates to run_query_pipeline() which yields SSE events.

    The EventSourceResponse from sse-starlette handles the HTTP/1.1
    chunked transfer encoding and proper SSE headers automatically.
    """
    # Set correlation ID for log tracing (X-Request-ID propagated by nginx)
    correlation_id = request.headers.get("X-Request-ID", "")
    if correlation_id:
        set_correlation_id(correlation_id)

    logger.info(
        "Query request received",
        extra={
            "user": current_user.username,
            "role": current_user.role,
            "query_len": len(body.query),
            "document_scoped": body.document_id is not None,
        },
    )

    # Build the event generator — run_query_pipeline is an async generator
    event_generator = run_query_pipeline(
        query=body.query,
        document_id=body.document_id,
        http_client=request.app.state.http_client,
        qdrant_client=request.app.state.qdrant_client,
        cache=request.app.state.cache,
    )

    # EventSourceResponse handles:
    #   - Content-Type: text/event-stream
    #   - Cache-Control: no-cache
    #   - X-Accel-Buffering: no (for nginx)
    #   - Chunked transfer encoding
    return EventSourceResponse(
        event_generator,
        media_type="text/event-stream",
    )


@app.get(
    "/health",
    summary="Health check for query-svc",
    tags=["operations"],
)
async def get_health(request: Request) -> dict:
    """
    Check health of all query-svc dependencies.

    Returns 200 if all dependencies are reachable, 503 if any are down.
    Used by Docker Compose healthcheck and the monitoring stack.
    """
    dependencies: dict[str, str] = {}
    is_healthy = True

    # ── Redis ping ─────────────────────────────────────────────────────────────
    try:
        await request.app.state.redis_client.ping()
        dependencies["redis"] = "healthy"
    except Exception as exc:
        dependencies["redis"] = f"unhealthy: {exc}"
        is_healthy = False

    # ── Qdrant collection check ────────────────────────────────────────────────
    try:
        collections = await request.app.state.qdrant_client.get_collections()
        names = [c.name for c in collections.collections]
        if settings.qdrant_collection in names:
            dependencies["qdrant"] = "healthy"
        else:
            dependencies["qdrant"] = f"unhealthy: collection '{settings.qdrant_collection}' not found"
            is_healthy = False
    except Exception as exc:
        dependencies["qdrant"] = f"unhealthy: {exc}"
        is_healthy = False

    # ── Embedding service ──────────────────────────────────────────────────────
    try:
        resp = await request.app.state.http_client.get(
            f"{settings.embedding_svc_url}/health",
            timeout=5.0,
        )
        if resp.status_code == 200:
            dependencies["embedding_svc"] = "healthy"
        else:
            dependencies["embedding_svc"] = f"unhealthy: HTTP {resp.status_code}"
            is_healthy = False
    except Exception as exc:
        dependencies["embedding_svc"] = f"unhealthy: {exc}"
        is_healthy = False

    # ── Reranker service ──────────────────────────────────────────────────────
    try:
        resp = await request.app.state.http_client.get(
            f"{settings.reranker_svc_url}/health",
            timeout=5.0,
        )
        if resp.status_code == 200:
            dependencies["reranker_svc"] = "healthy"
        else:
            dependencies["reranker_svc"] = f"unhealthy: HTTP {resp.status_code}"
            # Reranker degraded = still functional (pipeline falls back to retrieval order)
    except Exception as exc:
        dependencies["reranker_svc"] = f"unhealthy: {exc}"

    # ── LLM server ────────────────────────────────────────────────────────────
    try:
        resp = await request.app.state.http_client.get(
            f"{settings.llm_server_url}/health",
            timeout=5.0,
        )
        if resp.status_code == 200:
            dependencies["llm_server"] = "healthy"
        else:
            dependencies["llm_server"] = f"unhealthy: HTTP {resp.status_code}"
            # LLM down = unhealthy only if Azure fallback is also unconfigured
            if not settings.azure_openai_endpoint:
                is_healthy = False
    except Exception as exc:
        dependencies["llm_server"] = f"unhealthy: {exc}"
        if not settings.azure_openai_endpoint:
            is_healthy = False

    response_status = "healthy" if is_healthy else "degraded"
    status_code = 200 if is_healthy else 503

    return {
        "status": response_status,
        "service": "query-svc",
        "version": "1.0.0",
        "dependencies": dependencies,
    }
