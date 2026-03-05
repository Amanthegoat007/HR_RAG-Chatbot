"""
============================================================================
FILE: services/auth/app/main.py
PURPOSE: FastAPI auth service — handles login, JWT issuance, and health checks.
         The only service that creates JWT tokens; other services only validate.
ARCHITECTURE REF: §9 — Security Implementation
DEPENDENCIES: FastAPI, auth_service.py, jwt_handler.py, asyncpg
============================================================================

API Surface:
  POST /auth/login  — authenticate and receive JWT Bearer token
  GET  /health      — health check with dependency status
  GET  /metrics     — Prometheus metrics (auto-exposed by instrumentator)
"""

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from fastapi import FastAPI, HTTPException, Request, status
from prometheus_fastapi_instrumentator import Instrumentator

import sys
sys.path.insert(0, "/app")
from shared.logging_config import setup_logging, get_logger, set_correlation_id

from app.config import settings
from app.auth_service import authenticate_user, write_audit_log
from app.jwt_handler import issue_token
from app.models import LoginRequest, TokenResponse, HealthResponse

setup_logging(
    service_name=settings.service_name,
    log_level=settings.log_level,
    log_format=settings.log_format,
)
logger = get_logger(__name__)

# Module-level db pool — initialized at startup, shared across requests
_db_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan: create DB connection pool at startup, close at shutdown.

    asyncpg uses a connection pool to reuse DB connections across requests.
    This avoids the overhead of creating a new TCP connection per request.
    """
    global _db_pool

    logger.info("Auth service starting up...")

    # Create PostgreSQL connection pool
    # min_size=1: keep at least 1 connection open (avoids connection warmup latency)
    # max_size=5: auth is low-traffic; 5 connections is sufficient
    try:
        _db_pool = await asyncpg.create_pool(
            dsn=settings.postgres_dsn,
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
        logger.info("PostgreSQL connection pool created")
    except Exception as exc:
        logger.error("Failed to connect to PostgreSQL", extra={"error": str(exc)})
        raise

    # Store pool in app state for access in request handlers
    app.state.db_pool = _db_pool

    logger.info("Auth service ready")

    yield  # Application runs

    # SHUTDOWN: Close DB pool gracefully
    if _db_pool:
        await _db_pool.close()
        logger.info("PostgreSQL connection pool closed")


app = FastAPI(
    title="HR RAG — Auth Service",
    description="JWT-based authentication for HR RAG Chatbot (2 static accounts)",
    version=settings.service_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

# Track service start time for uptime reporting in health checks
_start_time = time.time()

Instrumentator().instrument(app).expose(app)


@app.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Login and receive JWT token",
    description="Authenticate with username/password. Returns a JWT Bearer token valid for 8 hours.",
)
async def login(request: Request, body: LoginRequest) -> TokenResponse:
    """
    Authenticate user and issue a JWT access token.

    Architecture Reference: §9 — Security Implementation

    Flow:
    1. Extract client IP from X-Forwarded-For header (set by nginx)
    2. Verify credentials against bcrypt hashes in environment variables
    3. If valid: issue JWT, write audit_log success event
    4. If invalid: write audit_log failure event, return 401

    The audit log captures ALL login attempts for security monitoring.
    Alert triggers when > 5 failures/minute (Architecture §10).

    Args:
        request: FastAPI Request (for IP extraction).
        body: LoginRequest with username and password.

    Returns:
        TokenResponse with JWT access_token, token_type, expires_in, and role.

    Raises:
        HTTPException(401): If credentials are invalid.
    """
    # Generate correlation ID for this request (appears in all log entries)
    correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)

    # Extract client IP (nginx passes real client IP via X-Forwarded-For)
    ip_address = request.headers.get("X-Forwarded-For", "")
    if ip_address:
        ip_address = ip_address.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else "unknown"

    logger.info("Login attempt", extra={"username": body.username, "ip": ip_address})

    # Authenticate against static accounts
    success, role = authenticate_user(body.username, body.password)

    db_pool: asyncpg.Pool = request.app.state.db_pool

    if success and role:
        # Issue JWT token
        token = issue_token(username=body.username, role=role)
        expires_in_seconds = settings.jwt_expiry_hours * 3600

        # Write success event to audit log
        await write_audit_log(
            db_pool=db_pool,
            event_type="login_success",
            role=role,
            username=body.username,
            ip_address=ip_address,
            details={"username": body.username, "role": role},
        )

        logger.info("Login successful", extra={
            "username": body.username, "role": role, "ip": ip_address
        })

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in_seconds,
            role=role,
        )

    else:
        # Write failure event to audit log
        await write_audit_log(
            db_pool=db_pool,
            event_type="login_failure",
            role=None,
            username=body.username,  # Record attempted username
            ip_address=ip_address,
            details={"attempted_username": body.username},
        )

        logger.warning("Login failed", extra={"username": body.username, "ip": ip_address})

        # Return 401 with a vague message (don't reveal if username or password was wrong)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/health", response_model=HealthResponse, summary="Health check")
async def health(request: Request) -> HealthResponse:
    """
    Health check endpoint.

    Checks PostgreSQL connectivity to report a comprehensive health status.
    Docker uses this to determine if the container is ready to serve traffic.
    """
    # Check PostgreSQL connectivity
    postgres_status = "healthy"
    try:
        db_pool: asyncpg.Pool = request.app.state.db_pool
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        logger.error("PostgreSQL health check failed", extra={"error": str(exc)})
        postgres_status = "unhealthy"

    overall_status = "healthy" if postgres_status == "healthy" else "degraded"

    return HealthResponse(
        status=overall_status,
        service=settings.service_name,
        version=settings.service_version,
        uptime_seconds=round(time.time() - _start_time, 1),
        dependencies={"postgres": postgres_status},
    )
