"""
============================================================================
FILE: services/ingest/app/main.py
PURPOSE: FastAPI ingest service — document upload API, status tracking,
         and deletion. Async uploads; background processing via Celery.
ARCHITECTURE REF: §3 — Document Ingestion Pipeline (API side)
DEPENDENCIES: FastAPI, asyncpg, minio_client.py, db.py, celery_app.py
============================================================================

API Surface:
  POST   /ingest/upload              Upload a document (admin only)
  GET    /ingest/documents           List all documents
  GET    /ingest/document/{id}       Get document details and status
  DELETE /ingest/document/{id}       Delete document (admin only)
  GET    /health                     Health check
  GET    /metrics                    Prometheus metrics
"""

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import asyncpg
from fastapi import (
    Depends, FastAPI, File, Header, HTTPException, Request,
    UploadFile, status
)
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

import sys
sys.path.insert(0, "/app")
from shared.logging_config import setup_logging, get_logger, set_correlation_id

from app.config import settings

import json as _json

def _safe_metadata(val) -> dict:
    """Safely convert asyncpg JSONB return value to a dict."""
    if not val:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return _json.loads(val)
        except (ValueError, TypeError):
            return {}
    return {}

from app.db import (
    create_db_pool, create_document_record, get_document,
    list_documents, write_audit_log, create_ingestion_job
)
from app.minio_client import get_minio_client, ensure_bucket_exists, upload_file
from app.qdrant_client_wrapper import get_qdrant_client, ensure_collection_exists
from app.models import (
    DocumentMetadata, DocumentListResponse, UploadResponse,
    DeleteResponse, HealthResponse
)
from app.tasks import process_document, delete_document as delete_document_task

# Re-use auth middleware from this service (copied from auth-svc pattern)

# Re-use auth middleware from this service (copied from auth-svc pattern)
# We define it locally using shared jwt_utils
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
from shared.jwt_utils import decode_token, TokenData

