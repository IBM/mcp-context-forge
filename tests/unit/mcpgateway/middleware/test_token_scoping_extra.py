# -*- coding: utf-8 -*-
"""Additional tests for token scoping middleware helpers."""

# Standard
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException

# First-Party
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware

# Hex-only IDs that match the regex pattern [a-f0-9\-]+
_SRV_ID = "aabbccdd-1122-3344-5566-778899aabbcc"
_TOOL_ID = "11223344-aabb-ccdd-eeff-001122334455"
_RES_ID = "aabbccdd-eeff-0011-2233-445566778899"
_PROMPT_ID = "00112233-4455-6677-8899-aabbccddeeff"
_GW_ID = "ffeeddcc-bbaa-9988-7766-554433221100"


def test_normalize_teams_and_client_ip():
    middleware = TokenScopingMiddleware()
    assert middleware._normalize_teams(None) == []
    assert middleware._normalize_teams([{"id": "t1"}, "t2", {"name": "x"}]) == ["t1", "t2"]

    req = SimpleNamespace(headers={"X-Forwarded-For": "1.2.3.4"}, client=SimpleNamespace(host="9.9.9.9"))
    assert middleware._get_client_ip(req) == "1.2.3.4"

    req = SimpleNamespace(headers={"X-Real-IP": "5.6.7.8"}, client=SimpleNamespace(host="9.9.9.9"))
    assert middleware._get_client_ip(req) == "5.6.7.8"


def test_check_ip_restrictions_invalid():
    middleware = TokenScopingMiddleware()
    assert middleware._check_ip_restrictions("invalid", ["10.0.0.0/24"]) is False


def test_check_ip_restrictions_exact_and_cidr():
    middleware = TokenScopingMiddleware()
    assert middleware._check_ip_restrictions("192.168.1.10", ["192.168.1.10"]) is True
    assert middleware._check_ip_restrictions("10.0.0.5", ["10.0.0.0/24"]) is True
    assert middleware._check_ip_restrictions("10.0.0.5", ["bad-cidr"]) is False


def test_check_time_restrictions(monkeypatch: pytest.MonkeyPatch):
    middleware = TokenScopingMiddleware()

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("mcpgateway.middleware.token_scoping.datetime", FakeDateTime)

    assert middleware._check_time_restrictions({"business_hours_only": True, "weekdays_only": True}) is True


def test_check_time_restrictions_weekend(monkeypatch: pytest.MonkeyPatch):
    middleware = TokenScopingMiddleware()

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 5, 10, 0, tzinfo=timezone.utc)  # Sunday

    monkeypatch.setattr("mcpgateway.middleware.token_scoping.datetime", FakeDateTime)

    assert middleware._check_time_restrictions({"weekdays_only": True}) is False


def test_check_server_and_permission_restrictions():
    middleware = TokenScopingMiddleware()
    assert middleware._check_server_restriction("/servers/abc/tools", "abc") is True
    assert middleware._check_server_restriction("/health", "abc") is True
    assert middleware._check_permission_restrictions("/tools", "GET", ["*"]) is True
    assert middleware._check_permission_restrictions("/tools", "POST", ["tools.read"]) is False


