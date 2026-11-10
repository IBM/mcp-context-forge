# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_oauth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for OAuth token resolution and audience validation on A2A agent calls.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import jwt
import pytest

# First-Party
from mcpgateway.services import a2a_oauth
from mcpgateway.services.a2a_oauth import A2AOAuthError, resolve_a2a_oauth_headers
from mcpgateway.services.a2a_protocol import prepare_a2a_invocation
from mcpgateway.services.gateway_service_token_cache import GatewayServiceTokenCache

ENDPOINT = "https://agent.example.com/a2a"
CONFIG = {"grant_type": "client_credentials", "client_id": "c", "client_secret": "s", "token_url": "https://idp.example.com/token"}  # pragma: allowlist secret


def _jwt(aud):
    return jwt.encode({"aud": aud, "iss": "https://idp.example.com"}, "k" * 32, algorithm="HS256")


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    cache = GatewayServiceTokenCache(redis_url=None)
    monkeypatch.setattr(a2a_oauth, "get_service_token_cache", lambda: cache)
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


def test_prepare_invocation_applies_oauth_headers_only_for_oauth_auth_type():
    kwargs = {"agent_type": "generic", "endpoint_url": ENDPOINT, "protocol_version": None, "parameters": {}, "interaction_type": "query", "oauth_headers": {"Authorization": "Bearer t"}}
    assert prepare_a2a_invocation(auth_type="oauth", **kwargs).headers["Authorization"] == "Bearer t"
    assert "Authorization" not in prepare_a2a_invocation(auth_type=None, **kwargs).headers


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
    assert ("resource", "https://agent.example.com") in list(manager._post_token_request.call_args.args[1])
