# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_auth_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for auth middleware.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request
from starlette.responses import Response
from mcpgateway.middleware.auth_middleware import AuthContextMiddleware


@pytest.mark.asyncio
async def test_health_and_static_paths_skipped(monkeypatch):
    """Ensure middleware skips health and static paths."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    for path in ["/health", "/healthz", "/ready", "/metrics", "/static/admin.css"]:
        request = MagicMock(spec=Request)
        request.url.path = path
        response = await middleware.dispatch(request, call_next)
        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200
        call_next.reset_mock()


@pytest.mark.asyncio
async def test_no_token_continues(monkeypatch):
    """If no token found, request continues without user context."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {}
    request.headers = {}

    response = await middleware.dispatch(request, call_next)
    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    # request.state is a MagicMock, so user may exist as mock attribute
    # Instead, ensure user was never set explicitly
    # Ensure user attribute was not explicitly set (MagicMock defaults to having attributes)
    assert "user" not in request.state.__dict__


@pytest.mark.asyncio
async def test_token_from_cookie(monkeypatch):
    """Token extracted from cookie triggers authentication."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "cookie_token"}
    request.headers = {}
    # Ensure no existing session (auth middleware should create and close one)
    request.state.db = None

    mock_user = MagicMock()
    mock_user.email = "user@example.com"

    # DB session is only created when security logging is enabled
    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=MagicMock()) as mock_session,
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
    ):
        response = await middleware.dispatch(request, call_next)

    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    assert request.state.user.email == "user@example.com"
    # Auth middleware should create and close the session (owned=True)
    mock_session.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_token_from_header(monkeypatch):
    """Token extracted from Authorization header triggers authentication."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {}
    request.headers = {"authorization": "Bearer header_token"}
    # Ensure no existing session (auth middleware should create and close one)
    request.state.db = None

    mock_user = MagicMock()
    mock_user.email = "header@example.com"

    # DB session is only created when security logging is enabled
    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=MagicMock()) as mock_session,
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
    ):
        response = await middleware.dispatch(request, call_next)

    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    assert request.state.user.email == "header@example.com"
    # Auth middleware should create and close the session (owned=True)
    mock_session.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_authentication_failure(monkeypatch):
    """Authentication failure should log and continue without user context."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {}
    # Ensure no existing session (auth middleware should create and close one)
    request.state.db = None
    # Mock request.client for security_logger
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    # Mock security_logger to prevent database operations
    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt = MagicMock(return_value=None)

    # DB session is only created when failure logging is enabled
    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=MagicMock()) as mock_session,
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=Exception("Invalid token"))),
        patch("mcpgateway.middleware.auth_middleware.logger") as mock_logger,
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    # Ensure user attribute was not explicitly set (MagicMock defaults to having attributes)
    assert "user" not in request.state.__dict__
    # Verify log message contains failure text
    logged_messages = [args[0] for args, _ in mock_logger.info.call_args_list]
    assert any("✗ Auth context extraction failed" in msg for msg in logged_messages)
    mock_session.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_db_close_exception(monkeypatch):
    """Ensure db.close exceptions are handled but do not break flow.

    With DB session optimization, sessions are only created when security
    logging is enabled. This test verifies that close() exceptions in the
    finally block don't prevent request processing.
    """
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "token"}
    request.headers = {}
    # Ensure no existing session (auth middleware should create and close one)
    request.state.db = None

    mock_user = MagicMock()
    mock_user.email = "user@example.com"
    mock_db = MagicMock()
    mock_db.close.side_effect = Exception("close error")

    # DB session is only created when security logging is enabled
    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_db),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
    ):
        # The close() exception should be caught in finally block
        # and not propagate to break the request
        response = await middleware.dispatch(request, call_next)

    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    # Verify close was called (even though it raised)
    mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_no_db_session_when_logging_disabled(monkeypatch):
    """Verify no DB session is created when security logging is disabled.

    This tests the DB session optimization - when neither success nor failure
    logging is enabled, no database session should be created.
    """
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "cookie_token"}
    request.headers = {}

    mock_user = MagicMock()
    mock_user.email = "user@example.com"

    # Disable both success and failure logging
    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal") as mock_session,
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
    ):
        response = await middleware.dispatch(request, call_next)

    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    assert request.state.user.email == "user@example.com"
    # SessionLocal should NOT have been called - key optimization
    mock_session.assert_not_called()


# ============================================================================
# Coverage improvement tests
# ============================================================================


@pytest.mark.asyncio
async def test_success_logging_exception(monkeypatch):
    """log_authentication_attempt raises during success logging (lines 139-140)."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "token"}
    request.headers = {}

    mock_user = MagicMock()
    mock_user.email = "user@example.com"
    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=MagicMock()),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    assert request.state.user.email == "user@example.com"


