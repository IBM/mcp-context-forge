# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_plugin_binding_bola_fix.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Mock-based security regression tests for plugin binding BOLA fixes.

These tests avoid database writes and verify:
- canonical admin/non-admin team scoping semantics
- explicit cross-team deny paths on router handlers
- list handlers pass allowed_teams through to the service layer
"""

# Standard
from typing import Any
from unittest.mock import MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
import pytest


@pytest.fixture
def mock_db():
    """Mock database session placeholder for router calls."""
    return MagicMock()


def _unwrap_route_handler(func):
    """Return the original route handler beneath auth decorators when available."""
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
    return func


class TestAllowedTeamsHelpers:
    """Canonical token-scoping semantics must match across both routers."""

    @pytest.mark.parametrize(
        ("ctx", "expected"),
        [
            ({"is_admin": True, "token_teams": None}, None),
            ({"is_admin": True, "token_teams": []}, set()),
            ({"is_admin": True, "token_teams": ["team-a"]}, {"team-a"}),
            ({"is_admin": False, "token_teams": None}, set()),
            ({"is_admin": False, "token_teams": []}, set()),
            ({"is_admin": False, "token_teams": ["team-a", "team-b"]}, {"team-a", "team-b"}),
        ],
    )
    def test_a2a_helper_matches_canonical_policy(self, ctx: dict[str, Any], expected: set[str] | None):
        """A2A helper follows canonical admin/public-only semantics."""
        from mcpgateway.routers.a2a_agent_plugin_bindings import _allowed_teams_from_ctx

        assert _allowed_teams_from_ctx(ctx) == expected

    @pytest.mark.parametrize(
        ("ctx", "expected"),
        [
            ({"is_admin": True, "token_teams": None}, None),
            ({"is_admin": True, "token_teams": []}, set()),
            ({"is_admin": True, "token_teams": ["team-a"]}, {"team-a"}),
            ({"is_admin": False, "token_teams": None}, set()),
            ({"is_admin": False, "token_teams": []}, set()),
            ({"is_admin": False, "token_teams": ["team-a", "team-b"]}, {"team-a", "team-b"}),
        ],
    )
    def test_tool_helper_matches_canonical_policy(self, ctx: dict[str, Any], expected: set[str] | None):
        """Tool helper follows canonical admin/public-only semantics."""
        from mcpgateway.routers.tool_plugin_bindings import _allowed_teams_from_ctx

        assert _allowed_teams_from_ctx(ctx) == expected


class TestA2AAgentPluginBindingRouters:
    """Router handlers must enforce deny paths and pass scoped teams to services."""

    @pytest.mark.asyncio
    async def test_list_all_passes_allowed_teams_to_service(self, mock_db):
        from mcpgateway.routers import a2a_agent_plugin_bindings as router_module

        current_user_ctx = {"is_admin": False, "token_teams": ["team-a"], "permissions": ["tools.read"]}
        handler = _unwrap_route_handler(router_module.list_a2a_agent_plugin_bindings)
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            result = await handler(
                current_user_ctx=current_user_ctx,
                db=mock_db,
            )

        assert result.total == 0
        mock_service.list_bindings.assert_called_once_with(
            mock_db,
            team_id=None,
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams={"team-a"},
        )

    @pytest.mark.asyncio
    async def test_list_by_team_returns_empty_scoped_result_for_cross_team_request(self, mock_db):
        from mcpgateway.routers import a2a_agent_plugin_bindings as router_module

        current_user_ctx = {"is_admin": False, "token_teams": ["team-a"], "permissions": ["tools.read"]}
        handler = _unwrap_route_handler(router_module.list_a2a_agent_plugin_bindings_for_team)
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            result = await handler(
                team_id="team-b",
                current_user_ctx=current_user_ctx,
                db=mock_db,
            )

        assert result.total == 0
        assert result.bindings == []
        mock_service.list_bindings.assert_called_once_with(
            mock_db,
            team_id="team-b",
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams={"team-a"},
        )

    @pytest.mark.asyncio
    async def test_list_by_team_allows_unrestricted_admin(self, mock_db):
        from mcpgateway.routers import a2a_agent_plugin_bindings as router_module

        current_user_ctx = {"is_admin": True, "token_teams": None, "permissions": ["tools.read"]}
        handler = _unwrap_route_handler(router_module.list_a2a_agent_plugin_bindings_for_team)
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            await handler(
                team_id="team-b",
                current_user_ctx=current_user_ctx,
                db=mock_db,
            )

        mock_service.list_bindings.assert_called_once_with(
            mock_db,
            team_id="team-b",
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams=None,
        )

    @pytest.mark.asyncio
    async def test_list_by_team_returns_empty_scoped_result_for_admin_with_empty_teams(self, mock_db):
        from mcpgateway.routers import a2a_agent_plugin_bindings as router_module

        current_user_ctx = {"is_admin": True, "token_teams": [], "permissions": ["tools.read"]}
        handler = _unwrap_route_handler(router_module.list_a2a_agent_plugin_bindings_for_team)
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            result = await handler(
                team_id="team-b",
                current_user_ctx=current_user_ctx,
                db=mock_db,
            )

        assert result.total == 0
        assert result.bindings == []
        mock_service.list_bindings.assert_called_once_with(
            mock_db,
            team_id="team-b",
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams=set(),
        )


class TestToolPluginBindingRouters:
    """Tool binding routers must enforce the same scoped-read behavior."""

    @pytest.mark.asyncio
    async def test_list_all_passes_allowed_teams_to_service(self, mock_db):
        from mcpgateway.routers import tool_plugin_bindings as router_module

        current_user_ctx = {"is_admin": False, "token_teams": ["team-a"], "permissions": ["tools.read"]}
        handler = _unwrap_route_handler(router_module.list_tool_plugin_bindings)
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = []

            result = await handler(
                current_user_ctx=current_user_ctx,
                db=mock_db,
            )

        assert result.total == 0
        mock_service.list_bindings.assert_called_once_with(
            mock_db,
            team_id=None,
            binding_reference_id=None,
            allowed_teams={"team-a"},
        )

    @pytest.mark.asyncio
    async def test_list_by_team_rejects_cross_team_request(self, mock_db):
        from mcpgateway.routers import tool_plugin_bindings as router_module

        current_user_ctx = {"is_admin": False, "token_teams": ["team-a"], "permissions": ["tools.read"]}
        handler = _unwrap_route_handler(router_module.list_tool_plugin_bindings_for_team)

        with pytest.raises(HTTPException) as exc_info:
            await handler(
                team_id="team-b",
                current_user_ctx=current_user_ctx,
                db=mock_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_list_by_team_allows_unrestricted_admin(self, mock_db):
        from mcpgateway.routers import tool_plugin_bindings as router_module

        current_user_ctx = {"is_admin": True, "token_teams": None, "permissions": ["tools.read"]}
        handler = _unwrap_route_handler(router_module.list_tool_plugin_bindings_for_team)
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = []

            await handler(
                team_id="team-b",
                current_user_ctx=current_user_ctx,
                db=mock_db,
            )

        mock_service.list_bindings.assert_called_once_with(
            mock_db,
            team_id="team-b",
            binding_reference_id=None,
            allowed_teams=None,
        )

    @pytest.mark.asyncio
    async def test_list_by_team_rejects_admin_with_empty_teams(self, mock_db):
        from mcpgateway.routers import tool_plugin_bindings as router_module

        current_user_ctx = {"is_admin": True, "token_teams": [], "permissions": ["tools.read"]}
        handler = _unwrap_route_handler(router_module.list_tool_plugin_bindings_for_team)

        with pytest.raises(HTTPException) as exc_info:
            await handler(
                team_id="team-b",
                current_user_ctx=current_user_ctx,
                db=mock_db,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