@pytest.mark.asyncio
async def test_extract_token_scopes_handles_exceptions(monkeypatch):
    middleware = TokenScopingMiddleware()
    request = SimpleNamespace(headers={"Authorization": "Bearer bad-token"})

    async def _raise_http(*_args, **_kwargs):
        raise HTTPException(status_code=401, detail="invalid")

    monkeypatch.setattr("mcpgateway.middleware.token_scoping.verify_jwt_token_cached", _raise_http)
    assert await middleware._extract_token_scopes(request) is None

    async def _raise_other(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("mcpgateway.middleware.token_scoping.verify_jwt_token_cached", _raise_other)
    assert await middleware._extract_token_scopes(request) is None


def test_check_team_membership_public_token():
    middleware = TokenScopingMiddleware()
    payload = {"teams": [], "sub": "user@example.com"}
    assert middleware._check_team_membership(payload) is True


def test_check_resource_team_ownership_no_resource():
    middleware = TokenScopingMiddleware()
    assert middleware._check_resource_team_ownership("/health", [], db=None, _user_email=None) is True


# --------------------------------------------------------------------------- #
# Coverage: _normalize_teams edge cases                                        #
# --------------------------------------------------------------------------- #
def test_normalize_teams_empty_list():
    middleware = TokenScopingMiddleware()
    assert middleware._normalize_teams([]) == []


def test_normalize_teams_dict_without_id():
    """Dict without 'id' key is skipped."""
    middleware = TokenScopingMiddleware()
    assert middleware._normalize_teams([{"name": "t1"}, {"id": "t2"}]) == ["t2"]


def test_normalize_teams_mixed_types():
    """Non-dict, non-string items are skipped."""
    middleware = TokenScopingMiddleware()
    assert middleware._normalize_teams([123, "team-1", None]) == ["team-1"]


# --------------------------------------------------------------------------- #
# Coverage: _get_client_ip fallback                                            #
# --------------------------------------------------------------------------- #
def test_get_client_ip_direct():
    middleware = TokenScopingMiddleware()
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.1"))
    assert middleware._get_client_ip(req) == "10.0.0.1"


def test_get_client_ip_no_client():
    middleware = TokenScopingMiddleware()
    req = SimpleNamespace(headers={}, client=None)
    assert middleware._get_client_ip(req) == "unknown"


# --------------------------------------------------------------------------- #
# Coverage: _check_resource_team_ownership - server visibility branches        #
# --------------------------------------------------------------------------- #
class TestResourceTeamOwnershipServers:
    """Tests for server visibility checks in _check_resource_team_ownership."""

    def _make_db_with_entity(self, entity):
        """Create mock DB that returns entity for select().where() queries."""
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = entity
        return mock_db

    def test_server_not_found(self):
        middleware = TokenScopingMiddleware()
        db = self._make_db_with_entity(None)
        result = middleware._check_resource_team_ownership(f"/servers/{_SRV_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True  # Not found = allow through

    def test_server_public_allowed(self):
        middleware = TokenScopingMiddleware()
        server = SimpleNamespace(visibility="public", team_id=None, owner_email=None)
        db = self._make_db_with_entity(server)
        result = middleware._check_resource_team_ownership(f"/servers/{_SRV_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_server_public_token_denied_team_server(self):
        middleware = TokenScopingMiddleware()
        server = SimpleNamespace(visibility="team", team_id="team-2", owner_email=None)
        db = self._make_db_with_entity(server)
        result = middleware._check_resource_team_ownership(f"/servers/{_SRV_ID}", [], db=db, _user_email="u@t.com")
        assert result is False

    def test_server_team_access_granted(self):
        middleware = TokenScopingMiddleware()
        server = SimpleNamespace(visibility="team", team_id="team-1", owner_email=None)
        db = self._make_db_with_entity(server)
        result = middleware._check_resource_team_ownership(f"/servers/{_SRV_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_server_team_access_denied(self):
        middleware = TokenScopingMiddleware()
        server = SimpleNamespace(visibility="team", team_id="team-2", owner_email=None)
        db = self._make_db_with_entity(server)
        result = middleware._check_resource_team_ownership(f"/servers/{_SRV_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False

    def test_server_private_owner_access(self):
        middleware = TokenScopingMiddleware()
        server = SimpleNamespace(visibility="private", team_id=None, owner_email="u@t.com")
        db = self._make_db_with_entity(server)
        result = middleware._check_resource_team_ownership(f"/servers/{_SRV_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_server_private_non_owner_denied(self):
        middleware = TokenScopingMiddleware()
        server = SimpleNamespace(visibility="private", team_id=None, owner_email="other@t.com")
        db = self._make_db_with_entity(server)
        result = middleware._check_resource_team_ownership(f"/servers/{_SRV_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False

    def test_server_unknown_visibility_denied(self):
        middleware = TokenScopingMiddleware()
        server = SimpleNamespace(visibility="unknown_vis", team_id=None, owner_email=None)
        db = self._make_db_with_entity(server)
        result = middleware._check_resource_team_ownership(f"/servers/{_SRV_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False


# --------------------------------------------------------------------------- #
# Coverage: _check_resource_team_ownership - tool visibility branches          #
# --------------------------------------------------------------------------- #
class TestResourceTeamOwnershipTools:
    """Tests for tool visibility checks."""

    def _make_db_with_entity(self, entity):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = entity
        return mock_db

    def test_tool_not_found(self):
        middleware = TokenScopingMiddleware()
        db = self._make_db_with_entity(None)
        result = middleware._check_resource_team_ownership(f"/tools/{_TOOL_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_tool_public_allowed(self):
        middleware = TokenScopingMiddleware()
        tool = SimpleNamespace(visibility="public", team_id=None, owner_email=None)
        db = self._make_db_with_entity(tool)
        result = middleware._check_resource_team_ownership(f"/tools/{_TOOL_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_tool_team_access_denied(self):
        middleware = TokenScopingMiddleware()
        tool = SimpleNamespace(visibility="team", team_id="team-2", owner_email=None)
        db = self._make_db_with_entity(tool)
        result = middleware._check_resource_team_ownership(f"/tools/{_TOOL_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False

    def test_tool_public_token_denied(self):
        middleware = TokenScopingMiddleware()
        tool = SimpleNamespace(visibility="team", team_id="team-1", owner_email=None)
        db = self._make_db_with_entity(tool)
        result = middleware._check_resource_team_ownership(f"/tools/{_TOOL_ID}", [], db=db, _user_email="u@t.com")
        assert result is False


# --------------------------------------------------------------------------- #
# Coverage: _check_resource_team_ownership - resource visibility               #
# --------------------------------------------------------------------------- #
class TestResourceTeamOwnershipResources:
    """Tests for resource visibility checks."""

    def _make_db_with_entity(self, entity):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = entity
        return mock_db

    def test_resource_not_found(self):
        middleware = TokenScopingMiddleware()
        db = self._make_db_with_entity(None)
        result = middleware._check_resource_team_ownership(f"/resources/{_RES_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_resource_team_denied(self):
        middleware = TokenScopingMiddleware()
        resource = SimpleNamespace(visibility="team", team_id="team-2", owner_email=None)
        db = self._make_db_with_entity(resource)
        result = middleware._check_resource_team_ownership(f"/resources/{_RES_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False


# --------------------------------------------------------------------------- #
# Coverage: _check_resource_team_ownership - prompt visibility                 #
# --------------------------------------------------------------------------- #
class TestResourceTeamOwnershipPrompts:
    """Tests for prompt visibility checks."""

    def _make_db_with_entity(self, entity):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = entity
        return mock_db

    def test_prompt_not_found(self):
        middleware = TokenScopingMiddleware()
        db = self._make_db_with_entity(None)
        result = middleware._check_resource_team_ownership(f"/prompts/{_PROMPT_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_prompt_public_allowed(self):
        middleware = TokenScopingMiddleware()
        prompt = SimpleNamespace(visibility="public", team_id=None, owner_email=None)
        db = self._make_db_with_entity(prompt)
        result = middleware._check_resource_team_ownership(f"/prompts/{_PROMPT_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_prompt_team_denied(self):
        middleware = TokenScopingMiddleware()
        prompt = SimpleNamespace(visibility="team", team_id="team-2", owner_email=None)
        db = self._make_db_with_entity(prompt)
        result = middleware._check_resource_team_ownership(f"/prompts/{_PROMPT_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False

    def test_prompt_private_owner_access(self):
        middleware = TokenScopingMiddleware()
        prompt = SimpleNamespace(visibility="private", team_id=None, owner_email="u@t.com")
        db = self._make_db_with_entity(prompt)
        result = middleware._check_resource_team_ownership(f"/prompts/{_PROMPT_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_prompt_private_non_owner_denied(self):
        middleware = TokenScopingMiddleware()
        prompt = SimpleNamespace(visibility="private", team_id=None, owner_email="other@t.com")
        db = self._make_db_with_entity(prompt)
        result = middleware._check_resource_team_ownership(f"/prompts/{_PROMPT_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False


# --------------------------------------------------------------------------- #
# Coverage: _check_resource_team_ownership - gateway visibility                #
# --------------------------------------------------------------------------- #
class TestResourceTeamOwnershipGateways:
    """Tests for gateway visibility checks."""

    def _make_db_with_entity(self, entity):
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = entity
        return mock_db

    def test_gateway_not_found(self):
        middleware = TokenScopingMiddleware()
        db = self._make_db_with_entity(None)
        result = middleware._check_resource_team_ownership(f"/gateways/{_GW_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_gateway_public_allowed(self):
        middleware = TokenScopingMiddleware()
        gw = SimpleNamespace(visibility="public", team_id=None, owner_email=None)
        db = self._make_db_with_entity(gw)
        result = middleware._check_resource_team_ownership(f"/gateways/{_GW_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_gateway_public_token_denied(self):
        middleware = TokenScopingMiddleware()
        gw = SimpleNamespace(visibility="team", team_id="team-1", owner_email=None)
        db = self._make_db_with_entity(gw)
        result = middleware._check_resource_team_ownership(f"/gateways/{_GW_ID}", [], db=db, _user_email="u@t.com")
        assert result is False

    def test_gateway_team_denied(self):
        middleware = TokenScopingMiddleware()
        gw = SimpleNamespace(visibility="team", team_id="team-2", owner_email=None)
        db = self._make_db_with_entity(gw)
        result = middleware._check_resource_team_ownership(f"/gateways/{_GW_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False

    def test_gateway_private_owner(self):
        middleware = TokenScopingMiddleware()
        gw = SimpleNamespace(visibility="private", team_id=None, owner_email="u@t.com")
        db = self._make_db_with_entity(gw)
        result = middleware._check_resource_team_ownership(f"/gateways/{_GW_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is True

    def test_gateway_unknown_visibility(self):
        middleware = TokenScopingMiddleware()
        gw = SimpleNamespace(visibility="weird", team_id=None, owner_email=None)
        db = self._make_db_with_entity(gw)
        result = middleware._check_resource_team_ownership(f"/gateways/{_GW_ID}", ["team-1"], db=db, _user_email="u@t.com")
        assert result is False


# --------------------------------------------------------------------------- #
# Coverage: _check_time_restrictions - business hours                          #
# --------------------------------------------------------------------------- #
def test_check_time_restrictions_outside_business_hours(monkeypatch):
    middleware = TokenScopingMiddleware()

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 1, 6, 22, 0, tzinfo=timezone.utc)  # Monday 10pm

    monkeypatch.setattr("mcpgateway.middleware.token_scoping.datetime", FakeDateTime)
    assert middleware._check_time_restrictions({"business_hours_only": True}) is False
