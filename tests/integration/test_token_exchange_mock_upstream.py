# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_token_exchange_mock_upstream.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Mock-upstream integration tests for RFC 8693 token exchange.

These tests prove two end-to-end invariants the unit tests only assert on
dicts:

- The inbound user JWT never reaches the upstream service; only the
  exchanged token is forwarded.
- A 401 from the upstream triggers exactly one re-exchange and retry.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

pytestmark = pytest.mark.integration

_FAKE_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1QGUifQ.sig"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _isolate_token_exchange_cache():
    """Guarantee a clean token-exchange cache for every test in this module.

    ``ToolService`` builds its ``TokenExchangeCache`` from ``settings.redis_url``;
    when a live Redis is reachable (e.g. the local compose stack), cached
    exchanged tokens outlive a single test and leak across tests and runs —
    both tests here intentionally share the same gateway/user/audience cache
    key. Purging the ``token_exchange:`` namespace before and after each test
    restores the isolation the per-instance in-memory fallback provides when
    Redis is absent (e.g. CI).
    """
    # First-Party
    from mcpgateway.config import settings

    client = None
    redis_url = getattr(settings, "redis_url", None)
    if redis_url:
        try:
            # Third-Party
            import redis as sync_redis

            client = sync_redis.from_url(redis_url, decode_responses=True)
            client.ping()
        except Exception:  # Redis unreachable -> per-instance memory cache already isolates
            client = None

    def _purge() -> None:
        if client is None:
            return
        for key in client.scan_iter("token_exchange:*"):
            client.delete(key)

    _purge()
    yield
    _purge()


