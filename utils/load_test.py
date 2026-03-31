"""
============================================================================
FILE: utils/load_test.py
PURPOSE: Load test for the HR RAG Chatbot — simulates concurrent users
         and measures P50/P95/P99 end-to-end query latency.
ARCHITECTURE REF: §12 — Testing & Validation
DEPENDENCIES: httpx, asyncio (standard library)
              Install: pip install httpx
USAGE:
    python utils/load_test.py --base-url https://localhost --users 30
    python utils/load_test.py --base-url https://localhost --users 10 --duration 60
============================================================================

What this test does:
  1. Authenticates as hr_user to get a JWT token
  2. Sends concurrent /query requests from N virtual users
  3. Each user sends a random question from a predefined set
  4. Measures time-to-first-token (TTFT) for SSE streaming responses
  5. Prints a latency report: P50, P95, P99, min, max, error rate

Notes:
  - Uses --insecure mode for self-signed certificates (dev environment)
  - The test uses SSE streaming; latency measured as TTFT (first token arrival)
  - Set BASE_URL and credentials via CLI flags or environment variables
"""

import argparse
import asyncio
import os
import random
import ssl
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Optional


# ─── Sample Queries ────────────────────────────────────────────────────────────
# Realistic HR questions to simulate diverse query patterns
SAMPLE_QUERIES = [
    "How many days of annual leave am I entitled to?",
    "What is the process for applying for sick leave?",
    "What are the working hours policy at the company?",
    "How do I request a no-objection certificate?",
    "What is the maternity leave policy?",
    "Explain the end-of-service gratuity calculation.",
    "What are the public holidays in the UAE?",
    "How do I submit a leave request?",
    "What is the probation period for new employees?",
    "What happens if I exceed my leave balance?",
    "What is the notice period for resignation?",
    "How is overtime calculated?",
    "What is the policy on remote work?",
    "How do I get a salary certificate?",
    "What are the health insurance benefits?",
]


# ─── Result Dataclass ──────────────────────────────────────────────────────────


@dataclass
class QueryResult:
    """Result of a single load test query."""
    user_id: int
    query: str
    ttft_seconds: Optional[float] = None   # Time to first token
    total_seconds: Optional[float] = None  # Total request duration
    token_count: int = 0
    success: bool = False
    error: Optional[str] = None


# ─── Single Query Execution ────────────────────────────────────────────────────


async def run_single_query(
    session,  # httpx.AsyncClient
    base_url: str,
    token: str,
    user_id: int,
    query: str,
) -> QueryResult:
    """
    Execute a single /query request and measure SSE streaming latency.

    Args:
        session: Shared httpx.AsyncClient
        base_url: API base URL (e.g., https://localhost)
        token: JWT Bearer token for authentication
        user_id: Virtual user identifier (for logging)
        query: The HR question to send

    Returns:
        QueryResult with timing metrics and token count
    """
    result = QueryResult(user_id=user_id, query=query)
    start_time = time.perf_counter()
    first_token_time: Optional[float] = None

    try:
        async with session.stream(
            "POST",
            f"{base_url}/api/query",
            json={"query": query},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "text/event-stream",
            },
            timeout=120.0,
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue

                payload = line[5:].strip()
                if payload == "[DONE]":
                    break

                # Check for first token
                if first_token_time is None and '"event": "token"' in payload or '"token":' in payload:
                    first_token_time = time.perf_counter()
                    result.ttft_seconds = first_token_time - start_time

                result.token_count += 1

                if result.token_count == 1 and first_token_time is None:
                    first_token_time = time.perf_counter()
                    result.ttft_seconds = first_token_time - start_time

        result.total_seconds = time.perf_counter() - start_time
        result.success = True

    except Exception as exc:
        result.total_seconds = time.perf_counter() - start_time
        result.error = str(exc)[:100]

    return result


# ─── Authentication ────────────────────────────────────────────────────────────


