from __future__ import annotations

import asyncio
import json
import math
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

QUERY_PACK = (
    "How many days of annual leave am I entitled to?",
    "What is the process for applying for sick leave?",
    "Explain the medical benefits eligibility policy.",
    "How is overtime calculated for employees?",
    "What is the notice period for resignation?",
    "Summarize the probation policy.",
    "How do I request a salary certificate?",
    "What are the public holiday rules in the UAE?",
    "Explain the end-of-service gratuity policy.",
    "What is the policy on remote work?",
    "What documents are required for dependent medical coverage?",
    "How do I apply for leave without pay?",
)
DEFAULT_TIERS = (5, 10, 20, 30)
DEFAULT_ROUNDS = 3
DEFAULT_ROUND_COOLDOWN_SECONDS = 20.0
DEFAULT_TIER_COOLDOWN_SECONDS = 30.0


@dataclass
class QueryResult:
    concurrency: int
    round_index: int
    user_id: int
    query: str
    conversation_id: str | None = None
    started_at_utc: str = ""
    finished_at_utc: str = ""
    ttft_seconds: float | None = None
    total_seconds: float | None = None
    token_events: int = 0
    success: bool = False
    error: str | None = None


@dataclass
class RoundWindow:
    concurrency: int
    round_index: int
    started_at_utc: str
    finished_at_utc: str
    active_seconds: float


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_tiers(raw_value: str | None, users: int | None) -> tuple[int, ...]:
    if users is not None:
        return (users,)
    if not raw_value:
        return DEFAULT_TIERS

    values: list[int] = []
    for token in raw_value.split(","):
        token = token.strip()
        if not token:
            continue
        value = int(token)
        if value <= 0:
            raise ValueError("Concurrency tiers must be positive integers")
        values.append(value)

    if not values:
        raise ValueError("At least one concurrency tier is required")

    return tuple(values)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * pct) - 1))
    return ordered[index]


def format_metric(value: float | None, *, unit: str = "s") -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}{unit}"


def build_monitoring_urls(base_url: str) -> dict[str, str]:
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    return {
        "grafana": f"http://{host}:3000",
        "prometheus": f"http://{host}:9090",
    }


def choose_query(concurrency: int, round_index: int, user_id: int) -> str:
    offset = ((round_index - 1) * concurrency + (user_id - 1)) % len(QUERY_PACK)
    return QUERY_PACK[offset]


def benchmark_output_dir(output_root: str | None) -> Path:
    root = Path(output_root or "benchmark-results")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / timestamp


def read_local_env_value(key: str) -> str | None:
    env_path = Path(".env")
    if not env_path.exists():
        return None

    prefix = f"{key}="
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or not line.startswith(prefix):
                continue
            return line[len(prefix) :].strip()
    except OSError:
        return None

    return None


def summarize_results(
    *,
    concurrency: int,
    results: list[QueryResult],
    rounds: list[RoundWindow],
) -> dict[str, Any]:
    total_requests = len(results)
    successful = [result for result in results if result.success]
    failed = [result for result in results if not result.success]
    ttft_values = [
        result.ttft_seconds for result in successful if result.ttft_seconds is not None
    ]
    total_values = [
        result.total_seconds for result in successful if result.total_seconds is not None
    ]
    error_counts = Counter(result.error or "unknown_error" for result in failed)
    active_seconds = sum(round_window.active_seconds for round_window in rounds)

    return {
        "concurrency": concurrency,
        "total_requests": total_requests,
        "successful_requests": len(successful),
        "failed_requests": len(failed),
        "success_rate": (len(successful) / total_requests) if total_requests else 0.0,
        "ttft_p50_seconds": percentile(ttft_values, 0.50),
        "ttft_p95_seconds": percentile(ttft_values, 0.95),
        "ttft_p99_seconds": percentile(ttft_values, 0.99),
        "ttft_mean_seconds": statistics.mean(ttft_values) if ttft_values else None,
        "total_p50_seconds": percentile(total_values, 0.50),
        "total_p95_seconds": percentile(total_values, 0.95),
        "total_mean_seconds": statistics.mean(total_values) if total_values else None,
        "throughput_rps": (total_requests / active_seconds) if active_seconds > 0 else 0.0,
        "tier_started_at_utc": rounds[0].started_at_utc if rounds else None,
        "tier_finished_at_utc": rounds[-1].finished_at_utc if rounds else None,
        "round_windows": [asdict(round_window) for round_window in rounds],
        "top_errors": [
            {"error": error, "count": count}
            for error, count in error_counts.most_common(5)
        ],
    }


