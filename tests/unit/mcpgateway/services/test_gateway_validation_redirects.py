# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_validation_redirects.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for gateway redirect handling during health checks, registration, and testing.

Validates that 3xx redirect responses (e.g. 301, 307) produce actionable error messages
directing the operator to register the redirected target URL, while ensuring redirects
are not followed automatically to preserve SSRF and credential protection.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import httpx2
import pytest

from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import GatewayHandshakeRequest, GatewayTestRequest
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayService,
    _classify_handshake_error,
    _safe_connection_error_text,
)
from mcpgateway.services.gateway_service import (
    test_gateway_connectivity as run_test_gateway_connectivity,
)
from mcpgateway.services.gateway_service import (
    test_gateway_handshake as run_test_gateway_handshake,
)


def _make_mock_gateway(url: str = "http://example.com/mcp", transport: str = "sse") -> DbGateway:
    """Build a minimal DbGateway mock."""
    gw = MagicMock(spec=DbGateway)
    gw.id = "gw-redirect-test-id"
    gw.name = "gw-redirect-test"
    gw.url = url
    gw.transport = transport
    gw.enabled = True
    gw.reachable = True
    gw.auth_type = "none"
    gw.auth_value = {}
    gw.oauth_config = None
    gw.ca_certificate = None
    gw.ca_certificate_sig = None
    gw.client_cert = None
    gw.client_key = None
    gw.last_refresh_at = None
    gw.refresh_interval_seconds = None
    gw.failure_count = 0
    gw.auth_query_params = None
    return gw


def test_safe_connection_error_text_3xx_with_location():
    """_safe_connection_error_text describes 3xx redirect with Location."""
    req = httpx.Request("GET", "http://example.com/mcp")
    resp = httpx.Response(307, headers={"Location": "http://example.com/mcp/"}, request=req)
    err = httpx.HTTPStatusError("307 Temporary Redirect", request=req, response=resp)

    text = _safe_connection_error_text(err)
    assert text == "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target."


def test_safe_connection_error_text_3xx_httpx2_with_location():
    """_safe_connection_error_text works with httpx2.HTTPStatusError."""
    req = httpx2.Request("POST", "http://example.com/mcp")
    resp = httpx2.Response(301, headers={"Location": "http://example.com/mcp/"}, request=req)
    err = httpx2.HTTPStatusError("301 Moved Permanently", request=req, response=resp)

    text = _safe_connection_error_text(err)
    assert text == "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target."


def test_safe_connection_error_text_3xx_without_location():
    """_safe_connection_error_text describes 3xx redirect when Location header is absent."""
    req = httpx.Request("GET", "http://example.com/mcp")
    resp = httpx.Response(307, request=req)
    err = httpx.HTTPStatusError("307 Temporary Redirect", request=req, response=resp)

    text = _safe_connection_error_text(err)
    assert text == "Upstream redirected with HTTP 307; update the gateway URL to the redirect target."


def test_classify_handshake_error_3xx():
    """_classify_handshake_error classifies 3xx redirects with actionable copy."""
    req = httpx.Request("POST", "http://example.com/mcp")
    resp = httpx.Response(307, headers={"Location": "http://example.com/mcp/"}, request=req)
    err = httpx.HTTPStatusError("307", request=req, response=resp)

    failure_class, copy = _classify_handshake_error(err)
    assert failure_class == "transport"
    assert copy == "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target."


