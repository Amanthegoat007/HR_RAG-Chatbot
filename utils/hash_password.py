"""
============================================================================
FILE: utils/hash_password.py
PURPOSE: CLI utility to generate bcrypt password hashes for .env configuration.
ARCHITECTURE REF: §5 — Authentication Service
DEPENDENCIES: passlib (install: pip install passlib[bcrypt])
============================================================================

Usage (cross-platform — runs on Windows, Linux, Mac):
    python utils/hash_password.py <password>

Example:
    python utils/hash_password.py MySecurePassword123!

Output:
    Password hash (bcrypt, cost=12):
    $2b$12$ABC...XYZ

Copy this hash into your .env file:
    ADMIN_PASSWORD_HASH=$2b$12$ABC...XYZ

Why bcrypt cost=12?
  - Cost=12 means 2^12 = 4096 bcrypt iterations
  - Takes ~250ms to verify on a modern CPU
  - This makes brute-force attacks impractically slow
  - The HR chatbot only verifies on login, so the delay is acceptable
  - Do NOT use cost < 10 in production
"""

import sys
import time


def hash_password(password: str) -> str:
    """
    Hash a plaintext password using bcrypt with cost factor 12.

    Args:
        password: The plaintext password to hash.

    Returns:
        The bcrypt hash string (starts with $2b$12$...).

    Raises:
        ImportError: If passlib is not installed.
    """
    try:
        from passlib.context import CryptContext
    except ImportError:
        print("ERROR: passlib is not installed.", file=sys.stderr)
        print("Install it with: pip install passlib[bcrypt]", file=sys.stderr)
        sys.exit(1)

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
    return pwd_ctx.hash(password)


def main() -> None:
    """Entry point: read password from CLI args and print hash."""
    if len(sys.argv) < 2:
        print("Usage: python utils/hash_password.py <password>")
        print()
        print("Example:")
        print("  python utils/hash_password.py MySecurePassword123!")
        sys.exit(1)

    password = sys.argv[1]

    if len(password) < 8:
        print("WARNING: Password is shorter than 8 characters — use a stronger password!", file=sys.stderr)

    print(f"Hashing password (bcrypt cost=12)...")
    start = time.perf_counter()
    hash_str = hash_password(password)
    elapsed = time.perf_counter() - start

    print()
    print(f"Password hash (bcrypt, cost=12):")
    print(hash_str)
    print()
    print(f"(Hash generated in {elapsed:.2f}s)")
    print()
    print("Add this to your .env file:")
    print(f"  ADMIN_PASSWORD_HASH={hash_str}")
    print("  or")
    print(f"  USER_PASSWORD_HASH={hash_str}")


if __name__ == "__main__":
    main()
