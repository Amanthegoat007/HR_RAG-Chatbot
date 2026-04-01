"""
============================================================================
FILE: services/backend/app/main.py
PURPOSE: FastAPI application entrypoint for the monolithic backend.
         Combines Auth, BFF (chat proxy), and Ingestion.
============================================================================
"""

import sys
import time
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

# Ensure shared lib can be imported
sys.path.insert(0, "/app")

from app.config import settings
from app.db import create_db_pool, ensure_runtime_schema
from app.minio_client import get_minio_client, ensure_bucket_exists
from app.qdrant_client_wrapper import get_qdrant_client, ensure_collection_exists

from app.routes import auth, benchmark, conversations, documents, messages

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB pool
    db_pool = await create_db_pool()
    await ensure_runtime_schema(db_pool)
    app.state.db_pool = db_pool
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=10.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    app.state.redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    # Initialize MinIO
    minio_client = get_minio_client()
    ensure_bucket_exists(minio_client, settings.minio_bucket_name)
    app.state.minio_client = minio_client

    # Initialize Qdrant
    qdrant_client = get_qdrant_client()
    ensure_collection_exists(qdrant_client)
    app.state.qdrant_client = qdrant_client
    
    yield

    # Cleanup
    await app.state.http_client.aclose()
    await app.state.redis.aclose()
    await db_pool.close()

app = FastAPI(
    title="HR RAG Backend",
    description="Unified Auth, BFF, and Ingest API",
    version=settings.service_version,
    lifespan=lifespan,
)

# CORS Middleware (Nginx handles production, but useful for dev)
# NOTE: allow_origins=["*"] + allow_credentials=True is FORBIDDEN by the CORS spec.
# Browsers will silently reject cookies. Use specific origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:80",
        "http://localhost:3000",  # Vite dev server
        "http://127.0.0.1",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = time.time()
Instrumentator().instrument(app).expose(app)

# Include Routers
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["Conversations"])
app.include_router(messages.router, prefix="/api/messages", tags=["Messages"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(benchmark.router, prefix="/api/benchmark", tags=["Benchmark"])

async def _http_dependency_status(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = 5.0,
    expect_json_status: bool = False,
) -> str:
    try:
        response = await client.get(url, timeout=timeout)
        if response.status_code >= 400:
            return "unhealthy"
        if expect_json_status:
            payload = response.json()
            return "healthy" if payload.get("status") == "healthy" else "unhealthy"
        return "healthy"
    except Exception:
        return "unhealthy"


async def _backend_dependency_statuses(request: Request) -> dict[str, str]:
    statuses: dict[str, str] = {}
    db_pool = request.app.state.db_pool
    http_client: httpx.AsyncClient = request.app.state.http_client

    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        statuses["postgres"] = "healthy"
    except Exception:
        statuses["postgres"] = "unhealthy"

    statuses["minio"] = await _http_dependency_status(
        http_client,
        f"{settings.minio_endpoint_url}/minio/health/live",
    )
    statuses["rag-pipeline"] = await _http_dependency_status(
        http_client,
        f"{settings.rag_pipeline_url}/ready",
        expect_json_status=True,
    )
    statuses["document-ingest"] = await _http_dependency_status(
        http_client,
        f"{settings.document_ingest_url}/ready",
        expect_json_status=True,
    )
    return statuses


def _health_payload(statuses: dict[str, str]) -> dict[str, object]:
    overall = "healthy" if all(value == "healthy" for value in statuses.values()) else "degraded"
    return {
        "status": overall,
        "service": settings.service_name,
        "version": settings.service_version,
        "uptime_seconds": round(time.time() - _start_time, 1),
        "dependencies": statuses,
    }


@app.get("/live", tags=["System"])
async def live() -> dict[str, object]:
    return {
        "status": "live",
        "service": settings.service_name,
        "version": settings.service_version,
        "uptime_seconds": round(time.time() - _start_time, 1),
    }


@app.get("/ready", tags=["System"])
async def ready(request: Request) -> dict[str, object]:
    return _health_payload(await _backend_dependency_statuses(request))


@app.get("/health", tags=["System"])
async def health(request: Request) -> dict[str, object]:
    """Backward-compatible readiness endpoint."""
    return await ready(request)
