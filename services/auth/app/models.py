"""
============================================================================
FILE: services/auth/app/models.py
PURPOSE: Pydantic request/response schemas for the auth service.
ARCHITECTURE REF: §9 — Security Implementation
DEPENDENCIES: pydantic
============================================================================
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """
    Request body for POST /auth/login.

    Supports both admin and employee accounts.
    Credentials are validated against bcrypt hashes stored in environment variables.
    """
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=200)


class TokenResponse(BaseModel):
    """
    Response from a successful login.

    The access_token is a JWT HS256 signed token.
    Clients must include this in subsequent requests as:
        Authorization: Bearer <access_token>
    """
    access_token: str = Field(description="JWT Bearer token")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(description="Token lifetime in seconds")
    role: str = Field(description="User role: 'admin' or 'user'")


class HealthResponse(BaseModel):
    """Standard health check response."""
    status: str
    service: str
    version: str
    uptime_seconds: float
    dependencies: dict[str, str]
