# -*- coding: utf-8 -*-
"""Additional tests for token scoping middleware helpers."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace

# Third-Party
import pytest

# First-Party
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware


def test_normalize_teams_and_client_ip():
    middleware = TokenScopingMiddleware()
    assert middleware._normalize_teams([{"id": "t1"}, "t2", {"name": "x"}]) == ["t1", "t2"]

    req = SimpleNamespace(headers={"X-Forwarded-For": "1.2.3.4"}, client=SimpleNamespace(host="9.9.9.9"))
    assert middleware._get_client_ip(req) == "1.2.3.4"

    req = SimpleNamespace(headers={"X-Real-IP": "5.6.7.8"}, client=SimpleNamespace(host="9.9.9.9"))
    assert middleware._get_client_ip(req) == "5.6.7.8"


def test_check_ip_restrictions_invalid():
    middleware = TokenScopingMiddleware()
    assert middleware._check_ip_restrictions("invalid", ["10.0.0.0/24"]) is False


def test_check_time_restrictions(monkeypatch: pytest.MonkeyPatch):
    middleware = TokenScopingMiddleware()

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("mcpgateway.middleware.token_scoping.datetime", FakeDateTime)

    assert middleware._check_time_restrictions({"business_hours_only": True, "weekdays_only": True}) is True


def test_check_server_and_permission_restrictions():
    middleware = TokenScopingMiddleware()
    assert middleware._check_server_restriction("/servers/abc/tools", "abc") is True
    assert middleware._check_server_restriction("/health", "abc") is True
    assert middleware._check_permission_restrictions("/tools", "GET", ["*"]) is True
    assert middleware._check_permission_restrictions("/tools", "POST", ["tools.read"]) is False


def test_check_team_membership_public_token():
    middleware = TokenScopingMiddleware()
    payload = {"teams": [], "sub": "user@example.com"}
    assert middleware._check_team_membership(payload) is True


def test_check_resource_team_ownership_no_resource():
    middleware = TokenScopingMiddleware()
    assert middleware._check_resource_team_ownership("/health", [], db=None, _user_email=None) is True