@pytest.mark.asyncio
async def test_success_logging_exception_rolls_back_shared_session():
    """When success logging fails on a shared session, rollback must clear PendingRollbackError."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "token"}
    request.headers = {}

    mock_user = MagicMock()
    mock_user.email = "user@example.com"
    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    # Shared session (owned=False) — simulate ObservabilityMiddleware providing it
    shared_session = MagicMock()
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    # Shared session must be rolled back to prevent PendingRollbackError downstream
    shared_session.rollback.assert_called_once()
    # Shared session must NOT be closed (owned by ObservabilityMiddleware)
    shared_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_hard_deny_logging_exception_rolls_back_shared_session():
    """When hard-deny logging fails on a shared session, rollback must clear PendingRollbackError."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "revoked_token"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "10.0.0.1"

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    # Shared session (owned=False)
    shared_session = MagicMock()
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401
    shared_session.rollback.assert_called_once()
    shared_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_generic_failure_logging_exception_rolls_back_shared_session():
    """When generic-exception logging fails on a shared session, rollback must clear PendingRollbackError."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    # Shared session (owned=False)
    shared_session = MagicMock()
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=Exception("decode error"))),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    shared_session.rollback.assert_called_once()
    shared_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_rollback_failure_falls_back_to_invalidate():
    """When rollback also fails, session.invalidate() is called as last resort."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "token"}
    request.headers = {}

    mock_user = MagicMock()
    mock_user.email = "user@example.com"
    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    # Shared session where rollback also fails
    shared_session = MagicMock()
    shared_session.rollback.side_effect = Exception("rollback failed")
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    shared_session.rollback.assert_called_once()
    shared_session.invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_success_invalidate_failure_silenced():
    """When rollback AND invalidate both fail on success path, request still succeeds."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "token"}
    request.headers = {}

    mock_user = MagicMock()
    mock_user.email = "user@example.com"
    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    shared_session = MagicMock()
    shared_session.rollback.side_effect = Exception("rollback failed")
    shared_session.invalidate.side_effect = Exception("invalidate failed")
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    shared_session.rollback.assert_called_once()
    shared_session.invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_hard_deny_invalidate_failure_silenced():
    """When rollback AND invalidate both fail on hard-deny path, response still returns."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "revoked_token"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "10.0.0.1"

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    shared_session = MagicMock()
    shared_session.rollback.side_effect = Exception("rollback failed")
    shared_session.invalidate.side_effect = Exception("invalidate failed")
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_generic_failure_invalidate_failure_silenced():
    """When rollback AND invalidate both fail on generic-exception path, request still continues."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    shared_session = MagicMock()
    shared_session.rollback.side_effect = Exception("rollback failed")
    shared_session.invalidate.side_effect = Exception("invalidate failed")
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=Exception("decode error"))),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_hard_deny_rollback_failure_falls_back_to_invalidate():
    """When hard-deny rollback also fails, session.invalidate() is called."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "revoked_token"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "10.0.0.1"

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    shared_session = MagicMock()
    shared_session.rollback.side_effect = Exception("rollback failed")
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401
    shared_session.rollback.assert_called_once()
    shared_session.invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_generic_failure_rollback_failure_falls_back_to_invalidate():
    """When generic-exception rollback also fails, session.invalidate() is called."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("db error")

    shared_session = MagicMock()
    shared_session.rollback.side_effect = Exception("rollback failed")
    request.state.db = shared_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=Exception("decode error"))),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    shared_session.rollback.assert_called_once()
    shared_session.invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_auth_failure_logging_disabled(monkeypatch):
    """Auth fails but failure logging is disabled (branch 153->176)."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {}

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal") as mock_session,
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=Exception("bad"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_failure_logging_exception(monkeypatch):
    """log_authentication_attempt raises during failure logging (lines 167-168)."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt.side_effect = RuntimeError("log fail")

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=MagicMock()),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=Exception("bad"))),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_failure_logging_close_exception(monkeypatch):
    """db.close() raises during failure logging (lines 172-173)."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {}
    # Ensure no existing session (auth middleware should create and close one)
    request.state.db = None
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    mock_db = MagicMock()
    mock_db.close.side_effect = RuntimeError("close fail")
    mock_security_logger = MagicMock()

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_db),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=Exception("bad"))),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    mock_db.close.assert_called_once()


# ============================================================================
# HTTPException 401/403 hard-deny tests (auth_middleware lines 148-194)
# ============================================================================


