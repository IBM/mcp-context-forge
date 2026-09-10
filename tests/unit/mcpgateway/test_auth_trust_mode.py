# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_trust_mode.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Trust-mode funnel branch tests (issue #5900).

The trust-eligible branch in get_current_user authenticates a
``token_use="trusted"`` token from its claims alone: the local user-record
lookup, the ``is_active`` check, the UUID->email seam, and DB team
resolution are skipped. The revocation check on the configured revocation
claim (default ``jti``) is retained.

The smoke-level SQL-listener test asserts that the trust path issues zero
SELECTs against ``email_users``. The full no-user-table proof is the
acceptance suite (#5905).
"""

# Standard
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailUser

CALLER_ID = "trust-subject-0001"
CALLER_EMAIL = "trust.user@example.com"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture
def db():
    """In-memory SQLite session with one non-personal team and no users.

    The principal exists only in the token claims; the database must not be
    consulted for a user record on the trust path.
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


def _trust_payload(**overrides):
    """Gateway-signed trust-token payload with the mapped claim set."""
    payload = {
        "sub": CALLER_ID,
        "token_use": "trusted",
        "email": CALLER_EMAIL,
        "teams": ["team-a"],
        "roles": [],
        "jti": "trusted_jti_smoke",
        "exp": _exp(),
    }
    payload.update(overrides)
    return payload


async def _drive_trust_funnel(monkeypatch: pytest.MonkeyPatch, db, payload, *, revoked: bool = False):
    """Drive get_current_user with the given payload on the trust path.

    Returns (user, request). Raises whatever the funnel raises.
    """
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
    _patch_funnel_sessions(monkeypatch, db)

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret
    request = SimpleNamespace(state=SimpleNamespace())

    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
        with patch("mcpgateway.auth._check_token_revoked_sync", return_value=revoked):
            # Fail the test loudly if the trust path touches the user table
            # through the default-funnel helpers.
            with patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("user lookup on trust path")):
                user = await get_current_user(credentials=credentials, request=request)
    return user, request


class TestTrustBranchSmoke:
    """Happy-path and request.state shape for the trust branch."""

    @pytest.mark.asyncio
    async def test_trust_token_authenticates_from_claims(self, monkeypatch, db):
        """Claims-derived principal: email, teams, roles; request.state set."""
        user, request = await _drive_trust_funnel(monkeypatch, db, _trust_payload(roles=["developer"]))

        assert user.user_id == CALLER_ID
        assert user.email == CALLER_EMAIL
        assert user.token_use == "trusted"
        assert request.state.token_use == "trusted"
        assert request.state.token_teams == ["team-a"]
        assert request.state.auth_method == "jwt"
        assert request.state.jti == "trusted_jti_smoke"

    @pytest.mark.asyncio
    async def test_trust_path_issues_zero_email_users_selects(self, monkeypatch, db):
        """Smoke-level proof: no SELECT against email_users on the trust path.

        A SQL listener on the test engine records every statement; the full
        no-user-table proof is the acceptance suite (#5905).
        """
        statements: list[str] = []
        engine = db.get_bind()

        def _listener(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        sa.event.listen(engine, "before_cursor_execute", _listener)
        try:
            await _drive_trust_funnel(monkeypatch, db, _trust_payload())
        finally:
            sa.event.remove(engine, "before_cursor_execute", _listener)

        user_table_reads = [stmt for stmt in statements if "email_users" in stmt]
        assert user_table_reads == []


class TestTrustBranchDeny:
    """Failure semantics: revocation and claim completeness fail closed."""

    @pytest.mark.asyncio
    async def test_revoked_trust_token_rejected(self, monkeypatch, db):
        """Revoked revocation-claim identifier -> 401 even in trust mode."""
        with pytest.raises(HTTPException) as exc_info:
            await _drive_trust_funnel(monkeypatch, db, _trust_payload(), revoked=True)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_missing_revocation_claim_rejected(self, monkeypatch, db):
        """A trust-eligible token without the configured revocation claim -> 401."""
        payload = _trust_payload()
        del payload["jti"]
        with pytest.raises(HTTPException) as exc_info:
            await _drive_trust_funnel(monkeypatch, db, payload)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_missing_user_id_claim_rejected(self, monkeypatch, db):
        """A trust-eligible token without the mapped user_id claim -> 401 (not fail-open)."""
        payload = _trust_payload()
        del payload["sub"]
        with pytest.raises(HTTPException) as exc_info:
            await _drive_trust_funnel(monkeypatch, db, payload)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_trusted_marker_rejected_when_trust_mode_off(self, monkeypatch, db):
        """token_use=trusted with trust mode OFF -> 401; the default funnel never sees it."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _patch_funnel_sessions(monkeypatch, db)

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret
        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=_trust_payload())):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_overage_marker_fail_closed_rejected(self, monkeypatch, db):
        """Entra overage marker + default fail_closed policy -> 401."""
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "fail_closed")
        payload = _trust_payload(_claim_names={"groups": "src1"})
        with pytest.raises(HTTPException) as exc_info:
            await _drive_trust_funnel(monkeypatch, db, payload)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_overage_marker_proceed_without_groups(self, monkeypatch, db):
        """Entra overage marker + proceed_without_groups -> authenticates, no group teams."""
        monkeypatch.setattr(settings, "jwt_trust_overage_policy", "proceed_without_groups")
        payload = _trust_payload(_claim_names={"groups": "src1"})
        user, request = await _drive_trust_funnel(monkeypatch, db, payload)
        assert user.user_id == CALLER_ID
        # Claim teams still apply; no group-derived teams are added.
        assert request.state.token_teams == ["team-a"]

    @pytest.mark.asyncio
    async def test_tampered_token_rejected_before_trust_branch(self, monkeypatch, db):
        """A token with an invalid signature never reaches claims extraction.

        The real verifier runs first; a token signed with the wrong secret is
        rejected with 401 before the trust branch reads any claim.
        """
        # First-Party
        from tests.helpers.auth import make_trusted_test_jwt

        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _patch_funnel_sessions(monkeypatch, db)

        forged = make_trusted_test_jwt(CALLER_ID, email=CALLER_EMAIL, teams=["team-a"], secret="wrong-secret-that-is-long-enough-32")  # pragma: allowlist secret
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=forged)  # pragma: allowlist secret

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
