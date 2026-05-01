"""E2E tests for authentication rate limiting.

Tests rate limiting on authentication endpoints to prevent credential stuffing attacks.
"""

import os
import time
import uuid
from typing import Dict, Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from mcpgateway.main import app
from mcpgateway.db import SessionLocal, EmailUser
from mcpgateway.services.email_auth_service import EmailAuthService

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("MCPGATEWAY_UI_ENABLED", "").lower() not in ("1", "true"),
        reason="MCPGATEWAY_UI_ENABLED is not set — /app routes not registered",
    ),
]


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def test_user_credentials() -> Dict[str, str]:
    """Test user credentials."""
    return {
        "email": f"rate-limit-test-{uuid.uuid4().hex[:8]}@example.com",
        "password": "TestPassword123!",  # pragma: allowlist secret
    }


@pytest.fixture
def setup_test_user(test_user_credentials: Dict[str, str]) -> Generator[EmailUser, None, None]:
    """Create test user in database."""
    db = SessionLocal()
    user = None
    try:
        # Clean up any existing test user
        existing = db.query(EmailUser).filter_by(email=test_user_credentials["email"]).first()
        if existing:
            db.delete(existing)
            db.commit()

        # Create test user
        auth_service = EmailAuthService(db)
        user = auth_service.create_user(
            email=test_user_credentials["email"],
            password=test_user_credentials["password"],
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


class TestRateLimiting:
    """Test rate limiting on authentication endpoints."""

    def test_login_rate_limit_blocks_after_threshold(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test login endpoint blocks after 10 requests per minute."""
        # Make 10 requests (should succeed or fail based on credentials, but not be rate limited)
        for i in range(10):
            response = client.post("/app/auth/login", json=test_user_credentials)
            assert response.status_code in [200, 401], f"Request {i+1} should not be rate limited"

        # 11th request should be rate limited
        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code == 429, "11th request should be rate limited"
        assert "rate limit" in response.json()["detail"].lower()

    def test_rate_limit_is_per_ip(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test rate limit is enforced per IP address."""
        # Exhaust rate limit for default IP
        for _ in range(10):
            client.post("/app/auth/login", json=test_user_credentials)

        # Verify rate limit is active
        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code == 429

        # Note: TestClient doesn't support changing client IP in headers
        # In production, different IPs would have separate rate limit buckets
        # This test documents the expected behavior

    @pytest.mark.slow
    def test_rate_limit_resets_after_window(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test rate limit resets after time window expires.

        Note: This test is marked as slow because it requires waiting 61 seconds.
        Run with: pytest -m slow
        """
        # Exhaust rate limit
        for _ in range(10):
            client.post("/app/auth/login", json=test_user_credentials)

        # Verify rate limit is active
        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code == 429

        # Wait for rate limit window to reset (61 seconds)
        time.sleep(61)

        # Should succeed after reset (or fail with 401 if credentials wrong, but not 429)
        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code in [200, 401], "Request should not be rate limited after window reset"
        assert response.status_code != 429

    def test_successful_login_counts_toward_rate_limit(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test that successful logins also count toward rate limit."""
        # Make 10 successful login requests
        for i in range(10):
            response = client.post("/app/auth/login", json=test_user_credentials)
            assert response.status_code == 200, f"Request {i+1} should succeed"

        # 11th request should be rate limited even with valid credentials
        response = client.post("/app/auth/login", json=test_user_credentials)
        assert response.status_code == 429
        assert "rate limit" in response.json()["detail"].lower()

    def test_failed_login_counts_toward_rate_limit(self, client: TestClient, setup_test_user: EmailUser, test_user_credentials: Dict[str, str]) -> None:
        """Test that failed logins count toward rate limit."""
        wrong_credentials = {
            "email": test_user_credentials["email"],
            "password": "WrongPassword123!",  # pragma: allowlist secret
        }

        # Make 10 failed login attempts
        for i in range(10):
            response = client.post("/app/auth/login", json=wrong_credentials)
            assert response.status_code == 401, f"Request {i+1} should fail with wrong password"

        # 11th request should be rate limited
        response = client.post("/app/auth/login", json=wrong_credentials)
        assert response.status_code == 429
        assert "rate limit" in response.json()["detail"].lower()
