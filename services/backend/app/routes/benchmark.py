from uuid import uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request

from app.benchmark_service import (
    acquire_active_lock,
    build_monitoring_urls_for_request,
    initial_run_payload,
    load_active_payload,
    load_latest_payload,
    load_run_payload,
    resolve_benchmark_config,
    release_active_lock,
    store_run_payload,
)
from app.dependencies import require_benchmark
from app.models import (
    BenchmarkBootstrapResponse,
    BenchmarkRunCreatedResponse,
    BenchmarkRunRequest,
    BenchmarkRunStatusResponse,
)
from app.maintenance import run_smoke_benchmark

router = APIRouter()


@router.get("", response_model=BenchmarkBootstrapResponse)
async def get_benchmark_bootstrap(
    request: Request,
    payload: dict = Depends(require_benchmark),
):
    redis_client: aioredis.Redis = request.app.state.redis
    active_run = await load_active_payload(redis_client)
    latest_run = await load_latest_payload(redis_client)
    return BenchmarkBootstrapResponse(
        monitoring=build_monitoring_urls_for_request(request),
        canRun=active_run is None,
        activeRun=active_run,
        latestRun=latest_run,
    )


@router.post("/run", response_model=BenchmarkRunCreatedResponse)
async def launch_benchmark_run(
    body: BenchmarkRunRequest,
    request: Request,
    payload: dict = Depends(require_benchmark),
):
    try:
        benchmark_config = resolve_benchmark_config(body.preset, body.concurrency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    redis_client: aioredis.Redis = request.app.state.redis
    job_id = str(uuid4())
    acquired = await acquire_active_lock(redis_client, job_id)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="A benchmark run is already active.",
        )

    await store_run_payload(
        redis_client,
        job_id,
        initial_run_payload(
            job_id,
            body.preset,
            requested_concurrency=benchmark_config.get("requested_concurrency"),
        ),
    )
    try:
        run_smoke_benchmark.apply_async(
            kwargs={"preset": body.preset, "concurrency": body.concurrency},
            task_id=job_id,
        )
    except Exception as exc:
        await release_active_lock(redis_client, job_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to queue benchmark run.",
        ) from exc
    return BenchmarkRunCreatedResponse(jobId=job_id, status="queued")


@router.get("/runs/{job_id}", response_model=BenchmarkRunStatusResponse)
async def get_benchmark_run(
    job_id: str,
    request: Request,
    payload: dict = Depends(require_benchmark),
):
    redis_client: aioredis.Redis = request.app.state.redis
    run_payload = await load_run_payload(redis_client, job_id)
    if not run_payload:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    return BenchmarkRunStatusResponse(**run_payload)