setup_logging(
    service_name=settings.service_name,
    log_level=settings.log_level,
    log_format=settings.log_format,
)
logger = get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_jwt_local(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenData:
    """JWT validation dependency using this service's JWT_SECRET."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(credentials.credentials, settings.jwt_secret)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_admin(token_data: TokenData = Depends(require_jwt_local)) -> TokenData:
    """Require admin role."""
    if token_data.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return token_data


def require_internal_token(x_ingest_token: str = Header(default="", alias="X-Ingest-Token")) -> None:
    if not settings.ingest_internal_token:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal ingest token is not configured")
    if x_ingest_token != settings.ingest_internal_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal ingest token")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Service startup: create DB pool, ensure MinIO bucket and Qdrant collection exist.
    """
    logger.info("Ingest service starting up...")

    db_pool = await create_db_pool()
    app.state.db_pool = db_pool

    minio_client = get_minio_client()
    ensure_bucket_exists(minio_client, settings.minio_bucket_name)
    app.state.minio_client = minio_client

    qdrant_client = get_qdrant_client()
    ensure_collection_exists(qdrant_client)
    app.state.qdrant_client = qdrant_client

    logger.info("Ingest service ready")
    yield

    await db_pool.close()
    logger.info("Ingest service shutdown complete")


app = FastAPI(
    title="HR RAG — Ingest Service",
    description="Document upload and management for the HR RAG system",
    version=settings.service_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

_start_time = time.time()
Instrumentator().instrument(app).expose(app)

# Supported MIME types mapped to format strings
SUPPORTED_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/plain": "txt",
    "text/markdown": "md",
}


@app.post(
    "/ingest/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for ingestion",
    description="Upload a PDF, DOCX, XLSX, PPTX, TXT, or MD file. Admin only. Returns job ID for status tracking.",
)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="Document to upload (max 200MB)"),
    current_user: TokenData = Depends(require_admin),
) -> UploadResponse:
    """
    Accept a document upload and queue it for processing.

    Architecture Reference: §3 — Document Ingestion Pipeline

    Flow:
    1. Validate file size and format
    2. Generate document UUID
    3. Upload original to MinIO
    4. Create document record in PostgreSQL (status: pending)
    5. Dispatch Celery task (process_document)
    6. Create ingestion_job record
    7. Return 202 Accepted with job_id for status polling

    Args:
        request: FastAPI request (for IP extraction).
        file: Uploaded file (validated by FastAPI).
        current_user: Admin JWT (enforced by require_admin dependency).

    Returns:
        UploadResponse with document_id and job_id.
    """
    correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()

    # Validate file size
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {settings.max_upload_size_mb} MB"
        )

    # Validate file format by extension
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ("pdf", "docx", "xlsx", "pptx", "txt", "md"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported format: .{ext}. Supported: pdf, docx, xlsx, pptx, txt, md"
        )

    document_id = str(uuid.uuid4())
    db_pool: asyncpg.Pool = request.app.state.db_pool
    minio_client = request.app.state.minio_client

    # Upload original file to MinIO
    content_type = file.content_type or "application/octet-stream"
    minio_path = upload_file(
        minio_client, document_id, filename, file_bytes, content_type
    )

    # Create DB record
    from app.metadata_extractor import build_document_metadata
    initial_metadata = {"filename": filename, "format": ext}
    await create_document_record(
        db_pool, document_id, filename, ext, minio_path,
        len(file_bytes), current_user.username, initial_metadata,
    )

    # Dispatch Celery task (non-blocking)
    task = process_document.apply_async(
        args=[document_id],
        queue="document_processing",
        task_id=str(uuid.uuid4()),
    )

    # Record ingestion job
    job_id = await create_ingestion_job(db_pool, document_id, task.id)

    # Audit log
    await write_audit_log(
        db_pool, "upload_start",
        role=current_user.role, username=current_user.username,
        ip_address=ip_address,
        details={"filename": filename, "document_id": document_id, "size": len(file_bytes)},
    )

    logger.info("Document upload queued", extra={
        "document_id": document_id,
        "doc_filename": filename,
        "task_id": task.id,
    })

    return UploadResponse(
        document_id=document_id,
        filename=filename,
        file_size_bytes=len(file_bytes),
        status="pending",
        job_id=task.id,
        message="Document queued for processing. Poll GET /ingest/document/{id} for status.",
    )


@app.post(
    "/ingest/internal/enqueue/{document_id}",
    summary="Queue processing for an existing document record",
)
async def internal_enqueue_document(
    document_id: str,
    request: Request,
    _: None = Depends(require_internal_token),
) -> JSONResponse:
    db_pool: asyncpg.Pool = request.app.state.db_pool
    doc = await get_document(db_pool, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    task = process_document.apply_async(
        args=[document_id],
        queue="document_processing",
        task_id=str(uuid.uuid4()),
    )
    job_id = await create_ingestion_job(db_pool, document_id, task.id)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "queued",
            "document_id": document_id,
            "task_id": task.id,
            "job_id": job_id,
        },
    )


@app.post(
    "/ingest/internal/delete/{document_id}",
    summary="Queue document deletion from backend",
)
async def internal_delete_document(
    document_id: str,
    request: Request,
    _: None = Depends(require_internal_token),
) -> JSONResponse:
    db_pool: asyncpg.Pool = request.app.state.db_pool
    doc = await get_document(db_pool, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    filename = doc["filename"]
    delete_document_task.apply_async(
        args=[document_id, filename],
        queue="document_processing",
        task_id=str(uuid.uuid4()),
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "queued",
            "document_id": document_id,
            "filename": filename,
        },
    )


