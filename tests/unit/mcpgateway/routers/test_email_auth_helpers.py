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
    captured = {}

    async def fake_create_jwt_token(payload):
        captured.update(payload)
        return "token"

    monkeypatch.setattr(email_auth, "create_jwt_token", fake_create_jwt_token)

    user = DummyUser("user@example.com", is_admin=False)
    token, expires = await email_auth.create_access_token(user)

    assert token == "token"
    assert "teams" in captured


@pytest.mark.asyncio
async def test_create_access_token_admin(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    async def fake_create_jwt_token(payload):
        captured.update(payload)
        return "token"

    monkeypatch.setattr(email_auth, "create_jwt_token", fake_create_jwt_token)

    user = DummyUser("admin@example.com", is_admin=True)
    await email_auth.create_access_token(user)

    assert "teams" not in captured


def test_get_client_ip_and_user_agent():
    request = SimpleNamespace(headers={"X-Forwarded-For": "1.2.3.4"}, client=SimpleNamespace(host="9.9.9.9"))
    assert email_auth.get_client_ip(request) == "1.2.3.4"

    request = SimpleNamespace(headers={"X-Real-IP": "5.6.7.8"}, client=SimpleNamespace(host="9.9.9.9"))
    assert email_auth.get_client_ip(request) == "5.6.7.8"

    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="9.9.9.9"))
    assert email_auth.get_client_ip(request) == "9.9.9.9"

    request = SimpleNamespace(headers={"User-Agent": "agent"})
    assert email_auth.get_user_agent(request) == "agent"