@pytest.mark.asyncio
async def test_sse_health_check_handles_307_redirect_actionable_error():
    """SSE health check raises on 307 redirect and reports actionable message without following."""
    service = GatewayService()
    service._instance_id = "test-instance"
    service._gateway_failure_counts = {}
    service._active_gateways = set()
    service._mark_gateway_reachable = AsyncMock()
    service._handle_gateway_failure = AsyncMock()
    service._classification_service = None

    gateway = _make_mock_gateway(url="http://sse.example.com/mcp", transport="sse")
    requested_urls: list[str] = []

    class _MockResponse:
        status_code = 307
        headers = {"Location": "http://sse.example.com/mcp/"}
        request = httpx.Request("GET", "http://sse.example.com/mcp")

        def raise_for_status(self):
            pass

    class _IsoClientCM:
        async def __aenter__(self_inner):
            client = MagicMock()
            stream_cm = MagicMock()

            async def _stream_enter():
                return _MockResponse()

            stream_cm.__aenter__ = AsyncMock(side_effect=_stream_enter)
            stream_cm.__aexit__ = AsyncMock(return_value=False)

            def _stream(method, url, **kwargs):
                requested_urls.append(str(url))
                return stream_cm

            client.stream = MagicMock(side_effect=_stream)
            return client

        async def __aexit__(self_inner, *exc):
            return False

    with (
        patch(
            "mcpgateway.services.gateway_service.settings",
            MagicMock(
                enable_ed25519_signing=False,
                httpx_admin_read_timeout=5,
                health_check_timeout=5,
                httpx_max_connections=10,
                httpx_max_keepalive_connections=5,
                httpx_keepalive_expiry=30,
                auto_refresh_servers=False,
            ),
        ),
        patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
        patch("mcpgateway.services.gateway_service.create_span", return_value=MagicMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))),
        patch("mcpgateway.services.gateway_service.sanitize_url_for_logging", side_effect=lambda u, *_a, **_k: u),
        patch("mcpgateway.services.gateway_service.SecurityValidator") as mock_sv,
    ):
        mock_sv.sanitize_log_message.side_effect = lambda x: x
        mock_sv.sanitize_credential_value.side_effect = lambda x: x
        await service._check_single_gateway_health(gateway)

    service._handle_gateway_failure.assert_awaited_once()
    called_error = service._handle_gateway_failure.call_args[1]["error"]
    assert isinstance(called_error, httpx.HTTPStatusError)
    assert _safe_connection_error_text(called_error) == "Upstream redirected to http://sse.example.com/mcp/; update the gateway URL to the redirect target."
    # Ensure no request was sent to the redirect location
    assert "http://sse.example.com/mcp/" not in requested_urls


@pytest.mark.asyncio
async def test_streamablehttp_health_check_handles_307_redirect_actionable_error():
    """Streamable HTTP health check raises on 307 redirect and reports actionable message."""
    service = GatewayService()
    service._instance_id = "test-instance"
    service._gateway_failure_counts = {}
    service._active_gateways = set()
    service._mark_gateway_reachable = AsyncMock()
    service._handle_gateway_failure = AsyncMock()
    service._classification_service = None

    gateway = _make_mock_gateway(url="http://streamable.example.com/mcp", transport="streamablehttp")

    req = httpx2.Request("POST", "http://streamable.example.com/mcp")
    resp = httpx2.Response(307, headers={"Location": "http://streamable.example.com/mcp/"}, request=req)
    redirect_status_error = httpx2.HTTPStatusError("307 Temporary Redirect", request=req, response=resp)

    with (
        patch(
            "mcpgateway.services.gateway_service.settings",
            MagicMock(
                enable_ed25519_signing=False,
                httpx_admin_read_timeout=5,
                health_check_timeout=5,
                httpx_max_connections=10,
                httpx_max_keepalive_connections=5,
                httpx_keepalive_expiry=30,
                auto_refresh_servers=False,
            ),
        ),
        patch("mcpgateway.services.gateway_service.get_isolated_http_client"),
        patch("mcpgateway.services.gateway_service.mcp_proxy_client", side_effect=redirect_status_error),
        patch("mcpgateway.services.gateway_service.create_span", return_value=MagicMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))),
        patch("mcpgateway.services.gateway_service.sanitize_url_for_logging", side_effect=lambda u, *_a, **_k: u),
        patch("mcpgateway.services.gateway_service.SecurityValidator") as mock_sv,
    ):
        mock_sv.sanitize_log_message.side_effect = lambda x: x
        mock_sv.sanitize_credential_value.side_effect = lambda x: x
        await service._check_single_gateway_health(gateway)

    service._handle_gateway_failure.assert_awaited_once()
    called_error = service._handle_gateway_failure.call_args[1]["error"]
    assert isinstance(called_error, httpx2.HTTPStatusError)
    assert _safe_connection_error_text(called_error) == "Upstream redirected to http://streamable.example.com/mcp/; update the gateway URL to the redirect target."


