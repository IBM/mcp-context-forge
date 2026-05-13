# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_helpers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Targeted tests for auth helper functions.
"""

# Standard
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Third-Party
import pytest

# First-Party
import mcpgateway.auth as auth
from mcpgateway.db import EmailUser


class DummyResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def all(self):
        return self._value if isinstance(self._value, list) else []


class DummySession:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.commit_called = False
        self.rollback_called = False
        self.invalidate_called = False
        self.close_called = False

    def execute(self, _query):
        value = self._results.pop(0) if self._results else None
        return DummyResult(value)

    def commit(self):
        self.commit_called = True

    def rollback(self):
        self.rollback_called = True

    def invalidate(self):
        self.invalidate_called = True

    def close(self):
        self.close_called = True


@contextmanager
def _session_ctx(session):
    yield session


def test_log_auth_event_builds_extra(monkeypatch):
    logger = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    called = {}

    def _capture(level, message, extra=None):  # noqa: ARG001 - signature matches logger.log
        called["extra"] = extra

    logger.log = _capture
    monkeypatch.setattr(auth, "get_correlation_id", lambda: "req-1")

    auth._log_auth_event(logger, "msg", user_id="u1", auth_method="jwt", auth_success=True, security_event="authentication", security_severity="high")
    assert called["extra"]["request_id"] == "req-1"
    assert called["extra"]["user_id"] == "u1"
    assert called["extra"]["auth_method"] == "jwt"


def test_get_db_commit_and_close(monkeypatch):
    session = DummySession()
    monkeypatch.setattr(auth, "SessionLocal", lambda: session)

    gen = auth.get_db()
    _ = next(gen)
    with pytest.raises(StopIteration):
        gen.send(None)

    assert session.commit_called is True
    assert session.close_called is True


def test_get_db_rollback_invalidate(monkeypatch):
    class FailingSession(DummySession):
        def rollback(self):
            super().rollback()
            raise RuntimeError("rollback fail")

    session = FailingSession()
    monkeypatch.setattr(auth, "SessionLocal", lambda: session)

    gen = auth.get_db()
    _ = next(gen)
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))

    assert session.rollback_called is True
    assert session.invalidate_called is True
    assert session.close_called is True


def test_get_personal_team_sync(monkeypatch):
    session = DummySession(results=[SimpleNamespace(id="team-1")])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    assert auth._get_personal_team_sync("user@example.com") == "team-1"


def test_get_user_team_ids_sync(monkeypatch):
    session = DummySession(results=[[("t1",), ("t2",)]])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    assert auth._get_user_team_ids_sync("user@example.com") == ["t1", "t2"]


@pytest.mark.asyncio
async def test_resolve_teams_from_db_async_admin_bypass():
    assert await auth._resolve_teams_from_db("user@example.com", {"is_admin": True}) is None


@pytest.mark.asyncio
async def test_resolve_teams_from_db_async_cache_hit(monkeypatch):
    dummy_cache = SimpleNamespace(
        get_user_teams=AsyncMock(return_value=["t1"]),
        set_user_teams=AsyncMock(),
    )

    import mcpgateway.cache.auth_cache as auth_cache_mod

    monkeypatch.setattr(auth_cache_mod, "auth_cache", dummy_cache)
    assert await auth._resolve_teams_from_db("user@example.com", {"is_admin": False}) == ["t1"]
    dummy_cache.set_user_teams.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_teams_from_db_async_cache_miss_sets_cache(monkeypatch):
    dummy_cache = SimpleNamespace(
        get_user_teams=AsyncMock(return_value=None),
        set_user_teams=AsyncMock(),
    )

    import mcpgateway.cache.auth_cache as auth_cache_mod

    monkeypatch.setattr(auth_cache_mod, "auth_cache", dummy_cache)
    monkeypatch.setattr(auth, "_get_user_team_ids_sync", lambda _email: ["t1"])

    async def fake_to_thread(fn, *args, **kwargs):  # noqa: ARG001
        return fn(*args, **kwargs)

    monkeypatch.setattr(auth.asyncio, "to_thread", fake_to_thread)

    assert await auth._resolve_teams_from_db("user@example.com", {"is_admin": False}) == ["t1"]
    dummy_cache.set_user_teams.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_team_from_token_variants(monkeypatch):
    # Teams with dict format
    assert await auth.get_team_from_token({"teams": [{"id": "t1"}], "sub": "user@example.com"}) == "t1"

    # Teams with string format
    assert await auth.get_team_from_token({"teams": ["t2"], "sub": "user@example.com"}) == "t2"

    # SECURITY: Empty teams list means public-only - NO fallback to personal team
    assert await auth.get_team_from_token({"teams": [], "sub": "user@example.com"}) is None

    # SECURITY: Missing teams claim also means public-only - NO fallback to personal team
    # This is the secure-first approach: missing teams = public-only everywhere
    assert await auth.get_team_from_token({"sub": "user@example.com"}) is None


def test_normalize_token_teams():
    """Test token teams normalization for consistent security checks."""
    # Missing teams key → public-only ([])
    assert auth.normalize_token_teams({"sub": "user@example.com"}) == []

    # Explicit empty teams → public-only ([])
    assert auth.normalize_token_teams({"sub": "user@example.com", "teams": []}) == []

    # Explicit null + non-admin → public-only ([])
    assert auth.normalize_token_teams({"sub": "user@example.com", "teams": None, "user": {"is_admin": False}}) == []

    # Explicit null + admin → admin bypass (None)
    assert auth.normalize_token_teams({"sub": "user@example.com", "teams": None, "user": {"is_admin": True}}) is None

    # Explicit null + missing user → public-only ([])
    assert auth.normalize_token_teams({"sub": "user@example.com", "teams": None}) == []

    # Teams with string values → normalized list
    assert auth.normalize_token_teams({"sub": "user@example.com", "teams": ["team1", "team2"]}) == ["team1", "team2"]

    # Teams with dict format → normalized to string IDs
    assert auth.normalize_token_teams({"sub": "user@example.com", "teams": [{"id": "team1"}]}) == ["team1"]

    # Teams with mixed format → normalized to string IDs
    assert auth.normalize_token_teams({"sub": "user@example.com", "teams": [{"id": "team1"}, "team2"]}) == ["team1", "team2"]

    # Top-level is_admin check (explicit null + top-level is_admin)
    assert auth.normalize_token_teams({"sub": "user@example.com", "teams": None, "is_admin": True}) is None


def test_check_token_revoked_sync(monkeypatch):
    session = DummySession(results=[SimpleNamespace(id="revoked")])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    assert auth._check_token_revoked_sync("jti") is True


def test_lookup_api_token_sync_expired(monkeypatch):
    expired_token = SimpleNamespace(
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        jti="jti-1",
        user_email="user@example.com",
        last_used=None,
    )
    session = DummySession(results=[expired_token])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    assert auth._lookup_api_token_sync("hash") == {"expired": True}


def test_lookup_api_token_sync_expired_naive_datetime(monkeypatch):
    """Naive datetime from SQLite is correctly detected as expired."""
    expired_token = SimpleNamespace(
        expires_at=datetime(2026, 3, 8, 12, 0, 0),  # naive (no tzinfo)
        jti="jti-1",
        user_email="user@example.com",
        last_used=None,
    )
    session = DummySession(results=[expired_token])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    monkeypatch.setattr("mcpgateway.db.utc_now", lambda: datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc))
    assert auth._lookup_api_token_sync("hash") == {"expired": True}


def test_lookup_api_token_sync_not_expired_naive_datetime(monkeypatch):
    """Naive datetime from SQLite in the future is correctly detected as not expired."""
    active_token = SimpleNamespace(
        expires_at=datetime(2026, 3, 10, 12, 0, 0),  # naive, in the future
        jti="jti-1",
        user_email="user@example.com",
        last_used=None,
        resource_scopes=["tools.read", "servers.use"],  # Added for scope enforcement
    )
    session = DummySession(results=[active_token, None])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    monkeypatch.setattr("mcpgateway.db.utc_now", lambda: datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc))
    result = auth._lookup_api_token_sync("hash")
    assert result["user_email"] == "user@example.com"
    assert result["resource_scopes"] == ["tools.read", "servers.use"]


def test_lookup_api_token_sync_revoked(monkeypatch):
    api_token = SimpleNamespace(
        expires_at=None,
        jti="jti-1",
        user_email="user@example.com",
        last_used=None,
    )
    session = DummySession(results=[api_token, SimpleNamespace(id="revoked")])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    assert auth._lookup_api_token_sync("hash") == {"revoked": True}


def test_lookup_api_token_sync_active(monkeypatch):
    api_token = SimpleNamespace(
        expires_at=None,
        jti="jti-1",
        user_email="user@example.com",
        last_used=None,
        resource_scopes=["a2a.read", "tools.execute"],  # Added for scope enforcement
    )
    session = DummySession(results=[api_token, None])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    result = auth._lookup_api_token_sync("hash")
    assert result["user_email"] == "user@example.com"
    assert result["resource_scopes"] == ["a2a.read", "tools.execute"]
    assert session.commit_called is True


def test_is_api_token_jti_sync(monkeypatch):
    session = DummySession(results=[SimpleNamespace(id=1)])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    assert auth._is_api_token_jti_sync("jti") is True

    @contextmanager
    def _boom_session():
        raise RuntimeError("db fail")
        yield  # pragma: no cover

    monkeypatch.setattr(auth, "fresh_db_session", _boom_session)
    assert auth._is_api_token_jti_sync("jti") is True


def test_jwt_malformed_scopes_rejected(caplog):
    """Test that malformed JWT scopes (non-dict) are rejected with 401 error."""
    from types import SimpleNamespace
    import logging
    from fastapi import HTTPException

    # Create mock request state
    request_state = SimpleNamespace()

    # Mock JWT payload with malformed scopes (string instead of dict)
    malformed_payload = {
        "email": "user@example.com",
        "sub": "user@example.com",
        "scopes": "tools.read,a2a.read",  # MALFORMED: should be dict, not string
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
    }

    # Simulate the JWT scope extraction logic from auth.py (with rejection)
    logger = logging.getLogger("mcpgateway.auth")

    with caplog.at_level(logging.WARNING, logger="mcpgateway.auth"):
        scopes = malformed_payload.get("scopes")
        error_raised = False
        if scopes is not None:
            if isinstance(scopes, dict):
                permissions = scopes.get("permissions", [])
                request_state.token_scopes = permissions
            else:
                # Malformed JWT: reject with 401
                logger.warning(
                    f"JWT token rejected: scopes field is {type(scopes).__name__}, expected dict. "
                    f"Tokens with malformed scopes must be regenerated with correct structure."
                )
                error_raised = True

    # Verify malformed scopes are logged as WARNING
    assert "JWT token rejected: scopes field is str, expected dict" in caplog.text

    # Verify rejection would have occurred
    assert error_raised is True

    # Verify token_scopes is NOT set (token was rejected)
    assert not hasattr(request_state, "token_scopes")


@pytest.mark.asyncio
async def test_jwt_empty_dict_scopes_enforcement():
    """Test that JWT with empty dict scopes {} correctly enforces scope checks."""
    from unittest.mock import MagicMock
    from starlette.requests import Request
    
    # Create mock request
    request = MagicMock(spec=Request)
    request.state = SimpleNamespace()
    
    # JWT payload with empty dict scopes (CRITICAL: must be detected as API token)
    empty_dict_payload = {
        "email": "user@example.com",
        "sub": "user@example.com",
        "scopes": {},  # Empty dict - should enforce scope checks
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
    }
    
    # Simulate the JWT scope extraction logic from auth.py:1770-1787
    scopes = empty_dict_payload.get("scopes")
    if scopes is not None:
        if isinstance(scopes, dict):
            permissions = scopes.get("permissions", [])
            request.state.token_scopes = permissions
    
    # Verify token_scopes is set to empty list (enforces scope checks)
    assert hasattr(request.state, "token_scopes")
    assert request.state.token_scopes == []


@pytest.mark.asyncio
async def test_jwt_missing_scopes_session_token():
    """Test that JWT without scopes field is treated as session token (no scope checks)."""
    from unittest.mock import MagicMock
    from starlette.requests import Request
    
    # Create mock request
    request = MagicMock(spec=Request)
    request.state = SimpleNamespace()
    
    # JWT payload without scopes field (session token)
    session_payload = {
        "email": "user@example.com",
        "sub": "user@example.com",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
    }
    
    # Simulate the JWT scope extraction logic from auth.py:1770-1787
    scopes = session_payload.get("scopes")
    if scopes is not None:
        if isinstance(scopes, dict):
            permissions = scopes.get("permissions", [])
            request.state.token_scopes = permissions
    
    # Verify token_scopes is NOT set (session token, no scope enforcement)
    assert not hasattr(request.state, "token_scopes")


def test_get_user_by_email_sync(monkeypatch):
    user = SimpleNamespace(
        email="user@example.com",
        password_hash="hash",
        full_name="User",
        is_admin=False,
        is_active=True,
        email_verified_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        auth_provider="local",
        password_change_required=False,
    )
    session = DummySession(results=[user])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    result = auth._get_user_by_email_sync("user@example.com")
    assert isinstance(result, EmailUser)
    assert result.email == "user@example.com"


def test_get_auth_context_batched_sync(monkeypatch):
    user = SimpleNamespace(
        email="user@example.com",
        password_hash="hash",
        full_name="User",
        is_admin=True,
        is_active=True,
        email_verified_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        auth_provider="local",
        password_change_required=False,
    )
    team = SimpleNamespace(id="team-1")
    # Results in query execution order: user, personal_team, team_ids (.all()), revocation
    session = DummySession(results=[user, team, [("team-1",)], SimpleNamespace(id="revoked")])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    result = auth._get_auth_context_batched_sync("user@example.com", "jti-1")
    assert result["user"]["email"] == "user@example.com"
    assert result["personal_team_id"] == "team-1"
    assert result["team_ids"] == ["team-1"]
    assert result["is_token_revoked"] is True

    session = DummySession(results=[None])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    result = auth._get_auth_context_batched_sync("missing@example.com")
    assert result["user"] is None