@app.get(
    "/ingest/documents",
    response_model=DocumentListResponse,
    summary="List all documents",
)
async def list_all_documents(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    current_user: TokenData = Depends(require_jwt_local),
) -> DocumentListResponse:
    """List all documents with optional status filtering. Both roles can access."""
    db_pool: asyncpg.Pool = request.app.state.db_pool
    rows, total = await list_documents(db_pool, limit, offset, status_filter)

    documents = []
    for row in rows:
        documents.append(DocumentMetadata(
            id=str(row["id"]),
            filename=row["filename"],
            original_format=row["original_format"],
            status=row["status"],
            file_size_bytes=row["file_size_bytes"],
            page_count=row["page_count"],
            chunk_count=row["chunk_count"] or 0,
            uploaded_by=row["uploaded_by"] or "hr_admin",
            uploaded_at=row["uploaded_at"],
            processed_at=row.get("processed_at"),
            error_message=row.get("error_message"),
            metadata=_safe_metadata(row["metadata"]),
        ))

    return DocumentListResponse(documents=documents, total=total)


@app.get(
    "/ingest/document/{document_id}",
    response_model=DocumentMetadata,
    summary="Get document details and processing status",
)
async def get_document_status(
    document_id: str,
    request: Request,
    current_user: TokenData = Depends(require_jwt_local),
) -> DocumentMetadata:
    """Get a single document's metadata and current processing status."""
    db_pool: asyncpg.Pool = request.app.state.db_pool
    doc = await get_document(db_pool, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    return DocumentMetadata(
        id=str(doc["id"]),
        filename=doc["filename"],
        original_format=doc["original_format"],
        status=doc["status"],
        file_size_bytes=doc["file_size_bytes"],
        page_count=doc["page_count"],
        chunk_count=doc["chunk_count"] or 0,
        uploaded_by=doc["uploaded_by"] or "hr_admin",
        uploaded_at=doc["uploaded_at"],
        processed_at=doc.get("processed_at"),
        error_message=doc.get("error_message"),
        metadata=_safe_metadata(doc["metadata"]),
    )


@app.delete(
    "/ingest/document/{document_id}",
    response_model=DeleteResponse,
    summary="Delete a document and all its data",
    description="Removes file from MinIO, vectors from Qdrant, and record from PostgreSQL. Admin only.",
)
async def delete_document_endpoint(
    document_id: str,
    request: Request,
    current_user: TokenData = Depends(require_admin),
) -> DeleteResponse:
    """
    Delete a document completely from all storage systems.

    Dispatches a Celery task for the actual deletion to avoid blocking the API.
    """
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    db_pool: asyncpg.Pool = request.app.state.db_pool

    doc = await get_document(db_pool, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")

    filename = doc["filename"]

    # Dispatch deletion task
    delete_document_task.apply_async(
        args=[document_id, filename],
        queue="document_processing",
    )

    await write_audit_log(
        db_pool, "document_delete",
        role=current_user.role, username=current_user.username,
        ip_address=ip_address,
        details={"document_id": document_id, "filename": filename},
    )

    return DeleteResponse(
        document_id=document_id,
        filename=filename,
        message="Document deletion queued.",
        vectors_deleted=0,  # Will be updated by the Celery task
        minio_deleted=False,
    )


@app.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Health check including PostgreSQL, MinIO, and Qdrant connectivity."""
    statuses = {}

    # Check PostgreSQL
    try:
        db_pool: asyncpg.Pool = request.app.state.db_pool
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        statuses["postgres"] = "healthy"
    except Exception as exc:
        statuses["postgres"] = f"unhealthy: {exc}"

    # Check MinIO
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{settings.minio_endpoint_url}/minio/health/live")
            statuses["minio"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        statuses["minio"] = "unhealthy"

    # Check Qdrant
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{settings.qdrant_url}/healthz")
            statuses["qdrant"] = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        statuses["qdrant"] = "unhealthy"

    overall = "healthy" if all(v == "healthy" for v in statuses.values()) else "degraded"

    return HealthResponse(
        status=overall,
        service=settings.service_name,
        version=settings.service_version,
        uptime_seconds=round(time.time() - _start_time, 1),
        dependencies=statuses,
    )
