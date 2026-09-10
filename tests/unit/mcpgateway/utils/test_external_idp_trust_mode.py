# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_external_idp_trust_mode.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the external-IdP trust root (issue #5903).

When jwt_trust_mode is "jwt-trust" and the token issuer is a configured
trust root (trusted_for_api_auth + api_audience), build_external_identity
builds the identity from the verified token claims alone. No local user
record is read or written: a SQL listener proves zero INSERTs and zero
SELECTs against email_users. Teams and roles come from
resolve_external_groups_to_teams; is_admin comes from the mapped claim.
A token that lacks the configured revocation claim is rejected (the caller
maps the None return to a 401). The three overage policies are executable:
fail_closed, graph_lookup (WO-B.7 client mocked), proceed_without_groups.
"""

# Standard
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import jwt as pyjwt
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailUser, ExternalGroupMapping, Role, SSOProvider
from mcpgateway.utils import verify_credentials as vc

ISSUER = "https://login.example.com/tenant-1/v2.0"
TENANT = "tenant-1"
API_AUDIENCE = "api://my-app"
CALLER_ID = "oid-9f8e7d6c"
CALLER_EMAIL = "trust.user@example.com"


def _claims(**overrides):
    """Minimal trust-eligible external-IdP claims: sub, iss, jti, exp."""
    claims = {
        "sub": CALLER_ID,
        "oid": CALLER_ID,
        "iss": ISSUER,
        "tid": TENANT,
        "aud": API_AUDIENCE,
        "jti": "trusted-jti-1",
        "exp": 9999999999,
    }
    claims.update(overrides)
    return claims


class SqlRecorder:
    """Records every SQL statement emitted on an engine."""

    def __init__(self):
        """Initialize an empty statement log."""
        self.statements: list[str] = []

    def _record(self, _conn, _cursor, statement, _parameters, _context, _executemany):
        self.statements.append(statement)

    def attach(self, engine):
        """Start recording statements on the engine."""
        sa.event.listen(engine, "before_cursor_execute", self._record)

    def detach(self, engine):
        """Stop recording statements on the engine."""
        sa.event.remove(engine, "before_cursor_execute", self._record)

    def count(self, verb: str, table: str) -> int:
        """Count recorded statements of the given verb that touch the table."""
        return sum(1 for statement in self.statements if verb in statement.upper() and table in statement.upper())


@pytest.fixture
def db():
    """In-memory SQLite session seeded with a trust root and mapping rows.

    The SSO provider is a configured trust root (trusted_for_api_auth plus
    api_audience). Mapping rows: entra-group-guid-1 -> team-a with
    cf_role=developer; entra-group-guid-2 -> team-b with cf_role NULL. No
    EmailUser row exists for the caller identity.
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
    session.add(EmailTeam(id="team-a", name="Team A", slug="team-a", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(EmailTeam(id="team-b", name="Team B", slug="team-b", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(Role(name="developer", scope="team", permissions=["a2a.invoke"], created_by=owner.email, is_system_role=True, is_active=True))
    session.add(Role(name="viewer", scope="team", permissions=[], created_by=owner.email, is_system_role=True, is_active=True))
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="entra-group-guid-1", cf_team_id="team-a", cf_role="developer"))
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="entra-group-guid-2", cf_team_id="team-b", cf_role=None))
    session.add(
        SSOProvider(
            id="entra",
            name="entra",
            display_name="Entra",
            provider_type="oidc",
            is_enabled=True,
            client_id="client-1",
            client_secret_encrypted="encrypted",  # pragma: allowlist secret
            authorization_url="https://login.example.com/authorize",
            token_url="https://login.example.com/token",
            userinfo_url="https://login.example.com/userinfo",
            issuer=ISSUER,
            trusted_for_api_auth=True,
            api_audience=API_AUDIENCE,
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _provider(db):
    """Return the seeded trust-root provider row."""
    return db.query(SSOProvider).filter(SSOProvider.id == "entra").one()


async def _async_none():
    """Async stand-in for get_redis_client: forces the in-memory cache."""
    return None


class TestTrustModeNoProvisioning:
    """Trust mode + trust root: identity from claims, zero email_users access."""

    @pytest.mark.asyncio
    async def test_trust_root_token_builds_identity_without_email_users_access(self, db, monkeypatch):
        """Claims-derived identity: zero INSERTs and zero SELECTs on email_users."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        provider = _provider(db)
        claims = _claims(email=CALLER_EMAIL, name="Trust User", is_admin=True, groups=["entra-group-guid-1"])
        token = pyjwt.encode(claims, "k", algorithm="HS256")

        recorder = SqlRecorder()
        recorder.attach(db.get_bind())
        try:
            payload = await vc.build_external_identity(provider, claims, token, db)
        finally:
            recorder.detach(db.get_bind())

        assert recorder.count("INSERT", "EMAIL_USERS") == 0
        assert recorder.count("SELECT", "EMAIL_USERS") == 0
        assert payload is not None
        assert payload["token_use"] == "trusted"
        assert payload["sub"] == CALLER_ID
        assert payload["user_id"] == CALLER_ID
        assert payload["email"] == CALLER_EMAIL
        # Teams and roles derive from resolve_external_groups_to_teams, not a DB user.
        assert payload["teams"] == ["team-a"]
        assert payload["roles"] == ["developer", "platform_admin"]
        # is_admin derives from the mapped claim; no DB row exists for the caller.
        assert payload["is_admin"] is True

    @pytest.mark.asyncio
    async def test_maybe_verify_external_trust_mode_end_to_end(self, db, monkeypatch):
        """JWKS-mocked IdP: verification plus trust identity, zero provisioning."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "sso_api_token_auth_enabled", True)
        monkeypatch.setattr(vc, "_has_trusted_providers", lambda _db: True)
        monkeypatch.setattr(vc, "get_redis_client", _async_none)
        provider = _provider(db)
        monkeypatch.setattr(vc, "resolve_trusted_provider_by_issuer", lambda _iss, _db: provider)

        claims = _claims(email=CALLER_EMAIL, groups=["entra-group-guid-2"])
        token = pyjwt.encode(claims, "k", algorithm="HS256")

        async def fake_verify_oauth(_token, authorization_servers, *, expected_audience=None):
            return claims

        monkeypatch.setattr(vc, "verify_oauth_access_token", fake_verify_oauth)
        await vc.invalidate_external_identity_cache()

        recorder = SqlRecorder()
        recorder.attach(db.get_bind())
        try:
            request = SimpleNamespace(state=SimpleNamespace(db=db))
            payload = await vc._maybe_verify_external(token, request)
        finally:
            recorder.detach(db.get_bind())

        assert recorder.count("INSERT", "EMAIL_USERS") == 0
        assert recorder.count("SELECT", "EMAIL_USERS") == 0
        assert payload is not None
        assert payload["token_use"] == "trusted"
        assert payload["teams"] == ["team-b"]


class TestRevocationClaimGate:
    """A trust-eligible token must carry the configured revocation claim."""

    @pytest.mark.asyncio
    async def test_missing_configured_jti_returns_none_with_log(self, db, monkeypatch, caplog):
        """Revocation claim jti configured; token has no jti -> None + log naming jti."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "jwt_trust_revocation_claim", "jti")
        claims = _claims(email=CALLER_EMAIL)
        del claims["jti"]

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.verify_credentials"):
            payload = await vc.build_external_identity(_provider(db), claims, "rawtoken", db)

        assert payload is None
        assert "'jti'" in caplog.text

    @pytest.mark.asyncio
    async def test_uti_configured_uti_present_jti_absent_succeeds(self, db, monkeypatch):
        """Revocation claim uti configured; token has uti and no jti -> success."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "jwt_trust_revocation_claim", "uti")
        claims = _claims(email=CALLER_EMAIL, uti="entra-uti-1")
        del claims["jti"]

        payload = await vc.build_external_identity(_provider(db), claims, "rawtoken", db)

        assert payload is not None
        assert payload["token_use"] == "trusted"

    @pytest.mark.asyncio
    async def test_uti_configured_neither_claim_present_rejected(self, db, monkeypatch, caplog):
        """Revocation claim uti configured; token has neither uti nor jti -> rejected."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "jwt_trust_revocation_claim", "uti")
        claims = _claims(email=CALLER_EMAIL)
        del claims["jti"]

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.verify_credentials"):
            payload = await vc.build_external_identity(_provider(db), claims, "rawtoken", db)

        assert payload is None
        assert "'uti'" in caplog.text


class TestOveragePolicies:
    """The three jwt_trust_overage_policy behaviors are executable."""

    @pytest.mark.asyncio
    async def test_overage_fail_closed_rejects(self, db, monkeypatch):
        """Overage markers + fail_closed -> 401 semantics (None return)."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "fail_closed")
        claims = _claims(email=CALLER_EMAIL, _claim_names={"groups": "src1"}, hasgroups=True)

        payload = await vc.build_external_identity(_provider(db), claims, "rawtoken", db)

        assert payload is None

    @pytest.mark.asyncio
    async def test_overage_graph_lookup_resolves_via_client(self, db, monkeypatch):
        """Overage markers + graph_lookup -> groups resolve via the WO-B.7 client."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "graph_lookup")
        claims = _claims(email=CALLER_EMAIL, _claim_names={"groups": "src1"}, hasgroups=True)

        client = MagicMock()
        client.get_member_groups = AsyncMock(return_value=["entra-group-guid-1"])
        monkeypatch.setattr("mcpgateway.utils.trusted_claims.EntraGraphClient", lambda: client)

        payload = await vc.build_external_identity(_provider(db), claims, "rawtoken", db)

        assert payload is not None
        client.get_member_groups.assert_awaited_once()
        assert client.get_member_groups.await_args.args[1] == CALLER_ID
        # Resolved groups map through resolve_external_groups_to_teams.
        assert payload["teams"] == ["team-a"]
        assert payload["roles"] == ["developer"]

    @pytest.mark.asyncio
    async def test_overage_proceed_without_groups_degrades(self, db, monkeypatch, caplog):
        """Overage markers + proceed_without_groups -> teams=[], WARNING with oid."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "proceed_without_groups")
        claims = _claims(email=CALLER_EMAIL, _claim_names={"groups": "src1"}, hasgroups=True)

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.trusted_claims"):
            payload = await vc.build_external_identity(_provider(db), claims, "rawtoken", db)

        assert payload is not None
        assert payload["teams"] == []
        assert payload["token_use"] == "trusted"
        assert any(CALLER_ID in record.message for record in caplog.records)


class TestTrustIdentityCache:
    """invalidate_external_identity_cache covers the claims-derived path."""

    @pytest.mark.asyncio
    async def test_invalidate_clears_trust_mode_entry(self, monkeypatch):
        """A trust-mode cache entry (token-hash key) is gone after invalidate."""
        monkeypatch.setattr(vc, "get_redis_client", _async_none)
        token_hash = vc._token_hash("trust-mode-raw-token")  # pylint: disable=protected-access

        await vc._external_identity_cache_put(token_hash, {"sub": CALLER_ID, "token_use": "trusted"}, 9999999999)  # pylint: disable=protected-access
        assert await vc._external_identity_cache_get(token_hash) is not None  # pylint: disable=protected-access

        await vc.invalidate_external_identity_cache()

        assert await vc._external_identity_cache_get(token_hash) is None  # pylint: disable=protected-access
