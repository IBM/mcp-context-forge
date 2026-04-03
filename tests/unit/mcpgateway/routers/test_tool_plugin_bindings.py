# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_tool_plugin_bindings.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

Unit tests for the tool plugin bindings router.

Tests cover:
    - POST /  (upsert): success, service exception → 400
    - GET /   (list all): success
    - GET /{team_id} (list by team): success
    - DELETE /{binding_id}: success → 204, not found → 404
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.schemas import (
    PluginBindingMode,
    PluginId,
    PluginPolicyItem,
    TeamPolicies,
    ToolPluginBindingListResponse,
    ToolPluginBindingRequest,
    ToolPluginBindingResponse,
)
from mcpgateway.services.tool_plugin_binding_service import ToolPluginBindingNotFoundError

from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_binding_response(
    id_="binding-001",
    team_id="team-a",
    tool_name="tool_x",
    plugin_id="OUTPUT_LENGTH_GUARD",
    mode="enforce",
    priority=50,
) -> ToolPluginBindingResponse:
    """Build a minimal ToolPluginBindingResponse."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ToolPluginBindingResponse(
        id=id_,
        team_id=team_id,
        tool_name=tool_name,
        plugin_id=plugin_id,
        mode=mode,
        priority=priority,
        config={"max_chars": 2000, "strategy": "truncate"},
        created_at=now,
        created_by="admin@example.com",
        updated_at=now,
        updated_by="admin@example.com",
    )


def _make_list_response(bindings=None) -> ToolPluginBindingListResponse:
    """Build a ToolPluginBindingListResponse from a list of response objects."""
    if bindings is None:
        bindings = [_make_binding_response()]
    return ToolPluginBindingListResponse(bindings=bindings, total=len(bindings))


def _simple_request() -> ToolPluginBindingRequest:
    """Return a minimal single-team single-tool POST payload."""
    return ToolPluginBindingRequest(
        teams={
            "team-a": TeamPolicies(
                policies=[
                    PluginPolicyItem(
                        tool_names=["tool_x"],
                        plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                        mode=PluginBindingMode.ENFORCE,
                        priority=50,
                        config={"min_chars": 0, "max_chars": 2000, "strategy": "truncate", "ellipsis": "..."},
                    )
                ]
            )
        }
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestToolPluginBindingsRouter:
    """Unit tests for the tool plugin bindings FastAPI router."""

    @pytest.fixture(autouse=True)
    def setup_rbac_mocks(self):
        """Bypass RBAC decorators for every test in this class."""
        originals = patch_rbac_decorators()
        yield
        restore_rbac_decorators(originals)

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_user_ctx(self, mock_db):
        """Mock user context with plugin management permissions."""
        return {
            "email": "admin@example.com",
            "full_name": "Admin User",
            "is_admin": True,
            "db": mock_db,
            "permissions": ["tools.manage_plugins", "tools.read"],
        }

    # ------------------------------------------------------------------
    # POST / — upsert_tool_plugin_bindings
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_upsert_success(self, mock_user_ctx, mock_db):
        """POST with valid payload returns 200 with the upserted bindings."""
        expected_response = _make_list_response()

        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.upsert_bindings.return_value = expected_response.bindings

            from mcpgateway.routers.tool_plugin_bindings import upsert_tool_plugin_bindings

            result = await upsert_tool_plugin_bindings(
                request=_simple_request(),
                current_user_ctx=mock_user_ctx,
                db=mock_db,
            )

        assert isinstance(result, ToolPluginBindingListResponse)
        assert result.total == 1
        assert result.bindings[0].team_id == "team-a"
        mock_svc.upsert_bindings.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_passes_caller_email(self, mock_user_ctx, mock_db):
        """POST extracts caller email from user context and passes it to the service."""
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.upsert_bindings.return_value = [_make_binding_response()]

            from mcpgateway.routers.tool_plugin_bindings import upsert_tool_plugin_bindings

            await upsert_tool_plugin_bindings(
                request=_simple_request(),
                current_user_ctx=mock_user_ctx,
                db=mock_db,
            )

        _, call_kwargs = mock_svc.upsert_bindings.call_args
        assert call_kwargs.get("caller_email") == "admin@example.com"

    @pytest.mark.asyncio
    async def test_upsert_service_exception_raises_400(self, mock_user_ctx, mock_db):
        """POST raises HTTP 400 when the service layer throws an exception."""
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.upsert_bindings.side_effect = ValueError("team not found")

            from mcpgateway.routers.tool_plugin_bindings import upsert_tool_plugin_bindings

            with pytest.raises(HTTPException) as exc_info:
                await upsert_tool_plugin_bindings(
                    request=_simple_request(),
                    current_user_ctx=mock_user_ctx,
                    db=mock_db,
                )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "team not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_upsert_missing_email_in_context_raises_400(self, mock_db):
        """POST raises HTTP 400 when 'email' key is absent from user context.

        The auth middleware always populates 'email', so a missing key indicates
        a broken auth pipeline. The router catches the resulting KeyError via
        its broad except clause and surfaces it as 400.
        """
        user_ctx_no_email = {"is_admin": True, "db": mock_db}  # no 'email' key

        with patch("mcpgateway.routers.tool_plugin_bindings._service"):
            from mcpgateway.routers.tool_plugin_bindings import upsert_tool_plugin_bindings

            with pytest.raises(HTTPException) as exc_info:
                await upsert_tool_plugin_bindings(
                    request=_simple_request(),
                    current_user_ctx=user_ctx_no_email,
                    db=mock_db,
                )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    # ------------------------------------------------------------------
    # GET / — list_tool_plugin_bindings
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_all_success(self, mock_user_ctx, mock_db):
        """GET / returns all bindings with correct total count."""
        bindings = [_make_binding_response("b1"), _make_binding_response("b2")]

        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.list_bindings.return_value = bindings

            from mcpgateway.routers.tool_plugin_bindings import list_tool_plugin_bindings

            result = await list_tool_plugin_bindings(
                current_user_ctx=mock_user_ctx,
                db=mock_db,
            )

        assert isinstance(result, ToolPluginBindingListResponse)
        assert result.total == 2
        assert len(result.bindings) == 2
        mock_svc.list_bindings.assert_called_once_with(mock_db, team_id=None)

    @pytest.mark.asyncio
    async def test_list_all_empty(self, mock_user_ctx, mock_db):
        """GET / returns total=0 when no bindings exist."""
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.list_bindings.return_value = []

            from mcpgateway.routers.tool_plugin_bindings import list_tool_plugin_bindings

            result = await list_tool_plugin_bindings(
                current_user_ctx=mock_user_ctx,
                db=mock_db,
            )

        assert result.total == 0
        assert result.bindings == []

    # ------------------------------------------------------------------
    # GET /{team_id} — list_tool_plugin_bindings_for_team
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_by_team_success(self, mock_user_ctx, mock_db):
        """GET /{team_id} filters bindings by team and returns correct results."""
        binding = _make_binding_response(team_id="team-a")

        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.list_bindings.return_value = [binding]

            from mcpgateway.routers.tool_plugin_bindings import list_tool_plugin_bindings_for_team

            result = await list_tool_plugin_bindings_for_team(
                team_id="team-a",
                current_user_ctx=mock_user_ctx,
                db=mock_db,
            )

        assert result.total == 1
        assert result.bindings[0].team_id == "team-a"
        mock_svc.list_bindings.assert_called_once_with(mock_db, team_id="team-a")

    @pytest.mark.asyncio
    async def test_list_by_team_empty(self, mock_user_ctx, mock_db):
        """GET /{team_id} returns empty list when team has no bindings."""
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.list_bindings.return_value = []

            from mcpgateway.routers.tool_plugin_bindings import list_tool_plugin_bindings_for_team

            result = await list_tool_plugin_bindings_for_team(
                team_id="team-unknown",
                current_user_ctx=mock_user_ctx,
                db=mock_db,
            )

        assert result.total == 0
        assert result.bindings == []

    # ------------------------------------------------------------------
    # DELETE /{binding_id} — delete_tool_plugin_binding
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_user_ctx, mock_db):
        """DELETE with valid ID returns the deleted binding details (200)."""
        deleted_binding = _make_binding_response()
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.delete_binding.return_value = deleted_binding

            from mcpgateway.routers.tool_plugin_bindings import delete_tool_plugin_binding

            result = await delete_tool_plugin_binding(
                binding_id="binding-001",
                current_user_ctx=mock_user_ctx,
                db=mock_db,
            )

        assert result.id == deleted_binding.id
        assert result.team_id == deleted_binding.team_id
        mock_svc.delete_binding.assert_called_once_with(mock_db, "binding-001")

    @pytest.mark.asyncio
    async def test_delete_not_found_raises_404(self, mock_user_ctx, mock_db):
        """DELETE raises HTTP 404 when the binding does not exist."""
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.delete_binding.side_effect = ToolPluginBindingNotFoundError("Tool plugin binding 'xyz' not found")

            from mcpgateway.routers.tool_plugin_bindings import delete_tool_plugin_binding

            with pytest.raises(HTTPException) as exc_info:
                await delete_tool_plugin_binding(
                    binding_id="xyz",
                    current_user_ctx=mock_user_ctx,
                    db=mock_db,
                )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "xyz" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_is_coroutine(self):
        """All router functions are async (coroutine functions)."""
        import asyncio
        from mcpgateway.routers.tool_plugin_bindings import (
            delete_tool_plugin_binding,
            list_tool_plugin_bindings,
            list_tool_plugin_bindings_for_team,
            upsert_tool_plugin_bindings,
        )

        assert asyncio.iscoroutinefunction(upsert_tool_plugin_bindings)
        assert asyncio.iscoroutinefunction(list_tool_plugin_bindings)
        assert asyncio.iscoroutinefunction(list_tool_plugin_bindings_for_team)
        assert asyncio.iscoroutinefunction(delete_tool_plugin_binding)
