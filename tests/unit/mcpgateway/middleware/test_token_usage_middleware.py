# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_token_usage_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for token usage logging middleware.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.middleware.token_usage_middleware import TokenUsageMiddleware


async def _make_asgi_call(middleware, scope, receive=None, send=None):
    """Helper to call ASGI middleware."""
    if receive is None:
        receive = AsyncMock()
    if send is None:
        send = AsyncMock()
    await middleware(scope, receive, send)
    return send


@pytest.mark.asyncio
async def test_skips_health_check_paths():
    """Middleware should skip health check and static paths."""
    app = AsyncMock()
    middleware = TokenUsageMiddleware(app=app)

    for path in ["/health", "/healthz", "/ready", "/metrics", "/static/admin.css"]:
        scope = {"type": "http", "path": path, "method": "GET"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        app.assert_awaited_once_with(scope, receive, send)
        app.reset_mock()


@pytest.mark.asyncio
async def test_skips_non_api_token_requests():
    """Middleware should only log for API token requests."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {"auth_method": "jwt"},  # Not an API token
    }

    with patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_session:
        await _make_asgi_call(middleware, scope)

    app.assert_awaited_once()
    # Should not create DB session for non-API token requests
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_logs_api_token_usage_with_stored_jti():
    """Middleware should log API token usage using stored JTI from scope state."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    user_mock = MagicMock()
    user_mock.email = "user@example.com"

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": "jti-stored-123",
            "user": user_mock,
        },
        "client": ("192.168.1.100", 12345),
        "headers": [(b"user-agent", b"TestClient/1.0")],
    }

    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_fresh_session,
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        mock_fresh_session.return_value.__enter__.return_value = mock_db
        await _make_asgi_call(middleware, scope)

    # Verify log_token_usage was called with correct parameters
    mock_token_service.log_token_usage.assert_awaited_once()
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["jti"] == "jti-stored-123"
    assert call_args.kwargs["user_email"] == "user@example.com"
    assert call_args.kwargs["endpoint"] == "/api/tools"
    assert call_args.kwargs["method"] == "GET"
    assert call_args.kwargs["status_code"] == 200
    assert call_args.kwargs["blocked"] is False


@pytest.mark.asyncio
async def test_logs_api_token_usage_fallback_to_token_decode():
    """Middleware should decode token if JTI not in scope state."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/resources",
        "method": "POST",
        "state": {
            "auth_method": "api_token",
            "jti": None,
            "user": None,
        },
        "client": ("10.0.0.1", 12345),
        "headers": [(b"authorization", b"Bearer test_token_here"), (b"user-agent", b"TestClient/2.0")],
    }

    mock_payload = {"jti": "jti-decoded-456", "sub": "decoded@example.com"}
    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_fresh_session,
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
        patch("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached", AsyncMock(return_value=mock_payload)),
    ):
        mock_fresh_session.return_value.__enter__.return_value = mock_db
        await _make_asgi_call(middleware, scope)

    # Verify log_token_usage was called with decoded values
    mock_token_service.log_token_usage.assert_awaited_once()
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["jti"] == "jti-decoded-456"
    assert call_args.kwargs["user_email"] == "decoded@example.com"


@pytest.mark.asyncio
async def test_handles_missing_authorization_header():
    """Middleware should handle missing Authorization header gracefully."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": None,
            "user": None,
        },
        "headers": [],  # No authorization header
    }

    with patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_session:
        await _make_asgi_call(middleware, scope)

    # Should not attempt to log if no token can be extracted
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_handles_token_decode_failure():
    """Middleware should handle token decode failures gracefully."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/prompts",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": None,
            "user": None,
        },
        "headers": [(b"authorization", b"Bearer invalid_token")],
    }

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_session,
        patch("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached", AsyncMock(side_effect=Exception("Invalid token"))),
    ):
        await _make_asgi_call(middleware, scope)

    # Should not create DB session if token decode fails
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_handles_missing_jti_in_payload():
    """Middleware should handle missing JTI in token payload."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/servers",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": None,
            "user": None,
        },
        "headers": [(b"authorization", b"Bearer token_without_jti")],
    }

    mock_payload = {"sub": "user@example.com"}  # No JTI

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_session,
        patch("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached", AsyncMock(return_value=mock_payload)),
    ):
        await _make_asgi_call(middleware, scope)

    # Should not create DB session if JTI is missing
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_handles_database_errors_gracefully():
    """Middleware should handle database errors without breaking request flow."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    user_mock = MagicMock()
    user_mock.email = "user@example.com"

    scope = {
        "type": "http",
        "path": "/api/gateways",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": "jti-error-test",
            "user": user_mock,
        },
        "client": ("192.168.1.1", 12345),
        "headers": [(b"user-agent", b"TestClient/1.0")],
    }

    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock(side_effect=Exception("DB Error"))

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_fresh_session,
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        mock_fresh_session.return_value.__enter__.return_value = mock_db
        # Should not raise exception despite DB error
        await _make_asgi_call(middleware, scope)

    # Request should still succeed
    app.assert_awaited_once()


@pytest.mark.asyncio
async def test_records_response_time():
    """Middleware should record response time in milliseconds."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    user_mock = MagicMock()
    user_mock.email = "user@example.com"

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": "jti-timing-test",
            "user": user_mock,
        },
        "client": ("192.168.1.100", 12345),
        "headers": [(b"user-agent", b"TestClient/1.0")],
    }

    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_fresh_session,
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        mock_fresh_session.return_value.__enter__.return_value = mock_db
        await _make_asgi_call(middleware, scope)

    # Verify response_time_ms was recorded
    call_args = mock_token_service.log_token_usage.call_args
    response_time = call_args.kwargs["response_time_ms"]
    assert isinstance(response_time, int)
    assert response_time >= 0


