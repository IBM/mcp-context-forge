# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_token_usage_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for token usage logging middleware.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request
from starlette.responses import Response
from mcpgateway.middleware.token_usage_middleware import TokenUsageMiddleware


@pytest.mark.asyncio
async def test_skips_health_check_paths():
    """Middleware should skip health check and static paths."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    for path in ["/health", "/healthz", "/ready", "/metrics", "/static/logo.png"]:
        request = MagicMock(spec=Request)
        request.url.path = path
        response = await middleware.dispatch(request, call_next)
        call_next.assert_awaited_once_with(request)
        assert response.status_code == 200
        call_next.reset_mock()


@pytest.mark.asyncio
async def test_skips_non_api_token_requests():
    """Middleware should only log for API token requests."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))
    
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.state.auth_method = "jwt"  # Not an API token
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal") as mock_session:
        response = await middleware.dispatch(request, call_next)
    
    call_next.assert_awaited_once()
    assert response.status_code == 200
    # Should not create DB session for non-API token requests
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_logs_api_token_usage_with_stored_jti():
    """Middleware should log API token usage using stored JTI from request.state."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    
    # Mock request with API token authentication
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.method = "GET"
    request.state.auth_method = "api_token"
    request.state.jti = "jti-stored-123"
    request.state.user = MagicMock(email="user@example.com")
    request.client.host = "192.168.1.100"
    request.headers = {"user-agent": "TestClient/1.0"}
    
    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal", return_value=mock_db), \
         patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service):
        response = await middleware.dispatch(request, call_next)
    
    assert response.status_code == 200
    
    # Verify log_token_usage was called with correct parameters
    mock_token_service.log_token_usage.assert_awaited_once()
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["jti"] == "jti-stored-123"
    assert call_args.kwargs["user_email"] == "user@example.com"
    assert call_args.kwargs["endpoint"] == "/api/tools"
    assert call_args.kwargs["method"] == "GET"
    assert call_args.kwargs["status_code"] == 200
    assert call_args.kwargs["blocked"] is False
    
    # Verify DB session was committed and closed
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_logs_api_token_usage_fallback_to_token_decode():
    """Middleware should decode token if JTI not in request.state."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    
    # Mock request with API token but no stored JTI
    request = MagicMock(spec=Request)
    request.url.path = "/api/resources"
    request.method = "POST"
    request.state.auth_method = "api_token"
    # No request.state.jti or request.state.user
    request.client.host = "10.0.0.1"
    request.headers = {
        "authorization": "Bearer test_token_here",
        "user-agent": "TestClient/2.0"
    }
    
    mock_payload = {"jti": "jti-decoded-456", "sub": "decoded@example.com"}
    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal", return_value=mock_db), \
         patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service), \
         patch("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached", AsyncMock(return_value=mock_payload)):
        response = await middleware.dispatch(request, call_next)
    
    assert response.status_code == 200
    
    # Verify log_token_usage was called with decoded values
    mock_token_service.log_token_usage.assert_awaited_once()
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["jti"] == "jti-decoded-456"
    assert call_args.kwargs["user_email"] == "decoded@example.com"
    
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_handles_missing_authorization_header():
    """Middleware should handle missing Authorization header gracefully."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.state.auth_method = "api_token"
    request.headers = {}  # No authorization header
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal") as mock_session:
        response = await middleware.dispatch(request, call_next)
    
    assert response.status_code == 200
    # Should not attempt to log if no token can be extracted
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_handles_token_decode_failure():
    """Middleware should handle token decode failures gracefully."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    
    request = MagicMock(spec=Request)
    request.url.path = "/api/prompts"
    request.state.auth_method = "api_token"
    request.headers = {"authorization": "Bearer invalid_token"}
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal") as mock_session, \
         patch("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached", AsyncMock(side_effect=Exception("Invalid token"))):
        response = await middleware.dispatch(request, call_next)
    
    assert response.status_code == 200
    # Should not create DB session if token decode fails
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_handles_missing_jti_in_payload():
    """Middleware should handle missing JTI in token payload."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    
    request = MagicMock(spec=Request)
    request.url.path = "/api/servers"
    request.state.auth_method = "api_token"
    request.headers = {"authorization": "Bearer token_without_jti"}
    
    mock_payload = {"sub": "user@example.com"}  # No JTI
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal") as mock_session, \
         patch("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached", AsyncMock(return_value=mock_payload)):
        response = await middleware.dispatch(request, call_next)
    
    assert response.status_code == 200
    # Should not create DB session if JTI is missing
    mock_session.assert_not_called()


@pytest.mark.asyncio
async def test_handles_database_errors_gracefully():
    """Middleware should handle database errors without breaking request flow."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    
    request = MagicMock(spec=Request)
    request.url.path = "/api/gateways"
    request.method = "GET"
    request.state.auth_method = "api_token"
    request.state.jti = "jti-error-test"
    request.state.user = MagicMock(email="user@example.com")
    request.client.host = "192.168.1.1"
    request.headers = {"user-agent": "TestClient/1.0"}
    
    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock(side_effect=Exception("DB Error"))
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal", return_value=mock_db), \
         patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service):
        response = await middleware.dispatch(request, call_next)
    
    # Request should still succeed despite DB error
    assert response.status_code == 200
    
    # Verify rollback was called
    mock_db.rollback.assert_called_once()
    mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_records_response_time():
    """Middleware should record response time in milliseconds."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    
    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.method = "GET"
    request.state.auth_method = "api_token"
    request.state.jti = "jti-timing-test"
    request.state.user = MagicMock(email="user@example.com")
    request.client.host = "192.168.1.100"
    request.headers = {"user-agent": "TestClient/1.0"}
    
    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal", return_value=mock_db), \
         patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service):
        response = await middleware.dispatch(request, call_next)
    
    assert response.status_code == 200
    
    # Verify response_time_ms was recorded
    call_args = mock_token_service.log_token_usage.call_args
    response_time = call_args.kwargs["response_time_ms"]
    assert isinstance(response_time, int)
    assert response_time >= 0


@pytest.mark.asyncio
async def test_uses_user_email_from_state():
    """Middleware should prefer user email from request.state.user."""
    middleware = TokenUsageMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok", status_code=200))
    
    request = MagicMock(spec=Request)
    request.url.path = "/api/resources"
    request.method = "GET"
    request.state.auth_method = "api_token"
    request.state.jti = "jti-from-state"
    request.state.user = MagicMock(email="state_user@example.com")
    request.client.host = "192.168.1.50"
    request.headers = {"user-agent": "TestClient/1.0"}
    
    mock_db = MagicMock()
    mock_token_service = MagicMock()
    mock_token_service.log_token_usage = AsyncMock()
    
    with patch("mcpgateway.middleware.token_usage_middleware.SessionLocal", return_value=mock_db), \
         patch("mcpgateway.middleware.token_usage_middleware.TokenCatalogService", return_value=mock_token_service), \
         patch("mcpgateway.middleware.token_usage_middleware.verify_jwt_token_cached") as mock_verify:
        response = await middleware.dispatch(request, call_next)
    
    assert response.status_code == 200
    
    # Should use email from state, not decode token
    mock_verify.assert_not_called()
    
    call_args = mock_token_service.log_token_usage.call_args
    assert call_args.kwargs["user_email"] == "state_user@example.com"
