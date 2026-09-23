# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_outbound_dns_pinning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for outbound DNS pinning on SSRF-sensitive paths.
"""

# Standard
from contextlib import asynccontextmanager, contextmanager
import socket
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.common.validators import SecurityValidator


@pytest.fixture
def fake_resolver(monkeypatch):
    """Force the pinning validator to return a chosen address list.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        Callable that installs the chosen address list.
    """

    def _install(addresses):
        async def _resolve(_cls, _hostname, _field_name, _timeout):
            return list(addresses)

        monkeypatch.setattr(
            SecurityValidator,
            "_resolve_hostname_for_connection_pinning",
            classmethod(_resolve),
        )

    return _install


async def test_validator_returns_punycode_hostname(fake_resolver):
    fake_resolver(["93.184.216.34"])

    result = await SecurityValidator.validate_url_for_connection_pinning("https://ünicode.com/mcp", "Gateway URL")

    assert result["hostname"] == "xn--nicode-2ya.com"
    assert result["original_authority"] == "xn--nicode-2ya.com"


async def test_validator_rejects_userinfo_in_url(fake_resolver):
    fake_resolver(["93.184.216.34"])

    with pytest.raises(ValueError, match="credentials"):
        await SecurityValidator.validate_url_for_connection_pinning("https://user:secret@example.com:8443/mcp", "Gateway URL")  # pragma: allowlist secret


async def test_validator_authority_includes_port_without_userinfo(fake_resolver):
    fake_resolver(["93.184.216.34"])

    result = await SecurityValidator.validate_url_for_connection_pinning("https://example.com:8443/mcp", "Gateway URL")

    assert result["original_authority"] == "example.com:8443"
    assert "@" not in result["original_authority"]


async def test_validator_returns_every_validated_address(fake_resolver):
    fake_resolver(["93.184.216.34", "93.184.216.35"])

    result = await SecurityValidator.validate_url_for_connection_pinning("https://example.com/mcp", "Gateway URL")

    assert result["resolved_ips"] == ["93.184.216.34", "93.184.216.35"]
    assert result["resolved_ip"] == "93.184.216.34"


async def test_validator_pins_ipv6_literal_with_bracketed_host_header():
    """An IPv6 literal has no hostname to resolve, so it never reaches ``fake_resolver``.

    ``hostname`` must stay unbracketed (it feeds TLS SNI and is compared against httpx's
    unbracketed ``request.url.raw_host``); ``original_authority`` must carry brackets, since
    that value becomes the outbound ``Host`` header and RFC 3986 requires brackets there.
    """
    result = await SecurityValidator.validate_url_for_connection_pinning("https://[2001:db8::1]:8443/mcp", "Gateway URL")

    assert result["hostname"] == "2001:db8::1"
    assert result["original_authority"] == "[2001:db8::1]:8443"
    assert result["resolved_ips"] == ["2001:db8::1"]


@pytest.mark.parametrize("blocked_ipv6", ["fd00::1", "fe80::1", "169.254.169.254"])
async def test_resolve_pinned_target_blocks_ipv6_literal_in_blocked_range(blocked_ipv6):
    """An IPv6 literal skips DNS, but the SSRF check on the literal address itself must
    still run — this is the test that stops the IPv6-literal carve-out in
    ``validate_url_for_connection_pinning`` from becoming an SSRF hole. ``fd00::1`` and
    ``fe80::1`` are always-blocked IPv6 metadata/link-local ranges; ``169.254.169.254``
    (IPv4 metadata) is included as a non-regression check on the same code path.
    """
    with pytest.raises(ValueError, match="blocked by SSRF protection"):
        await resolve_pinned_target(f"https://[{blocked_ipv6}]:8080/mcp" if ":" in blocked_ipv6 else f"https://{blocked_ipv6}/mcp", "Gateway URL")


def _raise_gaierror(*_args, **_kwargs):
    """Simulate a hostname that DNS cannot resolve.

    Args:
        *_args: Ignored positional arguments matching ``socket.getaddrinfo``.
        **_kwargs: Ignored keyword arguments matching ``socket.getaddrinfo``.

    Returns:
        Never returns.

    Raises:
        socket.gaierror: Always, to simulate an unresolvable hostname.
    """
    raise socket.gaierror("does-not-resolve.invalid")


async def test_validator_passes_through_when_dns_fails_open():
    with patch("mcpgateway.common.validators.settings") as mock_settings, patch("mcpgateway.common.validators.socket.getaddrinfo", side_effect=_raise_gaierror):
        mock_settings.ssrf_protection_enabled = True
        mock_settings.ssrf_dns_fail_closed = False
        mock_settings.gateway_test_dns_timeout = 5.0
        mock_settings.ssrf_blocked_hosts = []
        result = await SecurityValidator.validate_url_for_connection_pinning("http://does-not-resolve.invalid/mcp", "Gateway URL")

    assert result["resolved_ips"] == []
    assert result["resolved_ip"] is None


async def test_validator_fails_closed_when_configured():
    with patch("mcpgateway.common.validators.settings") as mock_settings, patch("mcpgateway.common.validators.socket.getaddrinfo", side_effect=_raise_gaierror):
        mock_settings.ssrf_protection_enabled = True
        mock_settings.ssrf_dns_fail_closed = True
        mock_settings.gateway_test_dns_timeout = 5.0
        mock_settings.ssrf_blocked_hosts = []
        with pytest.raises(ValueError):
            await SecurityValidator.validate_url_for_connection_pinning("http://does-not-resolve.invalid/mcp", "Gateway URL")


# First-Party
from mcpgateway.utils.ssrf_pinning import PinnedTarget, resolve_pinned_target, SniPinningTransport


async def test_resolve_pinned_target_returns_validated_address(fake_resolver):
    fake_resolver(["93.184.216.34"])

    target = await resolve_pinned_target("https://example.com/mcp", "Gateway URL")

    assert target.is_pinned is True
    assert target.resolved_ips == ("93.184.216.34",)
    assert target.hostname == "example.com"
    assert target.pin("https://example.com:8443/mcp?x=1") == "https://93.184.216.34:8443/mcp?x=1"
    assert target.extensions == {"sni_hostname": "example.com"}


async def test_apply_headers_forces_clean_authority(fake_resolver):
    fake_resolver(["93.184.216.34"])

    target = await resolve_pinned_target("https://example.com/mcp", "Gateway URL")

    headers = target.apply_headers({"host": "evil.test", "X-Keep": "1"})

    assert headers == {"X-Keep": "1", "Host": "example.com"}


async def test_resolve_pinned_target_blocks_metadata_address(fake_resolver):
    fake_resolver(["169.254.169.254"])

    with pytest.raises(ValueError):
        await resolve_pinned_target("https://rebind.example/mcp", "Gateway URL")


async def test_no_pinning_when_protection_disabled(fake_resolver):
    fake_resolver(["93.184.216.34"])

    with patch("mcpgateway.utils.ssrf_pinning.settings") as mock_settings:
        mock_settings.ssrf_protection_enabled = False
        target = await resolve_pinned_target("https://example.com/mcp", "Gateway URL")

    assert target.is_pinned is False
    assert target.pin("https://example.com/mcp") == "https://example.com/mcp"
    assert target.extensions == {}
    assert target.apply_headers({"X-Keep": "1"}) == {"X-Keep": "1"}


@pytest.mark.parametrize(
    ("url", "match"),
    [
        ("file:///etc/passwd", "must start with one of"),
        ("https://example.com/<script>alert(1)</script>", "HTML tags"),
    ],
)
async def test_protection_disabled_still_validates_the_url(url, match):
    """Skipping the PIN must never skip the VALIDATION.

    With ``SSRF_PROTECTION_ENABLED=false``, ``resolve_pinned_target`` still runs
    ``SecurityValidator``'s scheme allowlist and XSS checks; only DNS-based SSRF
    checks and address pinning are skipped.
    """
    with patch("mcpgateway.utils.ssrf_pinning.settings") as mock_settings:
        mock_settings.ssrf_protection_enabled = False
        with pytest.raises(ValueError, match=match):
            await resolve_pinned_target(url, "Gateway URL")


async def test_protection_disabled_still_returns_an_unpinned_target_for_a_safe_url():
    with patch("mcpgateway.utils.ssrf_pinning.settings") as mock_settings:
        mock_settings.ssrf_protection_enabled = False
        target = await resolve_pinned_target("https://example.com/mcp", "Gateway URL")

    assert target.is_pinned is False
    assert target.validated_url == "https://example.com/mcp"


async def test_no_pinning_when_egress_proxy_configured(fake_resolver, monkeypatch):
    fake_resolver(["93.184.216.34"])
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")

    target = await resolve_pinned_target("https://example.com/mcp", "Gateway URL")

    assert target.is_pinned is False


async def test_client_kwargs_keeps_env_proxies_when_unpinned():
    target = PinnedTarget(validated_url="https://example.com/mcp", hostname="example.com", original_authority="example.com", resolved_ips=())

    kwargs = target.client_kwargs(verify=True)

    assert kwargs == {"verify": True}
    assert "transport" not in kwargs


async def test_client_kwargs_supplies_transport_when_pinned():
    target = PinnedTarget(validated_url="https://example.com/mcp", hostname="example.com", original_authority="example.com", resolved_ips=("93.184.216.34",))

    kwargs = target.client_kwargs(verify=True)

    assert isinstance(kwargs["transport"], SniPinningTransport)
    assert "verify" not in kwargs
    await kwargs["transport"].aclose()


async def test_transport_dials_pinned_host_and_keeps_identity(monkeypatch):
    seen = {}

    async def _capture(_self, request):
        seen["dialled_host"] = request.url.host
        seen["sni"] = request.extensions.get("sni_hostname")
        seen["host_header"] = request.headers.get("Host")
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _capture)
    transport = SniPinningTransport(sni_hostname="example.com", pinned_hosts=["93.184.216.34"])

    await transport.handle_async_request(httpx.Request("GET", "https://example.com/mcp"))

    assert seen == {"dialled_host": "93.184.216.34", "sni": "example.com", "host_header": "example.com"}


async def test_transport_falls_back_to_the_next_address(monkeypatch):
    dialled = []

    async def _capture(_self, request):
        dialled.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise httpx.ConnectError("no route", request=request)
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _capture)
    transport = SniPinningTransport(sni_hostname="example.com", pinned_hosts=["93.184.216.34", "93.184.216.35"])

    response = await transport.handle_async_request(httpx.Request("GET", "https://example.com/mcp"))

    assert response.status_code == 200
    assert dialled == ["93.184.216.34", "93.184.216.35"]


async def test_transport_refuses_an_unvalidated_host():
    transport = SniPinningTransport(sni_hostname="example.com", pinned_hosts=["93.184.216.34"])

    with pytest.raises(httpx.UnsupportedProtocol):
        await transport.handle_async_request(httpx.Request("GET", "https://evil.test/mcp"))


# First-Party
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayService


def _refuse_to_dial(*_args, **_kwargs):
    """Fail loudly if a connector dials a blocked target.

    Raises:
        AssertionError: Always.
    """
    raise AssertionError("connector must not dial a blocked target")


@pytest.mark.parametrize("connector", ["connect_to_sse_server", "connect_to_streamablehttp_server", "_connect_to_sse_server_without_validation"])
async def test_gateway_connectors_pin_the_validated_address(fake_resolver, monkeypatch, connector):
    fake_resolver(["93.184.216.34"])
    captured = {}

    def _capture_factory(*_args, **kwargs):
        captured["factory"] = kwargs["httpx_client_factory"]
        raise RuntimeError("stop after the client factory is built")

    monkeypatch.setattr("mcpgateway.services.gateway_service.sse_client", _capture_factory)
    monkeypatch.setattr("mcpgateway.services.gateway_service.streamablehttp_client", _capture_factory)
    service = GatewayService()

    try:
        with pytest.raises(Exception):
            await getattr(service, connector)("https://example.com/mcp")

        client = captured["factory"](headers={}, timeout=None, auth=None)
        try:
            assert isinstance(client._transport, SniPinningTransport)
            assert client._transport._pinned_hosts == ("93.184.216.34",)
            assert client._transport._sni_hostname == "example.com"
        finally:
            await client.aclose()
    finally:
        await service._http_client.aclose()


@pytest.mark.parametrize("connector", ["connect_to_sse_server", "connect_to_streamablehttp_server", "_connect_to_sse_server_without_validation"])
async def test_gateway_connectors_refuse_a_rebound_address(fake_resolver, monkeypatch, connector):
    fake_resolver(["169.254.169.254"])
    monkeypatch.setattr("mcpgateway.services.gateway_service.sse_client", _refuse_to_dial)
    monkeypatch.setattr("mcpgateway.services.gateway_service.streamablehttp_client", _refuse_to_dial)
    service = GatewayService()

    try:
        with pytest.raises(GatewayConnectionError, match="blocked by URL policy"):
            await getattr(service, connector)("https://rebind.example/mcp")
    finally:
        await service._http_client.aclose()


async def _noop_async(*_args, **_kwargs):
    """Swallow a health-check side effect in tests.

    Returns:
        None: Always.
    """
    return None


def _health_check_gateway(url: str, transport: str):
    """Build the gateway stand-in that a health check reads.

    Args:
        url: Gateway URL under test.
        transport: Gateway transport, "SSE" or "streamablehttp".

    Returns:
        SimpleNamespace: A gateway stand-in.
    """
    return SimpleNamespace(
        id="gw-1",
        name="pinning-test",
        url=url,
        transport=transport,
        enabled=True,
        reachable=True,
        ca_certificate=None,
        ca_certificate_sig=None,
        auth_type=None,
        auth_value=None,
        auth_query_params=None,
        oauth_config=None,
        client_cert=None,
        client_key=None,
        last_refresh_at=None,
        refresh_interval_seconds=None,
    )


def _isolated_client_stub(transport, captured_kwargs):
    """Return a stand-in for get_isolated_http_client that serves a fixed transport.

    Args:
        transport: HTTPX transport that answers every request.
        captured_kwargs: Dict that receives the call's keyword arguments.

    Returns:
        Callable: An async context manager factory.
    """

    @asynccontextmanager
    async def _stub(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        async with httpx.AsyncClient(transport=transport) as client:
            yield client

    return _stub


async def test_health_check_dials_the_pinned_address(fake_resolver, monkeypatch):
    fake_resolver(["93.184.216.34"])
    seen = {}
    client_kwargs = {}

    def _handler(request):
        seen["dialled_host"] = request.url.host
        seen["host_header"] = request.headers.get("Host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200)

    service = GatewayService()
    monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", _isolated_client_stub(httpx.MockTransport(_handler), client_kwargs))
    monkeypatch.setattr(service, "_mark_gateway_reachable", _noop_async)
    monkeypatch.setattr(service, "_handle_gateway_failure", _noop_async)

    try:
        await service._check_single_gateway_health(_health_check_gateway("https://example.com/sse", "SSE"))
    finally:
        await service._http_client.aclose()

    assert seen["dialled_host"] == "93.184.216.34"
    assert seen["host_header"] == "example.com"
    assert seen["sni"] == "example.com"
    assert client_kwargs["follow_redirects"] is False


async def test_health_check_refuses_a_rebound_address(fake_resolver, monkeypatch):
    fake_resolver(["169.254.169.254"])
    failures = []

    async def _record_failure(_gateway, error=None, auth_query_params=None):
        failures.append(error)

    service = GatewayService()
    monkeypatch.setattr("mcpgateway.services.gateway_service.get_isolated_http_client", _isolated_client_stub(httpx.MockTransport(lambda _r: httpx.Response(200)), {}))
    monkeypatch.setattr(service, "_handle_gateway_failure", _record_failure)
    monkeypatch.setattr(service, "_mark_gateway_reachable", _noop_async)

    try:
        await service._check_single_gateway_health(_health_check_gateway("https://rebind.example/sse", "SSE"))
    finally:
        await service._http_client.aclose()

    assert failures, "a blocked health-check target must mark the gateway unhealthy"


# First-Party
from mcpgateway.db import LLMProviderType
from mcpgateway.llm_schemas import ChatCompletionRequest
from mcpgateway.services.llm_proxy_service import LLMProxyRequestError, LLMProxyService


def _llm_provider_and_model():
    """Build the provider and model stand-ins an OpenAI-compatible request needs.

    Returns:
        tuple: A provider stand-in and a model stand-in.
    """
    provider = SimpleNamespace(
        id="p-1",
        name="pinning-test",
        provider_type=LLMProviderType.OPENAI,
        api_base="https://example.com/v1",
        api_key=None,
        default_temperature=None,
        default_max_tokens=None,
    )
    model = SimpleNamespace(id="m-1", model_id="gpt-test")
    return provider, model


def _llm_service_with(handler, monkeypatch):
    """Build an LLM proxy service whose client answers through a mock transport.

    Args:
        handler: Callable that answers each request.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        LLMProxyService: Service wired to the mock transport.
    """
    service = LLMProxyService()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider, model = _llm_provider_and_model()
    monkeypatch.setattr(service, "_resolve_model", lambda _db, _name: (provider, model))
    return service


def _chat_request():
    """Build the minimal chat completion request used by the pinning tests.

    Returns:
        ChatCompletionRequest: A one-message request.
    """
    return ChatCompletionRequest(model="gpt-test", messages=[{"role": "user", "content": "hi"}])


async def test_llm_proxy_posts_to_the_pinned_address(fake_resolver, monkeypatch):
    fake_resolver(["93.184.216.34"])
    seen = {}

    def _handler(request):
        seen["dialled_host"] = request.url.host
        seen["host_header"] = request.headers.get("Host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0, "model": "gpt-test", "choices": [], "usage": {}})

    service = _llm_service_with(_handler, monkeypatch)

    try:
        await service.chat_completion(None, _chat_request())
    except Exception:  # noqa: BLE001 - the stub response shape is not the subject of this test
        pass
    finally:
        await service._client.aclose()

    assert seen["dialled_host"] == "93.184.216.34"
    assert seen["host_header"] == "example.com"
    assert seen["sni"] == "example.com"


async def test_llm_proxy_streams_from_the_pinned_address(fake_resolver, monkeypatch):
    fake_resolver(["93.184.216.34"])
    seen = {}

    def _handler(request):
        seen["dialled_host"] = request.url.host
        seen["host_header"] = request.headers.get("Host")
        return httpx.Response(200, text="data: [DONE]\n\n")

    service = _llm_service_with(_handler, monkeypatch)

    try:
        async for _chunk in service.chat_completion_stream(None, _chat_request()):
            break
    finally:
        await service._client.aclose()

    assert seen["dialled_host"] == "93.184.216.34"
    assert seen["host_header"] == "example.com"


async def test_llm_proxy_refuses_a_rebound_address(fake_resolver, monkeypatch):
    fake_resolver(["169.254.169.254"])
    service = _llm_service_with(lambda _r: httpx.Response(200, json={}), monkeypatch)

    try:
        with pytest.raises(LLMProxyRequestError):
            await service.chat_completion(None, _chat_request())
    finally:
        await service._client.aclose()


# First-Party
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager


async def _as_awaitable(value):
    """Wrap a value so a sync lambda can stand in for an async getter.

    Args:
        value: Value to return.

    Returns:
        The value, awaited.
    """
    return value


async def test_oauth_token_post_uses_the_pinned_address(fake_resolver, monkeypatch):
    fake_resolver(["93.184.216.34"])
    seen = {}

    def _handler(request):
        seen["dialled_host"] = request.url.host
        seen["host_header"] = request.headers.get("Host")
        return httpx.Response(200, json={"access_token": "t"})

    manager = OAuthManager()
    stub_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(manager, "_get_client", lambda: _as_awaitable(stub_client))

    try:
        await manager._post_token_request("https://example.com/token", {"grant_type": "client_credentials"})
    finally:
        await stub_client.aclose()

    assert seen["dialled_host"] == "93.184.216.34"
    assert seen["host_header"] == "example.com"


async def test_oauth_token_post_refuses_a_rebound_address(fake_resolver, monkeypatch):
    fake_resolver(["169.254.169.254"])
    manager = OAuthManager()
    stub_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={})))
    monkeypatch.setattr(manager, "_get_client", lambda: _as_awaitable(stub_client))

    try:
        with pytest.raises(OAuthError):
            await manager._post_token_request("https://rebind.example/token", {"grant_type": "client_credentials"})
    finally:
        await stub_client.aclose()


# First-Party
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentService


def _uaid_for(native_id: str) -> str:
    """Build a minimal `aid`-method UAID that routes to the given endpoint.

    Args:
        native_id: Hostname to place in the UAID's `nativeId` component.

    Returns:
        str: A UAID string with `proto=a2a` and the given `nativeId`.
    """
    return f"uaid:aid:9BjK3mP7xQv;uid=0;registry=cf;proto=a2a;nativeId={native_id}"


async def test_uaid_cross_gateway_call_uses_the_pinned_address(fake_resolver, monkeypatch):
    fake_resolver(["93.184.216.34"])
    seen = {}

    def _handler(request):
        seen["dialled_host"] = request.url.host
        seen["host_header"] = request.headers.get("Host")
        return httpx.Response(200, json={"result": "ok"})

    stub_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    async def _stub_get_http_client():
        return stub_client

    # `_invoke_remote_agent` imports `get_http_client` locally from
    # `http_client_service` on every call, so patching that name on
    # `a2a_service` (where it is never bound at module scope) would not
    # reach the local import. Patch the defining module instead.
    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", _stub_get_http_client)
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])

    service = A2AAgentService()
    try:
        result = await service._invoke_remote_agent(_uaid_for("example.com"), {})
    finally:
        await stub_client.aclose()

    assert result == {"result": "ok"}
    assert seen["dialled_host"] == "93.184.216.34"
    assert seen["host_header"] == "example.com"


async def test_uaid_cross_gateway_call_refuses_a_rebound_address(fake_resolver, monkeypatch):
    fake_resolver(["169.254.169.254"])
    calls = []

    def _handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={"result": "ok"})

    stub_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    async def _stub_get_http_client():
        return stub_client

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", _stub_get_http_client)
    monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])

    service = A2AAgentService()
    try:
        with pytest.raises(A2AAgentError, match="blocked by URL policy"):
            await service._invoke_remote_agent(_uaid_for("example.com"), {})
    finally:
        await stub_client.aclose()

    assert calls == [], "a blocked cross-gateway target must never be dialled"


# First-Party
from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache
from mcpgateway.services.tool_service import ToolInvocationError, ToolService
from tests.unit.mcpgateway.services.test_tool_service import mock_gateway, mock_tool  # noqa: F401 - fixture re-export


@pytest.fixture(autouse=True)
def _reset_tool_lookup_cache():
    """Clear the process-wide tool lookup cache so MCP-arm tests below don't see a prior test's entry.

    Yields:
        None: Control returns to the test after the cache is cleared.
    """
    tool_lookup_cache.invalidate_all_local()
    yield
    tool_lookup_cache.invalidate_all_local()


def _capture_client_factory(captured):
    """Return a stand-in for ``sse_client``/``streamablehttp_client`` that captures the httpx client factory.

    Args:
        captured: Dict that receives the captured ``httpx_client_factory`` under "factory".

    Returns:
        Callable: Raises immediately after capturing, before any connection is attempted.
    """

    def _stub(*_args, **kwargs):
        captured["factory"] = kwargs["httpx_client_factory"]
        raise RuntimeError("stop after the client factory is built")

    return _stub


def _direct_proxy_gateway(url: str):
    """Build the direct_proxy gateway stand-in that ``invoke_tool_direct`` reads.

    Args:
        url: Remote MCP gateway URL under test.

    Returns:
        MagicMock: A gateway stand-in in direct_proxy mode.
    """
    gateway = MagicMock()
    gateway.id = "gw-direct-1"
    gateway.name = "direct_gateway"
    gateway.slug = "direct-gateway"
    gateway.url = url
    gateway.gateway_mode = "direct_proxy"
    gateway.auth_type = "bearer"
    gateway.auth_value = {"Authorization": "Bearer remote-token"}
    gateway.passthrough_headers = None
    gateway.visibility = "public"
    gateway.team_id = None
    gateway.owner_email = None
    return gateway


def _direct_proxy_db_session(gateway):
    """Build a ``fresh_db_session`` stand-in for invoke_tool_direct's two sequential lookups.

    Args:
        gateway: Gateway stand-in returned by the first lookup; the tool lookup returns None.

    Returns:
        Callable: A zero-argument context manager factory, matching ``fresh_db_session``'s shape.
    """

    @contextmanager
    def _session():
        mock_db = MagicMock()
        gateway_result = MagicMock()
        gateway_result.scalar_one_or_none.return_value = gateway
        tool_result = MagicMock()
        tool_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [gateway_result, tool_result]
        yield mock_db

    return _session


async def test_tool_invoke_direct_pins_the_validated_address(fake_resolver, monkeypatch):
    fake_resolver(["93.184.216.34"])
    gateway = _direct_proxy_gateway("http://remote-mcp:8080/mcp")
    captured = {}

    service = ToolService()
    service._http_client = AsyncMock()

    monkeypatch.setattr("mcpgateway.services.tool_service.fresh_db_session", _direct_proxy_db_session(gateway))
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.mcpgateway_direct_proxy_enabled", True)
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.mcpgateway_direct_proxy_timeout", 30)
    monkeypatch.setattr("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.services.tool_service.build_gateway_auth_headers", lambda _gw: {"Authorization": "Bearer remote-token"})
    monkeypatch.setattr("mcpgateway.services.tool_service.streamablehttp_client", _capture_client_factory(captured))

    with pytest.raises(Exception):
        await service.invoke_tool_direct(gateway_id="gw-direct-1", name="remote_tool", arguments={"key": "value"}, user_email="user@example.com", token_teams=["team-1"])

    client = captured["factory"](headers={}, timeout=None, auth=None)
    try:
        assert isinstance(client._transport, SniPinningTransport)
        assert client._transport._pinned_hosts == ("93.184.216.34",)
        assert client._transport._sni_hostname == "remote-mcp"
    finally:
        await client.aclose()


async def test_tool_invoke_direct_refuses_a_rebound_address(fake_resolver, monkeypatch):
    fake_resolver(["169.254.169.254"])
    gateway = _direct_proxy_gateway("http://remote-mcp:8080/mcp")

    service = ToolService()
    service._http_client = AsyncMock()

    monkeypatch.setattr("mcpgateway.services.tool_service.fresh_db_session", _direct_proxy_db_session(gateway))
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.mcpgateway_direct_proxy_enabled", True)
    monkeypatch.setattr("mcpgateway.services.tool_service.settings.mcpgateway_direct_proxy_timeout", 30)
    monkeypatch.setattr("mcpgateway.services.tool_service.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.services.tool_service.build_gateway_auth_headers", lambda _gw: {"Authorization": "Bearer remote-token"})
    monkeypatch.setattr("mcpgateway.services.tool_service.streamablehttp_client", _refuse_to_dial)

    with pytest.raises(ToolInvocationError, match="Outbound URL blocked by URL policy"):
        await service.invoke_tool_direct(gateway_id="gw-direct-1", name="remote_tool", arguments={"key": "value"}, user_email="user@example.com", token_teams=["team-1"])


def _mcp_gateway(url: str, transport: str) -> SimpleNamespace:
    """Build the gateway stand-in ``invoke_tool``'s MCP arm reads.

    Args:
        url: Remote MCP server URL under test.
        transport: Gateway transport, "SSE" or "STREAMABLEHTTP".

    Returns:
        SimpleNamespace: A gateway stand-in.
    """
    return SimpleNamespace(
        id="42",
        name="test_gateway",
        description=None,
        slug="test-gateway",
        url=url,
        enabled=True,
        deprecated=False,
        reachable=True,
        auth_type="bearer",
        auth_value="Bearer abc123",
        capabilities={"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}},
        transport=transport,
        passthrough_headers=[],
        team_id=None,
        owner_email=None,
        visibility="public",
        tags=[],
        gateway_mode="cache",
        client_cert=None,
        client_key=None,
        ca_certificate=None,
        ca_certificate_sig=None,
    )


def _wire_mcp_tool(tool, gateway, request_type):
    """Configure a shared ``mock_tool`` stand-in for an MCP call routed through ``gateway``.

    Args:
        tool: The ``mock_tool`` fixture instance to configure.
        gateway: The gateway stand-in the tool routes through.
        request_type: The tool's MCP request type, "SSE" or "StreamableHTTP".

    Returns:
        The configured tool stand-in (same object as ``tool``).
    """
    tool.integration_type = "MCP"
    tool.request_type = request_type
    tool.jsonpath_filter = ""
    tool.auth_type = None
    tool.auth_value = None
    tool.original_name = "dummy_tool"
    tool.headers = {}
    tool.name = "test-gateway-dummy-tool"
    tool.gateway_slug = "test-gateway"
    tool.gateway_id = gateway.id
    # `_resolve_tool_for_invocation` reads `tool.gateway` directly (no second DB query) to
    # build `gateway_payload`, so the gateway stand-in must be wired through this attribute.
    tool.gateway = gateway
    return tool


def _mcp_db_execute(tool, gateway):
    """Build a ``db.execute`` side effect answering invoke_tool's three sequential MCP lookups.

    Args:
        tool: The tool row returned by the first lookup.
        gateway: The gateway row returned by the second and third lookups.

    Returns:
        Callable: A ``Mock(side_effect=...)``-compatible function.
    """
    returns = [tool, gateway, gateway]

    def _execute(*_args, **_kwargs):
        value = returns.pop(0) if returns else None
        result = Mock()
        result.scalar_one_or_none.return_value = value
        result.scalars.return_value = result
        result.all.return_value = [] if value is None else [value]
        return result

    return _execute


@pytest.mark.parametrize(
    ("tool_request_type", "gateway_transport", "patch_target"),
    [
        ("SSE", "SSE", "sse_client"),
        ("StreamableHTTP", "STREAMABLEHTTP", "streamablehttp_client"),
    ],
)
async def test_tool_invoke_mcp_pins_the_validated_address(fake_resolver, monkeypatch, mock_tool, test_db, tool_request_type, gateway_transport, patch_target):
    fake_resolver(["93.184.216.34"])
    gateway = _mcp_gateway("http://fake-mcp:8080/mcp", gateway_transport)
    tool = _wire_mcp_tool(mock_tool, gateway, tool_request_type)
    test_db.execute = Mock(side_effect=_mcp_db_execute(tool, gateway))

    service = ToolService()
    service._http_client = AsyncMock()
    captured = {}

    monkeypatch.setattr(f"mcpgateway.services.tool_service.{patch_target}", _capture_client_factory(captured))
    monkeypatch.setattr("mcpgateway.services.tool_service.decode_auth", lambda *_a, **_k: {"Authorization": "Bearer xyz"})
    monkeypatch.setattr("mcpgateway.services.tool_service.extract_using_jq", lambda data, _filt: data)
    monkeypatch.setattr("mcpgateway.services.tool_service.metrics_buffer", Mock(record_tool_metric=Mock()))

    with pytest.raises(Exception):
        await service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)

    client = captured["factory"](headers={}, timeout=None, auth=None)
    try:
        assert isinstance(client._transport, SniPinningTransport)
        assert client._transport._pinned_hosts == ("93.184.216.34",)
        assert client._transport._sni_hostname == "fake-mcp"
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("tool_request_type", "gateway_transport", "patch_target"),
    [
        ("SSE", "SSE", "sse_client"),
        ("StreamableHTTP", "STREAMABLEHTTP", "streamablehttp_client"),
    ],
)
async def test_tool_invoke_mcp_refuses_a_rebound_address(fake_resolver, monkeypatch, mock_tool, test_db, tool_request_type, gateway_transport, patch_target):
    fake_resolver(["169.254.169.254"])
    gateway = _mcp_gateway("http://fake-mcp:8080/mcp", gateway_transport)
    tool = _wire_mcp_tool(mock_tool, gateway, tool_request_type)
    test_db.execute = Mock(side_effect=_mcp_db_execute(tool, gateway))

    service = ToolService()
    service._http_client = AsyncMock()

    monkeypatch.setattr(f"mcpgateway.services.tool_service.{patch_target}", _refuse_to_dial)
    monkeypatch.setattr("mcpgateway.services.tool_service.decode_auth", lambda *_a, **_k: {"Authorization": "Bearer xyz"})
    monkeypatch.setattr("mcpgateway.services.tool_service.metrics_buffer", Mock(record_tool_metric=Mock()))

    with pytest.raises(ToolInvocationError, match="Outbound URL blocked by URL policy"):
        await service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)


# First-Party
from mcpgateway.services.upstream_session_registry import _default_session_factory, SessionCreateRequest, TransportType


def _session_request(url: str, httpx_client_factory=None):
    """Build the request the pooled session factory takes.

    Args:
        url: Upstream URL for the session.
        httpx_client_factory: Optional caller-supplied httpx client factory.

    Returns:
        SessionCreateRequest: A minimal request.
    """
    return SessionCreateRequest(
        url=url,
        transport_type=TransportType.SSE,
        headers={},
        gateway_id="gw-1",
        downstream_session_id="ds-1",
        httpx_client_factory=httpx_client_factory,
        message_handler_factory=None,
        timeout_seconds=5.0,
    )


async def test_pooled_session_pins_the_validated_address(fake_resolver, monkeypatch):
    fake_resolver(["93.184.216.34"])
    captured = {}

    monkeypatch.setattr("mcpgateway.services.upstream_session_registry.sse_client", _capture_client_factory(captured))

    with pytest.raises(Exception):
        await _default_session_factory(_session_request("https://example.com/sse"))

    client = captured["factory"](headers={}, timeout=None, auth=None)
    try:
        assert isinstance(client._transport, SniPinningTransport)
        assert client._transport._pinned_hosts == ("93.184.216.34",)
    finally:
        await client.aclose()


async def test_pooled_session_refuses_a_rebound_address(fake_resolver, monkeypatch):
    fake_resolver(["169.254.169.254"])
    monkeypatch.setattr("mcpgateway.services.upstream_session_registry.sse_client", _refuse_to_dial)

    with pytest.raises(Exception, match="blocked by URL policy"):
        await _default_session_factory(_session_request("https://rebind.example/sse"))


async def test_pooled_session_wraps_caller_httpx_client_factory(fake_resolver, monkeypatch):
    """A caller-supplied httpx_client_factory must be pinned, not replaced — its TLS settings must survive."""
    fake_resolver(["93.184.216.34"])
    marker_ctx = ssl.create_default_context()
    captured = {}

    def _caller_factory(headers=None, timeout=None, auth=None):
        """Stand in for a caller's own factory carrying custom TLS settings.

        Args:
            headers: Unused; matches the HttpxClientFactory signature.
            timeout: Unused; matches the HttpxClientFactory signature.
            auth: Unused; matches the HttpxClientFactory signature.

        Returns:
            httpx.AsyncClient: A client built with a marker SSL context.
        """
        return httpx.AsyncClient(verify=marker_ctx)

    def _capture_factory(*_args, **kwargs):
        captured["factory"] = kwargs["httpx_client_factory"]
        raise RuntimeError("stop after the client factory is built")

    monkeypatch.setattr("mcpgateway.services.upstream_session_registry.sse_client", _capture_factory)

    with pytest.raises(Exception):
        await _default_session_factory(_session_request("https://example.com/sse", httpx_client_factory=_caller_factory))

    client = captured["factory"](headers={}, timeout=None, auth=None)
    try:
        assert isinstance(client._transport, SniPinningTransport)
        assert client._transport._pinned_hosts == ("93.184.216.34",)
        # The caller's own SSL context must survive the wrap, not be silently replaced.
        assert client._transport._pool._ssl_context is marker_ctx
    finally:
        await client.aclose()


async def test_pooled_session_wrap_fails_closed_when_tls_context_missing(fake_resolver, monkeypatch):
    """If the caller's built client carries no discoverable TLS context, refuse to dial rather than fall back to default trust.

    Simulates an httpx/httpcore internals change that renames or removes
    ``_transport._pool._ssl_context``: the wrap must fail closed instead of
    silently downgrading to ``get_default_verify()``, which is ``False`` under
    ``SKIP_SSL_VERIFY=true``.
    """
    fake_resolver(["93.184.216.34"])
    captured = {}

    def _caller_factory(headers=None, timeout=None, auth=None):
        """Stand in for a caller's own factory whose transport exposes no _ssl_context.

        Args:
            headers: Unused; matches the HttpxClientFactory signature.
            timeout: Unused; matches the HttpxClientFactory signature.
            auth: Unused; matches the HttpxClientFactory signature.

        Returns:
            httpx.AsyncClient: A client whose transport pool has no _ssl_context attribute.
        """
        client = httpx.AsyncClient()
        client._transport._pool = object()  # no _ssl_context attribute, unlike the real httpcore pool
        return client

    def _capture_factory(*_args, **kwargs):
        captured["factory"] = kwargs["httpx_client_factory"]
        raise RuntimeError("stop after the client factory is built")

    monkeypatch.setattr("mcpgateway.services.upstream_session_registry.sse_client", _capture_factory)

    with pytest.raises(Exception):
        await _default_session_factory(_session_request("https://example.com/sse", httpx_client_factory=_caller_factory))

    # The real SDK's sse_client was replaced above and never got past building the pinning
    # factory — no transport context was ever entered, so nothing was ever dialled. Calling
    # the captured factory directly, outside that flow, isolates the fail-closed check itself.
    with pytest.raises(RuntimeError, match="TLS context was not found"):
        captured["factory"](headers={}, timeout=None, auth=None)
