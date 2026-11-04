# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_validation_redirects.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for gateway redirect handling during health checks, registration, and testing.

Validates that 3xx redirect responses (e.g. 301, 307) produce actionable error messages
directing the operator to register the redirected target URL, while ensuring redirects
are not followed automatically to preserve SSRF and credential protection.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import httpx2
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import GatewayHandshakeRequest, GatewayTestRequest
from mcpgateway.services.gateway_service import (
    _classify_handshake_error,
    _HANDSHAKE_TRANSPORT_COPY,
    _is_redirect_error,
    _redirect_error_text,
    _safe_connection_error_text,
    _safe_log_exception_text,
    GatewayConnectionError,
    GatewayService,
)
from mcpgateway.services.gateway_service import test_gateway_connectivity as run_test_gateway_connectivity
from mcpgateway.services.gateway_service import test_gateway_handshake as run_test_gateway_handshake


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
    """_classify_handshake_error classes a 3xx as a transport failure; the caller adds the redirect detail."""
    req = httpx.Request("POST", "http://example.com/mcp")
    resp = httpx.Response(307, headers={"Location": "http://example.com/mcp/"}, request=req)
    err = httpx.HTTPStatusError("307", request=req, response=resp)

    failure_class, copy = _classify_handshake_error(err)
    assert failure_class == "transport"
    assert copy == _HANDSHAKE_TRANSPORT_COPY


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

    def _upstream(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(307, headers={"Location": "http://sse.example.com/mcp/"})

    class _IsoClientCM:
        async def __aenter__(self_inner):
            self_inner.client = httpx.AsyncClient(transport=httpx.MockTransport(_upstream), follow_redirects=False)
            return self_inner.client

        async def __aexit__(self_inner, *exc):
            await self_inner.client.aclose()
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
    assert len(requested_urls) == 1
    assert requested_urls[0].endswith("/mcp")


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
    assert response.body == {"error": "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target.", "details": ""}


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
    redirect_text = "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target."
    assert response.error == f"{_HANDSHAKE_TRANSPORT_COPY}: {redirect_text}"
    assert response.error.count("Upstream redirected") == 1


@pytest.mark.parametrize(
    "location, expected",
    [
        ("http://example.com/mcp/", "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target."),
        ("/mcp/", "Upstream redirected to /mcp/; update the gateway URL to the redirect target."),
        ("http://a.example/b?token=secret&x=1", "Upstream redirected to http://a.example/b; update the gateway URL to the redirect target."),
        ("http://a.example/mcp/?X-Custom-Key=SECRET123#frag", "Upstream redirected to http://a.example/mcp/; update the gateway URL to the redirect target."),
        ("http://user:pw@a.example/b", "Upstream redirected to http://a.example/b; update the gateway URL to the redirect target."),  # pragma: allowlist secret
        ("http://[invalid", "Upstream redirected with HTTP 307; update the gateway URL to the redirect target."),
        ("", "Upstream redirected with HTTP 307; update the gateway URL to the redirect target."),
        (None, "Upstream redirected with HTTP 307; update the gateway URL to the redirect target."),
    ],
)
def test_redirect_error_text_sanitizes_and_survives_hostile_location(location, expected):
    """The shared helper drops userinfo, query, and fragment, and falls back to the status code when Location cannot be parsed."""
    text = _redirect_error_text(307, location)
    assert text == expected
    assert "@" not in text and "?" not in text and "#" not in text


def test_redirect_error_text_truncates_and_strips_control_characters():
    """An oversized or control-character Location cannot flood last_error or inject log lines."""
    text = _redirect_error_text(302, "http://a.example/" + "x" * 5000 + "\r\nINJECTED")
    assert len(text) < 400
    assert "\r" not in text and "\n" not in text


def test_safe_connection_error_text_does_not_raise_on_malformed_location():
    """A malformed upstream Location must not break health-check bookkeeping."""
    req = httpx.Request("GET", "http://example.com/mcp")
    resp = httpx.Response(307, headers={"Location": "http://[invalid"}, request=req)
    err = httpx.HTTPStatusError("307", request=req, response=resp)
    assert _safe_connection_error_text(err) == "Upstream redirected with HTTP 307; update the gateway URL to the redirect target."


@pytest.mark.asyncio
async def test_test_gateway_connectivity_redirect_keeps_upstream_body_text():
    """Test Connection reports the redirect and keeps what the upstream sent."""
    request = GatewayTestRequest(base_url="http://example.com/mcp", method="GET", path="")
    target = {
        "validated_base_url": "http://example.com/mcp",
        "validated_hostname": "example.com",
        "pinned_base_url": "http://127.0.0.1/mcp",
        "resolved_ip": "127.0.0.1",
        "original_authority": "example.com",
    }
    req = httpx.Request("GET", "http://example.com/mcp")
    resp = httpx.Response(301, headers={"Location": "http://example.com/mcp/"}, content=b"Moved", request=req)

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, **kwargs):
            return resp

    with (
        patch("mcpgateway.services.gateway_service._validate_gateway_test_target", return_value=target),
        patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=_Client()),
        patch("mcpgateway.services.gateway_service.structured_logger"),
    ):
        response = await run_test_gateway_connectivity(request, team_id=None, user={"email": "t@example.com"}, db=MagicMock())

    assert response.status_code == 301
    assert response.body["details"] == "Moved"
    assert response.body["error"].startswith("Upstream redirected to http://example.com/mcp/")


