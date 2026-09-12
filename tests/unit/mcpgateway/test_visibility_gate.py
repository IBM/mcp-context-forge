# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_visibility_gate.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Agent visibility-gate and end-to-end team-isolation tests for trust mode
(issue #5976).

Every test in this file exercises the trust branch in get_current_user, which
lands with #5900. Until then the default funnel rejects the trust-mode token
with 401 and each test fails, so all tests carry
pytest.mark.xfail(strict=True, reason="Requires trust branch from #5900").
strict=True turns a premature XPASS into a suite failure.

Visibility semantics under test (per _check_agent_access in
mcpgateway/services/a2a_service.py):
- visibility="team": allowed only when the agent team_id is in token_teams.
  A denied lookup raises A2AAgentNotFoundError: 404, not 403, so the gateway
  never leaks the existence of another team's agent.
- visibility="public": allowed for every authenticated caller, regardless of
  token_teams. The Layer-1 gate does not apply to public agents.
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
from mcpgateway.db import A2AAgent, Base, EmailTeam, EmailUser, ExternalGroupMapping
from mcpgateway.services.a2a_service import A2AAgentNotFoundError, A2AAgentService
from mcpgateway.utils.trusted_claims import resolve_external_groups_to_teams

ISSUER = "https://login.example.com/tenant-1/v2.0"
TENANT = "tenant-1"
CALLER = "trust.user@example.com"
XFAIL_REASON = "Requires trust branch from #5900"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture
def db():
    """In-memory SQLite session seeded with teams, agents, and one mapping row.

    Layout: CF-Team-A and CF-Team-B. Agent-A (visibility=team, team=CF-Team-A),
    Agent-B (visibility=team, team=CF-Team-B), Agent-Pub (visibility=public).
    One mapping row: Entra-Group-GUID-1 -> CF-Team-A with cf_role=developer.
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
    session.add(EmailTeam(id="team-a", name="CF-Team-A", slug="cf-team-a", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(EmailTeam(id="team-b", name="CF-Team-B", slug="cf-team-b", created_by=owner.email, is_personal=False, visibility="private"))
    session.add(
        A2AAgent(
            name="agent-a",
            slug="agent-a",
            endpoint_url="https://agent-a.example.com",
            agent_type="generic",
            protocol_version="1.0",
            capabilities={},
            config={},
            enabled=True,
            team_id="team-a",
            owner_email=owner.email,
            visibility="team",
            tags=[],
        )
    )
    session.add(
        A2AAgent(
            name="agent-b",
            slug="agent-b",
            endpoint_url="https://agent-b.example.com",
            agent_type="generic",
            protocol_version="1.0",
            capabilities={},
            config={},
            enabled=True,
            team_id="team-b",
            owner_email=owner.email,
            visibility="team",
            tags=[],
        )
    )
    session.add(
        A2AAgent(
            name="agent-pub",
            slug="agent-pub",
            endpoint_url="https://agent-pub.example.com",
            agent_type="generic",
            protocol_version="1.0",
            capabilities={},
            config={},
            enabled=True,
            team_id=None,
            owner_email=owner.email,
            visibility="public",
            tags=[],
        )
    )
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=TENANT, external_group_id="entra-group-guid-1", cf_team_id="team-a", cf_role="developer"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


async def _drive_trust_funnel(monkeypatch: pytest.MonkeyPatch, db, groups: list[str]):
    """Drive get_current_user with a trust-mode JWT carrying the given groups.

    The funnel's internal sessions are re-pointed at the test database so the
    group resolver sees the seeded mapping rows. Returns (user, request).
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

    jwt_payload = {
        "sub": CALLER,
        "token_use": "trusted",
        "iss": ISSUER,
        "tid": TENANT,
        "groups": groups,
        "jti": "trusted_jti_visibility_gate",
        "exp": _exp(),
    }
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret
    request = SimpleNamespace(state=SimpleNamespace())

    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=jwt_payload)):
        with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
            # No local user record exists for the virtual principal.
            with patch("mcpgateway.auth._get_user_by_email_sync", return_value=None):
                with patch("mcpgateway.auth._get_personal_team_sync", return_value=None):
                    user = await get_current_user(credentials=credentials, request=request)
    return user, request


