# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_mode_cross_gateway.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Cross-gateway UAID trust-mode acceptance suite (issue #5905, suite f).

When the calling gateway and a remote gateway both run trust mode, the
forwarded bearer token is the caller's inbound JWT (per the existing UAID
bearer-forwarding rules; see docs/security/uaid-cross-gateway-auth.md). The
remote gateway re-evaluates RBAC against its OWN ``external_group_mappings``
table; team membership the calling gateway derived from its own mappings
does NOT transfer.

The remote gateway is modeled by a second in-memory database with its own
mapping table and agents; the REAL trust-mode funnel
(``get_current_user`` -> ``extract_trusted_principal`` ->
``resolve_external_groups_to_teams``) runs against it, driven by the exact
payload the calling gateway authenticated. The caller's token maps only to
Team-A on the remote gateway, so an agent on remote Team-B returns 404 via
``_check_agent_access`` (the route maps ``A2AAgentNotFoundError`` to HTTP
404; see ``mcpgateway/main.py`` ``get_a2a_agent``).
"""

# Standard
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi.security import HTTPAuthorizationCredentials
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Base, EmailTeam, EmailUser, ExternalGroupMapping
from mcpgateway.services.a2a_service import A2AAgentNotFoundError, A2AAgentService

CALLER_ID = "trust-xgw-subject-0001"
CALLER_EMAIL = "xgw.user@example.com"
SHARED_ISSUER = "https://idp.example.com"  # both gateways trust the same issuer
EXT_GROUP = "ext-group-1"
AGENT_OK = object()  # sentinel for the convert_agent_to_read patch


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


def _make_db(seed):
    """Build an in-memory gateway database and seed it.

    Args:
        seed: Callback receiving the session after the owner user exists.

    Returns:
        A session bound to the in-memory engine.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    now = datetime.now(timezone.utc)
    owner = EmailUser(
        email="owner@example.com",
        password_hash="hash",  # pragma: allowlist secret
        full_name="Owner",
        is_admin=False,
        is_active=True,
        email_verified_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(owner)
    session.commit()
    seed(session)
    session.commit()
    return session


def _team(team_id: str, name: str, slug: str) -> EmailTeam:
    """Build a non-personal team row."""
    return EmailTeam(id=team_id, name=name, slug=slug, created_by="owner@example.com", is_personal=False, visibility="private")


@pytest.fixture
def calling_db():
    """Calling gateway: maps the caller's external group to caller Team-X."""
    session = _make_db(
        lambda s: (
            s.add(_team("caller-team-x", "Caller Team X", "caller-team-x")),
            s.flush(),  # parent before child: no ORM relationship on the FK
            s.add(ExternalGroupMapping(issuer=SHARED_ISSUER, tenant=None, external_group_id=EXT_GROUP, cf_team_id="caller-team-x")),
        )
    )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def remote_db():
    """Remote gateway: maps the caller's external group to remote Team-A only.

    Hosts the target agent on remote Team-B (plus a public control agent).
    """
    def _seed(s):
        s.add(_team("remote-team-a", "Remote Team A", "remote-team-a"))
        s.add(_team("remote-team-b", "Remote Team B", "remote-team-b"))
        s.flush()  # parents before children: no ORM relationship on the FKs
        s.add(ExternalGroupMapping(issuer=SHARED_ISSUER, tenant=None, external_group_id=EXT_GROUP, cf_team_id="remote-team-a"))
        s.flush()
        s.add(
            DbA2AAgent(
                id="agent-team-b",
                name="team-b-agent",
                slug="team-b-agent",
                endpoint_url="https://b.example.com/agent",
                visibility="team",
                team_id="remote-team-b",
                enabled=True,
            )
        )
        s.add(
            DbA2AAgent(
                id="agent-public",
                name="public-agent",
                slug="public-agent",
                endpoint_url="https://public.example.com/agent",
                visibility="public",
                enabled=True,
            )
        )

    session = _make_db(_seed)
    try:
        yield session
    finally:
        session.close()


def _forwarded_payload() -> dict:
    """Claims of the bearer token the calling gateway forwards cross-gateway.

    The token carries the raw external group IDs; it does NOT carry any
    ContextForge team IDs derived on the calling gateway.
    """
    return {
        "sub": CALLER_ID,
        "token_use": "trusted",
        "iss": SHARED_ISSUER,
        "email": CALLER_EMAIL,
        "groups": [EXT_GROUP],
        "roles": [],
        "jti": "cross-gateway-jti-0001",
        "exp": _exp(),
    }


def _patch_funnel_sessions(monkeypatch: pytest.MonkeyPatch, db) -> None:
    """Re-point the funnel's internal sessions at the given gateway database."""
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


async def _authenticate_on_gateway(monkeypatch: pytest.MonkeyPatch, gateway_db, payload: dict):
    """Authenticate the forwarded bearer token on one gateway's database.

    Runs the real trust-mode funnel: claim extraction, group-to-team
    resolution against that gateway's ``external_group_mappings``, and the
    revocation check.
    """
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
    _patch_funnel_sessions(monkeypatch, gateway_db)

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="forwarded_jwt")  # pragma: allowlist secret
    request = SimpleNamespace(state=SimpleNamespace())
    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
        user = await get_current_user(credentials=credentials, request=request)
    return user, request