async def get_jwt_token(
    session,  # httpx.AsyncClient
    base_url: str,
    username: str,
    password: str,
) -> str:
    """Authenticate and return a JWT token."""
    try:
        response = await session.post(
            f"{base_url}/auth/login",
            json={"username": username, "password": password},
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["access_token"]
    except Exception as exc:
        print(f"Authentication failed: {exc}")
        print("Make sure the services are running and credentials are correct.")
        sys.exit(1)


# ─── Load Test Orchestrator ────────────────────────────────────────────────────


async def run_load_test(
    base_url: str,
    num_users: int,
    duration_seconds: int,
    username: str,
    password: str,
    verify_ssl: bool,
) -> None:
    """
    Run the load test with concurrent virtual users.

    Args:
        base_url: API base URL
        num_users: Number of concurrent virtual users
        duration_seconds: How long to run the test (0 = one round per user)
        username: HR user login
        password: HR user password
        verify_ssl: Whether to verify SSL certificates
    """
    import httpx

    # Create SSL context that ignores certificate verification (for dev/self-signed)
    ssl_context = ssl.create_default_context()
    if not verify_ssl:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    async with httpx.AsyncClient(verify=ssl_context) as session:
        print(f"Authenticating as {username}...")
        token = await get_jwt_token(session, base_url, username, password)
        print(f"Authentication successful. Starting load test...")
        print(f"  Users: {num_users}")
        print(f"  Duration: {duration_seconds}s" if duration_seconds > 0 else f"  Mode: one round ({num_users} queries)")
        print()

        all_results: list[QueryResult] = []
        start_time = time.perf_counter()

        async def user_loop(user_id: int) -> list[QueryResult]:
            """Simulate one virtual user sending queries."""
            results = []
            while True:
                query = random.choice(SAMPLE_QUERIES)
                result = await run_single_query(session, base_url, token, user_id, query)
                results.append(result)

                # Check if we should stop
                elapsed = time.perf_counter() - start_time
                if duration_seconds > 0 and elapsed >= duration_seconds:
                    break
                elif duration_seconds == 0:
                    break  # One query per user

                # Small jitter between requests to avoid thundering herd
                await asyncio.sleep(random.uniform(0.1, 0.5))

            return results

        # Launch all virtual users concurrently
        tasks = [user_loop(i + 1) for i in range(num_users)]
        user_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results
        for results in user_results:
            if isinstance(results, list):
                all_results.extend(results)

    # ─── Print Report ─────────────────────────────────────────────────────────
    print_report(all_results)


def print_report(results: list[QueryResult]) -> None:
    """Print a formatted latency report."""
    total = len(results)
    if total == 0:
        print("No results collected.")
        return

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print()
    print("=" * 50)
    print("LOAD TEST RESULTS")
    print("=" * 50)
    print(f"Total queries:   {total}")
    print(f"Successful:      {len(successful)} ({len(successful)/total*100:.1f}%)")
    print(f"Failed:          {len(failed)} ({len(failed)/total*100:.1f}%)")
    print()

    if successful:
        ttft_values = [r.ttft_seconds for r in successful if r.ttft_seconds is not None]
        total_values = [r.total_seconds for r in successful if r.total_seconds is not None]

        if ttft_values:
            ttft_sorted = sorted(ttft_values)
            p50_idx = int(len(ttft_sorted) * 0.50)
            p95_idx = int(len(ttft_sorted) * 0.95)
            p99_idx = int(len(ttft_sorted) * 0.99)

            print("Time to First Token (TTFT):")
            print(f"  P50:  {ttft_sorted[min(p50_idx, len(ttft_sorted)-1)]:.2f}s")
            print(f"  P95:  {ttft_sorted[min(p95_idx, len(ttft_sorted)-1)]:.2f}s")
            print(f"  P99:  {ttft_sorted[min(p99_idx, len(ttft_sorted)-1)]:.2f}s")
            print(f"  Min:  {min(ttft_values):.2f}s")
            print(f"  Max:  {max(ttft_values):.2f}s")
            print(f"  Mean: {statistics.mean(ttft_values):.2f}s")
            print()

        if total_values:
            total_sorted = sorted(total_values)
            p50_idx = int(len(total_sorted) * 0.50)
            p95_idx = int(len(total_sorted) * 0.95)

            print("Total Query Duration:")
            print(f"  P50:  {total_sorted[min(p50_idx, len(total_sorted)-1)]:.2f}s")
            print(f"  P95:  {total_sorted[min(p95_idx, len(total_sorted)-1)]:.2f}s")
            print(f"  Mean: {statistics.mean(total_values):.2f}s")
            print()

    if failed:
        print("Error Summary:")
        error_counts: dict[str, int] = {}
        for r in failed:
            error = r.error or "unknown"
            error_counts[error] = error_counts.get(error, 0) + 1
        for error, count in sorted(error_counts.items(), key=lambda x: -x[1]):
            print(f"  [{count}x] {error[:80]}")
        print()

    print("=" * 50)


# ─── CLI Entry Point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load test for HR RAG Chatbot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python utils/load_test.py --base-url https://localhost --users 30
  python utils/load_test.py --base-url https://192.168.1.10 --users 10 --duration 60
  BASE_URL=https://server python utils/load_test.py
        """,
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", "https://localhost"),
        help="API base URL (default: https://localhost)",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=30,
        help="Number of concurrent virtual users (default: 30)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Test duration in seconds (0 = one round, default: 0)",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("TEST_USERNAME", "hr_user"),
        help="Username for authentication (default: hr_user)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("TEST_PASSWORD", ""),
        help="Password for authentication (set TEST_PASSWORD env var)",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        default=True,
        help="Skip SSL certificate verification (default: True for dev)",
    )

    args = parser.parse_args()

    if not args.password:
        print("ERROR: Password is required.")
        print("Set it via --password flag or TEST_PASSWORD environment variable.")
        sys.exit(1)

    try:
        import httpx  # noqa: F401
    except ImportError:
        print("ERROR: httpx is not installed. Run: pip install httpx")
        sys.exit(1)

    asyncio.run(run_load_test(
        base_url=args.base_url.rstrip("/"),
        num_users=args.users,
        duration_seconds=args.duration,
        username=args.username,
        password=args.password,
        verify_ssl=not args.no_verify_ssl,
    ))


if __name__ == "__main__":
    main()