@pytest.mark.xfail(strict=True, reason=XFAIL_REASON)
class TestVisibilityGate:
    """AC-visibility-gate: team isolation and the public baseline."""

    @pytest.mark.asyncio
    async def test_team_visibility_isolation(self, monkeypatch, db):
        """Caller maps to CF-Team-A only: Agent-A 200, Agent-B 404.

        The denied lookup raises A2AAgentNotFoundError (404, not 403) per
        _check_agent_access, so agent existence never leaks across teams.
        """
        _, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-1"])
        token_teams = request.state.token_teams
        assert token_teams == ["team-a"]

        service = A2AAgentService()
        agent_a = db.query(A2AAgent).filter(A2AAgent.slug == "agent-a").one()
        agent_b = db.query(A2AAgent).filter(A2AAgent.slug == "agent-b").one()

        assert await service._check_agent_access(db, agent_a, CALLER, token_teams) is True
        assert await service._check_agent_access(db, agent_b, CALLER, token_teams) is False
        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(db, agent_b.id, user_email=CALLER, token_teams=token_teams)

    @pytest.mark.asyncio
    async def test_public_visibility_baseline(self, monkeypatch, db):
        """Public agents stay accessible to every authenticated caller.

        Documents the deliberate behavior that the Layer-1 team gate does
        not apply to visibility="public" agents.
        """
        _, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-1"])
        token_teams = request.state.token_teams

        service = A2AAgentService()
        agent_pub = db.query(A2AAgent).filter(A2AAgent.slug == "agent-pub").one()
        assert agent_pub.visibility == "public"
        assert await service._check_agent_access(db, agent_pub, CALLER, token_teams) is True


@pytest.mark.xfail(strict=True, reason=XFAIL_REASON)
class TestE2ETeamIsolation:
    """AC-e2e-team-isolation: mapping row + trust JWT drives the gate."""

    @pytest.mark.asyncio
    async def test_e2e_team_isolation(self, monkeypatch, db):
        """Full flow: teams, agents, mapping row, trust JWT, invoke gate.

        1. CF-Team-A and CF-Team-B exist; Agent-A (team=CF-Team-A) and
           Agent-B (team=CF-Team-B) are registered with visibility=team.
        2. Mapping row: Entra-Group-GUID-1 -> CF-Team-A, cf_role=developer.
        3. Trust-mode JWT carries groups=[Entra-Group-GUID-1].
        4. Agent-A is reachable; Agent-B answers 404 (A2AAgentNotFoundError).
        """
        # The resolver (landed in #5976) proves the mapping row translates
        # the external group into exactly one team and one role.
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["entra-group-guid-1"], db)
        assert team_ids == ["team-a"]
        assert role_names == ["developer"]

        _, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-1"])
        token_teams = request.state.token_teams
        assert token_teams == ["team-a"]

        service = A2AAgentService()
        agent_a = db.query(A2AAgent).filter(A2AAgent.slug == "agent-a").one()
        agent_b = db.query(A2AAgent).filter(A2AAgent.slug == "agent-b").one()

        assert await service._check_agent_access(db, agent_a, CALLER, token_teams) is True
        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(db, agent_b.id, user_email=CALLER, token_teams=token_teams)


@pytest.mark.xfail(strict=True, reason=XFAIL_REASON)
class TestE2ENoMapping:
    """AC-e2e-no-mapping: an unmapped group fails closed."""

    @pytest.mark.asyncio
    async def test_e2e_no_mapping_fail_closed(self, monkeypatch, db):
        """Trust JWT with an unmapped group: token_teams=[].

        A visibility=team agent answers 404; a visibility=public agent
        stays reachable.
        """
        team_ids, role_names = resolve_external_groups_to_teams(ISSUER, TENANT, ["entra-group-guid-unmapped"], db)
        assert team_ids == []
        assert role_names == []

        _, request = await _drive_trust_funnel(monkeypatch, db, ["entra-group-guid-unmapped"])
        token_teams = request.state.token_teams
        assert token_teams == []

        service = A2AAgentService()
        agent_a = db.query(A2AAgent).filter(A2AAgent.slug == "agent-a").one()
        agent_pub = db.query(A2AAgent).filter(A2AAgent.slug == "agent-pub").one()

        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(db, agent_a.id, user_email=CALLER, token_teams=token_teams)
        assert await service._check_agent_access(db, agent_pub, CALLER, token_teams) is True
