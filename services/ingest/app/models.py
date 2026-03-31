"""
============================================================================
FILE: services/ingest/app/models.py
PURPOSE: Pydantic schemas for the ingest service API.
ARCHITECTURE REF: §3 — Document Ingestion Pipeline, §7 — Database Schema
DEPENDENCIES: pydantic
============================================================================
"""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any


class UploadResponse(BaseModel):
    """Response when a document is uploaded successfully."""
    document_id: str = Field(description="UUID of the created document record")
    filename: str
    file_size_bytes: int
    status: str = Field(description="'pending' — processing queued via Celery")
    job_id: str = Field(description="Celery task ID for tracking processing status")
    message: str


class DocumentMetadata(BaseModel):
    """Metadata for a single document in the system."""
    id: str
    filename: str
    original_format: str
    status: str          # queued | pending | normalizing | processing | embedding | ready | failed | needs_review
    file_size_bytes: int
    page_count: int | None
    chunk_count: int
    uploaded_by: str
    uploaded_at: datetime
    processed_at: datetime | None
    error_message: str | None
    metadata: dict[str, Any] = {}


class DocumentListResponse(BaseModel):
    """Response for GET /ingest/documents."""
    documents: list[DocumentMetadata]
    total: int


class DeleteResponse(BaseModel):
    """Response when a document is deleted."""
    document_id: str
    filename: str
    message: str
    vectors_deleted: int   # Number of Qdrant vectors removed
    minio_deleted: bool    # Whether MinIO files were removed


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float
    dependencies: dict[str, str]
