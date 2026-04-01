import asyncio
import logging
import re

import asyncpg
import httpx
from celery.signals import worker_process_shutdown

from app.celery_app import celery_app
from app.config import settings
from app.db import create_db_pool, list_expired_session_document_ids

logger = logging.getLogger(__name__)

_db_pool: asyncpg.Pool | None = None
_http_client: httpx.AsyncClient | None = None


def _get_event_loop() -> asyncio.AbstractEventLoop:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


async def _get_db_pool() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        _db_pool = await create_db_pool()
    return _db_pool


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


async def _close_runtime_resources() -> None:
    global _db_pool, _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None


@worker_process_shutdown.connect
def _on_worker_process_shutdown(*_args, **_kwargs) -> None:
    loop = _get_event_loop()
    loop.run_until_complete(_close_runtime_resources())


def _clean_generated_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").replace('"', " ")).strip()
    cleaned = cleaned.removeprefix("Title:").strip()
    return cleaned[:80]


async def _generate_conversation_title_async(conversation_id: str, first_message: str) -> dict[str, str]:
    if not first_message.strip():
        return {"status": "skipped", "reason": "empty_message"}

    db_pool = await _get_db_pool()
    http_client = await _get_http_client()

    async with db_pool.acquire() as conn:
        existing_title = await conn.fetchval(
            "SELECT title FROM conversations WHERE id = $1::uuid",
            conversation_id,
        )

    if existing_title and str(existing_title).strip() and str(existing_title).strip() != "New Chat":
        return {"status": "skipped", "reason": "title_already_set"}

    prompt = (
        "Generate a very concise, 3 to 5 word title for a conversation that starts with "
        "this message. Only return the title itself, no quotes, no conversational filler.\n\n"
        f"Message: {first_message}\n\nTitle:"
    )
    response = await http_client.post(
        f"{settings.llm_server_url}/v1/chat/completions",
        json={
            "model": "local",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 15,
            "temperature": 0.3,
            "skip_special_tokens": True,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()
    title = _clean_generated_title(data["choices"][0]["message"]["content"])
    if not title:
        return {"status": "skipped", "reason": "empty_title"}

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE conversations
            SET title = $1
            WHERE id = $2::uuid
              AND (title IS NULL OR btrim(title) = '' OR title = 'New Chat')
            """,
            title,
            conversation_id,
        )
    return {"status": "updated", "title": title}


async def _cleanup_expired_session_documents_async() -> dict[str, int]:
    db_pool = await _get_db_pool()
    http_client = await _get_http_client()
    document_ids = await list_expired_session_document_ids(db_pool, max_age_hours=24)

    deleted_count = 0
    for document_id in document_ids:
        try:
            response = await http_client.post(
                f"{settings.document_ingest_url}/ingest/internal/delete/{document_id}",
                headers={"X-Ingest-Token": settings.ingest_internal_token},
            )
            response.raise_for_status()
            deleted_count += 1
        except Exception as exc:
            logger.warning(
                "Failed to enqueue expired session document deletion",
                extra={"document_id": document_id, "error": str(exc)},
            )

    return {"expired_documents": len(document_ids), "enqueued_deletes": deleted_count}


@celery_app.task(
    name="app.maintenance.generate_conversation_title",
    bind=True,
    max_retries=1,
    default_retry_delay=15,
)
def generate_conversation_title(self, conversation_id: str, first_message: str) -> dict[str, str]:
    loop = _get_event_loop()
    try:
        return loop.run_until_complete(_generate_conversation_title_async(conversation_id, first_message))
    except Exception as exc:
        logger.warning(
            "Conversation title generation failed",
            extra={"conversation_id": conversation_id, "error": str(exc)},
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {"status": "failed", "reason": str(exc)}


@celery_app.task(
    name="app.maintenance.cleanup_expired_session_documents",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def cleanup_expired_session_documents(self) -> dict[str, int]:
    loop = _get_event_loop()
    try:
        return loop.run_until_complete(_cleanup_expired_session_documents_async())
    except Exception as exc:
        logger.warning("Expired session cleanup failed", extra={"error": str(exc)})
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {"expired_documents": 0, "enqueued_deletes": 0}
