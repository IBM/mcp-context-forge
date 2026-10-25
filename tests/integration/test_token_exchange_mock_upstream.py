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


# ---------------------------------------------------------------------------
# RFC 8693 delegation against a mock authorization server
# ---------------------------------------------------------------------------

_DELEGATION_CLIENT_ID = "cf-gateway"
_UPSTREAM_SECRET = "mock-authorization-server-signing-secret"  # pragma: allowlist secret


class _DelegationAuthServer:
    """Mock authorization server: adds an ``act`` claim only when the exchange carries ``actor_token``.

    It issues client-credentials actor tokens, verifies ``client_assertion`` actor
    JWTs against the gateway's public key, and records every request body.
    """

    def __init__(self, *, public_pem=None, fail_client_credentials=False):
        self.requests = []
        self.public_pem = public_pem
        self.fail_client_credentials = fail_client_credentials

    def _actor_subject(self, form):
        """Resolve the ``act.sub`` value from an actor token, or ``None`` without one.

        Args:
            form: Parsed request form.

        Returns:
            Optional[str]: The actor's client id.
        """
        # Third-Party
        import jwt

        actor_token = form.get("actor_token")
        if not actor_token:
            return None
        if form["actor_token_type"] == "urn:ietf:params:oauth:token-type:access_token":
            return jwt.decode(actor_token, _UPSTREAM_SECRET, algorithms=["HS256"])["client_id"]
        claims = jwt.decode(actor_token, self.public_pem, algorithms=["RS256"], audience="https://as.example.com/token")
        assert claims["iss"] == claims["sub"]
        return claims["sub"]

    def handler(self, request):
        """Serve one token endpoint request.

        Args:
            request: Incoming ``httpx.Request``.

        Returns:
            httpx.Response: Token response.
        """
        # Standard
        from urllib.parse import parse_qsl

        # Third-Party
        import httpx
        import jwt

        form = dict(parse_qsl(request.content.decode("utf-8")))
        self.requests.append(form)
        if form["grant_type"] == "client_credentials":
            if self.fail_client_credentials:
                return httpx.Response(503, json={"error": "temporarily_unavailable"})
            actor = jwt.encode({"client_id": form["client_id"], "sub": form["client_id"]}, _UPSTREAM_SECRET, algorithm="HS256")
            return httpx.Response(200, json={"access_token": actor, "token_type": "Bearer", "expires_in": 600})
        claims = {"sub": "u@e", "aud": form["audience"]}
        actor_subject = self._actor_subject(form)
        if actor_subject:
            claims["act"] = {"sub": actor_subject}
        return httpx.Response(200, json={"access_token": jwt.encode(claims, _UPSTREAM_SECRET, algorithm="HS256"), "token_type": "Bearer", "expires_in": 600})


def _delegation_tool_service(auth_server, monkeypatch):
    """Build a ToolService whose real OAuthManager posts to the mock authorization server.

    Args:
        auth_server: The mock authorization server.
        monkeypatch: pytest monkeypatch fixture.

    Returns:
        ToolService: Service under test.
    """
    # Standard
    from contextlib import asynccontextmanager

    # Third-Party
    import httpx

    # First-Party
    from mcpgateway.services import gateway_service_token_cache
    from mcpgateway.services.oauth_manager import OAuthManager
    from mcpgateway.services.token_exchange_cache import TokenExchangeCache
    from mcpgateway.services.tool_service import ToolService

    @asynccontextmanager
    async def _client(*_args, **_kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(auth_server.handler)) as client:
            yield client

    monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", _client)
    monkeypatch.setattr(gateway_service_token_cache, "_shared_cache", gateway_service_token_cache.GatewayServiceTokenCache(redis_url=None))
    svc = ToolService()
    svc._token_exchange_cache = TokenExchangeCache(redis_url=None)
    svc.oauth_manager = OAuthManager(max_retries=1)
    return svc


def _delegation_cfg(**overrides):
    cfg = {
        "grant_type": "token-exchange",
        "token_url": "https://as.example.com/token",
        "client_id": _DELEGATION_CLIENT_ID,
        "client_secret": "cf-secret",  # pragma: allowlist secret
        "target_audience": "https://svc",
        "subject_token_source": "inbound_user_jwt",
    }
    cfg.update(overrides)
    return cfg


def _issued_claims(header):
    # Third-Party
    import jwt

    return jwt.decode(header["Authorization"].removeprefix("Bearer "), _UPSTREAM_SECRET, algorithms=["HS256"], audience="https://svc")


@pytest.mark.asyncio
async def test_delegation_client_credentials_issues_act_claim(monkeypatch):
    """The exchanged token names the gateway client in ``act.sub`` when the actor comes from client credentials."""
    auth_server = _DelegationAuthServer()
    svc = _delegation_tool_service(auth_server, monkeypatch)

    header = await svc._resolve_token_exchange_header(_delegation_cfg(actor_token_source="client_credentials"), "gw-del", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"})

    assert _issued_claims(header)["act"] == {"sub": _DELEGATION_CLIENT_ID}
    exchange = auth_server.requests[-1]
    assert exchange["subject_token"] == _FAKE_JWT
    assert exchange["actor_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
    assert [r["grant_type"] for r in auth_server.requests] == ["client_credentials", "urn:ietf:params:oauth:grant-type:token-exchange"]


@pytest.mark.asyncio
async def test_delegation_client_assertion_issues_act_claim(monkeypatch):
    """The exchanged token names the gateway client in ``act.sub`` when the actor is a signed assertion."""
    # Third-Party
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    auth_server = _DelegationAuthServer(public_pem=public_pem)
    svc = _delegation_tool_service(auth_server, monkeypatch)

    header = await svc._resolve_token_exchange_header(
        _delegation_cfg(actor_token_source="client_assertion", private_key=private_pem), "gw-del", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"}
    )

    assert _issued_claims(header)["act"] == {"sub": _DELEGATION_CLIENT_ID}
    assert [r["grant_type"] for r in auth_server.requests] == ["urn:ietf:params:oauth:grant-type:token-exchange"]
    assert auth_server.requests[0]["actor_token_type"] == "urn:ietf:params:oauth:token-type:jwt"


@pytest.mark.asyncio
async def test_impersonation_issues_no_act_claim(monkeypatch):
    """Without ``actor_token_source`` the exchange carries no actor token and the issued token has no ``act``."""
    auth_server = _DelegationAuthServer()
    svc = _delegation_tool_service(auth_server, monkeypatch)

    header = await svc._resolve_token_exchange_header(_delegation_cfg(), "gw-imp", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"})

    assert "act" not in _issued_claims(header)
    assert "actor_token" not in auth_server.requests[0]


@pytest.mark.asyncio
async def test_delegation_actor_failure_sends_no_fallback_exchange(monkeypatch):
    """When the actor token request fails, no impersonation exchange is sent and the call fails."""
    # First-Party
    from mcpgateway.services.tool_service import ToolInvocationError

    auth_server = _DelegationAuthServer(fail_client_credentials=True)
    svc = _delegation_tool_service(auth_server, monkeypatch)

    with pytest.raises(ToolInvocationError):
        await svc._resolve_token_exchange_header(_delegation_cfg(actor_token_source="client_credentials"), "gw-del", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"})

    assert [r["grant_type"] for r in auth_server.requests] == ["client_credentials"]