@pytest.mark.asyncio
async def test_upstream_receives_exchanged_token_not_user_jwt():
    """The upstream call must carry the exchanged token, never the user's inbound JWT."""
    # First-Party
    from mcpgateway.services.tool_service import ToolService

    svc = ToolService()
    svc.oauth_manager = MagicMock()
    svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "EXCHANGED", "expires_in": 3600})

    cfg = {
        "grant_type": "token-exchange",
        "token_url": "https://as/token",
        "client_id": "cf",
        "target_audience": "https://svc",
        "subject_token_source": "inbound_user_jwt",
    }
    header = await svc._resolve_token_exchange_header(cfg, "gw1", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"})

    captured = {}

    async def _send(headers):
        captured.update(headers)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    await svc._send_with_token_exchange_retry(_send, header, cfg, "gw1", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"})
    auth = captured.get("Authorization")
    assert auth == "Bearer EXCHANGED"
    assert _FAKE_JWT not in (auth or "")


@pytest.mark.asyncio
async def test_upstream_401_then_success_reexchanges_once():
    """A 401 from the upstream invalidates the cached token and triggers exactly one re-exchange."""
    # First-Party
    from mcpgateway.services.tool_service import ToolService

    svc = ToolService()
    svc.oauth_manager = MagicMock()
    # first exchange -> T1, after invalidation second exchange -> T2
    svc.oauth_manager.token_exchange = AsyncMock(
        side_effect=[
            {"access_token": "T1", "expires_in": 3600},
            {"access_token": "T2", "expires_in": 3600},
        ]
    )
    cfg = {
        "grant_type": "token-exchange",
        "token_url": "https://as/token",
        "client_id": "cf",
        "target_audience": "https://svc",
        "subject_token_source": "inbound_user_jwt",
    }
    req = {"authorization": f"Bearer {_FAKE_JWT}"}
    header = await svc._resolve_token_exchange_header(cfg, "gw1", "gw", "u@e", req)

    seen = []

    async def _send(headers):
        seen.append(headers.get("Authorization"))
        resp = MagicMock()
        resp.status_code = 401 if len(seen) == 1 else 200
        return resp

    resp = await svc._send_with_token_exchange_retry(_send, header, cfg, "gw1", "gw", "u@e", req)
    assert resp.status_code == 200
    assert seen == ["Bearer T1", "Bearer T2"]  # invalidated, re-exchanged once


# ---------------------------------------------------------------------------
# Discovery credential against an upstream that splits list and call policy
# ---------------------------------------------------------------------------

_SERVICE_TOKEN = "SVC-DISCOVERY-TOKEN"  # nosec B105 - test token value
_USER_TOKEN = "EXCHANGED-USER-TOKEN"  # nosec B105 - test token value
_DISCOVERY_CFG = {
    "grant_type": "token-exchange",
    "token_url": "https://as/token",
    "client_id": "cf",
    "client_secret": "cf-secret",  # pragma: allowlist secret
    "target_audience": "https://svc",
    "subject_token_source": "inbound_user_jwt",
    "discovery": {"grant_type": "client_credentials", "scopes": ["mcp.discover"]},
}


class _PolicyUpstream:
    """Mock MCP upstream: the service token is valid for initialize and list methods only."""

    LIST_METHODS = ("initialize", "tools/list", "resources/list", "prompts/list")

    def __init__(self):
        self.calls = []

    def handle(self, method, headers):
        """Record one upstream request and return its HTTP status.

        Args:
            method: MCP method name.
            headers: Request headers.

        Returns:
            int: 200 when the token is allowed for ``method``, otherwise 401.
        """
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        self.calls.append((method, token))
        allowed = {_SERVICE_TOKEN, _USER_TOKEN} if method in self.LIST_METHODS else {_USER_TOKEN}
        return 200 if token in allowed else 401

    def connect(self, _url, authentication, *_args, **_kwargs):
        """Stand in for ``connect_to_*_server``: run discovery against the policy.

        Args:
            _url: Upstream URL.
            authentication: Request headers.
            *_args: Ignored.
            **_kwargs: Ignored.

        Returns:
            tuple: Capabilities, tools, resources, prompts, validation errors.

        Raises:
            RuntimeError: If the upstream rejects any discovery request.
        """
        for method in self.LIST_METHODS:
            if self.handle(method, authentication) != 200:
                raise RuntimeError(f"upstream rejected {method}")
        tool = MagicMock()
        tool.name = "listed_tool"
        return {"tools": {}}, [tool], [], [], []


def _gateway_service(upstream):
    """Build a GatewayService wired to the policy upstream and a mocked token endpoint.

    Args:
        upstream: The policy upstream.

    Returns:
        GatewayService: Service under test.
    """
    # First-Party
    from mcpgateway.services.gateway_service import GatewayService
    from mcpgateway.services.gateway_service_token_cache import GatewayServiceTokenCache

    svc = GatewayService()
    svc._service_token_cache = GatewayServiceTokenCache(redis_url=None)
    svc.oauth_manager = MagicMock()
    svc.oauth_manager.get_client_credentials_token_response = AsyncMock(return_value={"access_token": _SERVICE_TOKEN, "expires_in": 3600})
    svc.oauth_manager.token_exchange = AsyncMock(side_effect=AssertionError("discovery must not exchange a user token"))
    svc.connect_to_streamablehttp_server = AsyncMock(side_effect=upstream.connect)
    return svc


@pytest.mark.asyncio
async def test_discovery_registration_uses_service_token_for_list_methods():
    """Registration discovers tools with the service token; the upstream accepts it for list methods."""
    upstream = _PolicyUpstream()
    svc = _gateway_service(upstream)

    _caps, tools, _r, _p, _e = await svc._initialize_gateway("https://upstream/mcp", None, "streamablehttp", "oauth", dict(_DISCOVERY_CFG))

    assert [t.name for t in tools] == ["listed_tool"]
    assert upstream.calls == [(m, _SERVICE_TOKEN) for m in _PolicyUpstream.LIST_METHODS]


@pytest.mark.asyncio
async def test_discovery_health_check_probes_with_service_token():
    """The health check probes the upstream with the service token and marks the gateway reachable."""
    # Standard
    from unittest.mock import patch

    # First-Party
    from mcpgateway.db import Gateway as DbGateway

    upstream = _PolicyUpstream()
    svc = _gateway_service(upstream)
    svc._handle_gateway_failure = AsyncMock()
    svc._mark_gateway_reachable = AsyncMock()
    svc._classification_service = None

    gateway = MagicMock(spec=DbGateway)
    gateway.id, gateway.name, gateway.url, gateway.transport = "gw-disc", "gw", "https://upstream/mcp", "streamablehttp"
    gateway.enabled, gateway.reachable, gateway.auth_type, gateway.auth_value = True, True, "oauth", {}
    gateway.oauth_config = dict(_DISCOVERY_CFG)
    gateway.ca_certificate = gateway.ca_certificate_sig = gateway.client_cert = gateway.client_key = gateway.auth_query_params = None
    gateway.last_refresh_at, gateway.refresh_interval_seconds = None, None

    class _ProbeCM:
        def __init__(self, headers):
            self.status = upstream.handle("initialize", headers)

        async def __aenter__(self):
            if self.status != 200:
                raise RuntimeError("upstream rejected health probe")
            return MagicMock()

        async def __aexit__(self, *exc):
            return False

    class _NullCM:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *exc):
            return False

        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *exc):
            return False

    pinned = MagicMock(pin=lambda url: url, apply_headers=lambda headers: headers, extensions={})
    with (
        patch("mcpgateway.services.gateway_service.settings", MagicMock(enable_ed25519_signing=False, httpx_admin_read_timeout=1, health_check_timeout=1, auto_refresh_servers=False)),
        patch("mcpgateway.services.gateway_service.create_span", return_value=_NullCM()),
        patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_NullCM()),
        patch("mcpgateway.services.gateway_service.resolve_pinned_target", new=AsyncMock(return_value=pinned)),
        patch("mcpgateway.services.gateway_service.mcp_proxy_client", side_effect=lambda url, headers, **_kw: _ProbeCM(headers)),
    ):
        await svc._check_single_gateway_health(gateway)

    assert upstream.calls == [("initialize", _SERVICE_TOKEN)]
    svc._handle_gateway_failure.assert_not_awaited()
    svc._mark_gateway_reachable.assert_awaited_once()


