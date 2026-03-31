"""
============================================================================
FILE: services/auth/app/auth_service.py
PURPOSE: Core authentication logic — bcrypt password verification against
         hashes stored in environment variables, plus audit log writing.
ARCHITECTURE REF: §9 — Security Implementation
DEPENDENCIES: passlib[bcrypt], asyncpg
============================================================================

Two-Account Static Authentication Design:
- Architecture specifies ONLY two accounts (hr_admin and hr_user)
- Passwords are bcrypt-hashed with cost factor 12 (security recommendation)
- Hashes are stored in environment variables (NOT in database)
- This design is intentional: no user management feature needed for MVP
- If multi-user support is needed later, replace this with a DB lookup

Audit Log Design:
- Every login attempt (success or failure) is written to PostgreSQL audit_log
- Failed logins record the attempted username (for brute-force detection)
- Successful logins record username and role
- IP address is captured from the HTTP request for tracking
"""

import asyncpg
import logging
from passlib.context import CryptContext

from app.config import settings

logger = logging.getLogger(__name__)

# CryptContext: handles bcrypt hashing with the correct cost factor
# auto_deprecated="auto" means old hashes are auto-upgraded when users log in
# Using bcrypt with cost factor 12 (Architecture §9 specifies bcrypt cost factor 12)
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # Cost factor 12: ~300ms per check — good balance of security/speed
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against a bcrypt hash.

    bcrypt is resistant to brute-force attacks because each verification
    takes ~300ms with cost factor 12. This limits password guessing to
    ~3 attempts/second per thread.

    Args:
        plain_password: The password submitted by the user.
        hashed_password: The bcrypt hash from environment variable.

    Returns:
        True if password matches, False otherwise.
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        # passlib raises exceptions for malformed hashes — treat as invalid
        return False


def authenticate_user(username: str, password: str) -> tuple[bool, str | None]:
    """
    Authenticate a user against the two static accounts.

    Checks username against admin and user accounts, then verifies
    the password using bcrypt. Returns a tuple of (success, role).

    Args:
        username: Submitted username.
        password: Submitted plain-text password.

    Returns:
        Tuple: (True, "admin") or (True, "user") on success,
               (False, None) on failure.
    """
    # Check admin account
    if username == settings.admin_username:
        if verify_password(password, settings.admin_password_hash):
            logger.info("Admin login success", extra={"username": username})
            return True, "admin"

    # Check employee account
    elif username == settings.user_username:
        if verify_password(password, settings.user_password_hash):
            logger.info("Employee login success", extra={"username": username})
            return True, "user"

    # Unknown username or wrong password — log without revealing which one
    # (prevents username enumeration attacks)
    logger.warning("Login failure", extra={"username": username})
    return False, None


async def write_audit_log(
    db_pool: asyncpg.Pool,
    event_type: str,
    role: str | None,
    username: str | None,
    ip_address: str | None,
    details: dict,
) -> None:
    """
    Write an event to the PostgreSQL audit_log table.

    Called after every login attempt (success or failure).
    Audit logs are critical for security compliance and intrusion detection.

    Args:
        db_pool: asyncpg connection pool (from application state).
        event_type: One of the event types defined in init.sql check constraint.
        role: "admin", "user", or None (for failed logins with unknown username).
        username: The username (or attempted username for failed logins).
        ip_address: Client IP from the request.
        details: JSONB details object with event-specific data.

    Note:
        If the audit log write fails, we log the error but do NOT propagate it
        to the client. A failed audit log should not block authentication.
    """
    try:
        import json
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (event_type, role, username, ip_address, details)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                event_type,
                role,
                username,
                ip_address,
                json.dumps(details),
            )
    except Exception as exc:
        # Log but don't raise — audit log failure must not block login
        logger.error(
            "Failed to write audit log",
            extra={"event_type": event_type, "error": str(exc)}
        )
