"""
============================================================================
FILE: shared/jwt_utils.py
PURPOSE: Shared JWT validation utilities used by query-svc and ingest-svc.
         auth-svc creates JWTs; other services validate them using this module.
         This file is COPIED into each service image at Docker build time
         (not mounted as a volume) to keep services independent.
ARCHITECTURE REF: §9 — Security Implementation, §2 — Auth Service
DEPENDENCIES: python-jose, pydantic
============================================================================

JWT Design:
- Algorithm: HS256 (HMAC-SHA256) — symmetric, suitable for single-server deployment
- Expiry: 8 hours (configurable via JWT_EXPIRY_HOURS env var)
- Payload: {"sub": "<username>", "role": "admin|user", "exp": <unix_timestamp>, "iat": <unix_timestamp>}
- Secret: 256-bit random string from JWT_SECRET env var

Security notes:
- The JWT_SECRET must be the same across ALL services (auth, query, ingest)
- If JWT_SECRET is rotated, all existing tokens are immediately invalidated
- No refresh token mechanism — users must re-login after 8 hours
- Bearer token format: Authorization: Bearer <token>
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# JWT algorithm — HS256 is standard for single-server symmetric JWT
ALGORITHM = "HS256"

# Accepted roles (matches static accounts configured in auth-svc)
RoleType = Literal["admin", "user"]


# ---------------------------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------------------------

class TokenPayload(BaseModel):
    """
    Decoded JWT payload structure.

    Attributes:
        sub: Subject — the username (e.g., "hr_admin", "hr_user")
        role: User role — "admin" can upload/delete; "user" can only query
        exp: Expiry timestamp (Unix time)
        iat: Issued-at timestamp (Unix time)
    """
    sub: str
    role: RoleType
    exp: int
    iat: int


class TokenData(BaseModel):
    """
    Simplified token data returned after validation.
    Used as the current_user object in API endpoints.
    """
    username: str
    role: RoleType


# ---------------------------------------------------------------------------
# JWT CREATION (used by auth-svc only)
# ---------------------------------------------------------------------------

def create_access_token(
    username: str,
    role: RoleType,
    secret: str,
    expiry_hours: int = 8,
) -> str:
    """
    Create a signed JWT access token.

    Called by auth-svc upon successful login. The token is returned to the
    client and must be sent as a Bearer token in subsequent requests.

    Args:
        username: The authenticated username.
        role: The user's role ("admin" or "user").
        secret: The JWT_SECRET — must be the same string used for validation.
        expiry_hours: Token validity duration in hours (default: 8).

    Returns:
        Signed JWT string.

    Raises:
        ValueError: If username or role are invalid.
    """
    if not username or not role:
        raise ValueError("username and role must be non-empty strings")

    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=expiry_hours)

    payload = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    token = jwt.encode(payload, secret, algorithm=ALGORITHM)
    logger.info(
        "JWT issued",
        extra={"username": username, "role": role, "expiry_hours": expiry_hours}
    )
    return token


# ---------------------------------------------------------------------------
# JWT VALIDATION (used by query-svc and ingest-svc)
# ---------------------------------------------------------------------------

def decode_token(token: str, secret: str) -> TokenData:
    """
    Decode and validate a JWT token.

    Validates the signature, expiry, and payload structure.
    Called by the JWT middleware in each protected service.

    Args:
        token: The raw JWT string (without "Bearer " prefix).
        secret: The JWT_SECRET — must match the secret used to create the token.

    Returns:
        TokenData with username and role of the authenticated user.

    Raises:
        JWTError: If the token is invalid, expired, or has a bad signature.
        ValueError: If the token payload is missing required fields.
    """
    try:
        # Decode and verify signature + expiry in one step
        payload_dict = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError as exc:
        # Log at debug level — auth failures are tracked in the audit_log
        # Logging at WARNING here would double-count with audit log
        logger.debug("JWT decode failed", extra={"error": str(exc)})
        raise

    # Validate payload structure using Pydantic
    try:
        payload = TokenPayload(**payload_dict)
    except Exception as exc:
        raise ValueError(f"Malformed JWT payload: {exc}") from exc

    return TokenData(username=payload.sub, role=payload.role)


def get_role_from_token(token: str, secret: str) -> RoleType:
    """
    Convenience function: extract only the role from a valid JWT.

    Args:
        token: Raw JWT string.
        secret: JWT signing secret.

    Returns:
        Role string ("admin" or "user").

    Raises:
        JWTError: If token is invalid or expired.
    """
    token_data = decode_token(token, secret)
    return token_data.role