@pytest.mark.asyncio
async def test_discovery_manual_refresh_uses_service_token_not_cookie_jwt():
    """Manual refresh with only a session cookie discovers through the service token."""
    # Standard
    from unittest.mock import patch

    upstream = _PolicyUpstream()
    svc = _gateway_service(upstream)
    gateway = MagicMock()
    gateway.id, gateway.name, gateway.oauth_config = "gw-disc", "gw", dict(_DISCOVERY_CFG)
    gateway.ca_certificate = gateway.client_cert = gateway.client_key = None

    async def _refresh(**kwargs):
        _c, tools, _r, _p, _e = await svc._initialize_gateway("https://upstream/mcp", None, "streamablehttp", "oauth", gateway.oauth_config, pre_auth_headers=kwargs["pre_auth_headers"])
        return {"success": True, "tools_added": len(tools), "tools_updated": 0, "tools_removed": 0, "resources_added": 0, "resources_updated": 0, "resources_removed": 0, "prompts_added": 0, "prompts_updated": 0, "prompts_removed": 0}

    svc._refresh_gateway_tools_resources_prompts = _refresh

    class _DBCM:
        def __enter__(self):
            db = MagicMock()
            db.execute.return_value.scalar_one_or_none.return_value = gateway
            return db

        def __exit__(self, *exc):
            return False

    with patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=_DBCM()):
        result = await svc.refresh_gateway_manually("gw-disc", user_email="admin@example.com", request_headers={"cookie": f"jwt_token={_FAKE_JWT}"})

    assert result["success"] is True
    assert result["tools_added"] == 1
    assert {token for _m, token in upstream.calls} == {_SERVICE_TOKEN}
    assert _FAKE_JWT not in repr(upstream.calls)
    svc.oauth_manager.token_exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_gateway_tool_call_uses_exchanged_user_token():
    """A tool call on a discovery-enabled gateway carries the user's exchanged token; the service token would be refused."""
    # First-Party
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from mcpgateway.services.tool_service import ToolService

    upstream = _PolicyUpstream()
    svc = ToolService()
    svc._token_exchange_cache = TokenExchangeCache(redis_url=None)
    svc.oauth_manager = MagicMock()
    svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": _USER_TOKEN, "expires_in": 3600})
    req = {"authorization": f"Bearer {_FAKE_JWT}"}

    header = await svc._resolve_token_exchange_header(dict(_DISCOVERY_CFG), "gw-disc", "gw", "u@e", req)

    async def _send(headers):
        resp = MagicMock()
        resp.status_code = upstream.handle("tools/call", headers)
        return resp

    resp = await svc._send_with_token_exchange_retry(_send, header, dict(_DISCOVERY_CFG), "gw-disc", "gw", "u@e", req)
    assert resp.status_code == 200
    assert upstream.calls == [("tools/call", _USER_TOKEN)]
    assert svc.oauth_manager.token_exchange.await_args.kwargs["subject_token"] == _FAKE_JWT
    # The policy upstream refuses the service token for tools/call.
    assert upstream.handle("tools/call", {"Authorization": f"Bearer {_SERVICE_TOKEN}"}) == 401
