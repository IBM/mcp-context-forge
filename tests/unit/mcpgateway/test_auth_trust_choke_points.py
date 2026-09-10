# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_trust_choke_points.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Secondary auth choke points in JWT trust mode (#5904).

- ``validate_token_user``: trust-mode tokens return the trust-mode principal
  (``token_use="trusted"``) through the same shared validation path.
- ``HTTP_AUTH_RESOLVE_USER`` plugin hook: fail-closed default — the hook is
  disabled in trust mode with a clear log line; a registered hook is never
  invoked. In default mode the hook is consulted as before.
"""

# Standard
import contextlib
from datetime import datetime, timedelta, timezone
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user, TokenValidationError, validate_token_user
from mcpgateway.config import settings
from mcpgateway.db import Base

CALLER_ID = "trust-subject-0007"
CALLER_EMAIL = "choke.point@example.com"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


@pytest.fixture
def db():
    """In-memory SQLite session with the full schema and no users."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
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
        "jti": "trusted_jti_choke",
        "exp": _exp(),
    }
    payload.update(overrides)
    return payload


def _enable_trust_mode(monkeypatch: pytest.MonkeyPatch, db) -> None:
    """Switch the funnel to trust mode against the test database."""
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr(settings, "auth_cache_enabled", False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
    _patch_funnel_sessions(monkeypatch, db)


class TestValidateTokenUserTrustMode:
    """validate_token_user handles trust-mode principals (documented return)."""

    @pytest.mark.asyncio
    async def test_trust_mode_token_returns_trust_principal(self, monkeypatch, db):
        """A trust-eligible token passes validate_token_user and returns the principal."""
        _enable_trust_mode(monkeypatch, db)
        request = SimpleNamespace(state=SimpleNamespace())

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=_trust_payload())):
            with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                user = await validate_token_user(request, "trusted_jwt_token")  # pragma: allowlist secret

        assert user.user_id == CALLER_ID
        assert user.email == CALLER_EMAIL
        assert user.token_use == "trusted"

    @pytest.mark.asyncio
    async def test_trusted_marker_rejected_when_trust_mode_off(self, monkeypatch, db):
        """token_use=trusted with trust mode OFF -> TokenValidationError 401."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _patch_funnel_sessions(monkeypatch, db)
        request = SimpleNamespace(state=SimpleNamespace())

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=_trust_payload())):
            with pytest.raises(TokenValidationError) as exc_info:
                await validate_token_user(request, "trusted_jwt_token")  # pragma: allowlist secret

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


class TestPluginHookTrustMode:
    """HTTP_AUTH_RESOLVE_USER is disabled in trust mode (fail-closed default)."""

    def _plugin_manager_mock(self):
        """Plugin manager with a registered HTTP_AUTH_RESOLVE_USER hook."""
        manager = MagicMock()
        manager.has_hooks_for = MagicMock(return_value=True)
        manager.invoke_hook = AsyncMock()
        return manager

    @pytest.mark.asyncio
    async def test_hook_not_invoked_in_trust_mode(self, monkeypatch, db, caplog):
        """Trust mode ON: registered hook is skipped; the clear log line is present."""
        _enable_trust_mode(monkeypatch, db)
        manager = self._plugin_manager_mock()
        request = SimpleNamespace(state=SimpleNamespace())
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret

        with patch("mcpgateway.auth.get_plugin_manager", AsyncMock(return_value=manager)):
            with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=_trust_payload())):
                with patch("mcpgateway.auth._check_token_revoked_sync", return_value=False):
                    with caplog.at_level(logging.INFO, logger="mcpgateway.auth"):
                        user = await get_current_user(credentials=credentials, request=request)

        manager.invoke_hook.assert_not_called()
        assert user.user_id == CALLER_ID
        assert "HTTP_AUTH_RESOLVE_USER hook disabled in trust mode" in caplog.text

    @pytest.mark.asyncio
    async def test_hook_invoked_in_default_mode(self, monkeypatch, db):
        """Default mode: the registered hook is consulted before standard auth."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        _patch_funnel_sessions(monkeypatch, db)

        manager = self._plugin_manager_mock()
        # Hook declines to authenticate: fall through to standard auth.
        auth_result = MagicMock()
        auth_result.modified_payload = None
        auth_result.metadata = {}
        manager.invoke_hook = AsyncMock(return_value=(auth_result, None))

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="default_jwt_token")  # pragma: allowlist secret
        request = SimpleNamespace(state=SimpleNamespace())

        with patch("mcpgateway.auth.get_plugin_manager", AsyncMock(return_value=manager)):
            with patch(
                "mcpgateway.auth.verify_jwt_token_cached",
                AsyncMock(side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_user(credentials=credentials, request=request)

        manager.invoke_hook.assert_called_once()
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