async def _run_connectivity(status_code: int, headers: dict, content: bytes = b""):
    """Run Test Connection against an upstream that answers with ``status_code``."""
    request = GatewayTestRequest(base_url="http://example.com/mcp", method="GET", path="")
    target = {
        "validated_base_url": "http://example.com/mcp",
        "validated_hostname": "example.com",
        "pinned_base_url": "http://127.0.0.1/mcp",
        "resolved_ip": "127.0.0.1",
        "original_authority": "example.com",
    }
    resp = httpx.Response(status_code, headers=headers, content=content, request=httpx.Request("GET", "http://example.com/mcp"))

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, **kwargs):
            return resp

    with (
        patch("mcpgateway.services.gateway_service._validate_gateway_test_target", return_value=target),
        patch("mcpgateway.services.gateway_service.ResilientHttpClient", return_value=_Client()),
        patch("mcpgateway.services.gateway_service.structured_logger"),
    ):
        return await run_test_gateway_connectivity(request, team_id=None, user={"email": "t@example.com"}, db=MagicMock())


@pytest.mark.asyncio
async def test_test_gateway_connectivity_redirect_keeps_parsed_json_body():
    """A JSON body on a redirect stays in the response next to the actionable error."""
    response = await _run_connectivity(307, {"Location": "http://example.com/mcp/", "content-type": "application/json"}, b'{"moved": true}')
    assert response.body["moved"] is True
    assert response.body["error"].startswith("Upstream redirected to http://example.com/mcp/")


@pytest.mark.asyncio
async def test_test_gateway_connectivity_200_with_location_is_not_a_redirect():
    """A 200 answer that carries a Location header takes the normal success path."""
    response = await _run_connectivity(200, {"Location": "http://example.com/other", "content-type": "application/json"}, b'{"ok": true}')
    assert response.status_code == 200
    assert response.body == {"ok": True}


@pytest.mark.asyncio
async def test_test_gateway_connectivity_304_is_not_a_redirect():
    """A 304 answer to a conditional request is not reported as a gateway URL change."""
    response = await _run_connectivity(304, {})
    assert response.status_code == 304
    assert "Upstream redirected" not in str(response.body)


def test_safe_connection_error_text_304_is_not_a_redirect():
    """A 304 status error keeps the generic status text."""
    req = httpx.Request("GET", "http://example.com/mcp")
    err = httpx.HTTPStatusError("304", request=req, response=httpx.Response(304, request=req))
    assert _safe_connection_error_text(err) == "server responded with HTTP 304"


def test_classify_handshake_error_304_is_not_a_redirect():
    """A 304 handshake failure is not classed as a redirect-driven transport failure."""
    req = httpx.Request("POST", "http://example.com/mcp")
    err = httpx.HTTPStatusError("304", request=req, response=httpx.Response(304, request=req))
    assert _classify_handshake_error(err)[0] == "invalid_response"


def test_safe_connection_error_text_never_echoes_custom_named_query_credential():
    """A Location that echoes a custom-named auth query param cannot reach last_error."""
    req = httpx.Request("GET", "http://example.com/mcp?X-Custom-Key=SECRET123")
    resp = httpx.Response(307, headers={"Location": "http://example.com/mcp/?X-Custom-Key=SECRET123"}, request=req)
    err = httpx.HTTPStatusError("307", request=req, response=resp)
    text = _safe_connection_error_text(err)
    assert "SECRET123" not in text
    assert text == "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target."


def test_safe_log_exception_text_sanitizes_redirect_and_drops_query_params():
    """_safe_log_exception_text formats redirect errors without query strings or secrets."""
    req = httpx.Request("GET", "http://example.com/mcp")
    resp = httpx.Response(307, headers={"Location": "http://example.com/mcp/?custom_secret_key=LEAK123#frag"}, request=req)
    err = httpx.HTTPStatusError("307 Temporary Redirect", request=req, response=resp)

    log_text = _safe_log_exception_text(err)
    assert "LEAK123" not in log_text
    assert "?" not in log_text
    assert "#" not in log_text
    assert log_text == "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target."

    # Non-redirect errors use sanitize_exception_message
    other_err = RuntimeError("Connection failed to http://example.com/mcp")
    assert _safe_log_exception_text(other_err) == "Connection failed to http://example.com/mcp"