@pytest.mark.asyncio
async def test_uses_user_email_from_state():
    """Middleware should prefer user email from scope state."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    user_mock = MagicMock()
    user_mock.email = "state_user@example.com"

    scope = {
        "type": "http",
        "path": "/api/resources",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": "jti-from-state",
            "user": user_mock,
        },
        "client": ("192.168.1.50", 12345),
        "headers": [(b"user-agent", b"TestClient/1.0")],
    }

    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_fresh_session,
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
        patch("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached") as mock_verify,
    ):
        mock_fresh_session.return_value.__enter__.return_value = mock_db
        await _make_asgi_call(middleware, scope)

    # Should use email from state, not decode token
    mock_verify.assert_not_called()

    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["user_email"] == "state_user@example.com"


@pytest.mark.asyncio
async def test_handles_non_http_scope():
    """Middleware should pass through non-HTTP scopes."""
    app = AsyncMock()
    middleware = TokenUsageMiddleware(app=app)

    scope = {"type": "websocket", "path": "/ws"}
    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)

    # Should just pass through to the app
    app.assert_awaited_once_with(scope, receive, send)


@pytest.mark.asyncio
async def test_handles_exception_extracting_token_info():
    """Middleware should handle exceptions when extracting token information."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": None,
            "user": None,
        },
        "headers": [(b"authorization", b"Bearer test_token")],
    }

    # Mock Headers to raise an exception
    with patch("mcpgateway.middleware.token_usage_middleware.Headers", side_effect=Exception("Headers error")), patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_session:
        await _make_asgi_call(middleware, scope)

    # Should not create DB session if header extraction fails
    mock_session.assert_not_called()
    # Request should still succeed
    app.assert_awaited_once()


