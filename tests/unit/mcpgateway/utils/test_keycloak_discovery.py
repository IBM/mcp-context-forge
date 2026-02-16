# -*- coding: utf-8 -*-
"""Tests for keycloak discovery utilities."""

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.utils import keycloak_discovery


class DummyAsyncResponse:
    def __init__(self, payload, raise_exc=None):
        self._payload = payload
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc:
            raise self._raise_exc

    def json(self):
        return self._payload


class DummyAsyncClient:
    def __init__(self, response):
        self.response = response
        self.requested = None

    async def get(self, url, timeout=10):
        self.requested = (url, timeout)
        return self.response


@pytest.mark.asyncio
async def test_discover_keycloak_endpoints_success(monkeypatch: pytest.MonkeyPatch):
    response = DummyAsyncResponse(
        {
            "authorization_endpoint": "https://kc/auth",
            "token_endpoint": "https://kc/token",
            "userinfo_endpoint": "https://kc/userinfo",
            "issuer": "https://kc/issuer",
            "jwks_uri": "https://kc/jwks",
        }
    )

    async def fake_get_http_client():
        return DummyAsyncClient(response)

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", fake_get_http_client)

    endpoints = await keycloak_discovery.discover_keycloak_endpoints("https://kc", "master")

    assert endpoints["authorization_url"] == "https://kc/auth"
    assert endpoints["jwks_uri"] == "https://kc/jwks"


@pytest.mark.asyncio
async def test_discover_keycloak_endpoints_rewrites_backchannel_urls(monkeypatch: pytest.MonkeyPatch):
    response = DummyAsyncResponse(
        {
            "authorization_endpoint": "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/auth",
            "token_endpoint": "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/token",
            "userinfo_endpoint": "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/userinfo",
            "issuer": "http://localhost:8180/realms/mcp-gateway",
            "jwks_uri": "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/certs",
        }
    )

    async def fake_get_http_client():
        return DummyAsyncClient(response)

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", fake_get_http_client)

    endpoints = await keycloak_discovery.discover_keycloak_endpoints("http://keycloak:8080", "mcp-gateway")

    assert endpoints["authorization_url"].startswith("http://localhost:8180/")
    assert endpoints["token_url"].startswith("http://keycloak:8080/")
    assert endpoints["userinfo_url"].startswith("http://keycloak:8080/")
    assert endpoints["jwks_uri"].startswith("http://keycloak:8080/")


@pytest.mark.asyncio
async def test_discover_keycloak_endpoints_rewrites_authorization_url_to_public_base(monkeypatch: pytest.MonkeyPatch):
    response = DummyAsyncResponse(
        {
            "authorization_endpoint": "http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/auth",
            "token_endpoint": "http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/token",
            "userinfo_endpoint": "http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/userinfo",
            "issuer": "http://localhost:8080/realms/mcp-gateway",
            "jwks_uri": "http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/certs",
        }
    )

    async def fake_get_http_client():
        return DummyAsyncClient(response)

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", fake_get_http_client)

    endpoints = await keycloak_discovery.discover_keycloak_endpoints(
        "http://keycloak:8080",
        "mcp-gateway",
        public_base_url="http://localhost:8180",
    )

    assert endpoints["authorization_url"].startswith("http://localhost:8180/")
    assert endpoints["token_url"].startswith("http://keycloak:8080/")
    assert endpoints["userinfo_url"].startswith("http://keycloak:8080/")
    assert endpoints["jwks_uri"].startswith("http://keycloak:8080/")


@pytest.mark.asyncio
async def test_discover_keycloak_endpoints_incomplete(monkeypatch: pytest.MonkeyPatch):
    response = DummyAsyncResponse({"authorization_endpoint": "https://kc/auth"})

    async def fake_get_http_client():
        return DummyAsyncClient(response)

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", fake_get_http_client)

    endpoints = await keycloak_discovery.discover_keycloak_endpoints("https://kc", "master")

    assert endpoints is None


@pytest.mark.asyncio
async def test_discover_keycloak_endpoints_http_error(monkeypatch: pytest.MonkeyPatch):
    response = DummyAsyncResponse({}, raise_exc=httpx.HTTPError("boom"))

    async def fake_get_http_client():
        return DummyAsyncClient(response)

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", fake_get_http_client)

    endpoints = await keycloak_discovery.discover_keycloak_endpoints("https://kc", "master")

    assert endpoints is None


