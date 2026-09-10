# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_entra_graph_client.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the app-only Entra Graph overage client (issue #5977).

Beyond the Entra group-claim limit a trusted token carries overage markers
instead of a groups array. ``resolve_overage_groups`` in trusted_claims.py
applies ``jwt_trust_overage_policy``: ``fail_closed`` rejects with 401,
``graph_lookup`` resolves security groups through the app-only Graph client
(oid-keyed Redis cache), and ``proceed_without_groups`` continues with an
empty group list plus a WARNING log carrying the user's oid. The client
acquires a client-credentials token with the SSO provider record's stored
encrypted client secret; the inbound bearer token is never used.
"""

# Standard
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.cache.auth_cache import AuthCache
from mcpgateway.utils.entra_graph_client import EntraGraphClient
from mcpgateway.utils.trusted_claims import resolve_overage_groups

ISSUER = "https://login.microsoftonline.com/tenant-1/v2.0"
OID = "oid-9f8e7d6c"
TOKEN_URL = "https://login.microsoftonline.com/tenant-1/oauth2/v2.0/token"
APP_ONLY_TOKEN = "app-only-graph-token"  # noqa: S105 — test fixture, not a real secret


def _overage_payload(**overrides):
    """Trust-eligible Entra payload with the overage marker shapes set."""
    payload = {
        "sub": OID,
        "oid": OID,
        "iss": ISSUER,
        "tid": "tenant-1",
        "jti": "trusted-jti-1",
        "exp": int(time.time()) + 600,
        "hasgroups": True,
        "_claim_names": {"groups": "src1"},
    }
    payload.update(overrides)
    return payload


def _settings(policy):
    """Minimal settings stand-in carrying the overage policy and claim map."""
    return SimpleNamespace(
        jwt_trust_overage_policy=policy,
        jwt_claim_user_id="sub",
    )


def _provider():
    """SSO provider record double: encrypted secret, never a plain secret."""
    return SimpleNamespace(
        id="entra",
        name="entra",
        issuer=ISSUER,
        is_enabled=True,
        client_id="app-client-id",
        client_secret_encrypted="ENC(plain-secret)",
        token_url=TOKEN_URL,
    )


def _db_returning(provider):
    """Session double whose SSO provider lookup returns ``provider``."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = provider
    return db


class _FakeRedis:
    """Dict-backed async Redis double that records keys and TTLs."""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl


class _BrokenRedis:
    """Redis double whose reads and writes raise ConnectionError."""

    async def get(self, key):
        raise ConnectionError("redis down")

    async def setex(self, key, ttl, value):
        raise ConnectionError("redis down")


def _graph_http_client(graph_calls, graph_status=200, graph_payload=None, token_status=200):
    """HTTP client double: client-credentials token POST plus getMemberObjects."""
    if graph_payload is None:
        graph_payload = {"value": ["group-1", "group-2"]}

    async def _post(url, **kwargs):
        if url == TOKEN_URL:
            return SimpleNamespace(status_code=token_status, json=lambda: {"access_token": APP_ONLY_TOKEN}, text="")
        if url.endswith("/getMemberObjects"):
            graph_calls.append(kwargs)
            return SimpleNamespace(status_code=graph_status, json=lambda: graph_payload, text="")
        raise AssertionError(f"unexpected URL {url}")

    return SimpleNamespace(post=_post)


def _patch_http_and_encryption(monkeypatch, http_client):
    """Point the lazy http/encryption lookups at test doubles."""
    monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", AsyncMock(return_value=http_client))
    encryption = SimpleNamespace(decrypt_secret_async=AsyncMock(return_value="plain-secret"))
    monkeypatch.setattr("mcpgateway.services.encryption_service.get_encryption_service", lambda _secret: encryption)


def _client_with_redis(redis):
    """EntraGraphClient on a real AuthCache whose Redis handle is a double."""
    auth_cache = AuthCache()

    async def _redis():
        return redis

    auth_cache._get_redis_client = _redis  # pyright: ignore[reportPrivateUsage]
    return EntraGraphClient(auth_cache=auth_cache), auth_cache