@pytest.mark.asyncio
async def test_uses_user_email_from_state_fallback():
    """Middleware should use user_email from scope state when user object is absent."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": "jti-opaque-123",
            "user": None,
            "user_email": "opaque@example.com",
        },
        "client": ("192.168.1.100", 12345),
        "headers": [(b"user-agent", b"TestClient/1.0")],
    }

    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_fresh_session,
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        mock_fresh_session.return_value.__enter__.return_value = mock_db
        await _make_asgi_call(middleware, scope)

    # Verify log_token_usage was called with user_email from state
    mock_token_service.log_token_usage.assert_awaited_once()
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["jti"] == "jti-opaque-123"
    assert call_args.kwargs["user_email"] == "opaque@example.com"


@pytest.mark.asyncio
async def test_logs_blocked_api_token_on_4xx():
    """Middleware marks usage as blocked and sets block_reason when an api_token request returns a 4xx status."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 429, "headers": []})
        await send({"type": "http.response.body", "body": b"rate limited"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    user_mock = MagicMock()
    user_mock.email = "user@example.com"

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {
            "auth_method": "api_token",
            "jti": "jti-blocked-789",
            "user": user_mock,
        },
        "client": ("192.168.1.100", 12345),
        "headers": [],
    }

    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_fresh_session,
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        mock_fresh_session.return_value.__enter__.return_value = mock_db
        await _make_asgi_call(middleware, scope)

    mock_token_service.log_token_usage.assert_awaited_once()
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["blocked"] is True
    assert call_args.kwargs["block_reason"] == "http_429"


@pytest.mark.asyncio
async def test_logs_revoked_api_token_on_401():
    """Middleware logs a blocked attempt using the DB-stored owner email, not the JWT claim."""
    # Standard
    import jwt as _jwt_lib
    from collections import namedtuple

    token_payload = {
        "jti": "jti-revoked-abc",
        "sub": "revoked@example.com",
        "user": {"auth_provider": "api_token"},
    }
    raw_token = _jwt_lib.encode(token_payload, "test-secret-key-for-unit-tests-only", algorithm="HS256")

    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b"unauthorized"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {},
        "client": ("10.0.0.1", 9000),
        "headers": [(b"authorization", f"Bearer {raw_token}".encode())],
    }

    # Mock the JTI verification to return a DB row with the real owner email
    TokenRow = namedtuple("TokenRow", ["id", "user_email"])
    mock_verify_db = MagicMock()
    mock_verify_db.execute.return_value.first.return_value = TokenRow(id="tok-1", user_email="real-owner@example.com")
    mock_log_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    call_count = [0]

    def fresh_session_factory():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_verify_db if call_count[0] == 0 else mock_log_db)
        ctx.__exit__ = MagicMock(return_value=False)
        call_count[0] += 1
        return ctx

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session", side_effect=fresh_session_factory),
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        await _make_asgi_call(middleware, scope)

    mock_token_service.log_token_usage.assert_awaited_once()
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["jti"] == "jti-revoked-abc"
    # Must use the DB-stored email, NOT the unverified JWT "sub" claim
    assert call_args.kwargs["user_email"] == "real-owner@example.com"
    assert call_args.kwargs["blocked"] is True
    assert call_args.kwargs["block_reason"] == "revoked_or_expired"


@pytest.mark.asyncio
async def test_logs_rejected_api_token_on_403():
    """Middleware logs a blocked attempt with http_403 reason using DB-stored email."""
    # Standard
    import jwt as _jwt_lib
    from collections import namedtuple

    token_payload = {
        "jti": "jti-rejected-def",
        "sub": "rejected@example.com",
        "user": {"auth_provider": "api_token"},
    }
    raw_token = _jwt_lib.encode(token_payload, "test-secret-key-for-unit-tests-only", algorithm="HS256")

    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 403, "headers": []})
        await send({"type": "http.response.body", "body": b"forbidden"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {},
        "client": ("10.0.0.1", 9000),
        "headers": [(b"authorization", f"Bearer {raw_token}".encode())],
    }

    TokenRow = namedtuple("TokenRow", ["id", "user_email"])
    mock_verify_db = MagicMock()
    mock_verify_db.execute.return_value.first.return_value = TokenRow(id="tok-2", user_email="db-owner@example.com")
    mock_log_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    call_count = [0]

    def fresh_session_factory():
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_verify_db if call_count[0] == 0 else mock_log_db)
        ctx.__exit__ = MagicMock(return_value=False)
        call_count[0] += 1
        return ctx

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session", side_effect=fresh_session_factory),
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        await _make_asgi_call(middleware, scope)

    mock_token_service.log_token_usage.assert_awaited_once()
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["blocked"] is True
    assert call_args.kwargs["block_reason"] == "http_403"
    assert call_args.kwargs["user_email"] == "db-owner@example.com"


