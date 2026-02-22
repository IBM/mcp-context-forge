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
from unittest.mock import AsyncMock, MagicMock, Mock
import uuid

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
SECRET = "unit-test-jwt-secret-key-with-minimum-32-bytes"
ALGO = "HS256"


def _token(payload: dict, *, exp_delta: int | None = 60, secret: str = SECRET, include_jti: bool = True) -> str:
    """Return a signed JWT with optional expiry offset (minutes).

    Args:
        payload: JWT payload claims
        exp_delta: Expiry offset in minutes (None for no expiry)
        secret: Signing secret
        include_jti: Whether to include JTI claim (default True for REQUIRE_JTI=true)
    """
    # Add required audience and issuer claims for compatibility with RBAC system
    token_payload = payload.copy()
    token_payload.update({"iss": "mcpgateway", "aud": "mcpgateway-api"})

    # Add JTI claim by default (required when REQUIRE_JTI=true)
    if include_jti and "jti" not in token_payload:
        token_payload["jti"] = str(uuid.uuid4())

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

    bad_token = _token({"x": 1}, secret="other-secret-key-with-minimum-32-bytes")
    with pytest.raises(HTTPException) as exc:
        await vc.verify_jwt_token(bad_token)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid token"


@pytest.mark.asyncio
async def test_verify_jwt_token_missing_exp_when_required(monkeypatch):
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", True, raising=False)

    # Valid signature but missing exp claim.
    token = jwt.encode({"sub": "missing-exp", "aud": "mcpgateway-api", "iss": "mcpgateway", "jti": str(uuid.uuid4())}, SECRET, algorithm=ALGO)

    with pytest.raises(HTTPException) as exc:
        await vc.verify_jwt_token(token)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "missing required expiration claim" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_jwt_token_skip_issuer_verification_only(monkeypatch):
    """Test that issuer verification can be disabled independently of audience verification."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", False, raising=False)  # Disable issuer verification
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", True, raising=False)  # Keep audience verification enabled
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)

    # Token with correct audience but wrong/missing issuer (include JTI for REQUIRE_JTI=true default)
    token = jwt.encode({"sub": "user-wrong-iss", "aud": "mcpgateway-api", "iss": "wrong-issuer", "jti": str(uuid.uuid4())}, SECRET, algorithm=ALGO)

    # Should succeed because issuer verification is disabled, but audience is still checked
    data = await vc.verify_jwt_token(token)
    assert data["sub"] == "user-wrong-iss"


@pytest.mark.asyncio
async def test_verify_jwt_token_skip_both_verifications(monkeypatch):
    """Test that both issuer and audience verification can be disabled together."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", False, raising=False)

    # Token without issuer or audience claims (include JTI for REQUIRE_JTI=true default)
    token = jwt.encode({"sub": "no-iss-aud", "jti": str(uuid.uuid4())}, SECRET, algorithm=ALGO)

    # Should succeed even without ISS/AUD claims
    data = await vc.verify_jwt_token(token)
    assert data["sub"] == "no-iss-aud"


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


@pytest.mark.asyncio
async def test_require_auth_rejects_revoked_token(monkeypatch):
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)
    monkeypatch.setattr(
        vc,
        "verify_credentials_cached",
        AsyncMock(return_value={"sub": "user@example.com", "jti": "jti-1", "token": "token"}),
    )
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: True)
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: MagicMock(is_active=True))

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    with pytest.raises(HTTPException) as exc:
        await vc.require_auth(request=mock_request, credentials=creds, jwt_token=None)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Token has been revoked"


@pytest.mark.asyncio
async def test_require_auth_rejects_inactive_user(monkeypatch):
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "require_user_in_db", False, raising=False)
    monkeypatch.setattr(
        vc,
        "verify_credentials_cached",
        AsyncMock(return_value={"sub": "user@example.com", "jti": "jti-1", "token": "token"}),
    )
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", lambda _jti: False)
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", lambda _email: MagicMock(is_active=False))

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    with pytest.raises(HTTPException) as exc:
        await vc.require_auth(request=mock_request, credentials=creds, jwt_token=None)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Account disabled"


