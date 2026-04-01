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


def normalize_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def normalize_json_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "json",
        schema="pg_catalog",
        encoder=json.dumps,
        decoder=json.loads,
        format="text",
    )
    await conn.set_type_codec(
        "jsonb",
        schema="pg_catalog",
        encoder=json.dumps,
        decoder=json.loads,
        format="text",
    )


async def create_db_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=2,
        max_size=10,
        command_timeout=30,
        init=_init_connection,
    )


async def ensure_runtime_schema(pool: asyncpg.Pool) -> None:
    """
    Apply lightweight runtime migrations required by the backend.

    The project still uses db/init.sql for fresh environments, but existing
    deployments need additive migrations when containers restart.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            """
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
            """
            SELECT id, role, content, metadata, created_at
            FROM messages
            WHERE conversation_id = $1::uuid
            ORDER BY created_at ASC
            """,
            conv_id
        )
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["metadata"] = normalize_json_object(payload.get("metadata"))
        normalized_rows.append(payload)
    return normalized_rows

async def create_message(
    pool: asyncpg.Pool,
    conv_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Save a message, and touch the conversation's updated_at via trigger."""
    payload = metadata or {}
    async with pool.acquire() as conn:
        msg_id = await conn.fetchval(
            """
            INSERT INTO messages (conversation_id, role, content, metadata)
            VALUES ($1::uuid, $2, $3, $4::jsonb)
            RETURNING id::text
            """,
            conv_id, role, content, payload
        )
        # Touch conversation explicitly if trigger isn't doing it on message insert
        await conn.execute("UPDATE conversations SET updated_at = NOW() WHERE id = $1::uuid", conv_id)
    return msg_id


async def conversation_has_session_documents(pool: asyncpg.Pool, conv_id: str) -> bool:
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                """
                SELECT 1
                FROM documents
                WHERE metadata->>'scope' = 'session'
                  AND (
                    metadata->>'conversation_id' = $1
                    OR metadata->>'session_id' = $1
                  )
                LIMIT 1
                """,
                conv_id,
            )
        )

async def fetch_popular_questions(pool: asyncpg.Pool, limit: int = 5) -> List[str]:
    """Fetch the most frequently asked user questions."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT trim(content) as question
            FROM messages
            WHERE role = 'user'
              AND content IS NOT NULL
              AND length(trim(content)) > 15
            GROUP BY trim(content)
            ORDER BY count(*) DESC
            LIMIT $1
            """,
            limit
        )
    return [r["question"] for r in rows]

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
            document_id, filename, original_format, minio_path, file_size_bytes, uploaded_by, metadata,
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
        "metadata": "metadata",
    }

    for kwarg_key, db_col in field_map.items():
        if kwarg_key in kwargs:
            set_parts.append(f"{db_col} = ${param_idx}")
            value = kwargs[kwarg_key]
            if kwarg_key == "metadata":
                set_parts[-1] = f"{db_col} = ${param_idx}::jsonb"
            params.append(value)
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
    if not row:
        return None
    payload = dict(row)
    payload["metadata"] = normalize_json_object(payload.get("metadata"))
    return payload


async def get_documents_by_ids(
    pool: asyncpg.Pool,
    document_ids: list[str],
) -> dict[str, dict[str, Any]]:
    unique_ids = list(dict.fromkeys(doc_id for doc_id in document_ids if doc_id))
    if not unique_ids:
        return {}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM documents WHERE id = ANY($1::uuid[])",
            unique_ids,
        )
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = dict(row)
        payload["metadata"] = normalize_json_object(payload.get("metadata"))
        normalized[str(row["id"])] = payload
    return normalized

async def list_documents(
    pool: asyncpg.Pool,
    limit: int = 100,
    offset: int = 0,
    status_filter: Optional[str] = None,
    scope: Optional[str] = None,
    session_owner_user_id: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    filters: list[str] = []
    params: list[Any] = []

    if status_filter:
        params.append(status_filter)
        filters.append(f"status = ${len(params)}")

    if scope == "session":
        filters.append(
            "(metadata->>'scope' = 'session' OR metadata ? 'session_id' OR metadata ? 'conversation_id')"
        )
        if session_owner_user_id:
            params.append(session_owner_user_id)
            filters.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM conversations c
                    WHERE c.id::text = COALESCE(
                        NULLIF(documents.metadata->>'conversation_id', ''),
                        NULLIF(documents.metadata->>'session_id', '')
                    )
                      AND c.user_id = ${len(params)}
                )
                """
            )
    elif scope == "library":
        filters.append(
            "(metadata->>'scope' IS NULL OR metadata->>'scope' = 'library') AND NOT (metadata ? 'session_id') AND NOT (metadata ? 'conversation_id')"
        )

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    async with pool.acquire() as conn:
        params_with_paging = [*params, limit, offset]
        rows = await conn.fetch(
            f"SELECT * FROM documents {where_clause} ORDER BY uploaded_at DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}",
            *params_with_paging,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM documents {where_clause}",
            *params,
        )

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["metadata"] = normalize_json_object(payload.get("metadata"))
        normalized_rows.append(payload)
    return normalized_rows, total

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
                event_type, role, username, ip_address, details,
            )
    except Exception as exc:
        logger.error("Audit log write failed", extra={"event": event_type, "error": str(exc)})


async def list_expired_session_document_ids(pool: asyncpg.Pool, max_age_hours: int = 24) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text AS id
            FROM documents
            WHERE metadata->>'scope' = 'session'
              AND uploaded_at < NOW() - ($1::text || ' hours')::interval
            ORDER BY uploaded_at ASC
            """,
            max_age_hours,
        )
    return [row["id"] for row in rows]
