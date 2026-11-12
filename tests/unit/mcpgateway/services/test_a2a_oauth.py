# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_oauth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for OAuth token resolution and audience validation on A2A agent calls.
"""

# Standard
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import jwt
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import A2AAgentCreate, A2AAgentUpdate
from mcpgateway.services import a2a_oauth
from mcpgateway.services.a2a_oauth import A2AOAuthError, resolve_a2a_agent_oauth_headers, resolve_a2a_oauth_headers
from mcpgateway.services.a2a_protocol import prepare_a2a_invocation
from mcpgateway.services.a2a_service import A2AAgentError
from mcpgateway.services.gateway_service_token_cache import GatewayServiceTokenCache

ENDPOINT = "https://agent.example.com/a2a"
CONFIG = {"grant_type": "client_credentials", "client_id": "c", "client_secret": "s", "token_url": "https://idp.example.com/token"}  # pragma: allowlist secret


def _jwt(aud):
    return jwt.encode({"aud": aud, "iss": "https://idp.example.com"}, "k" * 32, algorithm="HS256")


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    cache = GatewayServiceTokenCache(redis_url=None)
    monkeypatch.setattr(a2a_oauth, "get_service_token_cache", lambda: cache)
    a2a_oauth._recent_failures.clear()
    return cache


def _manager(token):
    manager = MagicMock()
    manager.get_client_credentials_token_response = AsyncMock(return_value={"access_token": token, "expires_in": 300})
    return manager


@pytest.mark.asyncio
async def test_sends_derived_resource_and_returns_bearer():
    token = _jwt("https://agent.example.com")
    manager = _manager(token)
    headers = await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=manager)
    assert headers == {"Authorization": f"Bearer {token}"}
    sent = manager.get_client_credentials_token_response.call_args
    assert sent.args[0]["resource"] == "https://agent.example.com"
    assert sent.kwargs["send_resource"] is True


@pytest.mark.asyncio
async def test_configured_resource_wins_and_mismatch_blocks():
    manager = _manager(_jwt("https://wrong.example.com"))
    with pytest.raises(A2AOAuthError, match="audience"):
        await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, {**CONFIG, "resource": "https://api.example.com"}, oauth_manager=manager)
    assert manager.get_client_credentials_token_response.call_args.args[0]["resource"] == "https://api.example.com"


@pytest.mark.asyncio
async def test_derived_mismatch_is_advisory_by_default():
    token = _jwt("https://wrong.example.com")
    headers = await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=_manager(token))
    assert headers["Authorization"] == f"Bearer {token}"


@pytest.mark.asyncio
async def test_derived_mismatch_blocks_in_strict_mode(monkeypatch):
    monkeypatch.setattr("mcpgateway.services.token_validation_service.settings.oauth_require_configured_resource", True)
    with pytest.raises(A2AOAuthError, match="audience"):
        await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=_manager(_jwt("https://wrong.example.com")))


@pytest.mark.asyncio
async def test_token_is_cached_and_blocked_token_is_not():
    manager = _manager(_jwt("https://agent.example.com"))
    await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=manager)
    await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=manager)
    assert manager.get_client_credentials_token_response.await_count == 1

    bad = _manager(_jwt("https://wrong.example.com"))
    cfg = {**CONFIG, "resource": "https://api.example.com"}
    for _ in range(2):
        with pytest.raises(A2AOAuthError):
            await resolve_a2a_oauth_headers("a2", "agent", ENDPOINT, cfg, oauth_manager=bad)
    assert bad.get_client_credentials_token_response.await_count == 2


@pytest.mark.asyncio
async def test_rejects_missing_config_unsupported_grant_and_token_failure():
    with pytest.raises(A2AOAuthError, match="no oauth_config"):
        await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, None)
    with pytest.raises(A2AOAuthError, match="unsupported"):
        await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, {**CONFIG, "grant_type": "authorization_code"})
    failing = MagicMock()
    failing.get_client_credentials_token_response = AsyncMock(side_effect=RuntimeError("secret-detail"))
    with pytest.raises(A2AOAuthError) as exc:
        await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=failing)
    assert "secret-detail" not in str(exc.value)


@pytest.mark.asyncio
async def test_helper_returns_no_headers_for_other_auth_types(monkeypatch):
    resolve = AsyncMock(return_value={"Authorization": "Bearer t"})
    monkeypatch.setattr(a2a_oauth, "resolve_a2a_oauth_headers", resolve)
    assert await resolve_a2a_agent_oauth_headers("a1", "agent", ENDPOINT, None, CONFIG) == {}
    assert await resolve_a2a_agent_oauth_headers("a1", "agent", ENDPOINT, "bearer", CONFIG) == {}
    resolve.assert_not_awaited()
    assert await resolve_a2a_agent_oauth_headers("a1", "agent", ENDPOINT, "oauth", CONFIG) == {"Authorization": "Bearer t"}


@pytest.mark.asyncio
async def test_helper_raises_a2a_agent_error_for_every_oauth_failure():
    assert issubclass(A2AOAuthError, A2AAgentError)
    with pytest.raises(A2AAgentError, match="no oauth_config"):
        await resolve_a2a_agent_oauth_headers("a1", "agent", ENDPOINT, "oauth", None)
    with pytest.raises(A2AAgentError, match="unsupported"):
        await resolve_a2a_agent_oauth_headers("a1", "agent", ENDPOINT, "oauth", {**CONFIG, "grant_type": "authorization_code"})


def test_prepare_invocation_applies_oauth_headers():
    kwargs = {"agent_type": "generic", "endpoint_url": ENDPOINT, "protocol_version": None, "parameters": {}, "interaction_type": "query", "oauth_headers": {"Authorization": "Bearer t"}}
    assert prepare_a2a_invocation(auth_type="oauth", **kwargs).headers["Authorization"] == "Bearer t"


@pytest.mark.asyncio
async def test_client_credentials_resource_is_opt_in():
    # First-Party
    from mcpgateway.services.oauth_manager import OAuthManager

    manager = OAuthManager()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"access_token": "t"})
    response.headers = {"content-type": "application/json"}
    response.text = '{"access_token": "t"}'
    manager._post_token_request = AsyncMock(return_value=response)
    cfg = {**CONFIG, "resource": "https://agent.example.com"}
    await manager.get_client_credentials_token_response(cfg)
    assert "resource" not in dict(manager._post_token_request.call_args.args[1])
    await manager.get_client_credentials_token_response(cfg, send_resource=True)
    assert dict(manager._post_token_request.call_args.args[1])["resource"] == "https://agent.example.com"


@pytest.mark.asyncio
async def test_invalid_expires_in_falls_back_to_default_ttl(fresh_cache):
    manager = MagicMock()
    manager.get_client_credentials_token_response = AsyncMock(return_value={"access_token": _jwt("https://agent.example.com"), "expires_in": "soon"})
    fresh_cache.set = AsyncMock()
    await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=manager)
    assert fresh_cache.set.call_args.kwargs["expires_in"] == a2a_oauth._FALLBACK_TTL


@pytest.mark.asyncio
async def test_token_cached_while_waiting_for_lock_skips_token_request(fresh_cache):
    manager = _manager(_jwt("https://agent.example.com"))
    fresh_cache.get = AsyncMock(side_effect=[None, "peer-token"])
    headers = await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=manager)
    assert headers == {"Authorization": "Bearer peer-token"}
    manager.get_client_credentials_token_response.assert_not_awaited()


def test_fingerprint_covers_audience():
    base = {**CONFIG, "resource": "https://agent.example.com"}
    assert a2a_oauth._cache_fingerprint({**base, "audience": "a"}) != a2a_oauth._cache_fingerprint({**base, "audience": "b"})


@pytest.mark.asyncio
async def test_audience_change_does_not_serve_the_old_token():
    first = _manager(_jwt("https://agent.example.com"))
    await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, {**CONFIG, "audience": "one"}, oauth_manager=first)
    second = _manager(_jwt("https://agent.example.com"))
    await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, {**CONFIG, "audience": "two"}, oauth_manager=second)
    second.get_client_credentials_token_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_idp_outage_costs_one_token_request_for_concurrent_callers():
    failing = MagicMock()
    failing.get_client_credentials_token_response = AsyncMock(side_effect=RuntimeError("idp down"))

    async def call():
        with pytest.raises(A2AOAuthError, match="token request failed"):
            await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=failing)

    await asyncio.gather(*(call() for _ in range(5)))
    assert failing.get_client_credentials_token_response.await_count == 1


@pytest.mark.asyncio
async def test_failure_is_retried_after_the_negative_window(monkeypatch):
    failing = MagicMock()
    failing.get_client_credentials_token_response = AsyncMock(side_effect=RuntimeError("idp down"))
    with pytest.raises(A2AOAuthError):
        await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=failing)
    for key, (_, message) in list(a2a_oauth._recent_failures.items()):
        a2a_oauth._recent_failures[key] = (0.0, message)
    healthy = _manager(_jwt("https://agent.example.com"))
    headers = await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, CONFIG, oauth_manager=healthy)
    assert headers["Authorization"].startswith("Bearer ")
    assert not a2a_oauth._recent_failures


@pytest.mark.asyncio
async def test_failure_memo_is_bounded(monkeypatch):
    monkeypatch.setattr(a2a_oauth, "_FAILURE_MAX_ENTRIES", 3)
    for index in range(10):
        a2a_oauth._remember_failure(f"a{index}", "f", "boom")
    assert len(a2a_oauth._recent_failures) == 3


@pytest.mark.asyncio
async def test_token_failure_logs_exception_class_and_never_the_token(caplog):
    failing = MagicMock()
    failing.get_client_credentials_token_response = AsyncMock(side_effect=RuntimeError("idp said no"))
    config = {**CONFIG, "client_secret": "distinct-client-secret-value"}  # pragma: allowlist secret
    with caplog.at_level(logging.WARNING, logger=a2a_oauth.logger.name), pytest.raises(A2AOAuthError):
        await resolve_a2a_oauth_headers("a1", "agent", ENDPOINT, config, oauth_manager=failing)
    assert "RuntimeError" in caplog.text
    assert "idp said no" in caplog.text
    assert "distinct-client-secret-value" not in caplog.text


def _create(oauth_config):
    return A2AAgentCreate(name="agent", endpoint_url=ENDPOINT, auth_type="oauth", oauth_config=oauth_config)


@pytest.mark.parametrize("build", [_create, lambda cfg: A2AAgentUpdate(oauth_config=cfg)], ids=["create", "update"])
class TestA2AOAuthConfigSchema:
    """The A2A schemas validate the token endpoint that now receives client credentials."""

    @pytest.mark.parametrize("grant", ["authorization_code", "password", "token-exchange"])
    def test_unsupported_grant_is_rejected(self, build, grant):
        with pytest.raises(ValidationError, match="only the client_credentials OAuth grant type"):
            build({**CONFIG, "grant_type": grant})

    def test_client_credentials_and_default_grant_are_accepted(self, build):
        assert build(CONFIG).oauth_config["grant_type"] == "client_credentials"
        without_grant = {key: value for key, value in CONFIG.items() if key != "grant_type"}
        assert build(without_grant).oauth_config["token_url"] == CONFIG["token_url"]

    @pytest.mark.parametrize("token_url", ["http://169.254.169.254/latest/meta-data", "ftp://idp.example.com/token", "javascript:alert(1)"])
    def test_token_url_deny_path(self, build, token_url):
        with pytest.raises(ValidationError, match="token_url"):
            build({**CONFIG, "token_url": token_url})

    def test_private_network_token_url_is_rejected_when_blocked(self, build, monkeypatch):
        monkeypatch.setattr("mcpgateway.common.validators.settings.ssrf_allow_private_networks", False)
        with pytest.raises(ValidationError, match="token_url"):
            build({**CONFIG, "token_url": "http://10.0.0.5/token"})


@pytest.mark.asyncio
async def test_repeated_resource_is_sent_as_an_encoded_form_body(monkeypatch):
    """A list of pairs becomes a form-encoded body, because httpx fails on a list as ``data``."""
    # First-Party
    from mcpgateway.services.oauth_manager import OAuthManager

    sent = {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            sent.update(kwargs)
            return MagicMock()

    pinned = MagicMock()
    pinned.pin = lambda url: url
    pinned.apply_headers = lambda headers: dict(headers)
    pinned.extensions = {}
    monkeypatch.setattr("mcpgateway.services.oauth_manager.resolve_pinned_target", AsyncMock(return_value=pinned))
    monkeypatch.setattr("mcpgateway.services.oauth_manager.get_isolated_http_client", lambda **_kwargs: _Client())

    await OAuthManager()._post_token_request("https://idp.example.com/token", [("grant_type", "client_credentials"), ("resource", "https://a"), ("resource", "https://b")])

    assert sent["content"] == "grant_type=client_credentials&resource=https%3A%2F%2Fa&resource=https%3A%2F%2Fb"
    assert sent["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert "data" not in sent


@pytest.mark.asyncio
async def test_client_credentials_sends_every_listed_resource():
    # First-Party
    from mcpgateway.services.oauth_manager import OAuthManager

    manager = OAuthManager()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"access_token": "t"})
    response.headers = {"content-type": "application/json"}
    response.text = '{"access_token": "t"}'
    manager._post_token_request = AsyncMock(return_value=response)
    cfg = {**CONFIG, "resource": ["https://a.example.com", "", "https://b.example.com"]}
    await manager.get_client_credentials_token_response(cfg, send_resource=True)
    pairs = manager._post_token_request.call_args.args[1]
    assert [value for key, value in pairs if key == "resource"] == ["https://a.example.com", "https://b.example.com"]
