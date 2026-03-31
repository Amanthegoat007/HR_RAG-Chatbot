"""
============================================================================
FILE: services/ingest/app/db.py
PURPOSE: PostgreSQL CRUD operations for document metadata, ingestion jobs,
         and audit log. Uses asyncpg for non-blocking async DB access.
ARCHITECTURE REF: §7 — Database Schema (PostgreSQL)
DEPENDENCIES: asyncpg
============================================================================
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)


async def create_db_pool() -> asyncpg.Pool:
    """
    Create the asyncpg connection pool used by both the API and worker.

    Returns:
        asyncpg connection pool.
    """
    return await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )


# ---------------------------------------------------------------------------
# DOCUMENTS TABLE
# ---------------------------------------------------------------------------

async def create_document_record(
    pool: asyncpg.Pool,
    document_id: str,
    filename: str,
    original_format: str,
    minio_path: str,
    file_size_bytes: int,
    uploaded_by: str,
    metadata: dict[str, Any],
) -> str:
    """
    Insert a new document record with status='pending'.

    Called immediately after upload, before Celery task is queued.

    Args:
        pool: asyncpg connection pool.
        document_id: Pre-generated UUID.
        filename: Original filename.
        original_format: File extension (pdf, docx, etc.).
        minio_path: Path to original file in MinIO.
        file_size_bytes: File size for tracking.
        uploaded_by: Username of uploader (from JWT).
        metadata: Initial metadata dict.

    Returns:
        The document_id (confirming successful insert).
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO documents
                (id, filename, original_format, minio_path, file_size_bytes, uploaded_by, metadata)
            VALUES
                ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb)
            """,
            document_id,
            filename,
            original_format,
            minio_path,
            file_size_bytes,
            uploaded_by,
            json.dumps(metadata),
        )
    return document_id


async def update_document_status(
    pool: asyncpg.Pool,
    document_id: str,
    status: str,
    **kwargs: Any,
) -> None:
    """
    Update document status and optional fields after processing.

    Args:
        pool: asyncpg connection pool.
        document_id: UUID of the document.
        status: New status (pending/normalizing/processing/embedding/ready/failed/needs_review).
        **kwargs: Optional fields to update:
            - markdown_path: MinIO path to markdown file
            - page_count: Number of pages extracted
            - chunk_count: Number of chunks created
            - error_message: Error description (for failed status)
            - metadata: JSON-serializable metadata payload
            - processed_at: Completion timestamp
    """
    # Build dynamic SET clause based on provided kwargs
    set_parts = ["status = $2"]
    params: list[Any] = [document_id, status]
    param_idx = 3

    field_map = {
        "markdown_path": "markdown_path",
        "page_count": "page_count",
        "chunk_count": "chunk_count",
        "error_message": "error_message",
        "metadata": "metadata",
        "processed_at": "processed_at",
    }

    for kwarg_key, db_col in field_map.items():
        if kwarg_key in kwargs:
            set_parts.append(f"{db_col} = ${param_idx}")
            if kwarg_key == "metadata":
                params.append(json.dumps(kwargs[kwarg_key]))
            else:
                params.append(kwargs[kwarg_key])
            param_idx += 1

    # Auto-set processed_at when reaching terminal states
    if status in ("ready", "failed", "needs_review") and "processed_at" not in kwargs:
        set_parts.append(f"processed_at = ${param_idx}")
        params.append(datetime.utcnow())
        param_idx += 1

    sql = f"UPDATE documents SET {', '.join(set_parts)} WHERE id = $1::uuid"

    async with pool.acquire() as conn:
        await conn.execute(sql, *params)


async def get_document(
    pool: asyncpg.Pool,
    document_id: str,
) -> Optional[dict[str, Any]]:
    """
    Fetch a single document record by ID.

    Args:
        pool: asyncpg connection pool.
        document_id: UUID of the document.

    Returns:
        Document record as dict, or None if not found.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM documents WHERE id = $1::uuid",
            document_id,
        )
    return dict(row) if row else None


