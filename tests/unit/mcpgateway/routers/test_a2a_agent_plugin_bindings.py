# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_a2a_agent_plugin_bindings.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the A2A agent plugin bindings router.

Tests cover:
    - POST / (upsert): success, validation errors
    - GET / (list all): scoped reads and empty responses
    - GET /{team_id}: filtered list, empty, and deny-path behavior
    - DELETE /{binding_id}: success, not found, forbidden (non-admin foreign team)
    - DELETE / (by reference): non-admin scoped to own teams
"""

# Standard
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
import pytest

# First-Party
from mcpgateway.routers.a2a_agent_plugin_bindings import (
    delete_a2a_agent_plugin_binding,
    delete_a2a_agent_plugin_bindings_by_reference,
    list_a2a_agent_plugin_bindings,
    list_a2a_agent_plugin_bindings_for_team,
    upsert_a2a_agent_plugin_binding,
)
from mcpgateway.schemas import A2AAgentPluginBindingListResponse, A2AAgentPluginBindingRequest, A2AAgentPluginBindingResponse

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


@pytest.fixture
def db_session() -> MagicMock:
    """Mock database session for router unit tests."""
    return MagicMock()


@pytest.fixture
def user_ctx(db_session: MagicMock) -> dict[str, Any]:
    return {
        "email": "admin@example.com",
        "full_name": "Admin User",
        "is_admin": True,
        "token_teams": None,
        "db": db_session,
        "permissions": ["tools.manage_plugins", "tools.read"],
    }


def _make_request(
    agent_name: str = "agent_x",
    plugin_id: str = "OutputLengthGuardPlugin",
    mode: str = "enforce",
    priority: int = 50,
    config: dict[str, Any] | None = None,
    on_error: str | None = None,
) -> A2AAgentPluginBindingRequest:
    return A2AAgentPluginBindingRequest(
        agent_name=agent_name,
        plugin_id=plugin_id,
        mode=mode,
        priority=priority,
        config=config or {"enabled": True},
        on_error=on_error,
    )


class TestA2AAgentPluginBindingsRouter:
    @pytest.fixture(autouse=True)
    def setup_rbac_mocks(self) -> Any:
        originals = patch_rbac_decorators()
        yield
        restore_rbac_decorators(originals)

    # ------------------------------------------------------------------
    # POST / — upsert
    # ------------------------------------------------------------------

    def _make_binding_response(
        self,
        *,
        binding_id: str = "binding-1",
        team_id: str = "team-a",
        agent_name: str = "agent_x",
        plugin_id: str = "OutputLengthGuardPlugin",
        mode: str = "enforce",
        priority: int = 50,
        config: dict[str, Any] | None = None,
        created_by: str = "admin@example.com",
        updated_by: str = "admin@example.com",
        binding_reference_id: str | None = None,
    ) -> A2AAgentPluginBindingResponse:
        now = datetime.now(timezone.utc)
        return A2AAgentPluginBindingResponse(
            id=binding_id,
            team_id=team_id,
            agent_name=agent_name,
            plugin_id=plugin_id,
            mode=mode,
            priority=priority,
            config=config or {"enabled": True},
            on_error=None,
            binding_reference_id=binding_reference_id,
            created_at=now,
            created_by=created_by,
            updated_at=now,
            updated_by=updated_by,
        )

    @pytest.mark.asyncio
    async def test_upsert_success(self, user_ctx: dict[str, Any], db_session: MagicMock) -> None:
        request = _make_request()
        expected = self._make_binding_response()
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service, patch(
            "mcpgateway.routers.a2a_agent_plugin_bindings._invalidate_and_broadcast",
            new_callable=AsyncMock,
        ) as mock_invalidate:
            mock_service.upsert_binding.return_value = expected

            result = await upsert_a2a_agent_plugin_binding(
                request=request,
                current_user_ctx=user_ctx,
                db=db_session,
                team_id="team-a",
            )

        assert isinstance(result, A2AAgentPluginBindingResponse)
        assert result.team_id == "team-a"
        assert result.agent_name == "agent_x"
        assert result.plugin_id == "OutputLengthGuardPlugin"
        assert result.mode == "enforce"
        assert result.priority == 50
        assert result.created_by == "admin@example.com"
        mock_service.upsert_binding.assert_called_once()
        db_session.commit.assert_called_once()
        mock_invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_idempotent_update(self, user_ctx: dict[str, Any], db_session: MagicMock) -> None:
        request = _make_request()
        first = self._make_binding_response(mode="enforce", priority=50, config={"enabled": True})
        second = self._make_binding_response(mode="permissive", priority=99, config={"enabled": True, "max_chars": 500})

        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service, patch(
            "mcpgateway.routers.a2a_agent_plugin_bindings._invalidate_and_broadcast",
            new_callable=AsyncMock,
        ):
            mock_service.upsert_binding.side_effect = [first, second]

            result1 = await upsert_a2a_agent_plugin_binding(
                request=request,
                current_user_ctx=user_ctx,
                db=db_session,
                team_id="team-a",
            )
            request2 = _make_request(mode="permissive", priority=99, config={"enabled": True, "max_chars": 500})
            result2 = await upsert_a2a_agent_plugin_binding(
                request=request2,
                current_user_ctx=user_ctx,
                db=db_session,
                team_id="team-a",
            )

        assert result2.id == result1.id
        assert result2.mode == "permissive"
        assert result2.priority == 99
        assert result2.config["max_chars"] == 500

    @pytest.mark.asyncio
    async def test_upsert_wildcard_agent(self, user_ctx: dict[str, Any], db_session: MagicMock) -> None:
        request = _make_request(agent_name="*", plugin_id="RateLimiterPlugin")
        expected = self._make_binding_response(agent_name="*", plugin_id="RateLimiterPlugin")
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service, patch(
            "mcpgateway.routers.a2a_agent_plugin_bindings._invalidate_and_broadcast",
            new_callable=AsyncMock,
        ):
            mock_service.upsert_binding.return_value = expected

            result = await upsert_a2a_agent_plugin_binding(
                request=request,
                current_user_ctx=user_ctx,
                db=db_session,
                team_id="team-a",
            )
        assert result.agent_name == "*"

    @pytest.mark.asyncio
    async def test_upsert_forbidden_team(self, user_ctx: dict[str, Any], db_session: MagicMock) -> None:
        non_admin_ctx = {**user_ctx, "is_admin": False, "token_teams": {"team-b"}}
        request = _make_request()
        # Third-Party
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await upsert_a2a_agent_plugin_binding(
                request=request,
                current_user_ctx=non_admin_ctx,
                db=db_session,
                team_id="team-a",
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_upsert_value_error(self, user_ctx: dict[str, Any], db_session: MagicMock) -> None:
        """ValueError from the service is converted to HTTP 400."""
        # Third-Party
        from fastapi import HTTPException

        # First-Party
        from mcpgateway.routers.a2a_agent_plugin_bindings import _service

        with patch.object(_service, "upsert_binding", side_effect=ValueError("invalid config")):
            with pytest.raises(HTTPException) as exc:
                await upsert_a2a_agent_plugin_binding(
                    request=_make_request(config={"invalid": object()}),
                    current_user_ctx=user_ctx,
                    db=db_session,
                    team_id="team-a",
                )
        assert exc.value.status_code == 400

    # ------------------------------------------------------------------
    # GET / — list all
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_all_empty(self, user_ctx: dict[str, Any], db_session: MagicMock) -> None:
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            result = await list_a2a_agent_plugin_bindings(
                current_user_ctx=user_ctx,
                db=db_session,
            )

        assert isinstance(result, A2AAgentPluginBindingListResponse)
        assert result.total == 0
        assert result.bindings == []
        mock_service.list_bindings.assert_called_once_with(
            db_session,
            team_id=None,
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams=None,
        )

    @pytest.mark.asyncio
    async def test_list_all_scopes_non_admin_to_allowed_teams(self, db_session: MagicMock) -> None:
        non_admin_ctx = {
            "email": "member@example.com",
            "full_name": "Member User",
            "is_admin": False,
            "token_teams": ["team-a"],
            "db": db_session,
            "permissions": ["tools.read"],
        }
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            result = await list_a2a_agent_plugin_bindings(
                current_user_ctx=non_admin_ctx,
                db=db_session,
            )

        assert result.total == 0
        mock_service.list_bindings.assert_called_once_with(
            db_session,
            team_id=None,
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams={"team-a"},
        )

    @pytest.mark.asyncio
    async def test_list_all_filtered_by_reference(self, user_ctx, db_session):
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 1)

            result = await list_a2a_agent_plugin_bindings(
                current_user_ctx=user_ctx,
                db=db_session,
                binding_reference_id="ref-001",
            )

        assert result.total == 1
        mock_service.list_bindings.assert_called_once_with(
            db_session,
            team_id=None,
            binding_reference_id="ref-001",
            limit=100,
            offset=0,
            allowed_teams=None,
        )

    # ------------------------------------------------------------------
    # GET /{team_id} — list by team
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_by_team(self, user_ctx, db_session):
        expected = self._make_binding_response(agent_name="agent_team-a")
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([expected], 1)

            result = await list_a2a_agent_plugin_bindings_for_team(
                team_id="team-a",
                current_user_ctx=user_ctx,
                db=db_session,
            )

        assert result.total == 1
        assert result.bindings[0].team_id == "team-a"
        mock_service.list_bindings.assert_called_once_with(
            db_session,
            team_id="team-a",
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams=None,
        )

    @pytest.mark.asyncio
    async def test_list_by_team_empty(self, user_ctx, db_session):
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            result = await list_a2a_agent_plugin_bindings_for_team(
                team_id="team-nonexistent",
                current_user_ctx=user_ctx,
                db=db_session,
            )

        assert result.total == 0
        mock_service.list_bindings.assert_called_once_with(
            db_session,
            team_id="team-nonexistent",
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams=None,
        )

    @pytest.mark.asyncio
    async def test_list_by_team_non_member_returns_empty_via_scoping(self, db_session):
        non_admin_ctx = {
            "email": "member@example.com",
            "full_name": "Member User",
            "is_admin": False,
            "token_teams": ["team-a"],
            "db": db_session,
            "permissions": ["tools.read"],
        }
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            result = await list_a2a_agent_plugin_bindings_for_team(
                team_id="team-b",
                current_user_ctx=non_admin_ctx,
                db=db_session,
            )

        assert result.total == 0
        assert result.bindings == []
        mock_service.list_bindings.assert_called_once_with(
            db_session,
            team_id="team-b",
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams={"team-a"},
        )

    @pytest.mark.asyncio
    async def test_list_by_team_admin_with_empty_token_teams_returns_empty_scoped_result(self, db_session):
        admin_ctx = {
            "email": "admin@example.com",
            "full_name": "Admin User",
            "is_admin": True,
            "token_teams": [],
            "db": db_session,
            "permissions": ["tools.read"],
        }
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            mock_service.list_bindings.return_value = ([], 0)

            result = await list_a2a_agent_plugin_bindings_for_team(
                team_id="team-a",
                current_user_ctx=admin_ctx,
                db=db_session,
            )

        assert result.total == 0
        assert result.bindings == []
        mock_service.list_bindings.assert_called_once_with(
            db_session,
            team_id="team-a",
            binding_reference_id=None,
            limit=100,
            offset=0,
            allowed_teams=set(),
        )

    # ------------------------------------------------------------------
    # DELETE /{binding_id} — delete by UUID
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_by_id_success(self, user_ctx, db_session):
        created = self._make_binding_response()
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service, patch(
            "mcpgateway.routers.a2a_agent_plugin_bindings._invalidate_and_broadcast",
            new_callable=AsyncMock,
        ) as mock_invalidate:
            mock_service.delete_binding.return_value = created

            deleted = await delete_a2a_agent_plugin_binding(
                binding_id=created.id,
                current_user_ctx=user_ctx,
                db=db_session,
            )

        assert isinstance(deleted, A2AAgentPluginBindingResponse)
        assert deleted.id == created.id
        mock_service.delete_binding.assert_called_once_with(db_session, created.id, allowed_teams=None)
        db_session.commit.assert_called_once()
        mock_invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_by_id_not_found(self, user_ctx, db_session):
        # Third-Party
        from fastapi import HTTPException

        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            from mcpgateway.services.a2a_agent_plugin_binding_service import A2AAgentPluginBindingNotFoundError

            mock_service.delete_binding.side_effect = A2AAgentPluginBindingNotFoundError("not found")
            with pytest.raises(HTTPException) as exc:
                await delete_a2a_agent_plugin_binding(
                    binding_id="nonexistent",
                    current_user_ctx=user_ctx,
                    db=db_session,
                )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_by_id_forbidden_non_admin(self, user_ctx, db_session):
        # Third-Party
        from fastapi import HTTPException

        user_ctx_b = {**user_ctx, "is_admin": False, "token_teams": {"team-b"}}
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service:
            from mcpgateway.services.a2a_agent_plugin_binding_service import A2AAgentPluginBindingForbiddenError

            mock_service.delete_binding.side_effect = A2AAgentPluginBindingForbiddenError("forbidden")
            with pytest.raises(HTTPException) as exc:
                await delete_a2a_agent_plugin_binding(
                    binding_id="binding-1",
                    current_user_ctx=user_ctx_b,
                    db=db_session,
                )
        assert exc.value.status_code == 403

    # ------------------------------------------------------------------
    # DELETE / — delete by external reference ID
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_by_reference_success(self, user_ctx, db_session):
        deleted_binding = self._make_binding_response(binding_reference_id="ref-001")
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service, patch(
            "mcpgateway.routers.a2a_agent_plugin_bindings._invalidate_and_broadcast",
            new_callable=AsyncMock,
        ) as mock_invalidate:
            mock_service.delete_bindings_by_reference.return_value = [deleted_binding]

            deleted = await delete_a2a_agent_plugin_bindings_by_reference(
                binding_reference_id="ref-001",
                current_user_ctx=user_ctx,
                db=db_session,
            )

        assert isinstance(deleted, A2AAgentPluginBindingListResponse)
        assert deleted.total == 1
        assert deleted.bindings[0].agent_name == "agent_x"
        mock_service.delete_bindings_by_reference.assert_called_once_with(db_session, "ref-001", allowed_teams=None)
        db_session.commit.assert_called_once()
        mock_invalidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_by_reference_scoped_to_team(self, user_ctx, db_session):
        deleted_binding = self._make_binding_response(team_id="team-a", binding_reference_id="ref-001")
        user_ctx_a = {**user_ctx, "is_admin": False, "token_teams": {"team-a"}}
        with patch("mcpgateway.routers.a2a_agent_plugin_bindings._service") as mock_service, patch(
            "mcpgateway.routers.a2a_agent_plugin_bindings._invalidate_and_broadcast",
            new_callable=AsyncMock,
        ):
            mock_service.delete_bindings_by_reference.return_value = [deleted_binding]

            deleted = await delete_a2a_agent_plugin_bindings_by_reference(
                binding_reference_id="ref-001",
                current_user_ctx=user_ctx_a,
                db=db_session,
            )

        assert deleted.total == 1
        assert deleted.bindings[0].team_id == "team-a"
        mock_service.delete_bindings_by_reference.assert_called_once_with(db_session, "ref-001", allowed_teams={"team-a"})
