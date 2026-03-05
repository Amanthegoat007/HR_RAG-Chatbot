"""
============================================================================
FILE: services/ingest/app/middleware.py
PURPOSE: JWT middleware for ingest service (copy of auth-svc middleware pattern).
         Validates JWT Bearer tokens using JWT_SECRET environment variable.
ARCHITECTURE REF: §9 — Security Implementation
============================================================================
"""

# Re-export from the canonical implementation
# This file exists so the import path works consistently across services
from app.main import require_jwt_local as require_jwt
from app.main import require_admin

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """Extract real client IP from X-Forwarded-For header."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