@pytest.mark.asyncio
async def test_require_auth_manual_cookie_overrides_header(monkeypatch):
    """Manual cookie reading should take precedence over the Authorization header."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    header_token = _token({"h": 1})
    cookie_token = _token({"c": 2})

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=header_token)
    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {"jwt_token": cookie_token}

    payload = await vc.require_auth(request=mock_request, credentials=creds, jwt_token=None)
    assert payload["c"] == 2
    assert "h" not in payload


@pytest.mark.asyncio
async def test_require_auth_manual_cookie_missing_falls_back_to_header(monkeypatch):
    """If cookies are present but don't include jwt_token, fall back to header token."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    header_token = _token({"h": 1})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=header_token)
    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {"other": "x"}  # truthy but no jwt_token key

    payload = await vc.require_auth(request=mock_request, credentials=creds, jwt_token=None)
    assert payload["h"] == 1


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


@pytest.mark.asyncio
async def test_require_docs_basic_auth_invalid_format_missing_colon(monkeypatch):
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", True, raising=False)

    # base64("userpass") => missing ":" separator
    userpass = base64.b64encode(b"userpass").decode()
    with pytest.raises(HTTPException) as exc:
        await vc.require_docs_basic_auth(f"Basic {userpass}")

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid basic auth credentials"


@pytest.mark.asyncio
async def test_require_docs_basic_auth_not_allowed_or_malformed(monkeypatch):
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", False, raising=False)

    userpass = base64.b64encode(b"alice:secret").decode()
    with pytest.raises(HTTPException) as exc:
        await vc.require_docs_basic_auth(f"Basic {userpass}")

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Basic authentication not allowed or malformed"


@pytest.mark.asyncio
async def test_require_docs_auth_override_basic_not_allowed_raises_not_authenticated(monkeypatch):
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", False, raising=False)

    userpass = base64.b64encode(b"alice:secret").decode()
    with pytest.raises(HTTPException) as exc:
        await vc.require_docs_auth_override(auth_header=f"Basic {userpass}", jwt_token=None)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Not authenticated"


@pytest.mark.asyncio
async def test_require_docs_auth_override_unknown_scheme_raises_not_authenticated(monkeypatch):
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", False, raising=False)

    with pytest.raises(HTTPException) as exc:
        await vc.require_docs_auth_override(auth_header="Token abc", jwt_token=None)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Not authenticated"


@pytest.mark.asyncio
async def test_require_docs_auth_override_no_header_no_cookie_raises_not_authenticated(monkeypatch):
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", False, raising=False)

    with pytest.raises(HTTPException) as exc:
        await vc.require_docs_auth_override(auth_header=None, jwt_token=None)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Not authenticated"


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


# ---------------------------------------------------------------------------
# Single-pass decode and error precedence tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_jwt_token_invalid_signature_before_missing_exp(monkeypatch):
    """Verify that invalid signature is detected before missing exp claim.

    With single-pass decoding, signature validation occurs before claim
    validation. This test confirms the expected error precedence.
    """
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", True, raising=False)

    # Create token with wrong secret AND no exp claim
    bad_token = jwt.encode(
        {"sub": "test", "aud": "mcpgateway-api", "iss": "mcpgateway"},  # No exp claim
        "wrong-secret-key-with-minimum-32-bytes",
        algorithm=ALGO,
    )

    with pytest.raises(HTTPException) as exc:
        await vc.verify_jwt_token(bad_token)

    # Should be "Invalid token" (signature error), not "missing exp claim"
    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid token" in exc.value.detail


# ---------------------------------------------------------------------------
# Request-level caching tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_jwt_token_cached_returns_cached_payload(monkeypatch):
    """Verify that cached function returns same payload without re-decoding."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", True, raising=False)

    token = _token({"sub": "cached_user"})

    # Create mock request with state
    class MockState:
        pass

    class MockRequest:
        state = MockState()

    request = MockRequest()

    # First call - should decode
    payload1 = await vc.verify_jwt_token_cached(token, request)
    assert payload1["sub"] == "cached_user"

    # Verify it was cached
    assert hasattr(request.state, "_jwt_verified_payload")
    assert request.state._jwt_verified_payload[0] == token

    # Second call - should return cached payload without re-decoding
    payload2 = await vc.verify_jwt_token_cached(token, request)
    assert payload2 == payload1


@pytest.mark.asyncio
async def test_verify_jwt_token_cached_without_request(monkeypatch):
    """Verify that cached function works without request (no caching)."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", True, raising=False)

    token = _token({"sub": "no_cache_user"})

    # Call without request - should still work
    payload = await vc.verify_jwt_token_cached(token, None)
    assert payload["sub"] == "no_cache_user"


