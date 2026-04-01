from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import redis.asyncio as aioredis
from fastapi import Request

from app.config import settings
from app.services.auth_service import create_access_token_for_user

ACTIVE_LOCK_KEY = "benchmark:active"
LATEST_RUN_KEY = "benchmark:latest"
RUN_KEY_PREFIX = "benchmark:run:"
LOCK_TTL_SECONDS = 1800
RUN_TTL_SECONDS = 86400
MAX_BENCHMARK_CONCURRENCY = 30
GRAFANA_DASHBOARD_SUFFIX = "/d/hr-rag-overview/hr-rag-chatbot-system-overview?orgId=1&refresh=30s"
PRESETS: dict[str, dict[str, Any]] = {
    "smoke-1": {
        "tiers": (1,),
        "rounds": 1,
        "round_cooldown_seconds": 0.0,
        "tier_cooldown_seconds": 0.0,
    },
    "smoke-5": {
        "tiers": (5,),
        "rounds": 1,
        "round_cooldown_seconds": 0.0,
        "tier_cooldown_seconds": 0.0,
    },
    "smoke-10": {
        "tiers": (10,),
        "rounds": 1,
        "round_cooldown_seconds": 0.0,
        "tier_cooldown_seconds": 0.0,
    },
    "smoke-20": {
        "tiers": (20,),
        "rounds": 1,
        "round_cooldown_seconds": 0.0,
        "tier_cooldown_seconds": 0.0,
    },
    "smoke-30": {
        "tiers": (30,),
        "rounds": 1,
        "round_cooldown_seconds": 0.0,
        "tier_cooldown_seconds": 0.0,
    },
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_key(job_id: str) -> str:
    return f"{RUN_KEY_PREFIX}{job_id}"


def _with_suffix(base_url: str, suffix: str) -> str:
    trimmed = base_url.rstrip("/")
    if suffix.startswith("/") and trimmed.endswith(suffix):
        return trimmed
    if "/d/" in trimmed or trimmed.endswith(".json"):
        return trimmed
    return f"{trimmed}{suffix}"


def build_monitoring_urls_for_request(request: Request) -> dict[str, str]:
    if settings.grafana_public_url and settings.prometheus_public_url:
        return {
            "grafanaUrl": _with_suffix(
                settings.grafana_public_url,
                GRAFANA_DASHBOARD_SUFFIX,
            ),
            "prometheusUrl": settings.prometheus_public_url,
        }

    parsed = urlparse(str(request.base_url))
    host = parsed.hostname or request.url.hostname or "localhost"
    scheme = parsed.scheme or request.url.scheme or "http"
    return {
        "grafanaUrl": _with_suffix(
            settings.grafana_public_url or f"{scheme}://{host}:3000",
            GRAFANA_DASHBOARD_SUFFIX,
        ),
        "prometheusUrl": settings.prometheus_public_url or f"{scheme}://{host}:9090",
    }


def build_benchmark_access_token() -> str:
    if not settings.benchmark_username:
        raise RuntimeError("BENCHMARK_USERNAME is not configured")
    return create_access_token_for_user(settings.benchmark_username, "benchmark")


def resolve_benchmark_config(
    preset: str,
    requested_concurrency: int | None = None,
) -> dict[str, Any]:
    if preset == "smoke-custom":
        concurrency = requested_concurrency
        if concurrency is None:
            raise ValueError("Custom benchmark runs require a concurrency value.")
        if concurrency < 1 or concurrency > MAX_BENCHMARK_CONCURRENCY:
            raise ValueError(
                f"Custom benchmark concurrency must be between 1 and {MAX_BENCHMARK_CONCURRENCY}.",
            )
        return {
            "tiers": (concurrency,),
            "rounds": 1,
            "round_cooldown_seconds": 0.0,
            "tier_cooldown_seconds": 0.0,
            "requested_concurrency": concurrency,
        }

    if preset not in PRESETS:
        raise ValueError(f"Unknown benchmark preset: {preset}")

    config = PRESETS[preset]
    return {
        **config,
        "requested_concurrency": config["tiers"][0],
    }


def normalize_tier_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not summary:
        return None
    return {
        "concurrency": summary.get("concurrency", 0),
        "totalRequests": summary.get("total_requests", 0),
        "successRate": summary.get("success_rate", 0.0),
        "ttftP95Seconds": summary.get("ttft_p95_seconds"),
        "totalP95Seconds": summary.get("total_p95_seconds"),
        "throughputRps": summary.get("throughput_rps", 0.0),
        "tierStartedAtUtc": summary.get("tier_started_at_utc"),
        "tierFinishedAtUtc": summary.get("tier_finished_at_utc"),
        "topErrors": summary.get("top_errors", []),
    }


async def acquire_active_lock(redis_client: aioredis.Redis, job_id: str) -> bool:
    return bool(
        await redis_client.set(
            ACTIVE_LOCK_KEY,
            job_id,
            ex=LOCK_TTL_SECONDS,
            nx=True,
        )
    )


async def release_active_lock(redis_client: aioredis.Redis, job_id: str) -> None:
    current = await redis_client.get(ACTIVE_LOCK_KEY)
    if current == job_id:
        await redis_client.delete(ACTIVE_LOCK_KEY)


async def extend_active_lock(redis_client: aioredis.Redis, job_id: str) -> None:
    current = await redis_client.get(ACTIVE_LOCK_KEY)
    if current == job_id:
        await redis_client.expire(ACTIVE_LOCK_KEY, LOCK_TTL_SECONDS)


async def get_active_job_id(redis_client: aioredis.Redis) -> str | None:
    active = await redis_client.get(ACTIVE_LOCK_KEY)
    return active if isinstance(active, str) and active else None


async def load_payload(redis_client: aioredis.Redis, key: str) -> dict[str, Any] | None:
    raw = await redis_client.get(key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def store_run_payload(
    redis_client: aioredis.Redis,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    await redis_client.set(run_key(job_id), json.dumps(payload), ex=RUN_TTL_SECONDS)


async def load_run_payload(
    redis_client: aioredis.Redis,
    job_id: str,
) -> dict[str, Any] | None:
    return await load_payload(redis_client, run_key(job_id))


async def store_latest_payload(
    redis_client: aioredis.Redis,
    payload: dict[str, Any],
) -> None:
    await redis_client.set(LATEST_RUN_KEY, json.dumps(payload), ex=RUN_TTL_SECONDS)


async def load_latest_payload(redis_client: aioredis.Redis) -> dict[str, Any] | None:
    return await load_payload(redis_client, LATEST_RUN_KEY)


async def load_active_payload(redis_client: aioredis.Redis) -> dict[str, Any] | None:
    job_id = await get_active_job_id(redis_client)
    if not job_id:
        return None
    return await load_run_payload(redis_client, job_id)


def initial_run_payload(
    job_id: str,
    preset: str,
    requested_concurrency: int | None = None,
) -> dict[str, Any]:
    return {
        "jobId": job_id,
        "preset": preset,
        "requestedConcurrency": requested_concurrency,
        "status": "queued",
        "queuedAtUtc": utcnow_iso(),
        "startedAtUtc": None,
        "finishedAtUtc": None,
        "summary": None,
        "error": None,
        "summaryPath": None,
        "resultsPath": None,
    }


def completed_run_payload(
    *,
    existing: dict[str, Any],
    status: str,
    finished_at_utc: str,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
    summary_path: str | None = None,
    results_path: str | None = None,
) -> dict[str, Any]:
    payload = {
        **existing,
        "status": status,
        "finishedAtUtc": finished_at_utc,
        "summary": summary,
        "error": error,
        "summaryPath": summary_path,
        "resultsPath": results_path,
    }
    return payload