def build_markdown_summary(
    *,
    base_url: str,
    monitoring_urls: dict[str, str],
    username: str,
    tiers: tuple[int, ...],
    rounds: int,
    summaries: list[dict[str, Any]],
) -> str:
    lines = [
        "# HR Copilot Concurrency Benchmark",
        "",
        f"- Base URL: `{base_url}`",
        f"- Benchmark user: `{username}`",
        f"- Reasoning mode: `fast`",
        f"- Concurrency tiers: `{', '.join(str(tier) for tier in tiers)}`",
        f"- Rounds per tier: `{rounds}`",
        f"- Grafana: {monitoring_urls['grafana']}",
        f"- Prometheus: {monitoring_urls['prometheus']}",
        "",
        "## Tier Summary",
        "",
        "| Concurrency | Requests | Success % | TTFT P50 | TTFT P95 | TTFT P99 | Total P50 | Total P95 | Throughput |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for summary in summaries:
        lines.append(
            "| {concurrency} | {total_requests} | {success_rate:.1%} | {ttft_p50} | {ttft_p95} | {ttft_p99} | {total_p50} | {total_p95} | {throughput:.2f} req/s |".format(
                concurrency=summary["concurrency"],
                total_requests=summary["total_requests"],
                success_rate=summary["success_rate"],
                ttft_p50=format_metric(summary["ttft_p50_seconds"]),
                ttft_p95=format_metric(summary["ttft_p95_seconds"]),
                ttft_p99=format_metric(summary["ttft_p99_seconds"]),
                total_p50=format_metric(summary["total_p50_seconds"]),
                total_p95=format_metric(summary["total_p95_seconds"]),
                throughput=summary["throughput_rps"],
            )
        )

    lines.extend(["", "## Grafana Correlation Windows", ""])
    for summary in summaries:
        lines.append(
            f"- `{summary['concurrency']} users`: {summary['tier_started_at_utc']} to {summary['tier_finished_at_utc']}"
        )

    lines.extend(["", "## Top Error Categories", ""])
    for summary in summaries:
        if not summary["top_errors"]:
            lines.append(f"- `{summary['concurrency']} users`: none")
            continue
        rendered = ", ".join(
            f"{item['error']} ({item['count']})" for item in summary["top_errors"]
        )
        lines.append(f"- `{summary['concurrency']} users`: {rendered}")

    return "\n".join(lines) + "\n"


def print_demo_summary(
    summaries: list[dict[str, Any]],
    monitoring_urls: dict[str, str],
) -> None:
    print()
    print("=" * 72)
    print("DEMO SUMMARY")
    print("=" * 72)
    for summary in summaries:
        print(
            f"[{summary['concurrency']:>2} users] "
            f"success {summary['success_rate'] * 100:5.1f}% | "
            f"TTFT P95 {format_metric(summary['ttft_p95_seconds'])} | "
            f"Total P95 {format_metric(summary['total_p95_seconds'])} | "
            f"Throughput {summary['throughput_rps']:.2f} req/s"
        )
    print(f"Grafana:    {monitoring_urls['grafana']}")
    print(f"Prometheus: {monitoring_urls['prometheus']}")
    print("=" * 72)


async def authenticate_session(
    session: httpx.AsyncClient,
    base_url: str,
    username: str,
    password: str,
) -> None:
    response = await session.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        timeout=20.0,
    )
    response.raise_for_status()
    if "access_token" not in session.cookies:
        raise RuntimeError("Login succeeded but access_token cookie was not set")


def apply_access_token(
    session: httpx.AsyncClient,
    *,
    base_url: str,
    access_token: str,
) -> None:
    parsed = urlparse(base_url)
    host = parsed.hostname
    session.headers["Authorization"] = f"Bearer {access_token}"
    session.cookies.set("access_token", access_token, path="/")
    if host:
        session.cookies.set("access_token", access_token, domain=host, path="/")


async def cleanup_conversations(
    session: httpx.AsyncClient,
    base_url: str,
) -> None:
    response = await session.delete(
        f"{base_url}/api/conversations",
        timeout=60.0,
    )
    response.raise_for_status()


