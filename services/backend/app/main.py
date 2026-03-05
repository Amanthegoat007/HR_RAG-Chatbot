"""
============================================================================
FILE: services/backend/app/main.py
PURPOSE: FastAPI application entrypoint for the monolithic backend.
         Combines Auth, BFF (chat proxy), and Ingestion.
============================================================================
"""

import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
import sys

# Ensure shared lib can be imported
sys.path.insert(0, "/app")

from app.config import settings
from app.db import create_db_pool
from app.minio_client import get_minio_client, ensure_bucket_exists
from app.qdrant_client_wrapper import get_qdrant_client, ensure_collection_exists

from app.routes import auth, conversations, messages, documents

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB pool
    db_pool = await create_db_pool()
    app.state.db_pool = db_pool

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

@app.get("/health", tags=["System"])
async def health(request: Request):
    """Health check endpoint mimicking unified status."""
    statuses = {}
    
    # Check PostgreSQL
    try:
        db_pool = request.app.state.db_pool
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        statuses["postgres"] = "healthy"
    except Exception as exc:
        statuses["postgres"] = f"unhealthy: {exc}"

    overall = "healthy" if all(v == "healthy" for v in statuses.values()) else "degraded"
    
    return {
        "status": overall,
        "service": settings.service_name,
        "uptime_seconds": round(time.time() - _start_time, 1),
        "dependencies": statuses
    }