@pytest.mark.asyncio
async def test_http_401_returns_json_deny_for_api_request():
    """HTTPException 401 from get_current_user returns JSON 401 for API requests."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "revoked_token"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_403_returns_json_deny_for_api_request():
    """HTTPException 403 from get_current_user returns JSON 403 for API requests."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=403, detail="Account disabled"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_401_browser_request_continues_for_redirect():
    """HTTPException 401 for browser/HTMX requests continues to allow RBAC redirect."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("login page", status_code=200))
    request = MagicMock(spec=Request)
    request.url.path = "/admin/overview/partial"
    request.cookies = {"jwt_token": "stale_cookie"}
    request.headers = {"accept": "text/html", "hx-request": "true"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    # Browser request should pass through for RBAC redirect, not get JSON 401
    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_http_401_with_failure_logging_enabled():
    """HTTPException 401 logs the failure when auth failure logging is enabled."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "revoked_token"}
    request.headers = {"accept": "application/json"}
    # Ensure no existing session (auth middleware should create and close one)
    request.state.db = None
    request.client = MagicMock()
    request.client.host = "10.0.0.1"

    mock_security_logger = MagicMock()
    mock_db = MagicMock()

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_db),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401
    mock_security_logger.log_authentication_attempt.assert_called_once()
    # Auth middleware must commit immediately because hard-deny paths (API requests)
    # return JSONResponse without reaching get_db()
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_http_401_logging_db_error_handled():
    """DB error during 401 failure logging is caught gracefully."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {"accept": "application/json"}
    # Ensure no existing session (auth middleware should create and close one)
    request.state.db = None
    request.client = MagicMock()
    request.client.host = "10.0.0.1"

    mock_security_logger = MagicMock()
    mock_security_logger.log_authentication_attempt = MagicMock(side_effect=Exception("DB down"))
    mock_db = MagicMock()

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_db),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    # Should still return 401 despite logging failure
    assert response.status_code == 401
    mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_http_401_logging_db_close_error_handled():
    """DB close error during 401 failure logging is caught gracefully."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "bad_token"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "10.0.0.1"

    mock_security_logger = MagicMock()
    mock_db = MagicMock()
    mock_db.close.side_effect = Exception("close failed")

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_db),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_non_401_403_http_exception_continues_as_anonymous():
    """HTTPException with non-401/403 status continues as anonymous."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "some_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=500, detail="Internal error"))),
    ):
        response = await middleware.dispatch(request, call_next)

    # Non-security error: continue as anonymous
    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_non_revocation_401_falls_through_as_anonymous():
    """Non-revocation 401 (e.g. malformed token) continues as anonymous for route-level auth."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "minimal_jwt"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid authentication credentials"))),
    ):
        response = await middleware.dispatch(request, call_next)

    # Non-revocation 401 should fall through, not hard-deny
    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_http_401_referer_admin_continues_for_redirect():
    """HTTPException 401 with Referer: /admin continues for RBAC redirect (not JSON deny)."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("login page", status_code=200))
    request = MagicMock(spec=Request)
    request.url.path = "/admin/tools/partial"
    request.cookies = {"jwt_token": "stale_cookie"}
    request.headers = {"accept": "*/*", "referer": "http://localhost:8080/admin/"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    # Referer-based admin detection should let the request through for redirect
    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_http_401_json_deny_includes_security_headers():
    """JSON 401 response includes essential security headers (X-Content-Type-Options, Referrer-Policy)."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "revoked_token"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=False),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


# Session Reuse Tests (Issue #3622)


def test_get_or_create_session_reuses_existing():
    """Verify _get_or_create_session reuses session from request.state.db."""
    from mcpgateway.middleware.auth_middleware import _get_or_create_session

    mock_session = MagicMock()
    mock_request = MagicMock(spec=Request)
    mock_request.state.db = mock_session

    db, owned = _get_or_create_session(mock_request)

    assert db is mock_session
    assert owned is False


def test_get_or_create_session_creates_when_none_exists():
    """Verify _get_or_create_session creates session when request.state.db is None."""
    from mcpgateway.middleware.auth_middleware import _get_or_create_session

    mock_request = MagicMock(spec=Request)
    # Configure getattr to return None for 'db' attribute
    mock_request.state = MagicMock()
    mock_request.state.db = None

    with patch("mcpgateway.middleware.auth_middleware.SessionLocal") as mock_session_local:
        mock_new_session = MagicMock()
        mock_session_local.return_value = mock_new_session

        db, owned = _get_or_create_session(mock_request)

        assert db is mock_new_session
        assert owned is True
        mock_session_local.assert_called_once()
        # Owned sessions are NOT stored in request.state.db to prevent
        # downstream code from reusing a session that will be closed
        assert mock_request.state.db is None


