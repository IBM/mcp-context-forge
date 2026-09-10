# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_mode_overage_degraded.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Overage-degraded acceptance suite for JWT trust mode (issue #5905, suite e).

An Entra trust token that exceeds the group-claim limit carries overage
markers instead of the groups claim. With
``jwt_trust_overage_policy=proceed_without_groups`` the token authenticates
with NO group-derived teams — a coherent degradation, never a silent
security bypass:

- the resolved principal has ``token_teams == []`` (public-only),
- a WARNING-level log carrying the user's ``oid`` is emitted on every
  overage-triggered request,
- ``visibility=team`` agents return 404 via ``_check_agent_access`` (the
  route maps ``A2AAgentNotFoundError`` to HTTP 404; see
  ``mcpgateway/main.py`` ``get_a2a_agent``),
- ``visibility=public`` agents stay reachable (200 path).

All three Entra overage marker shapes are exercised: ``_claim_names``,
``hasgroups``, and ``groups:srcN``.
"""

# Standard
import contextlib
from datetime import datetime, timedelta, timezone
import logging
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
from mcpgateway.db import Base, EmailTeam, EmailUser
from mcpgateway.services.a2a_service import A2AAgentNotFoundError, A2AAgentService

CALLER_ID = "trust-overage-subject-0001"
CALLER_EMAIL = "overage.user@example.com"
CALLER_OID = "oid-overage-0001"
AGENT_OK = object()  # sentinel for the convert_agent_to_read patch

#: The three Entra overage marker shapes (groups claim omitted).
OVERAGE_MARKERS = [
    {"_claim_names": {"groups": "src1"}},
    {"hasgroups": True},
    {"groups:src1": "https://graph.microsoft.com/oid"},  # noqa: S105 - marker key, not a credential
]


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture
def db():
    """In-memory SQLite session with one team agent and one public agent.

    Yields:
        Session bound to the in-memory engine.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    now = datetime.now(timezone.utc)
    session.add(
        EmailUser(
            email="owner@example.com",
            password_hash="hash",  # pragma: allowlist secret
            full_name="Owner",
            is_admin=False,
            is_active=True,
            email_verified_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(EmailTeam(id="team-x", name="CF-Team-X", slug="cf-team-x", created_by="owner@example.com", is_personal=False, visibility="private"))
    session.commit()
    session.add(
        DbA2AAgent(
            id="agent-team",
            name="team-agent",
            slug="team-agent",
            endpoint_url="https://team.example.com/agent",
            visibility="team",
            team_id="team-x",
            enabled=True,
        )
    )
    session.add(
        DbA2AAgent(
            id="agent-public",
            name="public-agent",
            slug="public-agent",
            endpoint_url="https://public.example.com/agent",
            visibility="public",
            enabled=True,
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _patch_funnel_sessions(monkeypatch: pytest.MonkeyPatch, db) -> None:
    """Re-point the funnel's internal sessions at the test database."""
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


def _overage_payload(marker: dict) -> dict:
    """Trust-token payload with one Entra overage marker shape; no groups claim."""
    payload = {
        "sub": CALLER_ID,
        "oid": CALLER_OID,
        "token_use": "trusted",
        "email": CALLER_EMAIL,
        "roles": [],
        "jti": "overage-degraded-jti-0001",
        "exp": _exp(),
    }
    payload.update(marker)
    return payload


async def _drive_overage(monkeypatch: pytest.MonkeyPatch, db, marker: dict):
    """Authenticate one overage-marked trust token; return (user, request)."""
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr(settings, "jwt_trust_overage_policy", "proceed_without_groups")
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
    _patch_funnel_sessions(monkeypatch, db)

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt_token")  # pragma: allowlist secret
    request = SimpleNamespace(state=SimpleNamespace())
    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=_overage_payload(marker))):
        user = await get_current_user(credentials=credentials, request=request)
    return user, request


class TestOverageDegraded:
    """proceed_without_groups: authenticated, public-only, WARNING with oid."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("marker", OVERAGE_MARKERS, ids=["claim_names", "hasgroups", "groups_srcN"])
    async def test_overage_degrades_to_empty_teams_with_warning(self, monkeypatch, db, caplog, marker):
        """Each marker shape: token_teams == [] and a WARNING carrying the oid."""
        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.trusted_claims"):
            user, request = await _drive_overage(monkeypatch, db, marker)

        # Authenticated, but with no group-derived teams (public-only).
        assert user.user_id == CALLER_ID
        assert user.teams == []
        assert request.state.token_teams == []

        # The degradation is observable: WARNING with the user's oid.
        warning_messages = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert any(CALLER_OID in message and "overage" in message.lower() for message in warning_messages), (
            f"no overage WARNING with oid emitted; got: {warning_messages}"
        )

    @pytest.mark.asyncio
    async def test_team_agent_404_public_agent_200(self, monkeypatch, db, caplog):
        """The degraded principal: team agents 404, public agents 200.

        ``get_agent`` raises ``A2AAgentNotFoundError`` (404 at the route)
        when ``_check_agent_access`` denies; the public agent passes the
        same check.
        """
        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.trusted_claims"):
            user, _request = await _drive_overage(monkeypatch, db, OVERAGE_MARKERS[0])

        service = A2AAgentService()
        team_agent = db.get(DbA2AAgent, "agent-team")
        public_agent = db.get(DbA2AAgent, "agent-public")

        # Direct check: _check_agent_access denies team, allows public.
        assert await service._check_agent_access(db, team_agent, user.email, user.teams) is False
        assert await service._check_agent_access(db, public_agent, user.email, user.teams) is True

        # Route-level semantics: team agent -> 404, public agent -> 200 path.
        service.convert_agent_to_read = lambda db_agent, **kwargs: AGENT_OK
        with pytest.raises(A2AAgentNotFoundError):
            await service.get_agent(db, "agent-team", user_email=user.email, token_teams=user.teams)
        assert await service.get_agent(db, "agent-public", user_email=user.email, token_teams=user.teams) is AGENT_OK