async def list_documents(
    pool: asyncpg.Pool,
    limit: int = 100,
    offset: int = 0,
    status_filter: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    List all documents with optional status filtering.

    Args:
        pool: asyncpg connection pool.
        limit: Maximum rows to return.
        offset: Pagination offset.
        status_filter: Optional status to filter by.

    Returns:
        Tuple of (list of document dicts, total count).
    """
    async with pool.acquire() as conn:
        if status_filter:
            rows = await conn.fetch(
                """
                SELECT * FROM documents
                WHERE status = $1
                ORDER BY uploaded_at DESC
                LIMIT $2 OFFSET $3
                """,
                status_filter, limit, offset,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM documents WHERE status = $1", status_filter
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM documents ORDER BY uploaded_at DESC LIMIT $1 OFFSET $2",
                limit, offset,
            )
            total = await conn.fetchval("SELECT COUNT(*) FROM documents")

    return [dict(row) for row in rows], total


async def delete_document_record(
    pool: asyncpg.Pool,
    document_id: str,
) -> bool:
    """
    Delete a document record (and cascade to ingestion_jobs).

    Args:
        pool: asyncpg connection pool.
        document_id: UUID of the document.

    Returns:
        True if a row was deleted, False if not found.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM documents WHERE id = $1::uuid", document_id
        )
    # result is like "DELETE 1" or "DELETE 0"
    return result.split()[-1] == "1"


# ---------------------------------------------------------------------------
# INGESTION JOBS TABLE
# ---------------------------------------------------------------------------

async def create_ingestion_job(
    pool: asyncpg.Pool,
    document_id: str,
    celery_task_id: str,
) -> str:
    """
    Create an ingestion job record when a Celery task is queued.

    Args:
        pool: asyncpg connection pool.
        document_id: UUID of the document being processed.
        celery_task_id: ID returned by Celery when the task is dispatched.

    Returns:
        Job UUID.
    """
    async with pool.acquire() as conn:
        job_id = await conn.fetchval(
            """
            INSERT INTO ingestion_jobs (document_id, celery_task_id, status)
            VALUES ($1::uuid, $2, 'queued')
            RETURNING id::text
            """,
            document_id, celery_task_id,
        )
    return job_id


async def update_ingestion_job(
    pool: asyncpg.Pool,
    celery_task_id: str,
    status: str,
    **kwargs: Any,
) -> None:
    """
    Update ingestion job status (called from Celery worker).

    Args:
        pool: asyncpg connection pool.
        celery_task_id: The Celery task ID to update.
        status: New job status.
        **kwargs: Optional: started_at, completed_at, error_message, processing_time_seconds
    """
    set_parts = ["status = $2"]
    params: list[Any] = [celery_task_id, status]
    param_idx = 3

    for key in ("started_at", "completed_at", "error_message", "processing_time_seconds"):
        if key in kwargs:
            set_parts.append(f"{key} = ${param_idx}")
            params.append(kwargs[key])
            param_idx += 1

    sql = f"UPDATE ingestion_jobs SET {', '.join(set_parts)} WHERE celery_task_id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, *params)


# ---------------------------------------------------------------------------
# AUDIT LOG TABLE
# ---------------------------------------------------------------------------

async def write_audit_log(
    pool: asyncpg.Pool,
    event_type: str,
    role: Optional[str],
    username: Optional[str],
    ip_address: Optional[str],
    details: dict[str, Any],
) -> None:
    """
    Write an event to the audit log.

    Args:
        pool: asyncpg connection pool.
        event_type: Event type matching the CHECK constraint in init.sql.
        role: User role or None.
        username: Username or None.
        ip_address: Client IP or None.
        details: Event-specific details dict.
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (event_type, role, username, ip_address, details)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                event_type, role, username, ip_address, json.dumps(details),
            )
    except Exception as exc:
        # Audit log failure must not block the main operation
        logger.error("Audit log write failed", extra={"event": event_type, "error": str(exc)})