@pytest.mark.asyncio
async def test_auth_middleware_reuses_session_on_success():
    """Verify auth middleware reuses session from request.state.db on success."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "valid_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    # Set up existing session in request.state
    existing_session = MagicMock()
    request.state.db = existing_session

    mock_user = MagicMock()
    mock_user.email = "user@example.com"

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal") as mock_session_local,
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
    ):
        response = await middleware.dispatch(request, call_next)

    # SessionLocal should NOT be called (session reused)
    mock_session_local.assert_not_called()
    # Existing session should NOT be closed (not owned)
    existing_session.close.assert_not_called()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_middleware_closes_only_owned_sessions():
    """Verify auth middleware only closes sessions it created."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "valid_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    # No existing session - auth middleware will create one
    request.state = MagicMock()
    request.state.db = None

    mock_user = MagicMock()
    mock_user.email = "user@example.com"

    mock_new_session = MagicMock()

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_new_session),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
    ):
        response = await middleware.dispatch(request, call_next)

    # New session should be closed (owned=True)
    mock_new_session.close.assert_called_once()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_middleware_handles_close_failure():
    """Verify graceful handling of session close failures."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "valid_token"}
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    # No existing session
    request.state = MagicMock()
    request.state.db = None

    mock_user = MagicMock()
    mock_user.email = "user@example.com"

    mock_new_session = MagicMock()
    mock_new_session.close.side_effect = Exception("Close failed")

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_new_session),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)),
        patch("mcpgateway.middleware.auth_middleware.logger") as mock_logger,
    ):
        response = await middleware.dispatch(request, call_next)

    # Close failure should be logged as warning
    mock_logger.warning.assert_called()
    assert "Failed to close auth session" in str(mock_logger.warning.call_args)
    # Request should still succeed
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_middleware_reuses_session_on_failure():
    """Verify auth middleware reuses session from request.state.db on auth failure."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "invalid_token"}
    request.headers = {"accept": "application/json"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    # Set up existing session
    existing_session = MagicMock()
    request.state.db = existing_session

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal") as mock_session_local,
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    # SessionLocal should NOT be called (session reused)
    mock_session_local.assert_not_called()
    # Existing session should NOT be closed (not owned)
    existing_session.close.assert_not_called()
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_failure_logs_committed_before_hard_deny_api_response():
    """
    REGRESSION TEST: Auth failure logs must be committed before returning hard-deny JSONResponse.

    This test validates the fix for the bug where auth failure logs were lost when:
    1. Auth fails with a hard-deny error (401/403 with specific details)
    2. Request is an API request (not browser)
    3. Middleware returns JSONResponse immediately without reaching route handler
    4. get_db() never runs, so logs were never committed

    The fix: Auth middleware commits immediately after logging to ensure persistence
    even when the request doesn't reach get_db().
    """
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "revoked_token"}
    request.headers = {"accept": "application/json"}  # API request, not browser
    request.state.db = None  # No existing session
    request.client = MagicMock()
    request.client.host = "10.0.0.1"

    mock_security_logger = MagicMock()
    mock_db = MagicMock()

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_db),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    # Verify hard-deny response
    assert response.status_code == 401
    # Verify call_next was NOT called (API hard-deny path returns immediately)
    call_next.assert_not_awaited()

    # CRITICAL: Verify logs were committed before returning JSONResponse
    # This is the regression test - without commit, logs are lost
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_auth_middleware_close_failure_in_hard_deny_path():
    """Verify close failure is handled gracefully in hard deny (401/403) path."""
    from fastapi import HTTPException

    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.cookies = {"jwt_token": "revoked_token"}
    request.headers = {"accept": "application/json"}
    # No existing session - auth middleware will create and try to close one
    request.state.db = None
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    mock_db = MagicMock()
    mock_db.close.side_effect = Exception("Close failed")
    mock_security_logger = MagicMock()

    with (
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_success", return_value=False),
        patch("mcpgateway.middleware.auth_middleware._should_log_auth_failure", return_value=True),
        patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_db),
        patch("mcpgateway.middleware.auth_middleware.security_logger", mock_security_logger),
        patch("mcpgateway.middleware.auth_middleware.logger") as mock_logger,
        patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=HTTPException(status_code=401, detail="Token has been revoked"))),
    ):
        response = await middleware.dispatch(request, call_next)

    # Should still return 401 despite close failure
    assert response.status_code == 401
    # Close should have been attempted
    mock_db.close.assert_called_once()
    # Warning should be logged
    mock_logger.warning.assert_called()
    assert any("Failed to close auth session" in str(call) for call in mock_logger.warning.call_args_list)
