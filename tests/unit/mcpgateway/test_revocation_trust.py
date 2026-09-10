# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_revocation_trust.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Trust-mode revocation persistence tests (issue #5901).

Trust-mode principals have no local user row, so the historical
``TokenRevocation.revoked_by`` foreign key to ``email_users.email``
(NOT NULL) made every trust-initiated revocation insert fail. The
idle-timeout path then swallowed the error and the revocation silently
never landed. These tests pin the fixed contract:

  * trust-mode logout writes a revocation row keyed by the canonical
    user_id of the virtual principal,
  * the same revocation identifier is rejected with 401 on the next
    request through the REAL revocation check (no mock),
  * an idle-timeout revocation persists even when the identity is a
    synthetic principal with no ``email_users`` row.
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
from mcpgateway.db import Base, TokenRevocation
from mcpgateway.routers.auth import logout
from mcpgateway.utils.trusted_claims import VirtualPrincipal

CALLER_ID = "trust-subject-0001"
LOGOUT_JTI = "trusted-logout-jti-0001"
IDLE_JTI = "idle-revoke-jti-0001"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture
def db():
    """In-memory SQLite session with the full schema and no user rows.

    Trust-mode principals exist only in token claims; no ``email_users``
    row backs them, which is exactly the shape that broke the old FK.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    # SQLite does not enforce foreign keys by default; PostgreSQL does.
    # Enforce them so this fixture reproduces the production failure mode.
    @sa.event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _patch_sessions(monkeypatch: pytest.MonkeyPatch, db) -> None:
    """Re-point funnel and blocklist-service sessions at the test database."""
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
    monkeypatch.setattr("mcpgateway.services.token_blocklist_service.fresh_db_session", _fresh_db_session)


def _revocation_row(db, jti: str):
    """Return the TokenRevocation row for jti, or None."""
    return db.execute(sa.select(TokenRevocation).where(TokenRevocation.jti == jti)).scalar_one_or_none()


async def _trust_logout(db, jti: str = LOGOUT_JTI) -> dict:
    """Drive the logout endpoint as a trust-mode principal with no email claim."""
    # First-Party
    from tests.helpers.auth import make_trusted_test_jwt

    token = make_trusted_test_jwt(CALLER_ID, revocation_id=jti)
    principal = VirtualPrincipal(user_id=CALLER_ID, email=None)
    request = SimpleNamespace(headers={"authorization": f"Bearer {token}"})
    return await logout(request=request, current_user=principal, db=db)


class TestTrustModeLogoutRevocation:
    """Trust-mode logout persists a revocation row despite no user record."""

    @pytest.mark.asyncio
    async def test_trust_mode_logout_writes_revocation_row(self, db):
        """Logout stores the canonical user_id, not an email FK reference."""
        result = await _trust_logout(db)

        assert result["revoked_token"] == LOGOUT_JTI
        row = _revocation_row(db, LOGOUT_JTI)
        assert row is not None
        assert row.revoked_by == CALLER_ID
        assert row.reason == "logout"

    @pytest.mark.asyncio
    async def test_same_jti_rejected_after_trust_logout(self, monkeypatch, db):
        """After logout, the same jti yields 401 via the real revocation check."""
        await _trust_logout(db)
        assert _revocation_row(db, LOGOUT_JTI) is not None

        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _patch_sessions(monkeypatch, db)

        payload = {
            "sub": CALLER_ID,
            "token_use": "trusted",
            "teams": [],
            "roles": [],
            "jti": LOGOUT_JTI,
            "exp": _exp(),
        }
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret
        request = SimpleNamespace(state=SimpleNamespace())

        # NOTE: _check_token_revoked_sync is deliberately NOT patched — the
        # real check must find the persisted row.
        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, request=request)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestIdleTimeoutRevocation:
    """Idle-timeout revoke persists; insert failures are never swallowed."""

    @pytest.mark.asyncio
    async def test_idle_timeout_revoke_persists(self, monkeypatch, db):
        """Synthetic principal (platform admin, no DB row): revocation row lands."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        monkeypatch.setattr(settings, "token_idle_timeout", 5)
        _patch_sessions(monkeypatch, db)

        old_activity = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
        payload = {
            "sub": settings.platform_admin_email,
            "jti": IDLE_JTI,
            "last_activity": old_activity,
            "exp": _exp(),
        }
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="idle_session_token")  # pragma: allowlist secret

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, request=SimpleNamespace(state=SimpleNamespace()))

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        row = _revocation_row(db, IDLE_JTI)
        assert row is not None
        assert row.revoked_by == settings.platform_admin_email
        assert row.reason == "idle_timeout"