@pytest.mark.asyncio
async def test_verify_jwt_token_cached_handles_object_without_state(monkeypatch):
    """Verify that cached function handles objects without state attribute."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", True, raising=False)

    token = _token({"sub": "no_state_user"})

    # Create object without state attribute
    class NoStateRequest:
        pass

    request = NoStateRequest()

    # Should work without raising AttributeError
    payload = await vc.verify_jwt_token_cached(token, request)
    assert payload["sub"] == "no_state_user"


@pytest.mark.asyncio
async def test_verify_credentials_cached_does_not_mutate_cache(monkeypatch):
    """Verify that verify_credentials_cached returns a copy, not the cached payload."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", True, raising=False)

    token = _token({"sub": "creds_user"})

    class MockState:
        pass

    class MockRequest:
        state = MockState()

    request = MockRequest()

    # Call verify_credentials_cached which adds "token" key
    creds_payload = await vc.verify_credentials_cached(token, request)
    assert creds_payload["sub"] == "creds_user"
    assert creds_payload["token"] == token

    # Now call verify_jwt_token_cached - should return cached payload WITHOUT "token" key
    jwt_payload = await vc.verify_jwt_token_cached(token, request)
    assert jwt_payload["sub"] == "creds_user"
    assert "token" not in jwt_payload  # Must not be mutated by verify_credentials_cached


@pytest.mark.asyncio
async def test_verify_jwt_token_cached_different_tokens(monkeypatch):
    """Verify that cached function re-verifies when token changes."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience", "mcpgateway-api", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer", "mcpgateway", raising=False)
    monkeypatch.setattr(vc.settings, "jwt_audience_verification", True, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_issuer_verification", True, raising=False)

    token1 = _token({"sub": "user1"})
    token2 = _token({"sub": "user2"})

    class MockState:
        pass

    class MockRequest:
        state = MockState()

    request = MockRequest()

    # First call with token1
    payload1 = await vc.verify_jwt_token_cached(token1, request)
    assert payload1["sub"] == "user1"

    # Second call with different token - should re-verify
    payload2 = await vc.verify_jwt_token_cached(token2, request)
    assert payload2["sub"] == "user2"

    # Cache should now hold token2
    assert request.state._jwt_verified_payload[0] == token2


# ---------------------------------------------------------------------------
# JTI (JWT ID) validation tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_jwt_token_require_jti_enabled_rejects_missing_jti(monkeypatch):
    """When require_jti is enabled, tokens without JTI should be rejected."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "require_jti", True, raising=False)

    # Token without JTI claim (explicitly exclude JTI to test rejection)
    token = _token({"sub": "user-no-jti"}, include_jti=False)

    with pytest.raises(HTTPException) as exc:
        await vc.verify_jwt_token(token)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "missing required JTI claim" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_jwt_token_require_jti_enabled_accepts_with_jti(monkeypatch):
    """When require_jti is enabled, tokens with JTI should be accepted."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "require_jti", True, raising=False)

    # Token with JTI claim
    token_payload = {"sub": "user-with-jti", "jti": "test-jti-12345", "iss": "mcpgateway", "aud": "mcpgateway-api"}
    token = jwt.encode(token_payload, SECRET, algorithm=ALGO)

    payload = await vc.verify_jwt_token(token)
    assert payload["sub"] == "user-with-jti"
    assert payload["jti"] == "test-jti-12345"


@pytest.mark.asyncio
async def test_verify_jwt_token_require_jti_disabled_accepts_missing_jti(monkeypatch, caplog):
    """When require_jti is disabled, tokens without JTI should be accepted with warning."""
    import logging

    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "require_jti", False, raising=False)

    # Token without JTI claim (explicitly exclude JTI to test the warning)
    token = _token({"sub": "user-no-jti-allowed"}, include_jti=False)

    with caplog.at_level(logging.WARNING):
        payload = await vc.verify_jwt_token(token)

    assert payload["sub"] == "user-no-jti-allowed"
    # Verify warning was logged
    assert any("JWT token without JTI accepted" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Environment claim validation tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_jwt_token_validate_environment_rejects_mismatch(monkeypatch):
    """When validate_token_environment is enabled, tokens with mismatched env claim should be rejected."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "validate_token_environment", True, raising=False)
    monkeypatch.setattr(vc.settings, "environment", "production", raising=False)

    # Token with env claim for different environment
    token = _token({"sub": "user@example.com", "env": "development"})

    with pytest.raises(HTTPException) as exc:
        await vc.verify_jwt_token(token)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "environment mismatch" in exc.value.detail


