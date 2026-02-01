# -*- coding: utf-8 -*-
"""Targeted tests for auth helper functions."""

# Standard
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_get_team_from_token_variants(monkeypatch):
    assert await auth.get_team_from_token({"teams": [{"id": "t1"}], "sub": "user@example.com"}) == "t1"
    monkeypatch.setattr(auth, "_get_personal_team_sync", lambda _email: "team-2")
    assert await auth.get_team_from_token({"teams": [], "sub": "user@example.com"}) == "team-2"

    def _boom(_email):
        raise RuntimeError("fail")

    monkeypatch.setattr(auth, "_get_personal_team_sync", _boom)
    assert await auth.get_team_from_token({"teams": [], "sub": "user@example.com"}) is None


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
    )
    session = DummySession(results=[api_token, None])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    result = auth._lookup_api_token_sync("hash")
    assert result["user_email"] == "user@example.com"
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
    )
    team = SimpleNamespace(id="team-1")
    session = DummySession(results=[user, team, SimpleNamespace(id="revoked")])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    result = auth._get_auth_context_batched_sync("user@example.com", "jti-1")
    assert result["user"]["email"] == "user@example.com"
    assert result["personal_team_id"] == "team-1"
    assert result["is_token_revoked"] is True

    session = DummySession(results=[None])
    monkeypatch.setattr(auth, "fresh_db_session", lambda: _session_ctx(session))
    result = auth._get_auth_context_batched_sync("missing@example.com")
    assert result["user"] is None
