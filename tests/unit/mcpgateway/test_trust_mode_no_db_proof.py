# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_mode_no_db_proof.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

NO-DB PROOF acceptance suite for JWT trust mode (issue #5905, suite a).

A SQLAlchemy event listener on the test engine records every statement
executed while 60 (>= 50) authenticated trust-mode requests pass through
``get_current_user``. The assertion runs on the executed SQL, not on source
text: ZERO ``SELECT`` statements against ``email_users`` are allowed. The
database holds a real ``email_users`` row for the caller's email, so a
user-table read would be observable if the trust path regressed.

The revocation check, the roles-table lookup, the external-group resolver,
and the team lookups are part of the trust path and DO run against their own
tables; the listener proves the only table that must stay unread is
``email_users``.



CI-eligible: in-memory SQLite only; no Docker, no Redis, no network.
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
from mcpgateway.db import Base, EmailTeam, EmailUser, ExternalGroupMapping, Role
from mcpgateway.utils.trusted_claims import VirtualPrincipal

CALLER_EMAIL = "trust.user@example.com"
ISSUER = "https://idp.example.com"

#: The acceptance contract requires at least 50 authenticated requests.
REQUEST_COUNT = 60


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture
def db():
    """In-memory SQLite session with FK enforcement and a seeded user row.

    The caller's ``email_users`` row exists on purpose: the proof is only
    meaningful when a user-table read would return data if it happened.

    Yields:
        Session bound to the in-memory engine.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    # Match production (PostgreSQL) FK enforcement so seeded rows must be
    # referentially valid.
    @sa.event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    now = datetime.now(timezone.utc)
    owner = EmailUser(
        email=CALLER_EMAIL,
        password_hash="hash",  # pragma: allowlist secret
        full_name="Trust User",
        is_admin=False,
        is_active=True,
        email_verified_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(owner)
    # Commit parents before children: ExternalGroupMapping has a foreign key
    # to email_teams without an ORM relationship, so the unit-of-work sorter
    # cannot see the dependency and might insert the mapping first.
    session.add(EmailTeam(id="team-a", name="CF-Team-A", slug="cf-team-a", created_by=owner.email, is_personal=False, visibility="private"))
    session.commit()
    session.add(
        Role(
            id="role-developer",
            name="developer",
            description="Developer role",
            scope="global",
            permissions=["tools.read"],
            created_by=owner.email,
            is_system_role=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(ExternalGroupMapping(issuer=ISSUER, tenant=None, external_group_id="ext-group-1", cf_team_id="team-a", cf_role="developer"))
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


def _trust_payload(index: int) -> dict:
    """Trust-token payload for request ``index``; claim shapes vary per request.

    Every request carries a unique ``jti`` so the revocation check does real
    work. Claim shapes rotate across: teams claim + role claim, external
    groups through the mapping resolver, and a minimal email-less token.
    """
    base = {
        "sub": f"trust-subject-{index:04d}",
        "token_use": "trusted",
        "iss": ISSUER,
        "jti": f"no-db-proof-jti-{index:04d}",
        "exp": _exp(),
    }
    shape = index % 3
    if shape == 0:
        base.update({"email": CALLER_EMAIL, "teams": ["team-a"], "roles": ["developer"]})
    elif shape == 1:
        base.update({"email": CALLER_EMAIL, "groups": ["ext-group-1"], "roles": []})
    else:
        # Minimal token: no email, no teams, no groups; the subject backs the
        # email attribute and teams resolve to [].
        base.update({"roles": []})
    return base


def _default_payload(index: int) -> dict:
    """Legacy default-mode payload (``sub`` = email) for request ``index``."""
    return {"sub": CALLER_EMAIL, "jti": f"default-mode-jti-{index:04d}", "exp": _exp()}


async def _drive(payload: dict):
    """Drive one authenticated request through get_current_user.

    The JWT verifier is patched (signature verification is covered
    elsewhere); every layer below it — dispatch, claim extraction, group
    resolution, revocation check, team derivation — runs for real against
    the test database.

    Returns:
        Tuple of (user, request).
    """
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt_token")  # pragma: allowlist secret
    request = SimpleNamespace(state=SimpleNamespace())
    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
        user = await get_current_user(credentials=credentials, request=request)
    return user, request


def _configure(monkeypatch: pytest.MonkeyPatch, db, *, mode: str) -> None:
    """Point the funnel at the test database in the given trust mode."""
    monkeypatch.setattr(settings, "jwt_trust_mode", mode)
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
    _patch_funnel_sessions(monkeypatch, db)


class TestNoDbProof:
    """Zero SELECTs against email_users across 50+ trust-mode requests."""

    @pytest.mark.asyncio
    async def test_zero_email_users_selects_across_50plus_trust_requests(self, monkeypatch, db):
        """60 authenticated trust-mode requests, zero email_users SELECTs.

        The SQL listener runs on the engine while every request executes;
        non-email_users tables (token_revocations, roles,
        external_group_mappings, email_teams) are expected to be read.
        """
        _configure(monkeypatch, db, mode="jwt-trust")

        # Warmup: settle one-time costs (imports, blocklist Redis probe)
        # before the measured, listener-covered run.
        for i in range(5):
            await _drive(_trust_payload(i))

        statements: list[str] = []
        engine = db.get_bind()

        def _listener(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        sa.event.listen(engine, "before_cursor_execute", _listener)
        try:
            for i in range(REQUEST_COUNT):
                payload = _trust_payload(i)
                user, request = await _drive(payload)
                # Every request must have authenticated on the trust path —
                # a silent 401 would make the zero-SELECT count meaningless.
                assert isinstance(user, VirtualPrincipal), f"request {i} did not resolve a trust principal"
                assert user.user_id == payload["sub"]
                assert request.state.token_use == "trusted"
        finally:
            sa.event.remove(engine, "before_cursor_execute", _listener)

        # Guard against a vacuous pass: the listener must have seen the trust
        # path's legitimate reads (roles / mappings / teams / revocations).
        assert statements, "SQL listener recorded nothing; the proof would be vacuous"

        email_users_reads = [stmt for stmt in statements if "email_users" in stmt]
        assert email_users_reads == [], f"trust path read the user table: {email_users_reads[:3]}"