@pytest.mark.asyncio
async def test_skips_rejected_api_token_missing_jti():
    """Middleware skips logging when a rejected API token payload has no jti or sub/email."""
    # Standard
    import jwt as _jwt_lib

    token_payload = {
        # No jti, no sub/email
        "user": {"auth_provider": "api_token"},
    }
    raw_token = _jwt_lib.encode(token_payload, "test-secret-key-for-unit-tests-only", algorithm="HS256")

    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b"unauthorized"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {},
        "client": ("10.0.0.1", 9000),
        "headers": [(b"authorization", f"Bearer {raw_token}".encode())],
    }

    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_fresh_session,
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        mock_fresh_session.return_value.__enter__.return_value = mock_db
        await _make_asgi_call(middleware, scope)

    mock_token_service.log_token_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_skips_rejected_request_without_bearer_header():
    """Middleware skips logging when a 401/403 response has no Bearer authorization header."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b"unauthorized"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {},
        "client": ("10.0.0.1", 9000),
        "headers": [],  # No authorization header
    }

    with patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_session:
        await _make_asgi_call(middleware, scope)

    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_skips_rejected_non_api_token_jwt():
    """Middleware skips logging when a 401/403 response carries a JWT that is not an API token."""
    # Standard
    import jwt as _jwt_lib

    token_payload = {
        "jti": "jti-jwt-session",
        "sub": "user@example.com",
        "user": {"auth_provider": "email"},  # Not an API token
    }
    raw_token = _jwt_lib.encode(token_payload, "test-secret-key-for-unit-tests-only", algorithm="HS256")

    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 403, "headers": []})
        await send({"type": "http.response.body", "body": b"forbidden"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {},
        "client": ("10.0.0.1", 9000),
        "headers": [(b"authorization", f"Bearer {raw_token}".encode())],
    }

    with patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_session:
        await _make_asgi_call(middleware, scope)

    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_skips_rejected_request_with_malformed_token():
    """Middleware skips logging when a 401/403 response carries a malformed token that cannot be decoded."""
    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b"unauthorized"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {},
        "client": ("10.0.0.1", 9000),
        "headers": [(b"authorization", b"Bearer not-a-valid-jwt-at-all")],
    }

    with patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session") as mock_session:
        await _make_asgi_call(middleware, scope)

    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_skips_forged_jwt_with_unknown_jti():
    """Middleware skips logging when a rejected API token's JTI doesn't exist in the database."""
    # Standard
    import jwt as _jwt_lib

    token_payload = {
        "jti": "forged-jti-not-in-db",
        "sub": "attacker@evil.com",
        "user": {"auth_provider": "api_token"},
    }
    raw_token = _jwt_lib.encode(token_payload, "test-secret-key-for-unit-tests-only", algorithm="HS256")

    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b"unauthorized"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {},
        "client": ("10.0.0.1", 9000),
        "headers": [(b"authorization", f"Bearer {raw_token}".encode())],
    }

    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    # Mock fresh_db_session: first call (JTI verify) returns no match, second would be for logging
    mock_verify_db = MagicMock()
    mock_verify_db.execute.return_value.first.return_value = None

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_verify_db)
    mock_ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session", return_value=mock_ctx),
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        await _make_asgi_call(middleware, scope)

    # Should NOT log usage because JTI was not found in DB
    mock_token_service.log_token_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_skips_logging_on_jti_verification_db_error():
    """Middleware skips logging when the JTI verification DB query fails."""
    # Standard
    import jwt as _jwt_lib

    token_payload = {
        "jti": "jti-db-error",
        "sub": "user@example.com",
        "user": {"auth_provider": "api_token"},
    }
    raw_token = _jwt_lib.encode(token_payload, "test-secret-key-for-unit-tests-only", algorithm="HS256")

    app = AsyncMock()

    async def app_impl(scope, receive, send):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b"unauthorized"})

    app.side_effect = app_impl
    middleware = TokenUsageMiddleware(app=app)

    scope = {
        "type": "http",
        "path": "/api/tools",
        "method": "GET",
        "state": {},
        "client": ("10.0.0.1", 9000),
        "headers": [(b"authorization", f"Bearer {raw_token}".encode())],
    }

    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()

    with (
        patch("mcpgateway.middleware.token_usage_middleware.fresh_db_session", side_effect=Exception("DB down")),
        patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service),
    ):
        await _make_asgi_call(middleware, scope)

    # Should NOT log usage because DB verification failed
    mock_token_service.log_token_usage.assert_not_awaited()
