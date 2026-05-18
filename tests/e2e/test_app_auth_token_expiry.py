"""E2E tests for token expiry synchronization.

Tests that CSRF and JWT tokens expire simultaneously to prevent auth/CSRF desynchronization.
"""

import asyncio
import os
import re
import uuid
from typing import Dict, Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from mcpgateway import db as db_mod
from mcpgateway.admin import rate_limit_storage
from mcpgateway.db import EmailUser
from mcpgateway.services.email_auth_service import EmailAuthService

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("MCPGATEWAY_UI_ENABLED", "").lower() not in ("1", "true"),
        reason="MCPGATEWAY_UI_ENABLED is not set — /app routes not registered",
    ),
]


@pytest.fixture(autouse=True)
def clear_auth_rate_limits() -> Generator[None, None, None]:
    """Keep auth rate limiting isolated between tests."""
    rate_limit_storage.clear()
    yield
    rate_limit_storage.clear()


def _set_cookie_headers(response) -> list[str]:
    """Return separate Set-Cookie headers from an httpx response."""
    return response.headers.get_list("set-cookie")


@pytest.fixture
def client(app_with_temp_db) -> TestClient:
    """Create test client."""
    return TestClient(app_with_temp_db)


@pytest.fixture
def test_user_credentials() -> Dict[str, str]:
    """Test user credentials."""
    return {
        "email": f"expiry-test-{uuid.uuid4().hex[:8]}@example.com",
        "password": "TestPassword123!",  # pragma: allowlist secret
    }


@pytest.fixture
def setup_test_user(test_user_credentials: Dict[str, str]) -> Generator[EmailUser, None, None]:
    """Create test user in database."""
    db = db_mod.SessionLocal()
    user = None
    try:
        # Clean up any existing test user
        existing = db.query(EmailUser).filter_by(email=test_user_credentials["email"]).first()
        if existing:
            db.delete(existing)
            db.commit()

        # Create test user
        auth_service = EmailAuthService(db)
        user = asyncio.run(
            auth_service.create_user(
                email=test_user_credentials["email"],
                password=test_user_credentials["password"],
            )
        )
        db.commit()
        yield user
    finally:
        try:
            if user is not None:
                db.delete(user)
                db.commit()
        except Exception:
            db.rollback()
        db.close()


class TestTokenExpirySynchronization:
    """Test CSRF and JWT token expiry synchronization."""

    def test_csrf_and_jwt_cookies_expire_simultaneously(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test CSRF and JWT cookies have identical max_age values."""
        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code == 200

        # Extract Set-Cookie headers
        set_cookies = _set_cookie_headers(response)

        # Find JWT and CSRF cookies
        jwt_cookie = next((c for c in set_cookies if "jwt_token=" in c), None)
        csrf_cookie = next((c for c in set_cookies if "csrf_token=" in c), None)

        assert jwt_cookie is not None, "JWT cookie should be set"
        assert csrf_cookie is not None, "CSRF cookie should be set"

        # Extract max-age from both cookies
        jwt_max_age_match = re.search(r"max-age=(\d+)", jwt_cookie, re.I)
        csrf_max_age_match = re.search(r"max-age=(\d+)", csrf_cookie, re.I)

        assert jwt_max_age_match is not None, "JWT cookie should have max-age"
        assert csrf_max_age_match is not None, "CSRF cookie should have max-age"

        jwt_max_age = int(jwt_max_age_match.group(1))
        csrf_max_age = int(csrf_max_age_match.group(1))

        # Verify synchronization
        assert jwt_max_age == csrf_max_age, f"JWT and CSRF cookies must expire simultaneously: " f"jwt_max_age={jwt_max_age}, csrf_max_age={csrf_max_age}"

    def test_token_expiry_matches_config(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test token expiry matches settings.token_expiry configuration."""
        from mcpgateway.config import settings

        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code == 200

        # Extract Set-Cookie headers
        set_cookies = _set_cookie_headers(response)
        jwt_cookie = next((c for c in set_cookies if "jwt_token=" in c), None)

        assert jwt_cookie is not None, "JWT cookie should be set"

        # Extract max-age
        jwt_max_age_match = re.search(r"max-age=(\d+)", jwt_cookie, re.I)
        assert jwt_max_age_match is not None, "JWT cookie should have max-age"

        jwt_max_age = int(jwt_max_age_match.group(1))
        expected_max_age = settings.token_expiry * 60  # Convert minutes to seconds

        # Verify cookie expiry matches config
        assert jwt_max_age == expected_max_age, f"JWT cookie max-age should match settings.token_expiry: " f"jwt_max_age={jwt_max_age}, expected={expected_max_age}"

    def test_csrf_cookie_security_flags(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test CSRF cookie has correct security flags."""
        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code == 200

        # Extract CSRF cookie
        set_cookies = _set_cookie_headers(response)
        csrf_cookie = next((c for c in set_cookies if "csrf_token=" in c), None)

        assert csrf_cookie is not None, "CSRF cookie should be set"

        # Verify security flags
        assert "httponly" not in csrf_cookie.lower() or "httponly=false" in csrf_cookie.lower(), "CSRF cookie must NOT be httpOnly (JS needs to read it for X-CSRF-Token header)"
        assert "samesite=strict" in csrf_cookie.lower(), "CSRF cookie must have SameSite=Strict"
        assert "path=/" in csrf_cookie.lower(), "CSRF cookie must be scoped to / path"

    def test_jwt_cookie_security_flags(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test JWT cookie has correct security flags."""
        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code == 200

        # Extract JWT cookie
        set_cookies = _set_cookie_headers(response)
        jwt_cookie = next((c for c in set_cookies if "jwt_token=" in c), None)

        assert jwt_cookie is not None, "JWT cookie should be set"

        # Verify security flags
        assert "httponly" in jwt_cookie.lower(), "JWT cookie must be httpOnly (prevent XSS)"
        assert "samesite=lax" in jwt_cookie.lower(), "JWT cookie should have SameSite=Lax"
        assert "path=/" in jwt_cookie.lower(), "JWT cookie should be scoped to / path"
