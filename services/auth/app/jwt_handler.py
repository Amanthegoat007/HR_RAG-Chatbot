"""
============================================================================
FILE: services/auth/app/jwt_handler.py
PURPOSE: JWT token creation for the auth service. Delegates to the shared
         jwt_utils module (which also handles validation in other services).
ARCHITECTURE REF: §9 — Security Implementation
DEPENDENCIES: shared/jwt_utils.py
============================================================================

The auth service is the ONLY service that creates JWTs.
Other services (query-svc, ingest-svc) only VALIDATE JWTs using shared/jwt_utils.py.
This is a key security design principle: token issuance is centralized.
"""

import sys
sys.path.insert(0, "/app")

from shared.jwt_utils import create_access_token, TokenData, decode_token

from app.config import settings


def issue_token(username: str, role: str) -> str:
    """
    Issue a JWT access token for an authenticated user.

    Wraps the shared create_access_token function with service-specific
    configuration (secret and expiry from environment variables).

    Args:
        username: The authenticated user's username.
        role: "admin" or "user"

    Returns:
        Signed JWT string.
    """
    return create_access_token(
        username=username,
        role=role,
        secret=settings.jwt_secret,
        expiry_hours=settings.jwt_expiry_hours,
    )


def validate_token(token: str) -> TokenData:
    """
    Validate a JWT token (used internally for testing/admin purposes).

    Args:
        token: Raw JWT string.

    Returns:
        TokenData with username and role.

    Raises:
        JWTError: If token is invalid or expired.
    """
    return decode_token(token, settings.jwt_secret)
