# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_idle_timeout.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the idle-timeout enforcement block inside
``mcpgateway.auth.get_current_user``.

These tests exercise the activity-source precedence chain introduced by PR
#4371 (Redis ``token:activity:{jti}`` → JWT ``last_activity`` claim → JWT
``iat`` claim) and the four behaviour branches that flow from it:

* Recent activity → request passes, ``update_activity`` is called.
* Idle exceeded → token revoked + 401 raised.
* Idle exceeded with ``revoke_token`` raising → still 401.
* ``update_activity`` raising on a valid request → debug-log only.

The diff-coverage report after PR #4371's rebase showed lines 1615-1651 of
``mcpgateway/auth.py`` as uncovered. Each test below is named for the
specific branch it exercises so a future coverage regression is easy to
diagnose.
"""

# Standard
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import uuid

# Third-Party
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailUser
from mcpgateway.main import app


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_session_factory(test_engine):
    return sessionmaker(bind=test_engine)


@pytest.fixture
def client(test_engine, test_session_factory):
    from mcpgateway.routers.auth import get_db

    original_session_local = mcpgateway.db.SessionLocal
    original_engine = mcpgateway.db.engine
    mcpgateway.db.SessionLocal = test_session_factory
    mcpgateway.db.engine = test_engine

    def override_get_db():
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = test_session_factory()
    if not db.query(EmailUser).filter_by(email="idle-test@example.com").first():
        db.add(
            EmailUser(
                email="idle-test@example.com",
                password_hash="x",
                full_name="Idle Test",
                is_admin=False,
                is_active=True,
                auth_provider="local",
                email_verified_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    db.close()

    yield TestClient(app)

    app.dependency_overrides.clear()
    mcpgateway.db.SessionLocal = original_session_local
    mcpgateway.db.engine = original_engine


def _jwt_secret() -> str:
    secret = settings.jwt_secret_key
    return secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret


def _build_token(*, last_activity: int | None, iat_offset_minutes: int = 0, include_jti: bool = True) -> tuple[str, str]:
    """Build a signed session JWT with controllable claims.

    Args:
        last_activity: explicit ``last_activity`` claim value, or ``None`` to omit.
        iat_offset_minutes: subtracted from "now" to age ``iat``.
        include_jti: when ``False``, the token has no ``jti`` (skips the
            entire revocation+idle block).

    Returns:
        Tuple of (encoded JWT, jti).
    """
    now = datetime.now(timezone.utc)
    iat = now - timedelta(minutes=iat_offset_minutes)
    jti = str(uuid.uuid4())
    payload: dict = {
        "sub": "idle-test@example.com",
        "email": "idle-test@example.com",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(iat.timestamp()),
        "exp": int((now + timedelta(minutes=20)).timestamp()),
        "is_admin": False,
        "teams": [],
    }
    if include_jti:
        payload["jti"] = jti
    if last_activity is not None:
        payload["last_activity"] = last_activity
    token = jwt.encode(payload, _jwt_secret(), algorithm=settings.jwt_algorithm)
    return token, jti


@contextmanager
def _patched_settings(token_idle_timeout: int):
    """Patch ``mcpgateway.auth.settings`` to disable batching and set timeout.

    Yields:
        The mock ``settings`` object so individual tests can override more.
    """
    with patch("mcpgateway.auth.settings") as mock_settings:
        for attr in dir(settings):
            if attr.startswith("_"):
                continue
            try:
                setattr(mock_settings, attr, getattr(settings, attr))
            except AttributeError:
                pass
        mock_settings.token_idle_timeout = token_idle_timeout
        mock_settings.auth_cache_enabled = False
        mock_settings.auth_cache_batch_queries = False
        yield mock_settings


def _make_blocklist_mock(*, last_activity_returns=None, last_activity_raises=None, update_activity_raises=False, revoke_raises=False):
    """Construct a configurable ``TokenBlocklistService`` mock."""
    mock = MagicMock()
    if last_activity_raises is not None:
        mock.get_last_activity.side_effect = last_activity_raises
    else:
        mock.get_last_activity.return_value = last_activity_returns
    if update_activity_raises:
        mock.update_activity.side_effect = RuntimeError("redis dropped")
    else:
        mock.update_activity.return_value = True
    if revoke_raises:
        mock.revoke_token.side_effect = RuntimeError("blocklist write failed")
    else:
        mock.revoke_token.return_value = True
    return mock


class TestIdleTimeoutRedisHit:
    """Redis returns a usable ``last_activity`` value (line 1614 success branch)."""

    def test_recent_redis_activity_passes_and_refreshes(self, client):
        token, jti = _build_token(last_activity=None)
        recent = datetime.now(timezone.utc) - timedelta(minutes=5)
        mock_blocklist = _make_blocklist_mock(last_activity_returns=recent)

        with (
            _patched_settings(token_idle_timeout=60),
            patch(
                "mcpgateway.services.token_blocklist_service.get_token_blocklist_service",
                return_value=mock_blocklist,
            ),
        ):
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        mock_blocklist.get_last_activity.assert_called_once_with(jti)
        mock_blocklist.update_activity.assert_called_once_with(jti)

    def test_idle_exceeded_via_redis_revokes_and_returns_401(self, client):
        token, jti = _build_token(last_activity=None)
        old = datetime.now(timezone.utc) - timedelta(minutes=120)
        mock_blocklist = _make_blocklist_mock(last_activity_returns=old)

        with (
            _patched_settings(token_idle_timeout=60),
            patch(
                "mcpgateway.services.token_blocklist_service.get_token_blocklist_service",
                return_value=mock_blocklist,
            ),
        ):
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert "idle timeout" in response.json()["detail"].lower()
        mock_blocklist.revoke_token.assert_called_once()
        kwargs = mock_blocklist.revoke_token.call_args.kwargs
        assert kwargs["jti"] == jti
        assert kwargs["reason"] == "idle_timeout"


class TestIdleTimeoutJwtFallback:
    """Redis returns ``None`` → fallback to ``last_activity``/``iat`` JWT claim."""

    def test_jwt_last_activity_used_when_redis_returns_none_and_idle_exceeded(self, client):
        old_ts = int((datetime.now(timezone.utc) - timedelta(minutes=120)).timestamp())
        token, jti = _build_token(last_activity=old_ts)
        mock_blocklist = _make_blocklist_mock(last_activity_returns=None)

        with (
            _patched_settings(token_idle_timeout=60),
            patch(
                "mcpgateway.services.token_blocklist_service.get_token_blocklist_service",
                return_value=mock_blocklist,
            ),
        ):
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert "idle timeout" in response.json()["detail"].lower()
        mock_blocklist.revoke_token.assert_called_once()
        assert mock_blocklist.revoke_token.call_args.kwargs["jti"] == jti

    def test_iat_used_when_redis_none_and_no_last_activity_claim(self, client):
        token, jti = _build_token(last_activity=None, iat_offset_minutes=120)
        mock_blocklist = _make_blocklist_mock(last_activity_returns=None)

        with (
            _patched_settings(token_idle_timeout=60),
            patch(
                "mcpgateway.services.token_blocklist_service.get_token_blocklist_service",
                return_value=mock_blocklist,
            ),
        ):
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert "idle timeout" in response.json()["detail"].lower()


class TestIdleTimeoutErrorPaths:
    """Failure modes inside the idle-timeout block."""

    def test_redis_lookup_exception_falls_back_to_jwt_claim(self, client):
        old_ts = int((datetime.now(timezone.utc) - timedelta(minutes=120)).timestamp())
        token, _ = _build_token(last_activity=old_ts)
        mock_blocklist = _make_blocklist_mock(last_activity_raises=RuntimeError("redis down"))

        with (
            _patched_settings(token_idle_timeout=60),
            patch(
                "mcpgateway.services.token_blocklist_service.get_token_blocklist_service",
                return_value=mock_blocklist,
            ),
        ):
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert "idle timeout" in response.json()["detail"].lower()
        mock_blocklist.revoke_token.assert_called_once()

    def test_idle_exceeded_with_revoke_failure_still_returns_401(self, client):
        old_ts = int((datetime.now(timezone.utc) - timedelta(minutes=120)).timestamp())
        token, _ = _build_token(last_activity=old_ts)
        mock_blocklist = _make_blocklist_mock(last_activity_returns=None, revoke_raises=True)

        with (
            _patched_settings(token_idle_timeout=60),
            patch(
                "mcpgateway.services.token_blocklist_service.get_token_blocklist_service",
                return_value=mock_blocklist,
            ),
        ):
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
        assert "idle timeout" in response.json()["detail"].lower()

    def test_update_activity_failure_does_not_block_request(self, client):
        token, _ = _build_token(last_activity=None, iat_offset_minutes=5)
        mock_blocklist = _make_blocklist_mock(last_activity_returns=None, update_activity_raises=True)

        with (
            _patched_settings(token_idle_timeout=60),
            patch(
                "mcpgateway.services.token_blocklist_service.get_token_blocklist_service",
                return_value=mock_blocklist,
            ),
        ):
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        mock_blocklist.update_activity.assert_called_once()


class TestIdleTimeoutDisabled:
    """``token_idle_timeout = 0`` skips the entire block — no calls to the blocklist."""

    def test_idle_block_skipped_when_timeout_zero(self, client):
        token, _ = _build_token(last_activity=None, iat_offset_minutes=120)
        mock_blocklist = _make_blocklist_mock()

        with (
            _patched_settings(token_idle_timeout=0),
            patch(
                "mcpgateway.services.token_blocklist_service.get_token_blocklist_service",
                return_value=mock_blocklist,
            ),
        ):
            response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        mock_blocklist.get_last_activity.assert_not_called()
        mock_blocklist.update_activity.assert_not_called()
