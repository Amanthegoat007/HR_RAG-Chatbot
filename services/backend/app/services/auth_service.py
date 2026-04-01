import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

from app.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        # bcrypt.checkpw requires bytes
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False

def authenticate_user(username: str, password: str):
    """
    Authenticate against static accounts.
    Returns (user_id, role) or (None, None)
    """
    if username == settings.admin_username:
        if verify_password(password, settings.admin_password_hash):
            return settings.admin_username, "admin"

    elif username == settings.user_username:
        if verify_password(password, settings.user_password_hash):
            return settings.user_username, "user"

    elif (
        settings.benchmark_username
        and settings.benchmark_password_hash
        and username == settings.benchmark_username
    ):
        if verify_password(password, settings.benchmark_password_hash):
            return settings.benchmark_username, "benchmark"

    return None, None


def create_access_token_for_user(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiry_hours)
    payload = {
        "sub": username,
        "roles": [f"ROLE_{role.upper()}"],
        "groups": [],
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def role_from_claims(roles: list[str]) -> str:
    if "ROLE_BENCHMARK" in roles:
        return "benchmark"
    if "ROLE_ADMINISTRATOR" in roles or "ROLE_ADMIN" in roles:
        return "admin"
    return "user"
