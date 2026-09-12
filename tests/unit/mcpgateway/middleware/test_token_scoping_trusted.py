# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_token_scoping_trusted.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Trust-aware TokenScopingMiddleware regression tests (#5904, finding F3).

A ``token_use="trusted"`` token carries teams derived at authentication
time by the external group-mapping resolver (``auth.py`` trust branch /
``TokenCatalogService.mint_trust_token``). Trust-only principals have no
local ``email_team_members`` rows, so the Layer-1 membership re-check —
designed for API/legacy tokens whose embedded teams claim may be stale —
denied every team-scoped trusted token with
``403 'User is no longer a member of the associated team'``.

These tests pin the fixed contract:

  * trusted token + trust mode ON -> the resolver-derived teams survive
    Layer-1 scoping without an ``email_team_members`` lookup,
  * a revoked trusted token is still denied (revocation is enforced by
    the auth layer on every request and is NOT weakened by the skip),
  * trusted token + trust mode OFF -> the membership check still applies
    (feature-disabled boundary; the auth layer rejects it with 401),
  * API/legacy tokens still validate membership against the local rows
    (behavior unchanged).
"""

# Standard
import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import Base, TokenRevocation
from mcpgateway.middleware.token_scoping import ResourceOwnershipResult, TokenScopingMiddleware

TRUSTED_SUBJECT = "entra-sub-123"
TRUSTED_JTI = "trusted-jti-0001"
MAPPED_TEAM = "agent-a-team"


def _exp(hours: int = 1) -> float:
    """Expiry timestamp for mocked JWT payloads."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


def _trusted_payload() -> dict:
    """Trusted-token payload as verified by ``verify_jwt_token_cached``."""
    return {
        "sub": TRUSTED_SUBJECT,
        "token_use": "trusted",  # nosec B105 - JWT claim type, not a password
        "teams": [MAPPED_TEAM],
        "roles": ["developer"],
        "jti": TRUSTED_JTI,
        "exp": _exp(),
        "scopes": {"permissions": ["*"]},
    }


@pytest.fixture
def middleware():
    """Create middleware instance."""
    return TokenScopingMiddleware()


@pytest.fixture
def mock_request():
    """Create mock request object (harness mirrors test_token_scoping.py)."""
    request = MagicMock(spec=Request)
    request.url.path = "/servers"
    request.method = "GET"
    request.headers = {"Authorization": "Bearer trusted-token"}  # pragma: allowlist secret
    request.cookies = {}
    request.scope = {"path": "/servers", "root_path": ""}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.state = MagicMock()
    request.state._token_scoping_done = False
    return request


async def _run_scoping(middleware, mock_request, monkeypatch, payload):
    """Drive the full middleware with a DB session whose membership lookup fails.

    ``validate_token_team_membership`` returns False, simulating ZERO
    ``email_team_members`` rows for the principal — the trust-only shape.
    Returns (response_or_result, call_next, membership_validator_mock).
    """
    db = MagicMock()
    monkeypatch.setattr("mcpgateway.db.get_db", lambda: iter([db]))
    with (
        patch.object(middleware, "_extract_token_scopes", new=AsyncMock(return_value=payload)),
        patch("mcpgateway.middleware.token_scoping.validate_token_team_membership", return_value=False) as validator,
        patch.object(middleware, "_check_resource_team_ownership", return_value=ResourceOwnershipResult.ALLOWED),
    ):
        call_next = AsyncMock(return_value="success")
        result = await middleware(mock_request, call_next)
    return result, call_next, validator


class TestTrustedTokenTeamScoping:
    """Trusted tokens skip the local email_team_members re-check."""

    @pytest.mark.asyncio
    async def test_trusted_token_teams_skip_local_membership_check(self, middleware, mock_request, monkeypatch):
        """Resolver-derived teams survive Layer-1 scoping with zero membership rows."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")

        result, call_next, validator = await _run_scoping(middleware, mock_request, monkeypatch, _trusted_payload())

        assert result == "success"
        call_next.assert_called_once()
        # The local membership lookup must not run for trusted tokens: the
        # group-mapping resolver already verified the mapped teams at
        # authentication time.
        validator.assert_not_called()

    @pytest.mark.asyncio
    async def test_trusted_token_with_trust_mode_off_still_checks_membership(self, middleware, mock_request, monkeypatch):
        """Feature-disabled boundary: trust mode OFF keeps the membership check."""
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")

        result, call_next, validator = await _run_scoping(middleware, mock_request, monkeypatch, _trusted_payload())

        assert result.status_code == status.HTTP_403_FORBIDDEN
        call_next.assert_not_called()
        validator.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token_use", ["api", None])
    async def test_api_and_legacy_tokens_without_membership_still_denied(self, middleware, mock_request, monkeypatch, token_use):
        """API/legacy tokens with teams but no membership rows are still denied."""
        payload = _trusted_payload()
        if token_use is None:
            del payload["token_use"]
        else:
            payload["token_use"] = token_use  # nosec B105 - JWT claim type, not a password

        result, call_next, validator = await _run_scoping(middleware, mock_request, monkeypatch, payload)

        assert result.status_code == status.HTTP_403_FORBIDDEN
        call_next.assert_not_called()
        validator.assert_called_once()


class TestTrustedTokenRevocation:
    """Revocation stays active for trusted tokens (auth layer, real DB)."""

    @pytest.fixture
    def db(self):
        """In-memory SQLite session with the full schema and no user rows."""
        engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine)()
        try:
            yield session
        finally:
            session.close()

    def _patch_sessions(self, monkeypatch: pytest.MonkeyPatch, db) -> None:
        """Re-point funnel sessions at the test database."""
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

    @pytest.mark.asyncio
    async def test_trusted_token_with_revoked_jti_still_denied(self, middleware, mock_request, monkeypatch, db):
        """A trusted token whose jti is revoked is denied regardless of team handling.

        The revocation check lives in the auth layer (``get_current_user``
        trust branch), keyed by the configured revocation claim; the
        middleware skip must not weaken it. ``_check_token_revoked_sync``
        is deliberately NOT patched — the real check must find the row.
        """
        db.add(
            TokenRevocation(
                jti=TRUSTED_JTI,
                revoked_by="system:test",
                reason="security",
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        db.commit()

        monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
        monkeypatch.setattr(settings, "auth_cache_enabled", False)
        monkeypatch.setattr(settings, "auth_cache_batch_queries", False)
        self._patch_sessions(monkeypatch, db)

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="trusted_jwt_token")  # pragma: allowlist secret
        request = SimpleNamespace(state=SimpleNamespace())

        with patch("mcpgateway.auth.verify_jwt_token_cached", AsyncMock(return_value=_trusted_payload())):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=credentials, request=request)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