@pytest.mark.asyncio
async def test_sse_initialize_gateway_307_redirect_actionable_error():
    """_initialize_gateway raises GatewayConnectionError with actionable message on SSE 307 redirect."""
    service = GatewayService()

    req = httpx2.Request("GET", "http://example.com/mcp")
    resp = httpx2.Response(307, headers={"Location": "http://example.com/mcp/"}, request=req)
    redirect_status_error = httpx2.HTTPStatusError("307 Temporary Redirect", request=req, response=resp)

    with patch("mcpgateway.services.gateway_service.resolve_pinned_target"):
        with patch.object(service, "connect_to_sse_server", side_effect=redirect_status_error):
            with pytest.raises(GatewayConnectionError) as exc_info:
                await service._initialize_gateway("http://example.com/mcp", transport="SSE")

    assert "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target." in str(exc_info.value)


@pytest.mark.asyncio
async def test_streamablehttp_initialize_gateway_307_redirect_actionable_error():
    """_initialize_gateway raises GatewayConnectionError with actionable message on StreamableHTTP 307 redirect."""
    service = GatewayService()

    req = httpx2.Request("POST", "http://example.com/mcp")
    resp = httpx2.Response(307, headers={"Location": "http://example.com/mcp/"}, request=req)
    redirect_status_error = httpx2.HTTPStatusError("307 Temporary Redirect", request=req, response=resp)

    with patch("mcpgateway.services.gateway_service.resolve_pinned_target"):
        with patch.object(service, "connect_to_streamablehttp_server", side_effect=redirect_status_error):
            with pytest.raises(GatewayConnectionError) as exc_info:
                await service._initialize_gateway("http://example.com/mcp", transport="StreamableHTTP")

    assert "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target." in str(exc_info.value)


@pytest.mark.asyncio
async def test_test_gateway_connectivity_307_redirect_actionable_error():
    """test_gateway_connectivity returns 307 with actionable error body and does not follow."""
    request = GatewayTestRequest(base_url="http://example.com/mcp", method="GET", path="")
    mock_db = MagicMock()
    user = {"email": "test@example.com"}

    mock_target = {
        "validated_base_url": "http://example.com/mcp",
        "validated_hostname": "example.com",
        "pinned_base_url": "http://127.0.0.1/mcp",
        "resolved_ip": "127.0.0.1",
        "original_authority": "example.com",
    }

    req = httpx.Request("GET", "http://example.com/mcp")
    resp = httpx.Response(307, headers={"Location": "http://example.com/mcp/"}, request=req)

    class MockResilientClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, **kwargs):
            return resp

    with (
        patch("mcpgateway.services.gateway_service._validate_gateway_test_target", return_value=mock_target),
        patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=MockResilientClient()),
        patch("mcpgateway.services.gateway_service.structured_logger"),
    ):
        response = await run_test_gateway_connectivity(request, team_id=None, user=user, db=mock_db)

    assert response.status_code == 307
    assert response.body == {"error": "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target."}


@pytest.mark.asyncio
async def test_test_gateway_handshake_307_redirect_actionable_error():
    """test_gateway_handshake returns failure with actionable error on 307 redirect."""
    request = GatewayHandshakeRequest(base_url="http://example.com/mcp")
    mock_db = MagicMock()
    user = {"email": "test@example.com"}

    mock_target = {
        "validated_base_url": "http://example.com/mcp",
        "validated_hostname": "example.com",
        "pinned_base_url": "http://127.0.0.1/mcp",
        "resolved_ip": "127.0.0.1",
        "original_authority": "example.com",
    }

    req = httpx.Request("POST", "http://example.com/mcp")
    resp = httpx.Response(307, headers={"Location": "http://example.com/mcp/"}, request=req)

    class MockResilientClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, **kwargs):
            return resp

    with (
        patch("mcpgateway.services.gateway_service._validate_gateway_test_target", return_value=mock_target),
        patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=MockResilientClient()),
        patch("mcpgateway.services.gateway_service.settings", MagicMock(mcp_client_connect_mode="default", federation_timeout=10, health_check_timeout=5)),
    ):
        response = await run_test_gateway_handshake(request, team_id=None, user=user, db=mock_db)

    assert response.success is False
    assert response.failure_class == "transport"
    assert "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target." in response.error