@pytest.mark.asyncio
async def test_discover_keycloak_endpoints_unexpected(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_http_client():
        raise RuntimeError("fail")

    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", fake_get_http_client)

    endpoints = await keycloak_discovery.discover_keycloak_endpoints("https://kc", "master")

    assert endpoints is None


class DummySyncResponse:
    def __init__(self, payload, raise_exc=None):
        self._payload = payload
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc:
            raise self._raise_exc

    def json(self):
        return self._payload


class DummySyncClient:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url):
        return self._response


def test_discover_keycloak_endpoints_sync_success(monkeypatch: pytest.MonkeyPatch):
    response = DummySyncResponse(
        {
            "authorization_endpoint": "https://kc/auth",
            "token_endpoint": "https://kc/token",
            "userinfo_endpoint": "https://kc/userinfo",
            "issuer": "https://kc/issuer",
            "jwks_uri": "https://kc/jwks",
        }
    )

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: DummySyncClient(response))

    endpoints = keycloak_discovery.discover_keycloak_endpoints_sync("https://kc", "master")

    assert endpoints["token_url"] == "https://kc/token"


def test_discover_keycloak_endpoints_sync_rewrites_backchannel_urls(monkeypatch: pytest.MonkeyPatch):
    response = DummySyncResponse(
        {
            "authorization_endpoint": "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/auth",
            "token_endpoint": "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/token",
            "userinfo_endpoint": "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/userinfo",
            "issuer": "http://localhost:8180/realms/mcp-gateway",
            "jwks_uri": "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/certs",
        }
    )

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: DummySyncClient(response))

    endpoints = keycloak_discovery.discover_keycloak_endpoints_sync("http://keycloak:8080", "mcp-gateway")

    assert endpoints["authorization_url"].startswith("http://localhost:8180/")
    assert endpoints["token_url"].startswith("http://keycloak:8080/")
    assert endpoints["userinfo_url"].startswith("http://keycloak:8080/")
    assert endpoints["jwks_uri"].startswith("http://keycloak:8080/")


def test_discover_keycloak_endpoints_sync_rewrites_authorization_url_to_public_base(monkeypatch: pytest.MonkeyPatch):
    response = DummySyncResponse(
        {
            "authorization_endpoint": "http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/auth",
            "token_endpoint": "http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/token",
            "userinfo_endpoint": "http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/userinfo",
            "issuer": "http://localhost:8080/realms/mcp-gateway",
            "jwks_uri": "http://localhost:8080/realms/mcp-gateway/protocol/openid-connect/certs",
        }
    )

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: DummySyncClient(response))

    endpoints = keycloak_discovery.discover_keycloak_endpoints_sync(
        "http://keycloak:8080",
        "mcp-gateway",
        public_base_url="http://localhost:8180",
    )

    assert endpoints["authorization_url"].startswith("http://localhost:8180/")
    assert endpoints["token_url"].startswith("http://keycloak:8080/")
    assert endpoints["userinfo_url"].startswith("http://keycloak:8080/")
    assert endpoints["jwks_uri"].startswith("http://keycloak:8080/")


def test_discover_keycloak_endpoints_sync_http_error(monkeypatch: pytest.MonkeyPatch):
    response = DummySyncResponse({}, raise_exc=httpx.HTTPError("boom"))

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: DummySyncClient(response))

    endpoints = keycloak_discovery.discover_keycloak_endpoints_sync("https://kc", "master")

    assert endpoints is None


def test_discover_keycloak_endpoints_sync_incomplete(monkeypatch: pytest.MonkeyPatch):
    """Sync discovery should return None for incomplete OIDC configs."""
    response = DummySyncResponse({"authorization_endpoint": "https://kc/auth"})
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: DummySyncClient(response))

    endpoints = keycloak_discovery.discover_keycloak_endpoints_sync("https://kc", "master")
    assert endpoints is None


def test_discover_keycloak_endpoints_sync_unexpected(monkeypatch: pytest.MonkeyPatch):
    """Sync discovery should handle unexpected exceptions gracefully."""
    def boom(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("fail")

    monkeypatch.setattr(httpx, "Client", boom)
    endpoints = keycloak_discovery.discover_keycloak_endpoints_sync("https://kc", "master")
    assert endpoints is None


def test_rewrite_endpoint_base_ignores_invalid_target_base():
    """Rewrite helper should return original URL when target base lacks scheme/netloc."""
    original = "http://localhost:8180/realms/mcp-gateway/protocol/openid-connect/token"
    rewritten = keycloak_discovery._rewrite_endpoint_base(  # pylint: disable=protected-access
        original,
        "localhost:8180",
        "token",
    )
    assert rewritten == original
