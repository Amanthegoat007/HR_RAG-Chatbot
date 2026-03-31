"""
============================================================================
FILE: services/auth/app/config.py
PURPOSE: Configuration for the auth service loaded from environment variables.
ARCHITECTURE REF: §9 — Security Implementation
DEPENDENCIES: pydantic-settings
============================================================================
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """
    Settings for the auth service.

    Security-critical settings (JWT_SECRET, password hashes) are loaded
    from environment variables only — never from code or config files.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # JWT configuration
    jwt_secret: str  # REQUIRED — no default, must be set in environment
    jwt_expiry_hours: int = 8    # 8-hour token lifetime per architecture §9

    # Static account credentials (bcrypt hashes from environment)
    # Hashes are generated with: python utils/hash_password.py <password>
    admin_username: str = "hr_admin"
    admin_password_hash: str  # REQUIRED — bcrypt hash of admin password

    user_username: str = "hr_user"
    user_password_hash: str   # REQUIRED — bcrypt hash of employee password

    # PostgreSQL for audit logging
    postgres_dsn: str  # REQUIRED — full DSN for asyncpg

    # Service settings
    host: str = "0.0.0.0"
    port: int = 8001
    log_level: str = "INFO"
    log_format: str = "json"
    service_name: str = "auth-svc"
    service_version: str = "1.0.0"


settings = AuthSettings()
