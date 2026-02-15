# -*- coding: utf-8 -*-
"""Tests for email auth helper functions."""

# Standard
from types import SimpleNamespace

# Third-Party
import pytest

# First-Party
from mcpgateway.routers import email_auth


class DummyTeam:
    def __init__(self, id, slug):
        self.id = id
        self.slug = slug
        self.name = slug
        self.is_personal = False


class DummyUser:
    def __init__(self, email, is_admin=False):
        self.email = email
        self.full_name = "User"
        self.is_admin = is_admin
        self.auth_provider = "local"
        self.team_memberships = []

    def get_teams(self):
        return [DummyTeam("t1", "team1")]


@pytest.mark.asyncio
async def test_create_access_token_payload(monkeypatch: pytest.MonkeyPatch):
    """Session tokens should have token_use='session' and no 'teams' claim."""
    captured = {}

    async def fake_create_jwt_token(payload):
        captured.update(payload)
        return "token"

    monkeypatch.setattr(email_auth, "create_jwt_token", fake_create_jwt_token)

    user = DummyUser("user@example.com", is_admin=False)
    token, expires = await email_auth.create_access_token(user)

    assert token == "token"
    assert captured.get("token_use") == "session"
    assert "teams" not in captured  # Session tokens don't embed teams
    assert "namespaces" not in captured  # Namespaces removed


@pytest.mark.asyncio
async def test_create_access_token_admin(monkeypatch: pytest.MonkeyPatch):
    """Admin session tokens should also have token_use='session' and no 'teams' claim."""
    captured = {}

    async def fake_create_jwt_token(payload):
        captured.update(payload)
        return "token"

    monkeypatch.setattr(email_auth, "create_jwt_token", fake_create_jwt_token)

    user = DummyUser("admin@example.com", is_admin=True)
    await email_auth.create_access_token(user)

    assert captured.get("token_use") == "session"
    assert "teams" not in captured  # Session tokens don't embed teams


@pytest.mark.asyncio
async def test_create_access_token_handles_team_errors(monkeypatch: pytest.MonkeyPatch):
    """Teams with broken id property should be silently skipped (no teams in session token anyway)."""
    captured = {}

    class BadTeam:
        @property
        def id(self):  # pragma: no cover - accessed in try block
            raise RuntimeError("boom")

        def __str__(self):
            return "bad-team"

    class UserWithBadTeams(DummyUser):
        def get_teams(self):
            return [BadTeam()]

    async def fake_create_jwt_token(payload):
        captured.update(payload)
        return "token"

    monkeypatch.setattr(email_auth, "create_jwt_token", fake_create_jwt_token)

    user = UserWithBadTeams("user@example.com", is_admin=False)
    token, _ = await email_auth.create_access_token(user)
    assert token == "token"
    assert captured.get("token_use") == "session"
    assert "teams" not in captured  # Session tokens don't embed teams


@pytest.mark.asyncio
async def test_create_access_token_handles_team_str_error(monkeypatch: pytest.MonkeyPatch):
    """Teams with broken str should be silently skipped."""
    captured = {}

    class BadTeam:
        @property
        def id(self):  # pragma: no cover - accessed in try block
            raise RuntimeError("boom")

        def __str__(self):
            raise RuntimeError("str boom")

    class UserWithBadTeams(DummyUser):
        def get_teams(self):
            return [BadTeam()]

    async def fake_create_jwt_token(payload):
        captured.update(payload)
        return "token"

    monkeypatch.setattr(email_auth, "create_jwt_token", fake_create_jwt_token)

    user = UserWithBadTeams("user@example.com", is_admin=False)
    token, _ = await email_auth.create_access_token(user)
    assert token == "token"
    assert captured.get("token_use") == "session"
    assert "teams" not in captured  # Session tokens don't embed teams


def test_get_db_commit_and_close(monkeypatch: pytest.MonkeyPatch):
    class DummyDB:
        def __init__(self):
            self.committed = False
            self.closed = False

        def commit(self):
            self.committed = True

        def rollback(self):
            raise RuntimeError("rollback should not be called")

        def invalidate(self):
            raise RuntimeError("invalidate should not be called")

        def close(self):
            self.closed = True

    db = DummyDB()
    monkeypatch.setattr(email_auth, "SessionLocal", lambda: db)

    gen = email_auth.get_db()
    assert next(gen) is db
    with pytest.raises(StopIteration):
        next(gen)

    assert db.committed is True
    assert db.closed is True


def test_get_db_rollback_on_exception(monkeypatch: pytest.MonkeyPatch):
    class DummyDB:
        def __init__(self):
            self.rolled_back = False
            self.closed = False

        def commit(self):
            raise RuntimeError("commit should not be called")

        def rollback(self):
            self.rolled_back = True

        def invalidate(self):
            raise RuntimeError("invalidate should not be called")

        def close(self):
            self.closed = True

    db = DummyDB()
    monkeypatch.setattr(email_auth, "SessionLocal", lambda: db)

    gen = email_auth.get_db()
    next(gen)

    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))

    assert db.rolled_back is True
    assert db.closed is True


def test_get_db_rollback_invalidate_on_failure(monkeypatch: pytest.MonkeyPatch):
    class DummyDB:
        def __init__(self):
            self.invalidated = False
            self.closed = False

        def commit(self):
            raise RuntimeError("commit should not be called")

        def rollback(self):
            raise RuntimeError("rollback failed")

        def invalidate(self):
            self.invalidated = True

        def close(self):
            self.closed = True

    db = DummyDB()
    monkeypatch.setattr(email_auth, "SessionLocal", lambda: db)

    gen = email_auth.get_db()
    next(gen)

    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))

    assert db.invalidated is True
    assert db.closed is True


def test_get_client_ip_and_user_agent():
    request = SimpleNamespace(headers={"X-Forwarded-For": "1.2.3.4"}, client=SimpleNamespace(host="9.9.9.9"))
    assert email_auth.get_client_ip(request) == "1.2.3.4"

    request = SimpleNamespace(headers={"X-Real-IP": "5.6.7.8"}, client=SimpleNamespace(host="9.9.9.9"))
    assert email_auth.get_client_ip(request) == "5.6.7.8"

    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="9.9.9.9"))
    assert email_auth.get_client_ip(request) == "9.9.9.9"

    request = SimpleNamespace(headers={"User-Agent": "agent"})
    assert email_auth.get_user_agent(request) == "agent"
