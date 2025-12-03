# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_auth_middleware.py
Copyright 2025
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

    for path in ["/health", "/healthz", "/ready", "/metrics", "/static/logo.png"]:
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

    mock_user = MagicMock()
    mock_user.email = "user@example.com"

    with patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=MagicMock()) as mock_session, \
         patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)):
        response = await middleware.dispatch(request, call_next)

    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    assert request.state.user.email == "user@example.com"
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

    mock_user = MagicMock()
    mock_user.email = "header@example.com"

    with patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=MagicMock()) as mock_session, \
         patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)):
        response = await middleware.dispatch(request, call_next)

    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    assert request.state.user.email == "header@example.com"
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

    with patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=MagicMock()) as mock_session, \
         patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(side_effect=Exception("Invalid token"))), \
         patch("mcpgateway.middleware.auth_middleware.logger") as mock_logger:
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
    """Ensure db.close exceptions are logged but do not break flow."""
    middleware = AuthContextMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    request = MagicMock(spec=Request)
    request.url.path = "/api/data"
    request.cookies = {"jwt_token": "token"}
    request.headers = {}

    mock_user = MagicMock()
    mock_user.email = "user@example.com"
    mock_db = MagicMock()
    mock_db.close.side_effect = Exception("close error")

    with patch("mcpgateway.middleware.auth_middleware.SessionLocal", return_value=mock_db), \
         patch("mcpgateway.middleware.auth_middleware.get_current_user", AsyncMock(return_value=mock_user)), \
         patch("mcpgateway.middleware.auth_middleware.logger") as mock_logger:
        response = await middleware.dispatch(request, call_next)

    call_next.assert_awaited_once_with(request)
    assert response.status_code == 200
    # Verify log message contains close error text
    logged_debugs = [args[0] for args, _ in mock_logger.debug.call_args_list]
    assert any("Failed to close database session" in msg for msg in logged_debugs)