async def create_conversation(
    session: httpx.AsyncClient,
    base_url: str,
    title: str,
) -> str:
    response = await session.post(
        f"{base_url}/api/conversations",
        json={"title": title},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["id"]


async def run_single_query(
    session: httpx.AsyncClient,
    *,
    base_url: str,
    concurrency: int,
    round_index: int,
    user_id: int,
    query: str,
) -> QueryResult:
    result = QueryResult(
        concurrency=concurrency,
        round_index=round_index,
        user_id=user_id,
        query=query,
        started_at_utc=utcnow_iso(),
    )
    start_time = time.perf_counter()
    full_text = ""
    stream_error: str | None = None

    try:
        conversation_id = await create_conversation(
            session,
            base_url,
            title=f"Benchmark {concurrency}u r{round_index} q{user_id}",
        )
        result.conversation_id = conversation_id

        async with session.stream(
            "POST",
            f"{base_url}/api/messages/stream",
            json={
                "conversationId": conversation_id,
                "message": query,
                "reasoningMode": "fast",
            },
            headers={"Accept": "text/event-stream"},
            timeout=300.0,
        ) as response:
            response.raise_for_status()

            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue

                try:
                    payload = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                event_type = payload.get("type")
                if event_type == "token":
                    result.token_events += 1
                    if result.ttft_seconds is None:
                        result.ttft_seconds = time.perf_counter() - start_time
                elif event_type == "error":
                    stream_error = str(payload.get("content") or "stream_error")[:200]
                elif event_type == "done":
                    full_text = str(payload.get("fullText") or "")
                    break

        result.total_seconds = time.perf_counter() - start_time
        result.finished_at_utc = utcnow_iso()

        if stream_error:
            result.error = stream_error
        elif not full_text.strip():
            result.error = "empty_final_answer"
        elif result.ttft_seconds is None:
            result.error = "no_first_token_observed"
        else:
            result.success = True

    except Exception as exc:
        result.total_seconds = time.perf_counter() - start_time
        result.finished_at_utc = utcnow_iso()
        result.error = str(exc)[:200]

    return result


async def run_round(
    session: httpx.AsyncClient,
    *,
    base_url: str,
    concurrency: int,
    round_index: int,
) -> tuple[list[QueryResult], RoundWindow]:
    round_started_at = utcnow_iso()
    round_start_time = time.perf_counter()

    tasks = [
        run_single_query(
            session,
            base_url=base_url,
            concurrency=concurrency,
            round_index=round_index,
            user_id=user_id,
            query=choose_query(concurrency, round_index, user_id),
        )
        for user_id in range(1, concurrency + 1)
    ]
    results = await asyncio.gather(*tasks)

    round_window = RoundWindow(
        concurrency=concurrency,
        round_index=round_index,
        started_at_utc=round_started_at,
        finished_at_utc=utcnow_iso(),
        active_seconds=time.perf_counter() - round_start_time,
    )
    return results, round_window


async def run_benchmark(
    *,
    base_url: str,
    username: str,
    password: str | None = None,
    access_token: str | None = None,
    verify_ssl: bool,
    tiers: tuple[int, ...],
    rounds: int,
    round_cooldown_seconds: float,
    tier_cooldown_seconds: float,
    output_root: str | None,
    allow_shared_user: bool,
    cleanup_before: bool = True,
    cleanup_after: bool = True,
) -> dict[str, Any]:
    if username in {"hr_user", "hr_admin"} and not allow_shared_user:
        raise RuntimeError(
            "Refusing to benchmark against hr_user/hr_admin because cleanup would delete demo conversations."
        )
    if not password and not access_token:
        raise RuntimeError("Either password or access_token is required for benchmarking.")

    monitoring_urls = build_monitoring_urls(base_url)
    output_dir = benchmark_output_dir(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(verify=verify_ssl, follow_redirects=True) as session:
        if access_token:
            apply_access_token(session, base_url=base_url, access_token=access_token)
        else:
            await authenticate_session(session, base_url, username, password or "")

        if cleanup_before:
            await cleanup_conversations(session, base_url)

        all_results: list[QueryResult] = []
        tier_summaries: list[dict[str, Any]] = []

        try:
            for tier_index, concurrency in enumerate(tiers):
                tier_results: list[QueryResult] = []
                round_windows: list[RoundWindow] = []

                for round_index in range(1, rounds + 1):
                    round_results, round_window = await run_round(
                        session,
                        base_url=base_url,
                        concurrency=concurrency,
                        round_index=round_index,
                    )
                    tier_results.extend(round_results)
                    round_windows.append(round_window)

                    if round_index < rounds and round_cooldown_seconds > 0:
                        await asyncio.sleep(round_cooldown_seconds)

                summary = summarize_results(
                    concurrency=concurrency,
                    results=tier_results,
                    rounds=round_windows,
                )
                tier_summaries.append(summary)
                all_results.extend(tier_results)

                if tier_index < len(tiers) - 1 and tier_cooldown_seconds > 0:
                    await asyncio.sleep(tier_cooldown_seconds)
        finally:
            if cleanup_after:
                await cleanup_conversations(session, base_url)

    summary_markdown = build_markdown_summary(
        base_url=base_url,
        monitoring_urls=monitoring_urls,
        username=username,
        tiers=tiers,
        rounds=rounds,
        summaries=tier_summaries,
    )
    raw_results_payload = {
        "base_url": base_url,
        "benchmark_user": username,
        "reasoning_mode": "fast",
        "tiers": list(tiers),
        "rounds": rounds,
        "monitoring_urls": monitoring_urls,
        "generated_at_utc": utcnow_iso(),
        "tier_summaries": tier_summaries,
        "results": [asdict(result) for result in all_results],
    }

    summary_path = output_dir / "summary.md"
    results_path = output_dir / "results.json"
    summary_path.write_text(summary_markdown, encoding="utf-8")
    results_path.write_text(
        json.dumps(raw_results_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "monitoring_urls": monitoring_urls,
        "summary_markdown": summary_markdown,
        "summary_path": str(summary_path),
        "results_path": str(results_path),
        "output_dir": str(output_dir),
        "raw_results_payload": raw_results_payload,
        "tier_summaries": tier_summaries,
    }
