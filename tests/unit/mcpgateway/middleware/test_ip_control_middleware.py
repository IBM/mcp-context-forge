# -*- coding: utf-8 -*-
"""Tests for IP access control middleware."""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.middleware.ip_control import IPControlMiddleware


@pytest.mark.asyncio
async def test_health_paths_always_pass(monkeypatch):
    """Health check paths should bypass IP control."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", ["/health", "/healthz", "/ready"])
    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    for path in ["/health", "/healthz", "/ready"]:
        request = MagicMock(spec=Request)
        request.url.path = path
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        call_next.reset_mock()


@pytest.mark.asyncio
async def test_allowed_ip_passes_through(monkeypatch):
    """An allowed IP should pass through to the handler."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", ["/health"])
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_trust_proxy_headers", False)
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_log_only", False)

    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.client.host = "192.168.1.1"
    request.headers = {}
    request.state = MagicMock()

    mock_service = MagicMock()
    mock_service.evaluate_ip.return_value = True

    with patch("mcpgateway.middleware.ip_control.get_ip_control_service", return_value=mock_service):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)
    assert request.state.client_ip == "192.168.1.1"
    assert request.state.ip_control_result is True


@pytest.mark.asyncio
async def test_denied_ip_returns_403(monkeypatch):
    """A denied IP should receive a 403 JSON response."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", ["/health"])
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_trust_proxy_headers", False)
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_log_only", False)

    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.client.host = "10.0.0.1"
    request.headers = {}
    request.state = MagicMock()

    mock_service = MagicMock()
    mock_service.evaluate_ip.return_value = False

    with patch("mcpgateway.middleware.ip_control.get_ip_control_service", return_value=mock_service):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_denied_ip_log_only_passes_through(monkeypatch):
    """In log-only mode, denied IPs should still pass through."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", ["/health"])
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_trust_proxy_headers", False)
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_log_only", True)

    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.client.host = "10.0.0.1"
    request.headers = {}
    request.state = MagicMock()

    mock_service = MagicMock()
    mock_service.evaluate_ip.return_value = False

    with patch("mcpgateway.middleware.ip_control.get_ip_control_service", return_value=mock_service):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_x_forwarded_for_extraction(monkeypatch):
    """X-Forwarded-For header should be used for client IP when trusted."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", ["/health"])
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_trust_proxy_headers", True)
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_log_only", False)

    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.client.host = "172.16.0.1"
    request.headers = {"x-forwarded-for": "203.0.113.50, 70.41.3.18, 150.172.238.178"}
    request.state = MagicMock()

    mock_service = MagicMock()
    mock_service.evaluate_ip.return_value = True

    with patch("mcpgateway.middleware.ip_control.get_ip_control_service", return_value=mock_service):
        await middleware.dispatch(request, call_next)

    # Should extract first IP from X-Forwarded-For
    mock_service.evaluate_ip.assert_called_once_with("203.0.113.50", "/api/tools")
    assert request.state.client_ip == "203.0.113.50"


@pytest.mark.asyncio
async def test_x_real_ip_extraction(monkeypatch):
    """X-Real-IP header should be used when X-Forwarded-For is absent."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", ["/health"])
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_trust_proxy_headers", True)
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_log_only", False)

    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.client.host = "172.16.0.1"
    request.headers = {"x-real-ip": "203.0.113.99"}
    request.state = MagicMock()

    mock_service = MagicMock()
    mock_service.evaluate_ip.return_value = True

    with patch("mcpgateway.middleware.ip_control.get_ip_control_service", return_value=mock_service):
        await middleware.dispatch(request, call_next)

    mock_service.evaluate_ip.assert_called_once_with("203.0.113.99", "/api/tools")
    assert request.state.client_ip == "203.0.113.99"


@pytest.mark.asyncio
async def test_fallback_to_client_host(monkeypatch):
    """Falls back to request.client.host when no proxy headers."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", ["/health"])
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_trust_proxy_headers", True)
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_log_only", False)

    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.client.host = "192.168.1.50"
    request.headers = {}
    request.state = MagicMock()

    mock_service = MagicMock()
    mock_service.evaluate_ip.return_value = True

    with patch("mcpgateway.middleware.ip_control.get_ip_control_service", return_value=mock_service):
        await middleware.dispatch(request, call_next)

    mock_service.evaluate_ip.assert_called_once_with("192.168.1.50", "/api/tools")
    assert request.state.client_ip == "192.168.1.50"


@pytest.mark.asyncio
async def test_403_response_body_format(monkeypatch):
    """Verify 403 response body has expected format."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", ["/health"])
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_trust_proxy_headers", False)
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_log_only", False)

    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    request = MagicMock(spec=Request)
    request.url.path = "/api/tools"
    request.client.host = "10.0.0.1"
    request.headers = {}
    request.state = MagicMock()

    mock_service = MagicMock()
    mock_service.evaluate_ip.return_value = False

    with patch("mcpgateway.middleware.ip_control.get_ip_control_service", return_value=mock_service):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    # JSONResponse stores the body directly
    import json
    data = json.loads(response.body)
    assert data["detail"] == "Access denied by IP access control policy"
    assert data["error"] == "ip_blocked"


@pytest.mark.asyncio
async def test_request_state_client_ip_set(monkeypatch):
    """Verify request.state.client_ip is set for allowed requests."""
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_skip_paths", [])
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_trust_proxy_headers", False)
    monkeypatch.setattr("mcpgateway.middleware.ip_control.settings.ip_control_log_only", False)

    middleware = IPControlMiddleware(app=AsyncMock())
    call_next = AsyncMock(return_value=Response("ok"))

    request = MagicMock(spec=Request)
    request.url.path = "/data"
    request.client.host = "127.0.0.1"
    request.headers = {}
    request.state = MagicMock()

    mock_service = MagicMock()
    mock_service.evaluate_ip.return_value = True

    with patch("mcpgateway.middleware.ip_control.get_ip_control_service", return_value=mock_service):
        await middleware.dispatch(request, call_next)

    assert request.state.client_ip == "127.0.0.1"
    assert request.state.ip_control_result is True
