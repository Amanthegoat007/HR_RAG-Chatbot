"""
============================================================================
FILE: services/backend/app/db.py
PURPOSE: PostgreSQL CRUD operations for conversations, messages, documents,
         ingestion jobs, and audit log. Uses asyncpg.
============================================================================
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional, List, Dict

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)


async def create_db_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )


# ---------------------------------------------------------------------------
# CONVERSATIONS & MESSAGES
# ---------------------------------------------------------------------------

async def list_conversations(pool: asyncpg.Pool, user_id: str) -> List[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, updated_at FROM conversations WHERE user_id = $1 ORDER BY updated_at DESC",
            user_id
        )
    return [dict(r) for r in rows]

async def create_conversation(pool: asyncpg.Pool, user_id: str, title: str) -> str:
    async with pool.acquire() as conn:
        conv_id = await conn.fetchval(
            "INSERT INTO conversations (user_id, title) VALUES ($1, $2) RETURNING id::text",
            user_id, title
        )
    return conv_id

async def delete_conversation(pool: asyncpg.Pool, conv_id: str, user_id: str) -> bool:
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM conversations WHERE id = $1::uuid AND user_id = $2",
            conv_id, user_id
        )
    return res.endswith("1")

async def delete_all_conversations(pool: asyncpg.Pool, user_id: str) -> int:
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM conversations WHERE user_id = $1",
            user_id
        )
    # returns like "DELETE 5"
    return int(res.split()[-1])

async def fetch_messages(pool: asyncpg.Pool, conv_id: str) -> List[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = $1::uuid ORDER BY created_at ASC",
            conv_id
        )
    return [dict(r) for r in rows]

async def create_message(pool: asyncpg.Pool, conv_id: str, role: str, content: str) -> str:
    """Save a message, and touch the conversation's updated_at via trigger."""
    async with pool.acquire() as conn:
        msg_id = await conn.fetchval(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1::uuid, $2, $3) RETURNING id::text",
            conv_id, role, content
        )
        # Touch conversation explicitly if trigger isn't doing it on message insert
        await conn.execute("UPDATE conversations SET updated_at = NOW() WHERE id = $1::uuid", conv_id)
    return msg_id

async def delete_messages_after(pool: asyncpg.Pool, conv_id: str, msg_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM messages 
            WHERE conversation_id = $1::uuid 
            AND created_at > (SELECT created_at FROM messages WHERE id = $2::uuid LIMIT 1)
            """,
            conv_id, msg_id
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
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO documents
                (id, filename, original_format, minio_path, file_size_bytes, uploaded_by, metadata)
            VALUES
                ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb)
            """,
            document_id, filename, original_format, minio_path, file_size_bytes, uploaded_by, json.dumps(metadata),
        )
    return document_id

async def update_document_status(
    pool: asyncpg.Pool,
    document_id: str,
    status: str,
    **kwargs: Any,
) -> None:
    set_parts = ["status = $2"]
    params: list[Any] = [document_id, status]
    param_idx = 3

    field_map = {
        "markdown_path": "markdown_path",
        "page_count": "page_count",
        "chunk_count": "chunk_count",
        "error_message": "error_message",
        "processed_at": "processed_at",
    }

    for kwarg_key, db_col in field_map.items():
        if kwarg_key in kwargs:
            set_parts.append(f"{db_col} = ${param_idx}")
            params.append(kwargs[kwarg_key])
            param_idx += 1

    if status in ("ready", "failed") and "processed_at" not in kwargs:
        set_parts.append(f"processed_at = ${param_idx}")
        params.append(datetime.now(timezone.utc))
        param_idx += 1

    sql = f"UPDATE documents SET {', '.join(set_parts)} WHERE id = $1::uuid"

    async with pool.acquire() as conn:
        await conn.execute(sql, *params)

async def get_document(pool: asyncpg.Pool, document_id: str) -> Optional[dict[str, Any]]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM documents WHERE id = $1::uuid", document_id)
    return dict(row) if row else None

async def list_documents(pool: asyncpg.Pool, limit: int = 100, offset: int = 0, status_filter: Optional[str] = None) -> tuple[list[dict[str, Any]], int]:
    async with pool.acquire() as conn:
        if status_filter:
            rows = await conn.fetch(
                "SELECT * FROM documents WHERE status = $1 ORDER BY uploaded_at DESC LIMIT $2 OFFSET $3",
                status_filter, limit, offset,
            )
            total = await conn.fetchval("SELECT COUNT(*) FROM documents WHERE status = $1", status_filter)
        else:
            rows = await conn.fetch(
                "SELECT * FROM documents ORDER BY uploaded_at DESC LIMIT $1 OFFSET $2",
                limit, offset,
            )
            total = await conn.fetchval("SELECT COUNT(*) FROM documents")

    return [dict(row) for row in rows], total

async def delete_document_record(pool: asyncpg.Pool, document_id: str) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM documents WHERE id = $1::uuid", document_id)
    return result.split()[-1] == "1"

# ---------------------------------------------------------------------------
# INGESTION JOBS TABLE
# ---------------------------------------------------------------------------

async def create_ingestion_job(pool: asyncpg.Pool, document_id: str, celery_task_id: str) -> str:
    async with pool.acquire() as conn:
        job_id = await conn.fetchval(
            "INSERT INTO ingestion_jobs (document_id, celery_task_id, status) VALUES ($1::uuid, $2, 'queued') RETURNING id::text",
            document_id, celery_task_id,
        )
    return job_id

async def update_ingestion_job(pool: asyncpg.Pool, celery_task_id: str, status: str, **kwargs: Any) -> None:
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
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO audit_log (event_type, role, username, ip_address, details) VALUES ($1, $2, $3, $4, $5::jsonb)",
                event_type, role, username, ip_address, json.dumps(details),
            )
    except Exception as exc:
        logger.error("Audit log write failed", extra={"event": event_type, "error": str(exc)})
