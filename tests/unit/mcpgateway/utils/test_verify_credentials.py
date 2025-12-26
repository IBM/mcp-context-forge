# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_verify_credentials.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for **mcpgateway.utils.verify_credentials**
Author: Mihai Criveti

Paths covered
-------------
* verify_jwt_token  - success, expired, invalid-signature branches
* verify_credentials - payload enrichment
* require_auth      - happy path, missing-token failure
* verify_basic_credentials - success & failure
* require_basic_auth - required & optional modes
* require_auth_override - header vs cookie precedence

Only dependencies needed are ``pytest`` and ``PyJWT`` (already required by the
target module).  FastAPI `HTTPException` objects are asserted for status code
and detail.
"""

# Future
from __future__ import annotations

# Standard
import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

# Third-Party
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from fastapi.testclient import TestClient
import jwt
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.utils import verify_credentials as vc  # module under test

try:
    # First-Party
    from mcpgateway.main import app
except ImportError:
    app = None

# ---------------------------------------------------------------------------
# Shared constants / helpers
# ---------------------------------------------------------------------------
SECRET = "unit-secret"
ALGO = "HS256"


def _token(payload: dict, *, exp_delta: int | None = 60, secret: str = SECRET) -> str:
    """Return a signed JWT with optional expiry offset (minutes)."""
    # Add required audience and issuer claims for compatibility with RBAC system
    token_payload = payload.copy()
    token_payload.update({"iss": "mcpgateway", "aud": "mcpgateway-api"})

    if exp_delta is not None:
        expire = datetime.now(timezone.utc) + timedelta(minutes=exp_delta)
        token_payload["exp"] = int(expire.timestamp())

    return jwt.encode(token_payload, secret, algorithm=ALGO)


# ---------------------------------------------------------------------------
# verify_jwt_token + verify_credentials
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_jwt_token_success(monkeypatch):
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)

    token = _token({"sub": "abc"})
    data = await vc.verify_jwt_token(token)

    assert data["sub"] == "abc"


@pytest.mark.asyncio
async def test_verify_jwt_token_expired(monkeypatch):
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)

    expired_token = _token({"x": 1}, exp_delta=-1)  # already expired
    with pytest.raises(HTTPException) as exc:
        await vc.verify_jwt_token(expired_token)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Token has expired"


@pytest.mark.asyncio
async def test_verify_jwt_token_invalid_signature(monkeypatch):
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)

    bad_token = _token({"x": 1}, secret="other-secret")
    with pytest.raises(HTTPException) as exc:
        await vc.verify_jwt_token(bad_token)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid token"


@pytest.mark.asyncio
async def test_verify_credentials_enriches(monkeypatch):
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)

    tok = _token({"foo": "bar"})
    enriched = await vc.verify_credentials(tok)

    assert enriched["foo"] == "bar"
    assert enriched["token"] == tok


# ---------------------------------------------------------------------------
# require_auth
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_require_auth_header(monkeypatch):
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)

    tok = _token({"uid": 7})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}  # Empty cookies dict, not Mock

    payload = await vc.require_auth(request=mock_request, credentials=creds, jwt_token=None)
    assert payload["uid"] == 7


@pytest.mark.asyncio
async def test_require_auth_missing_token(monkeypatch):
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}  # Empty cookies dict, not Mock

    with pytest.raises(HTTPException) as exc:
        await vc.require_auth(request=mock_request, credentials=None, jwt_token=None)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Not authenticated"


# ---------------------------------------------------------------------------
# Basic-auth helpers
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_basic_credentials_success(monkeypatch):
    monkeypatch.setattr(vc.settings, "basic_auth_user", "alice", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    creds = HTTPBasicCredentials(username="alice", password="secret")
    assert await vc.verify_basic_credentials(creds) == "alice"


@pytest.mark.asyncio
async def test_verify_basic_credentials_failure(monkeypatch):
    monkeypatch.setattr(vc.settings, "basic_auth_user", "alice", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    creds = HTTPBasicCredentials(username="bob", password="wrong")
    with pytest.raises(HTTPException) as exc:
        await vc.verify_basic_credentials(creds)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid credentials"


@pytest.mark.asyncio
async def test_require_basic_auth_optional(monkeypatch):
    monkeypatch.setattr(vc.settings, "auth_required", False, raising=False)
    result = await vc.require_basic_auth(credentials=None)
    assert result == "anonymous"


@pytest.mark.asyncio
async def test_require_basic_auth_raises_when_credentials_missing(monkeypatch):
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    with pytest.raises(HTTPException) as exc:
        await vc.require_basic_auth(None)

    err = exc.value
    assert err.status_code == status.HTTP_401_UNAUTHORIZED
    assert err.detail == "Not authenticated"
    assert err.headers["WWW-Authenticate"] == "Basic"


# ---------------------------------------------------------------------------
# require_auth_override
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_require_auth_override(monkeypatch):
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)

    header_token = _token({"h": 1})
    cookie_token = _token({"c": 2})

    # Header wins over cookie
    res1 = await vc.require_auth_override(auth_header=f"Bearer {header_token}", jwt_token=cookie_token)
    assert res1["h"] == 1

    # Only cookie present
    res2 = await vc.require_auth_override(auth_header=None, jwt_token=cookie_token)
    assert res2["c"] == 2


@pytest.mark.asyncio
async def test_require_auth_override_non_bearer(monkeypatch):
    # Arrange
    header = "Basic Zm9vOmJhcg=="  # non-Bearer scheme
    monkeypatch.setattr(vc.settings, "auth_required", False, raising=False)
    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}  # Empty cookies dict, not Mock

    # Act
    result = await vc.require_auth_override(auth_header=header)

    # Assert
    assert result == await vc.require_auth(request=mock_request, credentials=None, jwt_token=None)


@pytest.mark.asyncio
async def test_require_auth_override_basic_auth_enabled_success(monkeypatch):
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "alice", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)
    basic_auth_header = f"Basic {base64.b64encode('alice:secret'.encode()).decode()}"
    result = await vc.require_auth_override(auth_header=basic_auth_header)
    assert result == vc.settings.basic_auth_user
    assert result == "alice"


@pytest.mark.asyncio
async def test_require_auth_override_basic_auth_enabled_failure(monkeypatch):
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "alice", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    # case1. format is wrong
    header = "Basic fakeAuth"
    with pytest.raises(HTTPException) as exc:
        await vc.require_auth_override(auth_header=header)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid basic auth credentials"

    # case2. username or password is wrong
    header = "Basic dGVzdDp0ZXN0"
    with pytest.raises(HTTPException) as exc:
        await vc.require_auth_override(auth_header=header)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid credentials"


@pytest.mark.asyncio
async def test_require_auth_override_basic_auth_disabled(monkeypatch):
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    header = "Basic dGVzdDp0ZXN0"
    with pytest.raises(HTTPException) as exc:
        await vc.require_auth_override(auth_header=header)
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Not authenticated"


# ---------------------------------------------------------------------------
# JWT Caching Tests
# ---------------------------------------------------------------------------
class TestJWTCaching:
    """Test JWT verification caching functionality."""

    @pytest.mark.asyncio
    async def test_cache_hit_on_repeated_token(self, monkeypatch):
        """Verify that verifying the same token twice results in a cache hit."""
        monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_cache_enabled", True, raising=False)
        monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)

        # Clear cache and stats
        vc._jwt_verification_cache.clear()
        with vc._cache_stats_lock:
            vc._cache_stats["hits"] = 0
            vc._cache_stats["misses"] = 0
            vc._cache_stats["invalidations"] = 0

        token = _token({"sub": "alice", "email": "alice@example.com"})

        # First call should miss
        initial_stats = vc.get_cache_stats()
        initial_misses = initial_stats["cache_misses"]

        payload1 = await vc.verify_jwt_token(token)
        assert payload1["sub"] == "alice"

        stats_after_first = vc.get_cache_stats()
        assert stats_after_first["cache_misses"] == initial_misses + 1

        # Second call should hit
        payload2 = await vc.verify_jwt_token(token)
        assert payload2["sub"] == "alice"

        stats_after_second = vc.get_cache_stats()
        assert stats_after_second["cache_hits"] > initial_stats["cache_hits"]
        assert stats_after_second["cache_misses"] == stats_after_first["cache_misses"]

    @pytest.mark.asyncio
    async def test_cache_disabled(self, monkeypatch):
        """Verify caching is bypassed when jwt_cache_enabled=False."""
        monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_cache_enabled", False, raising=False)
        monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)

        token = _token({"sub": "bob"})

        # Both calls should result in full verification (no caching)
        payload1 = await vc.verify_jwt_token(token)
        payload2 = await vc.verify_jwt_token(token)

        assert payload1["sub"] == "bob"
        assert payload2["sub"] == "bob"

    @pytest.mark.asyncio
    async def test_invalidate_user_cache_removes_tokens(self, monkeypatch):
        """Verify that invalidate_user_cache removes all tokens for a user."""
        monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_cache_enabled", True, raising=False)
        monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)

        # Clear cache
        vc._jwt_verification_cache.clear()
        vc._user_cache.clear()
        with vc._cache_stats_lock:
            vc._cache_stats["invalidations"] = 0

        # Create and verify tokens for the same user
        token1 = _token({"sub": "charlie@example.com"})
        token2 = _token({"sub": "charlie@example.com", "extra": "data"})

        await vc.verify_jwt_token(token1)
        await vc.verify_jwt_token(token2)

        initial_size = vc.get_cache_stats()["jwt_cache_size"]
        assert initial_size >= 2

        # Invalidate user cache
        initial_invalidations = vc.get_cache_stats()["cache_invalidations"]
        vc.invalidate_user_cache("charlie@example.com")

        # Check that tokens were removed
        stats = vc.get_cache_stats()
        assert stats["cache_invalidations"] > initial_invalidations
        assert stats["jwt_cache_size"] < initial_size

    @pytest.mark.asyncio
    async def test_cache_stats_accurate(self, monkeypatch):
        """Verify cache statistics are accurately tracked."""
        monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_cache_enabled", True, raising=False)
        monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)

        # Clear cache
        vc._jwt_verification_cache.clear()
        with vc._cache_stats_lock:
            vc._cache_stats["hits"] = 0
            vc._cache_stats["misses"] = 0

        token = _token({"sub": "diana"})

        # First call: miss
        await vc.verify_jwt_token(token)
        stats1 = vc.get_cache_stats()
        assert stats1["cache_misses"] == 1
        assert stats1["cache_hits"] == 0

        # Second call: hit
        await vc.verify_jwt_token(token)
        stats2 = vc.get_cache_stats()
        assert stats2["cache_misses"] == 1
        assert stats2["cache_hits"] == 1

        # Hit rate calculation
        assert stats2["hit_rate"] == 0.5  # 1 hit / 2 total

    @pytest.mark.asyncio
    async def test_cache_hit_rate_calculation(self, monkeypatch):
        """Verify hit rate is calculated correctly."""
        monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_cache_enabled", True, raising=False)
        monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)

        # Clear cache
        vc._jwt_verification_cache.clear()
        with vc._cache_stats_lock:
            vc._cache_stats["hits"] = 0
            vc._cache_stats["misses"] = 0

        token1 = _token({"sub": "user1"})
        token2 = _token({"sub": "user2"})

        # 2 misses
        await vc.verify_jwt_token(token1)
        await vc.verify_jwt_token(token2)

        # 2 hits
        await vc.verify_jwt_token(token1)
        await vc.verify_jwt_token(token2)

        stats = vc.get_cache_stats()
        assert stats["cache_hits"] == 2
        assert stats["cache_misses"] == 2
        assert stats["hit_rate"] == 0.5  # 2/4

    @pytest.mark.asyncio
    async def test_thread_safety_of_cache_stats(self, monkeypatch):
        """Verify cache stats are thread-safe under concurrent access."""
        monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
        monkeypatch.setattr(vc.settings, "jwt_cache_enabled", True, raising=False)
        monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)

        # Clear cache
        vc._jwt_verification_cache.clear()
        with vc._cache_stats_lock:
            vc._cache_stats["hits"] = 0
            vc._cache_stats["misses"] = 0

        token = _token({"sub": "concurrent_user"})

        # Warm up cache
        await vc.verify_jwt_token(token)

        # Simulate concurrent cache hits
        async def verify_token():
            for _ in range(10):
                await vc.verify_jwt_token(token)

        import asyncio

        # Run 5 concurrent tasks, each doing 10 verifications = 50 hits
        await asyncio.gather(*[verify_token() for _ in range(5)])

        stats = vc.get_cache_stats()
        # Should have 1 miss (initial) + 50 hits
        assert stats["cache_hits"] == 50
        assert stats["cache_misses"] == 1


class TestUserCaching:
    """Test user object caching functionality."""

    @pytest.mark.asyncio
    async def test_invalidate_clears_user_cache(self, monkeypatch):
        """Verify invalidate_user_cache removes user from user cache."""
        # Clear caches
        vc._user_cache.clear()
        vc._jwt_verification_cache.clear()

        # Manually add user to cache
        vc._user_cache["test@example.com"] = {"email": "test@example.com", "name": "Test User"}

        assert "test@example.com" in vc._user_cache

        # Invalidate
        vc.invalidate_user_cache("test@example.com")

        assert "test@example.com" not in vc._user_cache


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------
@pytest.fixture
def test_client(app, monkeypatch):
    """Create a test client with the properly configured app fixture from conftest."""
    from unittest.mock import MagicMock

    # Patch security_logger at the middleware level where it's imported and called
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    monkeypatch.setattr("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)

    return TestClient(app)


def create_test_jwt_token():
    """Create a valid JWT token for integration tests."""
    return _token({"sub": "integration-user"})


@pytest.mark.asyncio
async def test_docs_auth_with_basic_auth_enabled_bearer_still_works(monkeypatch):
    """CRITICAL: Verify Bearer auth still works when Basic Auth is enabled."""
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    # Create a valid JWT token
    token = _token({"sub": "testuser"})
    bearer_header = f"Bearer {token}"
    # Bearer auth should STILL work
    result = await vc.require_auth_override(auth_header=bearer_header)
    assert result["sub"] == "testuser"


@pytest.mark.asyncio
async def test_docs_both_auth_methods_work_simultaneously(monkeypatch):
    """Test that both auth methods work when Basic Auth is enabled."""
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    # Test 1: Basic Auth works
    basic_header = f"Basic {base64.b64encode(b'admin:secret').decode()}"
    result1 = await vc.require_auth_override(auth_header=basic_header)
    assert result1 == "admin"
    # Test 2: Bearer Auth still works
    token = _token({"sub": "jwtuser"})
    bearer_header = f"Bearer {token}"
    result2 = await vc.require_auth_override(auth_header=bearer_header)
    assert result2["sub"] == "jwtuser"


@pytest.mark.asyncio
async def test_docs_invalid_basic_auth_fails(monkeypatch):
    """Test that invalid Basic Auth returns 401 and does not fall back to Bearer."""
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("correct"), raising=False)
    # Send wrong Basic Auth
    wrong_basic = f"Basic {base64.b64encode(b'admin:wrong').decode()}"
    with pytest.raises(HTTPException) as exc:
        await vc.require_auth_override(auth_header=wrong_basic)
    assert exc.value.status_code == 401


# Integration test for /docs endpoint (requires test_client fixture and create_test_jwt_token helper)
@pytest.mark.asyncio
async def test_integration_docs_endpoint_both_auth_methods(test_client, monkeypatch):
    """Integration test: /docs accepts both auth methods when enabled."""
    monkeypatch.setattr("mcpgateway.config.settings.docs_allow_basic_auth", True)
    monkeypatch.setattr("mcpgateway.config.settings.basic_auth_user", "admin")
    monkeypatch.setattr("mcpgateway.config.settings.basic_auth_password", SecretStr("changeme"))
    monkeypatch.setattr("mcpgateway.config.settings.jwt_secret_key", SECRET)
    monkeypatch.setattr("mcpgateway.config.settings.jwt_algorithm", ALGO)
    monkeypatch.setattr("mcpgateway.config.settings.jwt_audience", "mcpgateway-api")
    monkeypatch.setattr("mcpgateway.config.settings.jwt_issuer", "mcpgateway")
    # Test with Basic Auth
    basic_creds = base64.b64encode(b"admin:changeme").decode()
    response1 = test_client.get("/docs", headers={"Authorization": f"Basic {basic_creds}"})
    assert response1.status_code == 200
    # Test with Bearer token
    token = create_test_jwt_token()
    response2 = test_client.get("/docs", headers={"Authorization": f"Bearer {token}"})
    assert response2.status_code == 200
