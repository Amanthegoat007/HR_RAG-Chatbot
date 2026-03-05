"""
============================================================================
FILE: services/backend/app/dependencies.py
PURPOSE: FastAPI dependencies for authentication using cookie-based JWTs.
============================================================================
"""

from fastapi import Depends, HTTPException, Request, status
import jwt
from typing import Optional
from app.config import settings

def get_token_from_cookie(request: Request) -> Optional[str]:
    return request.cookies.get("access_token")

async def require_auth(request: Request) -> dict:
    """Validate JWT from cookie and return decoded payload."""
    token = get_token_from_cookie(request)
    if not token:
        # Also check Auth header as fallback for testing
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

import logging
logger = logging.getLogger(__name__)

async def require_admin(payload: dict = Depends(require_auth)) -> dict:
    """Ensure user has admin role."""
    roles = payload.get("roles", [])
    if "ROLE_ADMINISTRATOR" not in roles and "ROLE_ADMIN" not in roles:
        logger.warning(f"DEBUG: 403 Forbidden. User roles: {roles}, Token payload: {payload}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return payload
