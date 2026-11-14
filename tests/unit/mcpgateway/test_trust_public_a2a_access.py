# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_trust_public_a2a_access.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Public A2A access for trusted principals in JWT-trust mode.

With ``JWT_TRUST_PUBLIC_A2A_ACCESS_ENABLED=true`` a verified trust-mode principal
may read and invoke ``public`` A2A agents without a mapped role. The grant is
fail-closed:

- the flag is off by default and needs ``JWT_TRUST_MODE=jwt-trust``;
- only ``token_use == "trusted"`` principals qualify;
- only ``a2a.read`` and ``a2a.invoke`` qualify;
- only public, enabled agents qualify;
- token scopes and ``HTTP_AUTH_CHECK_PERMISSION`` plugin hooks stay authoritative.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Base
from mcpgateway.main import _a2a_access_scope, _extract_a2a_request_context
from mcpgateway.middleware import rbac
from mcpgateway.services.a2a_service import A2AAgentService

USER = "trusted-user@example.com"
PUBLIC_ID = "a" * 32
TEAM_ID = "b" * 32
DISABLED_ID = "c" * 32
PRIVATE_ID = "d" * 32
PUBLIC_UAID = "uaid:aid:public-agent"


@pytest.fixture
def db():
    """In-memory SQLite session seeded with public, team, private and disabled agents."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    def _agent(agent_id, name, visibility, enabled=True, uaid=None):
        return DbA2AAgent(
            id=agent_id,
            name=name,
            slug=name,
            endpoint_url=f"https://{name}.example.com/agent",
            visibility=visibility,
            enabled=enabled,
            uaid=uaid,
            team_id="team-1",
            owner_email="owner@example.com",
        )

    session.add_all(
        [
            _agent(PUBLIC_ID, "public-agent", "public", uaid=PUBLIC_UAID),
            _agent(TEAM_ID, "team-agent", "team"),
            _agent(PRIVATE_ID, "private-agent", "private"),
            _agent(DISABLED_ID, "disabled-agent", "public", enabled=False),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def grant_on(monkeypatch):
    """Enable the grant in trust mode with no plugin hooks."""
    monkeypatch.setattr(settings, "jwt_trust_mode", "jwt-trust")
    monkeypatch.setattr(settings, "jwt_trust_public_a2a_access_enabled", True)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))


@pytest.fixture
def denying_rbac(monkeypatch):
    """Make the normal RBAC check deny, as it does for an unmapped principal."""
    monkeypatch.setattr(rbac, "check_permission_inline", AsyncMock(return_value=False))
    monkeypatch.setattr(rbac, "_resolve_team_and_check_mode", AsyncMock(return_value=(None, True)))


def _request():
    return SimpleNamespace(state=SimpleNamespace())


def _user(db, **overrides):
    user = {"email": USER, "db": db, "token_use": "trusted", "token_scopes": [], "token_teams": []}
    user.update(overrides)
    return user


def _guarded(permission, param):
    async def handler(*, request, user, db, **_):
        return request

    return rbac.require_permission(permission, public_a2a_param=param)(handler)


class TestIsPublicEnabledAgent:
    """``A2AAgentService.is_public_enabled_agent`` matches id, name and UAID."""

    @pytest.mark.parametrize("identifier", [PUBLIC_ID, "public-agent", PUBLIC_UAID])
    def test_public_enabled_matches(self, db, identifier):
        assert A2AAgentService.is_public_enabled_agent(db, identifier) is True

    @pytest.mark.parametrize("identifier", [TEAM_ID, "team-agent", PRIVATE_ID, DISABLED_ID, "disabled-agent", "missing", "", None])
    def test_other_agents_do_not_match(self, db, identifier):
        assert A2AAgentService.is_public_enabled_agent(db, identifier) is False


class TestGrantAllowed:
    """A trusted principal with no role reaches public agents."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identifier", [PUBLIC_ID, "public-agent", PUBLIC_UAID])
    @pytest.mark.parametrize("permission", ["a2a.read", "a2a.invoke"])
    async def test_public_agent_granted(self, db, grant_on, denying_rbac, permission, identifier):
        request = _request()
        result = await _guarded(permission, "agent_id")(request=request, user=_user(db), db=db, agent_id=identifier)
        assert result is request
        assert request.state.trusted_public_a2a_grant is True

    @pytest.mark.asyncio
    async def test_app_only_principal_granted(self, db, grant_on, denying_rbac):
        user = _user(db, email="service-principal@example.com", idtyp="app")
        request = _request()
        await _guarded("a2a.invoke", "agent_name")(request=request, user=user, db=db, agent_name="public-agent")
        assert request.state.trusted_public_a2a_grant is True

    @pytest.mark.asyncio
    async def test_list_route_granted_without_identifier(self, db, grant_on, denying_rbac):
        request = _request()
        await _guarded("a2a.read", rbac.PUBLIC_A2A_LIST_SCOPE)(request=request, user=_user(db), db=db)
        assert request.state.trusted_public_a2a_grant is True

    @pytest.mark.asyncio
    async def test_scoped_token_with_matching_scope_granted(self, db, grant_on, denying_rbac):
        request = _request()
        await _guarded("a2a.invoke", "agent_name")(request=request, user=_user(db, token_scopes=["a2a.*"]), db=db, agent_name="public-agent")
        assert request.state.trusted_public_a2a_grant is True


