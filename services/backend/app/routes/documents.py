from __future__ import annotations

import json
import uuid
import asyncio
import logging
from pathlib import Path
from typing import Optional, Literal

logger = logging.getLogger(__name__)

import asyncpg
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app import db
from app.config import settings
from app.dependencies import require_admin, require_auth
from app.minio_client import upload_file
from app.models import DeleteResponse, DocumentListResponse, DocumentMetadata, UploadResponse

router = APIRouter()

SUPPORTED_EXTENSIONS = {
    "pdf",
    "docx",
    "xlsx",
    "pptx",
    "txt",
    "md",
    "png",
    "jpg",
    "jpeg",
    "webp",
}


def _is_admin(payload: dict) -> bool:
    roles = payload.get("roles", [])
    return "ROLE_ADMIN" in roles or "ROLE_ADMINISTRATOR" in roles


def _extract_scope(metadata: dict) -> Literal["library", "session"]:
    if metadata.get("scope") == "session" or metadata.get("session_id") or metadata.get("conversation_id"):
        return "session"
    return "library"


def _extract_conversation_id(metadata: dict) -> str | None:
    return metadata.get("conversation_id") or metadata.get("session_id")


def _serialize_document(row: dict) -> DocumentMetadata:
    metadata = json.loads(row.get("metadata", "{}")) if isinstance(row.get("metadata"), str) else row.get("metadata", {})
    return DocumentMetadata(
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
        metadata=metadata,
        scope=_extract_scope(metadata),
        conversation_id=_extract_conversation_id(metadata),
    )


async def _read_upload_bytes(file: UploadFile) -> bytes:
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {settings.max_upload_size_mb} MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported format: .{ext}")
    return ext


async def _create_document_upload(
    request: Request,
    *,
    file: UploadFile,
    payload: dict,
    scope: Literal["library", "session"],
    conversation_id: str | None = None,
) -> UploadResponse:
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    file_bytes = await _read_upload_bytes(file)
    filename = file.filename or "unknown"
    ext = _validate_extension(filename)

    document_id = str(uuid.uuid4())
    db_pool: asyncpg.Pool = request.app.state.db_pool
    minio_client = request.app.state.minio_client

    if scope == "session" and conversation_id and not _is_admin(payload):
        async with db_pool.acquire() as conn:
            owns_conversation = await conn.fetchval(
                "SELECT 1 FROM conversations WHERE id = $1::uuid AND user_id = $2",
                conversation_id,
                payload.get("sub"),
            )
        if not owns_conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

    content_type = file.content_type or "application/octet-stream"
    minio_path = upload_file(minio_client, document_id, filename, file_bytes, content_type)

    initial_metadata = {"filename": filename, "format": ext, "scope": scope}
    if scope == "session" and conversation_id:
        initial_metadata["conversation_id"] = conversation_id
        initial_metadata["session_id"] = conversation_id

    await db.create_document_record(
        db_pool,
        document_id,
        filename,
        ext,
        minio_path,
        len(file_bytes),
        payload.get("sub", "employee"),
        initial_metadata,
    )

    try:
        task_id, job_id = await _enqueue_processing(document_id)
    except Exception as exc:
        await db.update_document_status(
            db_pool,
            document_id,
            "failed",
            error_message=f"Failed to enqueue ingestion: {exc}",
            metadata={**initial_metadata, "enqueue_error": str(exc)},
        )
        await db.write_audit_log(
            db_pool,
            "upload_failed",
            role="admin" if _is_admin(payload) else "user",
            username=payload.get("sub"),
            ip_address=ip_address,
            details={
                "filename": filename,
                "document_id": document_id,
                "scope": scope,
                "conversation_id": conversation_id,
                "error": str(exc),
            },
        )
        raise HTTPException(status_code=502, detail="Document upload saved but queueing failed") from exc

    await db.write_audit_log(
        db_pool,
        "upload_start",
        role="admin" if _is_admin(payload) else "user",
        username=payload.get("sub"),
        ip_address=ip_address,
        details={
            "filename": filename,
            "document_id": document_id,
            "scope": scope,
            "conversation_id": conversation_id,
            "size": len(file_bytes),
            "task_id": task_id,
        },
    )

    return UploadResponse(
        document_id=document_id,
        filename=filename,
        file_size_bytes=len(file_bytes),
        status="pending",
        job_id=job_id or task_id,
        message="Document queued for processing." if scope == "library" else "Session document queued for processing.",
        scope=scope,
        conversation_id=conversation_id,
    )


async def _enqueue_processing(document_id: str) -> tuple[str, str]:
    url = f"{settings.document_ingest_url}/ingest/internal/enqueue/{document_id}"
    headers = {"X-Ingest-Token": settings.ingest_internal_token}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    return payload.get("task_id", ""), payload.get("job_id", "")


async def _enqueue_delete(document_id: str) -> None:
    url = f"{settings.document_ingest_url}/ingest/internal/delete/{document_id}"
    headers = {"X-Ingest-Token": settings.ingest_internal_token}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers)
        response.raise_for_status()