class TestOveragePolicyMatrix:
    """Three-policy dispatch matrix of jwt_trust_overage_policy."""

    async def test_fail_closed_rejects_with_401(self):
        """fail_closed (default): overage token is rejected, error is actionable."""
        with pytest.raises(HTTPException) as exc_info:
            await resolve_overage_groups(_overage_payload(), _settings("fail_closed"), MagicMock())
        assert exc_info.value.status_code == 401
        assert "jwt_trust_overage_policy" in exc_info.value.detail

    async def test_graph_lookup_resolves_groups_via_app_only_token(self, monkeypatch):
        """graph_lookup: groups resolve; Graph is called with the app-only token."""
        graph_calls = []
        _patch_http_and_encryption(monkeypatch, _graph_http_client(graph_calls))
        graph_client, _ = _client_with_redis(None)

        groups = await resolve_overage_groups(_overage_payload(), _settings("graph_lookup"), _db_returning(_provider()), graph_client=graph_client)

        assert groups == ["group-1", "group-2"]
        assert len(graph_calls) == 1
        # The Graph call carries the client-credentials token, never the inbound bearer token.
        assert graph_calls[0]["headers"]["Authorization"] == f"Bearer {APP_ONLY_TOKEN}"
        assert graph_calls[0]["json"] == {"securityEnabledOnly": True}

    async def test_proceed_without_groups_returns_empty_and_warns_with_oid(self, caplog):
        """proceed_without_groups: empty groups plus WARNING log carrying the oid (AC-extra-2)."""
        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.trusted_claims"):
            groups = await resolve_overage_groups(_overage_payload(), _settings("proceed_without_groups"), MagicMock())
        assert groups == []
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert any(OID in record.getMessage() for record in warnings)


class TestResolutionCache:
    """oid-keyed Redis cache over the shared AuthCache key helper."""

    async def test_second_identical_request_served_from_cache(self, monkeypatch):
        """Two identical requests hit Graph once; the second is a cache hit."""
        redis = _FakeRedis()
        graph_client, auth_cache = _client_with_redis(redis)
        graph_calls = []
        _patch_http_and_encryption(monkeypatch, _graph_http_client(graph_calls))
        db = _db_returning(_provider())
        payload = _overage_payload()

        before = int(time.time())
        first = await resolve_overage_groups(payload, _settings("graph_lookup"), db, graph_client=graph_client)
        second = await resolve_overage_groups(payload, _settings("graph_lookup"), db, graph_client=graph_client)

        assert first == ["group-1", "group-2"]
        assert second == first
        assert len(graph_calls) == 1
        # The cache key comes from the shared AuthCache helper (version segment).
        key = auth_cache._get_redis_key("graph", OID)  # pyright: ignore[reportPrivateUsage]
        assert key in redis.store
        # TTL is bounded by the presenting token's exp.
        assert 0 < redis.ttls[key] <= payload["exp"] - before


class TestCacheErrorFallback:
    """AC-extra-1: Redis read errors degrade to cache miss, never to 401."""

    async def test_redis_error_with_graph_success_authorizes(self, monkeypatch):
        """Redis raises ConnectionError on lookup and Graph succeeds -> authorized."""
        graph_client, _ = _client_with_redis(_BrokenRedis())
        _patch_http_and_encryption(monkeypatch, _graph_http_client([]))

        groups = await resolve_overage_groups(_overage_payload(), _settings("graph_lookup"), _db_returning(_provider()), graph_client=graph_client)

        assert groups == ["group-1", "group-2"]

    async def test_redis_error_with_graph_failure_yields_401(self, monkeypatch):
        """Redis raises ConnectionError on lookup and Graph fails -> 401."""
        graph_client, _ = _client_with_redis(_BrokenRedis())
        _patch_http_and_encryption(monkeypatch, _graph_http_client([], graph_status=500))

        with pytest.raises(HTTPException) as exc_info:
            await resolve_overage_groups(_overage_payload(), _settings("graph_lookup"), _db_returning(_provider()), graph_client=graph_client)

        assert exc_info.value.status_code == 401


class TestGraphLookupFailure:
    """graph_lookup is fail-closed on Graph acquisition failure."""

    async def test_graph_failure_under_graph_lookup_yields_401(self, monkeypatch):
        """Healthy cache, Graph returns HTTP 500 -> 401."""
        graph_client, _ = _client_with_redis(_FakeRedis())
        _patch_http_and_encryption(monkeypatch, _graph_http_client([], graph_status=500))

        with pytest.raises(HTTPException) as exc_info:
            await resolve_overage_groups(_overage_payload(), _settings("graph_lookup"), _db_returning(_provider()), graph_client=graph_client)

        assert exc_info.value.status_code == 401

    async def test_token_endpoint_failure_under_graph_lookup_yields_401(self, monkeypatch):
        """Client-credentials token acquisition fails -> 401."""
        graph_client, _ = _client_with_redis(_FakeRedis())
        _patch_http_and_encryption(monkeypatch, _graph_http_client([], token_status=400))

        with pytest.raises(HTTPException) as exc_info:
            await resolve_overage_groups(_overage_payload(), _settings("graph_lookup"), _db_returning(_provider()), graph_client=graph_client)

        assert exc_info.value.status_code == 401