@pytest.mark.asyncio
async def test_health_check_and_failure_logs_hold_no_query_string_on_redirect(caplog):
    """Health check debug and error logs do not echo query strings or unredacted secrets on 3xx redirect."""
    service = GatewayService()
    service._instance_id = "test-instance"
    service._gateway_failure_counts = {}
    service._active_gateways = set()
    service._mark_gateway_reachable = AsyncMock()
    service.set_gateway_state = AsyncMock()
    service._classification_service = None

    gateway = _make_mock_gateway(url="http://sse.example.com/mcp", transport="sse")

    def _upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"Location": "http://sse.example.com/mcp/?unknown_secret_param=LEAKED123#frag"})

    class _IsoClientCM:
        async def __aenter__(self_inner):
            self_inner.client = httpx.AsyncClient(transport=httpx.MockTransport(_upstream), follow_redirects=False)
            return self_inner.client

        async def __aexit__(self_inner, *exc):
            await self_inner.client.aclose()
            return False

    with (
        caplog.at_level("DEBUG"),
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
                max_consecutive_health_failures=1,
            ),
        ),
        patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
        patch("mcpgateway.services.gateway_service.create_span", return_value=MagicMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))),
        patch("mcpgateway.services.gateway_service.sanitize_url_for_logging", side_effect=lambda u, *_a, **_k: u),
        patch("mcpgateway.services.gateway_service.SecurityValidator") as mock_sv,
        patch("mcpgateway.services.gateway_service.SessionLocal"),
    ):
        mock_sv.sanitize_log_message.side_effect = lambda x: x
        mock_sv.sanitize_credential_value.side_effect = lambda x: x
        await service._check_single_gateway_health(gateway)

    log_output = caplog.text
    assert "LEAKED123" not in log_output
    assert "unknown_secret_param" not in log_output
    assert "Redirect location:" not in log_output
    assert "Upstream redirected to http://sse.example.com/mcp/; update the gateway URL to the redirect target." in log_output


def test_is_redirect_error_identifies_redirect_and_unwraps_exception_groups():
    """_is_redirect_error returns True for redirect HTTPStatusError even within BaseExceptionGroup."""
    req = httpx.Request("GET", "http://example.com/mcp")
    resp = httpx.Response(307, request=req)
    err = httpx.HTTPStatusError("307", request=req, response=resp)

    assert _is_redirect_error(err) is True
    assert _is_redirect_error(BaseExceptionGroup("group", [err])) is True
    assert _is_redirect_error(RuntimeError("failed")) is False
    assert _is_redirect_error(BaseExceptionGroup("group", [RuntimeError("failed")])) is False


@pytest.mark.asyncio
async def test_initialize_gateway_logs_hold_no_query_string_or_traceback_on_redirect(caplog):
    """_initialize_gateway error log omits traceback and does not leak unredacted query string on redirect."""
    service = GatewayService()

    req = httpx2.Request("GET", "http://example.com/mcp")
    resp = httpx2.Response(307, headers={"Location": "http://example.com/mcp/?custom_leak=SECRET_VALUE#frag"}, request=req)
    redirect_status_error = httpx2.HTTPStatusError("307 Temporary Redirect", request=req, response=resp)

    with (
        caplog.at_level("ERROR"),
        patch("mcpgateway.services.gateway_service.resolve_pinned_target"),
        patch.object(service, "connect_to_sse_server", side_effect=redirect_status_error),
    ):
        with pytest.raises(GatewayConnectionError):
            await service._initialize_gateway("http://example.com/mcp", transport="SSE")

    log_output = caplog.text
    assert "SECRET_VALUE" not in log_output
    assert "custom_leak" not in log_output
    assert "Redirect location:" not in log_output
    assert "Traceback (most recent call last)" not in log_output
    assert "Upstream redirected to http://example.com/mcp/; update the gateway URL to the redirect target." in log_output


@pytest.mark.asyncio
async def test_oauth_sse_connection_logs_hold_no_query_string_or_traceback_on_redirect(caplog):
    """_connect_to_sse_server_without_validation error log omits traceback and does not leak query string on redirect."""
    service = GatewayService()

    req = httpx2.Request("GET", "http://oauth.example.com/mcp")
    resp = httpx2.Response(307, headers={"Location": "http://oauth.example.com/mcp/?custom_oauth_leak=TOKEN123#frag"}, request=req)
    redirect_status_error = httpx2.HTTPStatusError("307 Temporary Redirect", request=req, response=resp)

    with (
        caplog.at_level("ERROR"),
        patch("mcpgateway.services.gateway_service.resolve_pinned_target"),
        patch("mcpgateway.services.gateway_service.mcp_proxy_client", side_effect=redirect_status_error),
    ):
        with pytest.raises(GatewayConnectionError):
            await service._connect_to_sse_server_without_validation(
                server_url="http://oauth.example.com/mcp",
                authentication={"Authorization": "Bearer test-token"},
            )

    log_output = caplog.text
    assert "TOKEN123" not in log_output
    assert "custom_oauth_leak" not in log_output
    assert "Redirect location:" not in log_output
    assert "Traceback (most recent call last)" not in log_output
    assert "Upstream redirected to http://oauth.example.com/mcp/; update the gateway URL to the redirect target." in log_output
