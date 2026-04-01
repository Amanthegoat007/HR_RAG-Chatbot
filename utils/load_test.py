"""
============================================================================
FILE: utils/load_test.py
PURPOSE: End-to-end concurrency benchmark for the HR Copilot chat flow.
         Simulates real chat sessions through login -> conversation creation
         -> streaming answer -> conversation cleanup.
DEPENDENCIES: httpx, asyncio (standard library)
USAGE:
    python utils/load_test.py --base-url http://localhost --password ...
    python utils/load_test.py --base-url http://10.119.1.22 --tiers 5,10,20,30 --rounds 3 --password ...
============================================================================
"""

import argparse
import asyncio
import os
import sys

from shared.benchmark_runner import (
    DEFAULT_ROUNDS,
    DEFAULT_ROUND_COOLDOWN_SECONDS,
    DEFAULT_TIER_COOLDOWN_SECONDS,
    parse_tiers,
    print_demo_summary,
    read_local_env_value,
    run_benchmark,
)


def main() -> None:
    default_username = (
        os.environ.get("TEST_USERNAME")
        or os.environ.get("BENCHMARK_USERNAME")
        or read_local_env_value("BENCHMARK_USERNAME")
        or "benchmark_user"
    )

    parser = argparse.ArgumentParser(
        description="End-to-end concurrency benchmark for the HR Copilot chat flow.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", "http://localhost"),
        help="Frontend/base URL that proxies /api/* (default: http://localhost)",
    )
    parser.add_argument(
        "--tiers",
        default="5,10,20,30",
        help="Comma-separated concurrency tiers (default: 5,10,20,30)",
    )
    parser.add_argument(
        "--users",
        type=int,
        default=None,
        help="Legacy single-tier override (e.g. --users 10)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help="Burst rounds per concurrency tier (default: 3)",
    )
    parser.add_argument(
        "--round-cooldown",
        type=float,
        default=DEFAULT_ROUND_COOLDOWN_SECONDS,
        help="Cooldown seconds between rounds in the same tier (default: 20)",
    )
    parser.add_argument(
        "--tier-cooldown",
        type=float,
        default=DEFAULT_TIER_COOLDOWN_SECONDS,
        help="Cooldown seconds between concurrency tiers (default: 30)",
    )
    parser.add_argument(
        "--username",
        default=default_username,
        help="Benchmark login username (default: TEST_USERNAME/BENCHMARK_USERNAME/.env benchmark user)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("TEST_PASSWORD") or os.environ.get("BENCHMARK_PASSWORD") or "",
        help="Benchmark login password (default: TEST_PASSWORD or BENCHMARK_PASSWORD)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("OUTPUT_DIR"),
        help="Output root directory for benchmark artifacts (default: benchmark-results/)",
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Verify SSL certificates (default: disabled for local/self-signed environments)",
    )
    parser.add_argument(
        "--allow-shared-user",
        action="store_true",
        help="Allow cleanup against hr_user/hr_admin. Use with care.",
    )

    args = parser.parse_args()

    if not args.password:
        print("ERROR: Password is required. Set --password or TEST_PASSWORD.")
        sys.exit(1)

    if args.rounds <= 0:
        print("ERROR: --rounds must be a positive integer.")
        sys.exit(1)

    try:
        tiers = parse_tiers(args.tiers, args.users)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    try:
        import httpx  # noqa: F401
    except ImportError:
        print("ERROR: httpx is not installed. Run: pip install httpx")
        sys.exit(1)

    execution = asyncio.run(
        run_benchmark(
            base_url=args.base_url.rstrip("/"),
            username=args.username,
            password=args.password,
            verify_ssl=args.verify_ssl,
            tiers=tiers,
            rounds=args.rounds,
            round_cooldown_seconds=args.round_cooldown,
            tier_cooldown_seconds=args.tier_cooldown,
            output_root=args.output_dir,
            allow_shared_user=args.allow_shared_user,
        )
    )

    print()
    print(f"Summary written to: {execution['summary_path']}")
    print(f"Raw results written to: {execution['results_path']}")
    print_demo_summary(execution["tier_summaries"], execution["monitoring_urls"])


if __name__ == "__main__":
    main()
