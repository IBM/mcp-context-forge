# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_entra_graph_client.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the app-only Entra Graph overage client (issue #5977) and the
app-only service-principal group resolution (issue #6756).

Beyond the Entra group-claim limit a trusted token carries overage markers
instead of a groups array. ``resolve_overage_groups`` in trusted_claims.py
applies ``jwt_trust_overage_policy``: ``fail_closed`` rejects with 401,
``graph_lookup`` resolves security groups through the app-only Graph client
(oid-keyed Redis cache), and ``proceed_without_groups`` continues with an
empty group list plus a WARNING log carrying the user's oid. The client
acquires a client-credentials token with the SSO provider record's stored
encrypted client secret; the inbound bearer token is never used.

App-only (client-credentials) tokens carry ``idtyp="app"`` and no groups
claim. ``resolve_service_principal_groups`` resolves the service principal's
group membership through ``/servicePrincipals/{oid}/getMemberObjects`` under
the ``graph_lookup`` policy; under ``fail_closed`` (default) and
``proceed_without_groups`` the token authenticates with empty teams and the
roles claim keeps the app-role path.
"""

# Standard
import contextlib
from datetime import datetime, timezone
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.cache.auth_cache import AuthCache
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailUser, ExternalGroupMapping, Role, SSOProvider
from mcpgateway.utils.entra_graph_client import EntraGraphClient, GRAPH_BASE_URL
from mcpgateway.utils.trusted_claims import detect_app_only_token, resolve_overage_groups, resolve_service_principal_groups

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


def _app_only_payload(**overrides):
    """App-only (client-credentials) Entra payload: idtyp=app, no groups claim."""
    payload = {
        "sub": OID,
        "oid": OID,
        "iss": ISSUER,
        "tid": "tenant-1",
        "idtyp": "app",
        "token_use": "trusted",
        "jti": "trusted-jti-app-1",
        "exp": int(time.time()) + 600,
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
    """HTTP client double: client-credentials token POST plus getMemberObjects.

    Every getMemberObjects call is recorded with its URL so tests assert the
    endpoint selection (``/users/`` versus ``/servicePrincipals/``).
    """
    if graph_payload is None:
        graph_payload = {"value": ["group-1", "group-2"]}

    async def _post(url, **kwargs):
        if url == TOKEN_URL:
            return SimpleNamespace(status_code=token_status, json=lambda: {"access_token": APP_ONLY_TOKEN}, text="")
        if url.endswith("/getMemberObjects"):
            graph_calls.append({"url": url, **kwargs})
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


class TestAppOnlyTokenDetection:
    """detect_app_only_token keys on the standard Entra idtyp claim."""

    def test_idtyp_app_detected(self):
        """idtyp == "app" marks an app-only (client-credentials) token."""
        assert detect_app_only_token(_app_only_payload()) is True

    def test_idtyp_absent_is_not_app(self):
        """A token without the idtyp claim is not app-only."""
        assert detect_app_only_token(_overage_payload()) is False

    def test_idtyp_user_is_not_app(self):
        """A delegated user token (idtyp absent or non-app) is not app-only."""
        assert detect_app_only_token(_app_only_payload(idtyp="user")) is False


class TestAppOnlyEndpointSelection:
    """App-only tokens resolve through /servicePrincipals, never /users."""

    async def test_app_only_calls_service_principals_endpoint(self, monkeypatch):
        """AC: /servicePrincipals/{oid}/getMemberObjects is called; /users/ never."""
        graph_calls = []
        _patch_http_and_encryption(monkeypatch, _graph_http_client(graph_calls))
        graph_client, _ = _client_with_redis(None)

        groups = await resolve_service_principal_groups(_app_only_payload(), _settings("graph_lookup"), _db_returning(_provider()), graph_client=graph_client)

        assert groups == ["group-1", "group-2"]
        assert len(graph_calls) == 1
        assert graph_calls[0]["url"] == f"{GRAPH_BASE_URL}/servicePrincipals/{OID}/getMemberObjects"
        assert "/users/" not in graph_calls[0]["url"]
        # The Graph call carries the client-credentials token, never the inbound bearer token.
        assert graph_calls[0]["headers"]["Authorization"] == f"Bearer {APP_ONLY_TOKEN}"
        assert graph_calls[0]["json"] == {"securityEnabledOnly": True}

    async def test_app_only_redis_error_degrades_to_live_lookup(self, monkeypatch):
        """Redis read error -> cache miss -> live Graph call (#5977 AC-extra-1 parity)."""
        graph_calls = []
        graph_client, _ = _client_with_redis(_BrokenRedis())
        _patch_http_and_encryption(monkeypatch, _graph_http_client(graph_calls))

        groups = await resolve_service_principal_groups(_app_only_payload(), _settings("graph_lookup"), _db_returning(_provider()), graph_client=graph_client)

        assert groups == ["group-1", "group-2"]
        assert len(graph_calls) == 1

    async def test_app_only_graph_failure_yields_401(self, monkeypatch):
        """Graph failure under graph_lookup -> 401 (fail-closed)."""
        graph_client, _ = _client_with_redis(_FakeRedis())
        _patch_http_and_encryption(monkeypatch, _graph_http_client([], graph_status=500))

        with pytest.raises(HTTPException) as exc_info:
            await resolve_service_principal_groups(_app_only_payload(), _settings("graph_lookup"), _db_returning(_provider()), graph_client=graph_client)

        assert exc_info.value.status_code == 401


@pytest.fixture
def funnel_db():
    """In-memory SQLite session seeded for the app-only trust-path dispatch.

    Seeds: the owner user, team-sp, the viewer role, an enabled Entra SSO
    provider row, and the group-1 -> team-sp external-group mapping row.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    owner = EmailUser(
        email="owner@example.com",
        password_hash="hash",  # pragma: allowlist secret
        full_name="Owner",
        is_admin=False,
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(owner)
    session.add(EmailTeam(id="team-sp", name="SP Team", slug="team-sp", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(Role(name="viewer", scope="team", permissions=[], created_by=owner.email, is_system_role=True, is_active=True))
    session.add(
        SSOProvider(
            id="entra",
            name="entra",
            display_name="Entra",
            provider_type="oidc",
            is_enabled=True,
            client_id="app-client-id",
            client_secret_encrypted="ENC(plain-secret)",
            authorization_url="https://login.microsoftonline.com/tenant-1/oauth2/v2.0/authorize",
            token_url=TOKEN_URL,
            userinfo_url="https://graph.microsoft.com/oidc/userinfo",
            issuer=ISSUER,
        )
    )
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant="tenant-1", external_group_id="group-1", cf_team_id="team-sp", cf_role=None))
    session.commit()
    try:
        yield session
    finally:
        session.close()


async def _drive_app_only_funnel(monkeypatch, db, payload, *, graph_client):
    """Drive get_current_user on the trust path with an app-only payload.

    The Graph client double is injected through the trusted_claims module
    binding so the trust path uses it instead of a live EntraGraphClient.
    Returns (user, request). Raises whatever the funnel raises.
    """
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)

    session_test = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr("mcpgateway.auth.SessionLocal", session_test)

    @contextlib.contextmanager
    def _fresh_db_session():
        session = session_test()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("mcpgateway.auth.fresh_db_session", _fresh_db_session)
    monkeypatch.setattr("mcpgateway.utils.trusted_claims.EntraGraphClient", lambda *args, **kwargs: graph_client)

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret
    request = SimpleNamespace(state=SimpleNamespace())

    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
        with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
            # Fail the test loudly if the trust path touches the user table
            # through the default-funnel helpers.
            with patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("user lookup on trust path")):
                user = await get_current_user(credentials=credentials, request=request)
    return user, request


class TestAppOnlyTrustPathDispatch:
    """Policy dispatch in the trust path for app-only tokens (idtyp=app)."""

    async def test_app_only_graph_lookup_maps_groups_to_teams(self, monkeypatch, funnel_db):
        """AC: SP endpoint called, groups mapped, token_teams carry mapped teams."""
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "graph_lookup")
        graph_calls = []
        _patch_http_and_encryption(monkeypatch, _graph_http_client(graph_calls))
        graph_client, _ = _client_with_redis(None)

        user, request = await _drive_app_only_funnel(monkeypatch, funnel_db, _app_only_payload(), graph_client=graph_client)

        assert user.user_id == OID
        assert user.token_use == "trusted"
        # group-1 maps to team-sp; group-2 is unmapped and contributes nothing.
        assert request.state.token_teams == ["team-sp"]
        assert len(graph_calls) == 1
        assert graph_calls[0]["url"] == f"{GRAPH_BASE_URL}/servicePrincipals/{OID}/getMemberObjects"
        assert "/users/" not in graph_calls[0]["url"]

    async def test_app_only_fail_closed_default_keeps_roles_only_path(self, monkeypatch, funnel_db):
        """AC: fail_closed (default) authenticates with token_teams=[] and the roles claim maps."""
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "fail_closed")
        graph_calls = []
        _patch_http_and_encryption(monkeypatch, _graph_http_client(graph_calls))
        graph_client, _ = _client_with_redis(None)

        user, request = await _drive_app_only_funnel(monkeypatch, funnel_db, _app_only_payload(roles=["viewer"]), graph_client=graph_client)

        assert user.user_id == OID
        assert request.state.token_teams == []
        # The app-role path (#5902) is intact: roles=["viewer"] grants the mapped CF role.
        assert user.roles == ["viewer"]
        # Graph is never called under the default policy.
        assert graph_calls == []

    async def test_app_only_proceed_without_groups_keeps_current_behavior(self, monkeypatch, funnel_db):
        """proceed_without_groups: authenticated with token_teams=[]; Graph is never called."""
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "proceed_without_groups")
        graph_calls = []
        _patch_http_and_encryption(monkeypatch, _graph_http_client(graph_calls))
        graph_client, _ = _client_with_redis(None)

        user, request = await _drive_app_only_funnel(monkeypatch, funnel_db, _app_only_payload(), graph_client=graph_client)

        assert user.user_id == OID
        assert request.state.token_teams == []
        assert graph_calls == []

    async def test_app_only_graph_failure_under_graph_lookup_yields_401(self, monkeypatch, funnel_db):
        """AC: Graph failure under graph_lookup rejects the request with 401."""
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "graph_lookup")
        _patch_http_and_encryption(monkeypatch, _graph_http_client([], graph_status=500))
        graph_client, _ = _client_with_redis(None)

        with pytest.raises(HTTPException) as exc_info:
            await _drive_app_only_funnel(monkeypatch, funnel_db, _app_only_payload(), graph_client=graph_client)

        assert exc_info.value.status_code == 401
