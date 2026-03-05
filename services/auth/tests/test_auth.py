"""
============================================================================
FILE: services/auth/tests/test_auth.py
PURPOSE: Unit tests for auth service — login success/failure, JWT validation.
ARCHITECTURE REF: §12 — Testing & Validation
DEPENDENCIES: pytest, unittest.mock, passlib
============================================================================
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from passlib.context import CryptContext

# Generate test bcrypt hashes using cost factor 4 (fast for tests; not for production)
_fast_pwd_ctx = CryptContext(schemes=["bcrypt"], bcrypt__rounds=4)
TEST_ADMIN_HASH = _fast_pwd_ctx.hash("admin_password_123")
TEST_USER_HASH  = _fast_pwd_ctx.hash("user_password_456")

# Set environment variables BEFORE importing the app
import os
os.environ.setdefault("JWT_SECRET", "test_secret_key_at_least_256_bits_long_for_testing")
os.environ.setdefault("ADMIN_USERNAME", "hr_admin")
os.environ.setdefault("ADMIN_PASSWORD_HASH", TEST_ADMIN_HASH)
os.environ.setdefault("USER_USERNAME", "hr_user")
os.environ.setdefault("USER_PASSWORD_HASH", TEST_USER_HASH)
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost/test")

sys.path.insert(0, "/app")

# Mock asyncpg pool so tests don't need a real database
mock_pool = AsyncMock()
mock_conn = AsyncMock()
mock_conn.fetchval = AsyncMock(return_value=1)
mock_conn.execute = AsyncMock()
mock_pool.acquire = MagicMock(return_value=AsyncMock(
    __aenter__=AsyncMock(return_value=mock_conn),
    __aexit__=AsyncMock(return_value=None),
))

with patch("asyncpg.create_pool", AsyncMock(return_value=mock_pool)):
    from app.main import app
    app.state.db_pool = mock_pool


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.app.state.db_pool = mock_pool
        yield c


class TestLoginEndpoint:
    """Tests for POST /auth/login."""

    def test_admin_login_success(self, client):
        """Admin credentials should return a JWT token."""
        response = client.post("/auth/login", json={
            "username": "hr_admin",
            "password": "admin_password_123"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "admin"
        assert data["expires_in"] == 8 * 3600

    def test_user_login_success(self, client):
        """Employee credentials should return a JWT token with user role."""
        response = client.post("/auth/login", json={
            "username": "hr_user",
            "password": "user_password_456"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "user"

    def test_wrong_password_returns_401(self, client):
        """Wrong password should return 401, not 403 (don't reveal which field was wrong)."""
        response = client.post("/auth/login", json={
            "username": "hr_admin",
            "password": "wrong_password"
        })
        assert response.status_code == 401

    def test_unknown_username_returns_401(self, client):
        """Unknown username should return 401 (not 404, to prevent username enumeration)."""
        response = client.post("/auth/login", json={
            "username": "attacker",
            "password": "any_password"
        })
        assert response.status_code == 401

    def test_empty_username_returns_422(self, client):
        """Empty username fails Pydantic validation before hitting auth logic."""
        response = client.post("/auth/login", json={"username": "", "password": "pass"})
        assert response.status_code == 422

    def test_jwt_token_is_decodable(self, client):
        """Returned token should be decodable with the JWT secret."""
        from jose import jwt as jose_jwt
        response = client.post("/auth/login", json={
            "username": "hr_admin",
            "password": "admin_password_123"
        })
        token = response.json()["access_token"]
        payload = jose_jwt.decode(
            token,
            "test_secret_key_at_least_256_bits_long_for_testing",
            algorithms=["HS256"]
        )
        assert payload["sub"] == "hr_admin"
        assert payload["role"] == "admin"


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_structure(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["status"] in ("healthy", "degraded")
        assert data["service"] == "auth-svc"
        assert "dependencies" in data
        assert "postgres" in data["dependencies"]