class TestGrantDenied:
    """Every deny path keeps the 403."""

    async def _expect_403(self, permission, param, user, db, request=None, **route_kwargs):
        with pytest.raises(HTTPException) as exc:
            await _guarded(permission, param)(request=request or _request(), user=user, db=db, **route_kwargs)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_flag_off(self, db, grant_on, denying_rbac, monkeypatch):
        monkeypatch.setattr(settings, "jwt_trust_public_a2a_access_enabled", False)
        await self._expect_403("a2a.read", "agent_id", _user(db), db, agent_id=PUBLIC_ID)

    @pytest.mark.asyncio
    async def test_trust_mode_off(self, db, grant_on, denying_rbac, monkeypatch):
        monkeypatch.setattr(settings, "jwt_trust_mode", "db")
        await self._expect_403("a2a.read", "agent_id", _user(db), db, agent_id=PUBLIC_ID)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("token_use", ["api", "session", None])
    async def test_non_trusted_token(self, db, grant_on, denying_rbac, token_use):
        await self._expect_403("a2a.read", "agent_id", _user(db, token_use=token_use), db, agent_id=PUBLIC_ID)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("identifier", [TEAM_ID, "team-agent", PRIVATE_ID, DISABLED_ID, "disabled-agent", "missing"])
    async def test_non_public_or_unknown_agent(self, db, grant_on, denying_rbac, identifier):
        await self._expect_403("a2a.invoke", "agent_id", _user(db), db, agent_id=identifier)

    @pytest.mark.asyncio
    async def test_team_agent_invoke_by_viewer_stays_forbidden(self, db, grant_on, denying_rbac):
        await self._expect_403("a2a.invoke", "agent_name", _user(db, token_teams=["team-1"]), db, agent_name="team-agent")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("permission", ["a2a.create", "a2a.update", "a2a.delete", "tools.read"])
    async def test_other_permissions(self, db, grant_on, denying_rbac, permission):
        await self._expect_403(permission, "agent_id", _user(db), db, agent_id=PUBLIC_ID)

    @pytest.mark.asyncio
    async def test_token_scope_without_a2a(self, db, grant_on, denying_rbac):
        await self._expect_403("a2a.read", "agent_id", _user(db, token_scopes=["tools.read"]), db, agent_id=PUBLIC_ID)

    @pytest.mark.asyncio
    async def test_plugin_permission_hook_stays_authoritative(self, db, grant_on, denying_rbac, monkeypatch):
        manager = MagicMock()
        manager.has_hooks_for.return_value = True
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=manager))
        await self._expect_403("a2a.read", "agent_id", _user(db), db, agent_id=PUBLIC_ID)

    @pytest.mark.asyncio
    async def test_missing_request(self, db, grant_on, denying_rbac):
        async def handler(*, user, db, agent_id):
            return "ok"

        guarded = rbac.require_permission("a2a.read", public_a2a_param="agent_id")(handler)
        with pytest.raises(HTTPException) as exc:
            await guarded(user=_user(db), db=db, agent_id=PUBLIC_ID)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_decorator_without_opt_in_ignores_grant(self, db, grant_on, denying_rbac):
        async def handler(*, request, user, db, agent_id):
            return "ok"

        guarded = rbac.require_permission("a2a.read")(handler)
        with pytest.raises(HTTPException) as exc:
            await guarded(request=_request(), user=_user(db), db=db, agent_id=PUBLIC_ID)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rbac_allow_does_not_set_marker(self, db, grant_on, monkeypatch):
        monkeypatch.setattr(rbac, "check_permission_inline", AsyncMock(return_value=True))
        monkeypatch.setattr(rbac, "_resolve_team_and_check_mode", AsyncMock(return_value=(None, True)))
        request = _request()
        await _guarded("a2a.read", "agent_id")(request=request, user=_user(db), db=db, agent_id=PUBLIC_ID)
        assert not hasattr(request.state, "trusted_public_a2a_grant")


class TestGrantNarrowsScope:
    """A grant-admitted request runs with public-only scope and no forwarded bearer token."""

    @staticmethod
    def _http_request(granted):
        state = SimpleNamespace(bearer_token="aaaa.bbbb.cccc", authenticated_bearer_token="aaaa.bbbb.cccc")
        if granted:
            state.trusted_public_a2a_grant = True
        return SimpleNamespace(state=state, headers={"authorization": "Bearer aaaa.bbbb.cccc"})

    def test_scope_forced_public_only(self, monkeypatch):
        monkeypatch.setattr("mcpgateway.main.get_scoped_resource_access_context", lambda request, user: (USER, ["team-1"]))
        assert _a2a_access_scope(self._http_request(granted=True), {"email": USER}) == (USER, [])

    def test_scope_unchanged_without_grant(self, monkeypatch):
        monkeypatch.setattr("mcpgateway.main.get_scoped_resource_access_context", lambda request, user: (USER, ["team-1"]))
        assert _a2a_access_scope(self._http_request(granted=False), {"email": USER}) == (USER, ["team-1"])

    def test_mock_state_is_not_a_grant(self, monkeypatch):
        monkeypatch.setattr("mcpgateway.main.get_scoped_resource_access_context", lambda request, user: (USER, ["team-1"]))
        request = SimpleNamespace(state=MagicMock(), headers={})
        assert _a2a_access_scope(request, {"email": USER}) == (USER, ["team-1"])

    def test_bearer_tokens_not_forwarded_under_grant(self, monkeypatch):
        monkeypatch.setattr("mcpgateway.main.get_scoped_resource_access_context", lambda request, user: (USER, None))
        context = _extract_a2a_request_context(self._http_request(granted=True), {"email": USER})
        assert context["token_teams"] == []
        assert context["bearer_token"] is None
        assert context["authenticated_bearer_token"] is None

    def test_bearer_token_kept_without_grant(self, monkeypatch):
        monkeypatch.setattr("mcpgateway.main.get_scoped_resource_access_context", lambda request, user: (USER, None))
        context = _extract_a2a_request_context(self._http_request(granted=False), {"email": USER})
        assert context["bearer_token"] == "aaaa.bbbb.cccc"