@pytest.mark.asyncio
async def test_verify_jwt_token_validate_environment_accepts_matching(monkeypatch):
    """When validate_token_environment is enabled, tokens with matching env claim should be accepted."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "validate_token_environment", True, raising=False)
    monkeypatch.setattr(vc.settings, "environment", "production", raising=False)

    # Token with matching env claim
    token = _token({"sub": "user@example.com", "env": "production"})

    payload = await vc.verify_jwt_token(token)
    assert payload["sub"] == "user@example.com"
    assert payload["env"] == "production"


@pytest.mark.asyncio
async def test_verify_jwt_token_validate_environment_allows_missing(monkeypatch):
    """When validate_token_environment is enabled, tokens without env claim should be allowed (backward compat)."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "validate_token_environment", True, raising=False)
    monkeypatch.setattr(vc.settings, "environment", "production", raising=False)

    # Token without env claim (legacy token or external IdP token)
    token = _token({"sub": "user@example.com"})

    payload = await vc.verify_jwt_token(token)
    assert payload["sub"] == "user@example.com"
    assert "env" not in payload


@pytest.mark.asyncio
async def test_verify_jwt_token_validate_environment_disabled_ignores_mismatch(monkeypatch):
    """When validate_token_environment is disabled, mismatched env claims should be ignored."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "require_token_expiration", False, raising=False)
    monkeypatch.setattr(vc.settings, "validate_token_environment", False, raising=False)
    monkeypatch.setattr(vc.settings, "environment", "production", raising=False)

    # Token with mismatched env claim - should be accepted when validation is disabled
    token = _token({"sub": "user@example.com", "env": "development"})

    payload = await vc.verify_jwt_token(token)
    assert payload["sub"] == "user@example.com"
    assert payload["env"] == "development"


# ---------------------------------------------------------------------------
# API_ALLOW_BASIC_AUTH tests for require_admin_auth()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_require_admin_auth_rejects_basic_auth_when_disabled(monkeypatch):
    """When API_ALLOW_BASIC_AUTH=false (default), basic auth should be rejected for API endpoints."""
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", False, raising=False)
    monkeypatch.setattr(vc.settings, "email_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    # Create mock request
    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    # Valid basic credentials that WOULD work if enabled
    basic_creds = HTTPBasicCredentials(username="admin", password="secret")

    with pytest.raises(HTTPException) as exc:
        await vc.require_admin_auth(
            request=mock_request,
            credentials=None,
            jwt_token=None,
            basic_credentials=basic_creds,
        )

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Basic authentication is disabled for API endpoints" in exc.value.detail
    assert exc.value.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_require_admin_auth_accepts_basic_auth_when_enabled(monkeypatch):
    """When API_ALLOW_BASIC_AUTH=true, basic auth should be accepted for API endpoints."""
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "email_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    # Create mock request
    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    # Valid basic credentials
    basic_creds = HTTPBasicCredentials(username="admin", password="secret")

    result = await vc.require_admin_auth(
        request=mock_request,
        credentials=None,
        jwt_token=None,
        basic_credentials=basic_creds,
    )

    assert result == "admin"


@pytest.mark.asyncio
async def test_require_admin_auth_invalid_basic_auth_rejected_even_when_enabled(monkeypatch):
    """When API_ALLOW_BASIC_AUTH=true, invalid credentials should still be rejected."""
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "email_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    # Create mock request
    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    # Invalid basic credentials
    basic_creds = HTTPBasicCredentials(username="admin", password="wrong")

    with pytest.raises(HTTPException) as exc:
        await vc.require_admin_auth(
            request=mock_request,
            credentials=None,
            jwt_token=None,
            basic_credentials=basic_creds,
        )

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid credentials"


@pytest.mark.asyncio
async def test_docs_basic_auth_independent_of_api_basic_auth(monkeypatch):
    """CRITICAL: Docs Basic auth should work independently of API Basic auth setting.

    When DOCS_ALLOW_BASIC_AUTH=true and API_ALLOW_BASIC_AUTH=false:
    - /docs endpoints (via require_auth_override) should accept Basic auth
    - /api/metrics/* endpoints (via require_admin_auth) should reject Basic auth
    """
    # Setup: docs enabled, API disabled
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", False, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    basic_header = f"Basic {base64.b64encode(b'admin:secret').decode()}"

    # Test 1: Docs path (require_auth_override) should ACCEPT Basic auth
    docs_result = await vc.require_auth_override(auth_header=basic_header)
    assert docs_result == "admin", "Docs Basic auth should work when DOCS_ALLOW_BASIC_AUTH=true"

    # Test 2: API path (require_admin_auth) should REJECT Basic auth
    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    basic_creds = HTTPBasicCredentials(username="admin", password="secret")
    monkeypatch.setattr(vc.settings, "email_auth_enabled", False, raising=False)

    with pytest.raises(HTTPException) as exc:
        await vc.require_admin_auth(
            request=mock_request,
            credentials=None,
            jwt_token=None,
            basic_credentials=basic_creds,
        )

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Basic authentication is disabled for API endpoints" in exc.value.detail


@pytest.mark.asyncio
async def test_require_admin_auth_no_credentials_provided(monkeypatch):
    """When no credentials are provided, require_admin_auth should return 401."""
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", False, raising=False)
    monkeypatch.setattr(vc.settings, "email_auth_enabled", False, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    with pytest.raises(HTTPException) as exc:
        await vc.require_admin_auth(
            request=mock_request,
            credentials=None,
            jwt_token=None,
            basic_credentials=None,
        )

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Authentication required"


@pytest.mark.asyncio
async def test_require_auth_override_uses_provided_request_instance(monkeypatch):
    """Cover the request!=None path (middleware can pass in a Request)."""
    monkeypatch.setattr(vc.settings, "auth_required", False, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    req = Request(scope={"type": "http", "headers": []})
    assert await vc.require_auth_override(auth_header=None, jwt_token=None, request=req) == "anonymous"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_success_admin_user(monkeypatch):
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)

    # Prevent basic-auth fallback from interfering if reached.
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", False, raising=False)

    # Patch DB + service layer imported inside require_admin_auth().
    db_session = MagicMock()
    monkeypatch.setattr("mcpgateway.db.get_db", lambda: iter([db_session]))

    class DummyUser:
        def __init__(self, email: str, is_admin: bool):
            self.email = email
            self.is_admin = is_admin

    class DummyEmailAuthService:
        def __init__(self, _db):
            pass

        async def get_user_by_email(self, email: str):
            return DummyUser(email=email, is_admin=True)

    monkeypatch.setattr("mcpgateway.services.email_auth_service.EmailAuthService", DummyEmailAuthService)
    monkeypatch.setattr(vc, "verify_jwt_token_cached", AsyncMock(return_value={"sub": "admin@example.com"}))

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    result = await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token="token", basic_credentials=None)
    assert result == "admin@example.com"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_uses_token_from_bearer_credentials(monkeypatch):
    """When jwt_token cookie is absent, token should be taken from Authorization credentials."""
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", False, raising=False)

    db_session = MagicMock()
    monkeypatch.setattr("mcpgateway.db.get_db", lambda: iter([db_session]))

    class DummyUser:
        def __init__(self, email: str, is_admin: bool):
            self.email = email
            self.is_admin = is_admin

    class DummyEmailAuthService:
        def __init__(self, _db):
            pass

        async def get_user_by_email(self, email: str):
            return DummyUser(email=email, is_admin=True)

    monkeypatch.setattr("mcpgateway.services.email_auth_service.EmailAuthService", DummyEmailAuthService)
    monkeypatch.setattr(vc, "verify_jwt_token_cached", AsyncMock(return_value={"sub": "admin@example.com"}))

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    bearer_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    result = await vc.require_admin_auth(request=mock_request, credentials=bearer_creds, jwt_token=None, basic_credentials=None)
    assert result == "admin@example.com"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_non_admin_user_falls_back_to_basic(monkeypatch):
    """Email auth non-admin path raises internally but falls back to basic auth."""
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    db_session = MagicMock()
    monkeypatch.setattr("mcpgateway.db.get_db", lambda: iter([db_session]))

    class DummyUser:
        def __init__(self, email: str, is_admin: bool):
            self.email = email
            self.is_admin = is_admin

    class DummyEmailAuthService:
        def __init__(self, _db):
            pass

        async def get_user_by_email(self, email: str):
            return DummyUser(email=email, is_admin=False)

    monkeypatch.setattr("mcpgateway.services.email_auth_service.EmailAuthService", DummyEmailAuthService)
    monkeypatch.setattr(vc, "verify_jwt_token_cached", AsyncMock(return_value={"sub": "user@example.com"}))

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "text/html"}
    mock_request.scope = {"root_path": ""}

    basic_creds = HTTPBasicCredentials(username="admin", password="secret")
    result = await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token="token", basic_credentials=basic_creds)
    assert result == "admin"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_non_admin_json_falls_back_to_basic(monkeypatch):
    """Cover the non-admin JSON branch (403 raised internally, then fallback)."""
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    db_session = MagicMock()
    monkeypatch.setattr("mcpgateway.db.get_db", lambda: iter([db_session]))

    class DummyUser:
        def __init__(self, email: str, is_admin: bool):
            self.email = email
            self.is_admin = is_admin

    class DummyEmailAuthService:
        def __init__(self, _db):
            pass

        async def get_user_by_email(self, email: str):
            return DummyUser(email=email, is_admin=False)

    monkeypatch.setattr("mcpgateway.services.email_auth_service.EmailAuthService", DummyEmailAuthService)
    monkeypatch.setattr(vc, "verify_jwt_token_cached", AsyncMock(return_value={"sub": "user@example.com"}))

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    basic_creds = HTTPBasicCredentials(username="admin", password="secret")
    result = await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token="token", basic_credentials=basic_creds)
    assert result == "admin"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_user_not_found_falls_back_to_basic(monkeypatch):
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    db_session = MagicMock()
    monkeypatch.setattr("mcpgateway.db.get_db", lambda: iter([db_session]))

    class DummyEmailAuthService:
        def __init__(self, _db):
            pass

        async def get_user_by_email(self, _email: str):
            return None

    monkeypatch.setattr("mcpgateway.services.email_auth_service.EmailAuthService", DummyEmailAuthService)
    monkeypatch.setattr(vc, "verify_jwt_token_cached", AsyncMock(return_value={"sub": "user@example.com"}))

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    basic_creds = HTTPBasicCredentials(username="admin", password="secret")
    result = await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token="token", basic_credentials=basic_creds)
    assert result == "admin"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_missing_username_falls_back_to_basic(monkeypatch):
    """If the verified payload lacks 'sub'/'username', email auth should fall back."""
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    db_session = MagicMock()
    monkeypatch.setattr("mcpgateway.db.get_db", lambda: iter([db_session]))

    class DummyEmailAuthService:
        def __init__(self, _db):
            pass

        async def get_user_by_email(self, _email: str):
            raise AssertionError("should not be called")

    monkeypatch.setattr("mcpgateway.services.email_auth_service.EmailAuthService", DummyEmailAuthService)
    monkeypatch.setattr(vc, "verify_jwt_token_cached", AsyncMock(return_value={}))

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    basic_creds = HTTPBasicCredentials(username="admin", password="secret")
    result = await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token="token", basic_credentials=basic_creds)
    assert result == "admin"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_get_db_http_401_redirects_html(monkeypatch):
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)

    def get_db_raises():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="boom")

    monkeypatch.setattr("mcpgateway.db.get_db", get_db_raises)

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "text/html"}
    mock_request.scope = {"root_path": "/root"}

    with pytest.raises(HTTPException) as exc:
        await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token="token", basic_credentials=None)

    assert exc.value.status_code == status.HTTP_302_FOUND
    assert exc.value.headers["Location"] == "/root/admin/login"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_get_db_http_403_is_reraised(monkeypatch):
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)

    def get_db_raises():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="nope")

    monkeypatch.setattr("mcpgateway.db.get_db", get_db_raises)

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    with pytest.raises(HTTPException) as exc:
        await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token="token", basic_credentials=None)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_get_db_http_401_non_html_falls_back_to_basic(monkeypatch):
    """401 from email auth should fall back to basic auth for non-browser requests."""
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "api_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "admin", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    def get_db_raises():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="boom")

    monkeypatch.setattr("mcpgateway.db.get_db", get_db_raises)

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    basic_creds = HTTPBasicCredentials(username="admin", password="secret")
    result = await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token="token", basic_credentials=basic_creds)
    assert result == "admin"


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_fallback_redirects_for_htmx(monkeypatch):
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json", "hx-request": "true"}
    mock_request.scope = {"root_path": ""}

    with pytest.raises(HTTPException) as exc:
        await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token=None, basic_credentials=None)

    assert exc.value.status_code == status.HTTP_302_FOUND
    assert exc.value.headers["Location"].endswith("/admin/login")


@pytest.mark.asyncio
async def test_require_admin_auth_email_auth_fallback_returns_json_401(monkeypatch):
    monkeypatch.setattr(vc.settings, "email_auth_enabled", True, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {"accept": "application/json"}
    mock_request.scope = {"root_path": ""}

    with pytest.raises(HTTPException) as exc:
        await vc.require_admin_auth(request=mock_request, credentials=None, jwt_token=None, basic_credentials=None)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Authentication required. Please login with email/password or use basic auth." in exc.value.detail


# ---------------------------------------------------------------------------
# require_auth_header_first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_auth_header_first_header_wins_over_request_cookie(monkeypatch):
    """Bearer Authorization header wins over a jwt_token present in request.cookies."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    header_token = _token({"user": "header-user"})
    cookie_token = _token({"user": "cookie-user"})

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    # Cookie is set directly in request.cookies (the path require_auth reads via step-1)
    mock_request.cookies = {"jwt_token": cookie_token}

    payload = await vc.require_auth_header_first(
        auth_header=f"Bearer {header_token}",
        jwt_token=None,  # cookie not passed as parameter either
        request=mock_request,
    )
    assert payload["user"] == "header-user"


@pytest.mark.asyncio
async def test_require_auth_header_first_header_wins_over_jwt_token_param(monkeypatch):
    """Bearer Authorization header wins over the jwt_token keyword argument."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    header_token = _token({"user": "header-user"})
    cookie_token = _token({"user": "cookie-user"})

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    payload = await vc.require_auth_header_first(
        auth_header=f"Bearer {header_token}",
        jwt_token=cookie_token,
        request=mock_request,
    )
    assert payload["user"] == "header-user"


@pytest.mark.asyncio
async def test_require_auth_header_first_cookie_used_when_no_header(monkeypatch):
    """Cookie is used when no Authorization header is present."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    cookie_token = _token({"user": "cookie-user"})

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {"jwt_token": cookie_token}

    payload = await vc.require_auth_header_first(
        auth_header=None,
        jwt_token=None,
        request=mock_request,
    )
    assert payload["user"] == "cookie-user"


@pytest.mark.asyncio
async def test_require_auth_header_first_jwt_token_param_fallback(monkeypatch):
    """jwt_token parameter is used when no header and no cookie in request.cookies."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    param_token = _token({"user": "param-user"})

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    payload = await vc.require_auth_header_first(
        auth_header=None,
        jwt_token=param_token,
        request=mock_request,
    )
    assert payload["user"] == "param-user"


@pytest.mark.asyncio
async def test_require_auth_header_first_no_token_raises_401(monkeypatch):
    """Raises 401 when auth_required=True and no token from any source."""
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    with pytest.raises(HTTPException) as exc:
        await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Not authenticated"


@pytest.mark.asyncio
async def test_require_auth_header_first_returns_anonymous_when_not_required(monkeypatch):
    """Returns 'anonymous' when auth_required=False and no token."""
    monkeypatch.setattr(vc.settings, "auth_required", False, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    result = await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)
    assert result == "anonymous"


@pytest.mark.asyncio
async def test_require_auth_header_first_non_bearer_header_falls_to_cookie(monkeypatch):
    """Unknown auth scheme in header does not extract a token; falls through to cookie."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", False, raising=False)

    cookie_token = _token({"user": "cookie-user"})

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {"jwt_token": cookie_token}

    payload = await vc.require_auth_header_first(
        auth_header="Token some-opaque-value",
        jwt_token=None,
        request=mock_request,
    )
    assert payload["user"] == "cookie-user"


@pytest.mark.asyncio
async def test_require_auth_header_first_no_request_uses_jwt_token_param(monkeypatch):
    """When request=None a default empty request is created; jwt_token param provides auth."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    param_token = _token({"user": "param-user"})

    payload = await vc.require_auth_header_first(auth_header=None, jwt_token=param_token, request=None)
    assert payload["user"] == "param-user"


@pytest.mark.asyncio
async def test_require_auth_header_first_proxy_auth_returns_proxy_user(monkeypatch):
    """Proxy user is returned when mcp_client_auth_enabled=False and trust_proxy_auth=True."""
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "trust_proxy_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "proxy_user_header", "x-authenticated-user", raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {"x-authenticated-user": "proxy-user@example.com"}
    mock_request.cookies = {}

    result = await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)
    assert result["sub"] == "proxy-user@example.com"
    assert result["source"] == "proxy"


@pytest.mark.asyncio
async def test_require_auth_header_first_proxy_auth_missing_header_raises_401(monkeypatch):
    """When proxy auth is required but header missing, raises 401."""
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "trust_proxy_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "proxy_user_header", "x-authenticated-user", raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    with pytest.raises(HTTPException) as exc:
        await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Proxy authentication header required" in exc.value.detail


@pytest.mark.asyncio
async def test_require_auth_header_first_no_auth_method_configured_raises_401(monkeypatch):
    """mcp_client_auth_enabled=False without proxy trust raises 401 when auth required."""
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "trust_proxy_auth", False, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    with pytest.raises(HTTPException) as exc:
        await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Authentication required but no auth method configured" in exc.value.detail


@pytest.mark.asyncio
async def test_require_auth_header_first_proxy_trust_no_header_auth_not_required_returns_anonymous(monkeypatch):
    """Line 928: trust_proxy_auth=True but no proxy header and auth_required=False returns 'anonymous'."""
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "trust_proxy_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "proxy_user_header", "x-authenticated-user", raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", False, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {}  # No proxy user header
    mock_request.cookies = {}

    result = await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)
    assert result == "anonymous"


@pytest.mark.asyncio
async def test_require_auth_header_first_no_auth_method_not_required_returns_anonymous(monkeypatch):
    """Line 935: mcp_client_auth_enabled=False, trust_proxy_auth=False, auth_required=False returns 'anonymous'."""
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", False, raising=False)
    monkeypatch.setattr(vc.settings, "trust_proxy_auth", False, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", False, raising=False)

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {}

    result = await vc.require_auth_header_first(auth_header=None, jwt_token=None, request=mock_request)
    assert result == "anonymous"


@pytest.mark.asyncio
async def test_require_auth_header_first_basic_auth_when_docs_allowed(monkeypatch):
    """Basic auth header is handled when docs_allow_basic_auth=True."""
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", True, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_user", "alice", raising=False)
    monkeypatch.setattr(vc.settings, "basic_auth_password", SecretStr("secret"), raising=False)

    basic_header = f"Basic {base64.b64encode(b'alice:secret').decode()}"
    result = await vc.require_auth_header_first(auth_header=basic_header, jwt_token=None, request=None)
    assert result == "alice"


@pytest.mark.asyncio
async def test_require_auth_header_first_empty_string_auth_header_falls_to_cookie(monkeypatch):
    """Empty string auth_header is treated as absent; falls through to cookie."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    cookie_token = _token({"user": "cookie-user"})

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {"jwt_token": cookie_token}

    payload = await vc.require_auth_header_first(
        auth_header="",  # empty string, not None
        jwt_token=None,
        request=mock_request,
    )
    assert payload["user"] == "cookie-user"


@pytest.mark.asyncio
async def test_require_auth_header_first_bearer_with_no_token_falls_to_cookie(monkeypatch):
    """'Bearer ' with no token value falls through to cookie (empty param is falsy)."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    cookie_token = _token({"user": "cookie-user"})

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {"jwt_token": cookie_token}

    payload = await vc.require_auth_header_first(
        auth_header="Bearer ",  # Bearer scheme with empty token
        jwt_token=None,
        request=mock_request,
    )
    assert payload["user"] == "cookie-user"


@pytest.mark.asyncio
async def test_require_auth_header_first_request_cookie_wins_over_jwt_token_param(monkeypatch):
    """When no header, request.cookies jwt_token wins over jwt_token parameter."""
    monkeypatch.setattr(vc.settings, "jwt_secret_key", SECRET, raising=False)
    monkeypatch.setattr(vc.settings, "jwt_algorithm", ALGO, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)

    cookie_token = _token({"user": "cookie-user"})
    param_token = _token({"user": "param-user"})

    mock_request = Mock(spec=Request)
    mock_request.headers = {}
    mock_request.cookies = {"jwt_token": cookie_token}

    payload = await vc.require_auth_header_first(
        auth_header=None,
        jwt_token=param_token,  # different token in parameter
        request=mock_request,
    )
    # request.cookies wins over jwt_token parameter (step 2 before step 3)
    assert payload["user"] == "cookie-user"