class TestCrossGatewayTrustMode:
    """The remote gateway re-evaluates the forwarded token against its own mappings."""

    @pytest.mark.asyncio
    async def test_remote_reevaluates_against_own_mappings(self, monkeypatch, calling_db, remote_db):
        """Same token, two gateways: divergent mappings produce divergent teams."""
        payload = _forwarded_payload()

        # Calling gateway: the external group maps to caller Team-X.
        caller, _ = await _authenticate_on_gateway(monkeypatch, calling_db, payload)
        assert caller.teams == ["caller-team-x"]

        # Remote gateway: the SAME forwarded token maps to remote Team-A.
        # caller-team-x does not transfer.
        remote_principal, request = await _authenticate_on_gateway(monkeypatch, remote_db, payload)
        assert remote_principal.teams == ["remote-team-a"]
        assert "caller-team-x" not in remote_principal.teams
        assert request.state.token_teams == ["remote-team-a"]

    @pytest.mark.asyncio
    async def test_agent_on_remote_team_b_returns_404(self, monkeypatch, calling_db, remote_db):
        """Caller mapped only to remote Team-A; agent on remote Team-B -> 404."""
        payload = _forwarded_payload()

        # The call chain: authenticate on the calling gateway (team-x), then
        # the remote gateway re-authenticates the forwarded bearer (team-a).
        caller, _ = await _authenticate_on_gateway(monkeypatch, calling_db, payload)
        assert caller.teams == ["caller-team-x"]
        remote_principal, _ = await _authenticate_on_gateway(monkeypatch, remote_db, payload)

        service = A2AAgentService()
        agent_b = remote_db.get(DbA2AAgent, "agent-team-b")
        public_agent = remote_db.get(DbA2AAgent, "agent-public")

        # Direct check: Team-B agent denied, public agent allowed.
        assert await service._check_agent_access(remote_db, agent_b, remote_principal.email, remote_principal.teams) is False
        assert await service._check_agent_access(remote_db, public_agent, remote_principal.email, remote_principal.teams) is True

        # Route-level semantics: 404 for the Team-B agent, 200 path for public.
        service.convert_agent_to_read = lambda db_agent, **kwargs: AGENT_OK
        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(remote_db, "agent-team-b", user_email=remote_principal.email, token_teams=remote_principal.teams)
        assert await service.get_agent(remote_db, "agent-public", user_email=remote_principal.email, token_teams=remote_principal.teams) is AGENT_OK