async def cleanup_expired_sessions(app) -> None:
    """Background task to delete session documents older than 24 hours."""
    while True:
        try:
            db_pool = app.state.db_pool
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id FROM documents 
                    WHERE metadata->>'scope' = 'session'
                      AND uploaded_at < NOW() - INTERVAL '24 hours'
                    """
                )
            
            deleted_count = 0
            for row in rows:
                doc_id = str(row["id"])
                try:
                    await _enqueue_delete(doc_id)
                    deleted_count += 1
                except Exception as exc:
                    logger.warning("Failed to delete expired session document", extra={"doc_id": doc_id, "error": str(exc)})
            
            if deleted_count > 0:
                logger.info("Cleaned up expired session documents", extra={"deleted_count": deleted_count})
                
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Error in cleanup_expired_sessions task", extra={"error": str(exc)})
            
        await asyncio.sleep(3600)  # run once an hour


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    payload: dict = Depends(require_admin),
):
    return await _create_document_upload(
        request,
        file=file,
        payload=payload,
        scope="library",
    )

@router.post("/session-upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_session_document(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form(...),
    payload: dict = Depends(require_auth),
):
    return await _create_document_upload(
        request,
        file=file,
        payload=payload,
        scope="session",
        conversation_id=session_id,
    )


@router.post("/intake", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def intake_document(
    request: Request,
    file: UploadFile = File(...),
    scope: Literal["library", "session"] = Form(...),
    conversation_id: Optional[str] = Form(None),
    payload: dict = Depends(require_auth),
):
    if scope == "library" and not _is_admin(payload):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    if scope == "session" and not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required for session uploads")

    return await _create_document_upload(
        request,
        file=file,
        payload=payload,
        scope=scope,
        conversation_id=conversation_id,
    )


@router.get("", response_model=DocumentListResponse)
async def list_all_documents(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    scope: Literal["library", "session"] = "library",
    payload: dict = Depends(require_auth),
):
    db_pool: asyncpg.Pool = request.app.state.db_pool
    is_admin = _is_admin(payload)
    if scope == "library" and not is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    rows, total = await db.list_documents(
        db_pool,
        limit,
        offset,
        status_filter,
        scope=scope,
        session_owner_user_id=None if is_admin or scope != "session" else payload.get("sub"),
    )
    return DocumentListResponse(documents=[_serialize_document(row) for row in rows], total=total)


@router.get("/{document_id}", response_model=DocumentMetadata)
async def get_document_status(
    document_id: str,
    request: Request,
    payload: dict = Depends(require_auth),
):
    db_pool: asyncpg.Pool = request.app.state.db_pool
    doc = await db.get_document(db_pool, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    serialized = _serialize_document(doc)
    if serialized.scope == "library" and not _is_admin(payload):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    if serialized.scope == "session" and serialized.conversation_id and not _is_admin(payload):
        async with db_pool.acquire() as conn:
            owns_conversation = await conn.fetchval(
                "SELECT 1 FROM conversations WHERE id = $1::uuid AND user_id = $2",
                serialized.conversation_id,
                payload.get("sub"),
            )
        if not owns_conversation:
            raise HTTPException(status_code=403, detail="You do not have permission to view this document")
    return serialized


@router.delete("/session/{session_id}/files", response_model=dict)
async def delete_session_files(
    session_id: str,
    request: Request,
    payload: dict = Depends(require_auth),
):
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    db_pool: asyncpg.Pool = request.app.state.db_pool

    if not _is_admin(payload):
        async with db_pool.acquire() as conn:
            owns_conversation = await conn.fetchval(
                "SELECT 1 FROM conversations WHERE id = $1::uuid AND user_id = $2",
                session_id,
                payload.get("sub"),
            )
        if not owns_conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Find all documents with this session_id
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id FROM documents
            WHERE metadata->>'scope' = 'session'
              AND (
                metadata->>'session_id' = $1
                OR metadata->>'conversation_id' = $1
              )
            """,
            session_id
        )
    
    deleted_count = 0
    for row in rows:
        doc_id = str(row["id"])
        try:
            await _enqueue_delete(doc_id)
            deleted_count += 1
        except Exception as exc:
            pass # continue deleting others
            
    await db.write_audit_log(
        db_pool,
        "session_delete",
        role="user",
        username=payload.get("sub"),
        ip_address=ip_address,
        details={"session_id": session_id, "deleted_count": deleted_count},
    )

    return {"message": f"Queued {deleted_count} files for deletion.", "deleted": deleted_count}

@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_document_endpoint(
    document_id: str,
    request: Request,
    payload: dict = Depends(require_auth),
):
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    db_pool: asyncpg.Pool = request.app.state.db_pool

    doc = await db.get_document(db_pool, document_id)
    if not doc:
        # Idempotent delete: if the document is already gone, treat as success
        return DeleteResponse(
            document_id=document_id,
            filename="unknown",
            message="Document already deleted.",
            vectors_deleted=0,
            minio_deleted=False,
        )

    filename = doc["filename"]
    metadata = json.loads(doc.get("metadata", "{}")) if isinstance(doc.get("metadata"), str) else doc.get("metadata", {})
    scope = _extract_scope(metadata)

    if scope == "library" and not _is_admin(payload):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    if scope == "session":
        conversation_id = _extract_conversation_id(metadata)
        async with db_pool.acquire() as conn:
            owns_conversation = await conn.fetchval(
                "SELECT 1 FROM conversations WHERE id = $1::uuid AND user_id = $2",
                conversation_id,
                payload.get("sub"),
            ) if conversation_id else None
        if not owns_conversation and not _is_admin(payload):
            raise HTTPException(status_code=403, detail="You do not have permission to delete this document")

    try:
        await _enqueue_delete(document_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to queue document deletion") from exc

    await db.write_audit_log(
        db_pool,
        "document_delete",
        role="admin" if _is_admin(payload) else "user",
        username=payload.get("sub"),
        ip_address=ip_address,
        details={"document_id": document_id, "filename": filename, "scope": scope},
    )

    return DeleteResponse(
        document_id=document_id,
        filename=filename,
        message="Document deletion queued.",
        vectors_deleted=0,
        minio_deleted=False,
    )
