"""
============================================================================
FILE: services/auth/app/middleware.py
PURPOSE: Reusable JWT Bearer token validation middleware/dependency.
         Shared pattern used by query-svc and ingest-svc to protect endpoints.
         This file is COPIED into each service's image (not auth-svc-specific).
ARCHITECTURE REF: §9 — Security Implementation
DEPENDENCIES: FastAPI, shared/jwt_utils.py
============================================================================

FastAPI Dependency Injection Pattern:
- JWT validation is implemented as a FastAPI Depends() dependency
- Each protected endpoint declares: current_user: TokenData = Depends(require_jwt)
- FastAPI automatically calls require_jwt() before the endpoint handler
- If validation fails, FastAPI returns 401 before the endpoint runs

Usage in other services (query-svc, ingest-svc):
    from app.middleware import require_jwt, require_admin_jwt

    @app.post("/query")
    async def query(request: QueryRequest, current_user = Depends(require_jwt)):
        # current_user.username and current_user.role are available here
        ...

    @app.delete("/ingest/document/{id}")
    async def delete_doc(doc_id: str, current_user = Depends(require_admin_jwt)):
        # Only admins can delete — non-admins get 403 before reaching here
        ...
"""

import os
import sys
import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

sys.path.insert(0, "/app")
from shared.jwt_utils import TokenData, decode_token

logger = logging.getLogger(__name__)

# HTTPBearer: FastAPI's built-in scheme that extracts Bearer tokens from Authorization header
# auto_error=False: Don't automatically raise 403 — we handle the error ourselves with 401
_bearer_scheme = HTTPBearer(auto_error=False)


def _get_jwt_secret() -> str:
    """
    Read JWT_SECRET from environment at call time (not at import time).

    This lazy evaluation ensures the secret is read after the container
    environment is fully initialized, not at module import.
    """
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET environment variable is not set. "
            "Cannot validate tokens without the signing secret."
        )
    return secret


async def require_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenData:
    """
    FastAPI dependency: validate JWT Bearer token from Authorization header.

    Use this for endpoints accessible by BOTH admin and employee roles.

    Args:
        credentials: Extracted by HTTPBearer from the Authorization header.

    Returns:
        TokenData with username and role of the authenticated user.

    Raises:
        HTTPException(401): If no token provided or token is invalid/expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing. Use: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        secret = _get_jwt_secret()
        token_data = decode_token(token, secret)
        return token_data
    except Exception as exc:
        logger.debug("JWT validation failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_admin_jwt(
    token_data: TokenData = Depends(require_jwt),
) -> TokenData:
    """
    FastAPI dependency: require admin role.

    Extends require_jwt — first validates the token, then checks the role.
    Use this for admin-only operations (document upload, delete).

    Args:
        token_data: Result from require_jwt dependency.

    Returns:
        TokenData (same as require_jwt, guaranteed to have role="admin").

    Raises:
        HTTPException(403): If the authenticated user is not an admin.
    """
    if token_data.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for this operation.",
        )
    return token_data


def get_client_ip(request: Request) -> str:
    """
    Extract the client IP address from a FastAPI request.

    Handles the X-Forwarded-For header (set by nginx reverse proxy)
    to get the actual client IP, not the proxy IP.

    Args:
        request: FastAPI Request object.

    Returns:
        IP address string (IPv4 or IPv6).
    """
    # X-Forwarded-For contains: client, proxy1, proxy2, ...
    # Take the first (leftmost) address — that's the original client
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    # Fall back to direct connection IP
    return request.client.host if request.client else "unknown"
