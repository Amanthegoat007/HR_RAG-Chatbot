import asyncio
import logging
import re

import asyncpg
import httpx
import redis.asyncio as aioredis
from celery.signals import worker_process_shutdown

from app.benchmark_service import (
    build_benchmark_access_token,
    completed_run_payload,
    extend_active_lock,
    load_run_payload,
    normalize_tier_summary,
    resolve_benchmark_config,
    release_active_lock,
    store_latest_payload,
    store_run_payload,
    utcnow_iso,
)
from app.celery_app import celery_app
from app.config import settings
from app.db import create_db_pool, list_expired_session_document_ids
from shared.benchmark_runner import run_benchmark

logger = logging.getLogger(__name__)

_db_pool: asyncpg.Pool | None = None
_http_client: httpx.AsyncClient | None = None
_redis_client: aioredis.Redis | None = None


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


async def _get_redis_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def _close_runtime_resources() -> None:
    global _db_pool, _http_client, _redis_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


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


async def _run_smoke_benchmark_async(
    job_id: str,
    preset: str,
    concurrency: int | None = None,
) -> dict[str, str]:
    redis_client = await _get_redis_client()
    existing = await load_run_payload(redis_client, job_id)
    if not existing:
        existing = {
            "jobId": job_id,
            "preset": preset,
            "requestedConcurrency": concurrency,
            "queuedAtUtc": utcnow_iso(),
        }

    running_payload = {
        **existing,
        "status": "running",
        "startedAtUtc": utcnow_iso(),
        "finishedAtUtc": None,
        "error": None,
    }
    await store_run_payload(redis_client, job_id, running_payload)
    await extend_active_lock(redis_client, job_id)

    try:
        access_token = build_benchmark_access_token()
        preset_config = resolve_benchmark_config(preset, concurrency)
        execution = await run_benchmark(
            base_url=settings.frontend_internal_url.rstrip("/"),
            username=settings.benchmark_username or "benchmark_user",
            access_token=access_token,
            verify_ssl=False,
            tiers=preset_config["tiers"],
            rounds=preset_config["rounds"],
            round_cooldown_seconds=preset_config["round_cooldown_seconds"],
            tier_cooldown_seconds=preset_config["tier_cooldown_seconds"],
            output_root="benchmark-results",
            allow_shared_user=False,
        )
        raw_summary = execution["tier_summaries"][0] if execution["tier_summaries"] else None
        final_payload = completed_run_payload(
            existing=running_payload,
            status="succeeded",
            finished_at_utc=utcnow_iso(),
            summary=normalize_tier_summary(raw_summary),
            summary_path=execution["summary_path"],
            results_path=execution["results_path"],
        )
        await store_run_payload(redis_client, job_id, final_payload)
        await store_latest_payload(redis_client, final_payload)
        return {"status": "succeeded", "job_id": job_id}
    except Exception as exc:
        failed_payload = completed_run_payload(
            existing=running_payload,
            status="failed",
            finished_at_utc=utcnow_iso(),
            error=str(exc),
        )
        await store_run_payload(redis_client, job_id, failed_payload)
        await store_latest_payload(redis_client, failed_payload)
        logger.warning(
            "Smoke benchmark failed",
            extra={"job_id": job_id, "preset": preset, "error": str(exc)},
        )
        return {"status": "failed", "job_id": job_id}
    finally:
        await release_active_lock(redis_client, job_id)


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


@celery_app.task(
    name="app.maintenance.run_smoke_benchmark",
    bind=True,
    max_retries=0,
)
def run_smoke_benchmark(self, preset: str, concurrency: int | None = None) -> dict[str, str]:
    loop = _get_event_loop()
    return loop.run_until_complete(
        _run_smoke_benchmark_async(self.request.id, preset, concurrency),
    )
