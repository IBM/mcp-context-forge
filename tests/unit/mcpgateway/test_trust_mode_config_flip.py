# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_mode_config_flip.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Config-flip acceptance suite for JWT trust mode (issue #5905, suite c).

Tokens behave per the dispatch rule in
``docs/docs/architecture/auth-token-dispatch.md`` (#5896) across mode
transitions:

- Default mode (``jwt_trust_mode="db"``): a legacy token follows the default
  funnel (user record from ``email_users``); a ``token_use="trusted"`` token
  is rejected with 401 — the marker never enters the default funnel.
- Trust mode (``jwt_trust_mode="jwt-trust"``): a ``token_use="trusted"``
  token authenticates from its claims alone (trust semantics); a legacy
  token still follows the default funnel — including the ``is_active``
  kill-switch, which trust mode deliberately does not have.
- Flip back to default mode: the trusted marker is 401 again; the legacy
  token authenticates again.

The mode is flipped on the live ``settings`` object inside one process, the
same way an operator flips ``JWT_TRUST_MODE`` between restarts.
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
from mcpgateway.utils.trusted_claims import VirtualPrincipal

CALLER_ID = "trust-flip-subject-0001"
CALLER_EMAIL = "flip.user@example.com"
LEGACY_EMAIL = "legacy.user@example.com"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture
def db():
    """In-memory SQLite session with one active user and one team.

    Yields:
        Session bound to the in-memory engine.
    """
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    now = datetime.now(timezone.utc)
    session.add(
        EmailUser(
            email=LEGACY_EMAIL,
            password_hash="hash",  # pragma: allowlist secret
            full_name="Legacy User",
            is_admin=False,
            is_active=True,
            email_verified_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.add(EmailTeam(id="team-a", name="CF-Team-A", slug="cf-team-a", created_by=LEGACY_EMAIL, is_personal=False, visibility="private"))
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
        "jti": "config-flip-trusted-jti",
        "exp": _exp(),
    }
    payload.update(overrides)
    return payload


def _legacy_payload(**overrides):
    """Legacy default-mode payload: ``sub`` = email, no ``token_use`` marker."""
    payload = {
        "sub": LEGACY_EMAIL,
        "jti": "config-flip-legacy-jti",
        "exp": _exp(),
    }
    payload.update(overrides)
    return payload


def _set_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """Flip the trust mode, with caches off so the flip takes effect at once."""
    monkeypatch.setattr(settings, "jwt_trust_mode", mode)
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)


async def _drive(payload: dict):
    """Drive one request through get_current_user with the given payload.

    Returns:
        Tuple of (user, request).

    Raises:
        HTTPException: Whatever the funnel raises.
    """
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt_token")  # pragma: allowlist secret
    request = SimpleNamespace(state=SimpleNamespace())
    with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=payload)):
        user = await get_current_user(credentials=credentials, request=request)
    return user, request


class TestDefaultMode:
    """jwt_trust_mode="db": the dispatch doc's default-mode rows."""

    @pytest.mark.asyncio
    async def test_legacy_token_follows_default_funnel(self, monkeypatch, db):
        """Default mode: legacy token resolves the user record from the DB."""
        _set_mode(monkeypatch, "db")
        _patch_funnel_sessions(monkeypatch, db)

        user, request = await _drive(_legacy_payload())

        # Default semantics: an EmailUser row, not a claims-derived principal.
        assert isinstance(user, EmailUser)
        assert not isinstance(user, VirtualPrincipal)
        assert user.email == LEGACY_EMAIL
        assert request.state.token_use is None

    @pytest.mark.asyncio
    async def test_trusted_marker_rejected(self, monkeypatch, db):
        """Default mode: token_use=trusted gets 401 and never enters the funnel."""
        _set_mode(monkeypatch, "db")
        _patch_funnel_sessions(monkeypatch, db)

        # Fail loudly if the marker slips past the dispatch rule into the
        # default funnel's user lookup.
        with patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("trusted marker entered the default funnel")):
            with pytest.raises(HTTPException) as exc_info:
                await _drive(_trust_payload())
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "trust mode" in exc_info.value.detail.lower()


class TestTrustMode:
    """jwt_trust_mode="jwt-trust": the dispatch doc's trust-mode rows."""

    @pytest.mark.asyncio
    async def test_trusted_token_trust_semantics(self, monkeypatch, db):
        """Trust mode: trusted token authenticates from its claims alone."""
        _set_mode(monkeypatch, "jwt-trust")
        _patch_funnel_sessions(monkeypatch, db)

        user, request = await _drive(_trust_payload())

        # Trust semantics: a claims-derived principal, no EmailUser row.
        assert isinstance(user, VirtualPrincipal)
        assert user.user_id == CALLER_ID
        assert user.email == CALLER_EMAIL
        assert request.state.token_use == "trusted"
        assert request.state.token_teams == ["team-a"]

    @pytest.mark.asyncio
    async def test_legacy_token_stays_on_default_funnel(self, monkeypatch, db):
        """Trust mode: a token without the marker follows the default funnel.

        The default funnel keeps the ``is_active`` kill-switch: disabling
        the user record rejects the token with 401 even in trust mode.
        """
        _set_mode(monkeypatch, "jwt-trust")
        _patch_funnel_sessions(monkeypatch, db)

        user, request = await _drive(_legacy_payload())
        assert isinstance(user, EmailUser)
        assert not isinstance(user, VirtualPrincipal)
        assert user.email == LEGACY_EMAIL
        assert request.state.token_use is None

        # Default semantics enforced: the is_active check runs on this path.
        legacy_user = db.query(EmailUser).filter(EmailUser.email == LEGACY_EMAIL).one()
        legacy_user.is_active = False
        db.commit()
        with pytest.raises(HTTPException) as exc_info:
            await _drive(_legacy_payload())
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc_info.value.detail == "Account disabled"


class TestFlipAcrossModes:
    """One process, both directions of the mode flip."""

    @pytest.mark.asyncio
    async def test_flip_default_to_trust_to_default(self, monkeypatch, db):
        """Tokens issued before the flip behave per the dispatch doc after it.

        Default -> trust: the legacy token keeps default semantics; the
        trusted marker becomes eligible. Trust -> default: the trusted
        marker is 401 again; the legacy token authenticates again.
        """
        _patch_funnel_sessions(monkeypatch, db)

        # Phase 1: default mode.
        _set_mode(monkeypatch, "db")
        with pytest.raises(HTTPException) as exc_info:
            await _drive(_trust_payload())
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        user, _ = await _drive(_legacy_payload())
        assert isinstance(user, EmailUser)

        # Phase 2: flip trust mode ON.
        _set_mode(monkeypatch, "jwt-trust")
        user, request = await _drive(_trust_payload())
        assert isinstance(user, VirtualPrincipal)
        assert request.state.token_use == "trusted"
        user, request = await _drive(_legacy_payload())
        assert isinstance(user, EmailUser)
        assert request.state.token_use is None

        # Phase 3: flip back to default mode.
        _set_mode(monkeypatch, "db")
        with pytest.raises(HTTPException) as exc_info:
            await _drive(_trust_payload())
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        user, _ = await _drive(_legacy_payload())
        assert isinstance(user, EmailUser)
        assert user.email == LEGACY_EMAIL
