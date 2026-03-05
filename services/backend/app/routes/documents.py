from fastapi import APIRouter, Depends, Request, HTTPException, File, UploadFile, status
from typing import Optional
import json
import uuid
import asyncpg
from pathlib import Path

from app.models import DocumentMetadata, DocumentListResponse, UploadResponse, DeleteResponse
from app.dependencies import require_auth, require_admin
from app import db
from app.config import settings
from app.minio_client import upload_file, get_minio_client
# Import celery tasks
from app.tasks import process_document, delete_document as delete_document_task

router = APIRouter()

@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    payload: dict = Depends(require_admin) # Admin only
):
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    
    # Validate size using chunked reading to prevent OOM
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(1024 * 1024)  # Read 1MB at a time
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large. Maximum size: {settings.max_upload_size_mb} MB")
        chunks.append(chunk)
    file_bytes = b"".join(chunks)

    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ("pdf", "docx", "xlsx", "pptx", "txt", "md"):
        raise HTTPException(status_code=415, detail=f"Unsupported format: .{ext}")

    document_id = str(uuid.uuid4())
    db_pool: asyncpg.Pool = request.app.state.db_pool
    minio_client = request.app.state.minio_client

    content_type = file.content_type or "application/octet-stream"
    minio_path = upload_file(minio_client, document_id, filename, file_bytes, content_type)

    initial_metadata = {"filename": filename, "format": ext}
    await db.create_document_record(
        db_pool, document_id, filename, ext, minio_path,
        len(file_bytes), payload.get("sub", "hr_admin"), initial_metadata,
    )

    task = process_document.apply_async(args=[document_id], queue="document_processing", task_id=str(uuid.uuid4()))
    job_id = await db.create_ingestion_job(db_pool, document_id, task.id)

    await db.write_audit_log(
        db_pool, "upload_start", role="admin", username=payload.get("sub"),
        ip_address=ip_address,
        details={"filename": filename, "document_id": document_id, "size": len(file_bytes)},
    )

    return UploadResponse(
        document_id=document_id, filename=filename, file_size_bytes=len(file_bytes),
        status="pending", job_id=task.id, message="Document queued for processing."
    )

@router.get("", response_model=DocumentListResponse)
async def list_all_documents(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    payload: dict = Depends(require_auth) # Anyone can list
):
    db_pool: asyncpg.Pool = request.app.state.db_pool
    rows, total = await db.list_documents(db_pool, limit, offset, status_filter)

    documents = []
    for row in rows:
        documents.append(DocumentMetadata(
            id=str(row["id"]), filename=row["filename"], original_format=row["original_format"],
            status=row["status"], file_size_bytes=row["file_size_bytes"],
            page_count=row["page_count"], chunk_count=row["chunk_count"] or 0,
            uploaded_by=row["uploaded_by"] or "hr_admin", uploaded_at=row["uploaded_at"],
            processed_at=row.get("processed_at"), error_message=row.get("error_message"),
            metadata=json.loads(row.get("metadata", "{}")) if isinstance(row.get("metadata"), str) else row.get("metadata", {})
        ))

    return DocumentListResponse(documents=documents, total=total)

@router.get("/{document_id}", response_model=DocumentMetadata)
async def get_document_status(
    document_id: str,
    request: Request,
    payload: dict = Depends(require_auth)
):
    db_pool: asyncpg.Pool = request.app.state.db_pool
    doc = await db.get_document(db_pool, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentMetadata(
        id=str(doc["id"]), filename=doc["filename"], original_format=doc["original_format"],
        status=doc["status"], file_size_bytes=doc["file_size_bytes"],
        page_count=doc["page_count"], chunk_count=doc["chunk_count"] or 0,
        uploaded_by=doc["uploaded_by"] or "hr_admin", uploaded_at=doc["uploaded_at"],
        processed_at=doc.get("processed_at"), error_message=doc.get("error_message"),
        metadata=json.loads(doc.get("metadata", "{}")) if isinstance(doc.get("metadata"), str) else doc.get("metadata", {})
    )

@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_document_endpoint(
    document_id: str,
    request: Request,
    payload: dict = Depends(require_admin) # Admin only
):
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    db_pool: asyncpg.Pool = request.app.state.db_pool

    doc = await db.get_document(db_pool, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    filename = doc["filename"]
    delete_document_task.apply_async(args=[document_id, filename], queue="document_processing")

    await db.write_audit_log(
        db_pool, "document_delete", role="admin", username=payload.get("sub"),
        ip_address=ip_address,
        details={"document_id": document_id, "filename": filename},
    )

    return DeleteResponse(
        document_id=document_id, filename=filename, message="Document deletion queued.",
        vectors_deleted=0, minio_deleted=False,
    )
