# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_tool_plugin_bindings.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

Unit tests for the tool plugin bindings router.

Uses an in-memory SQLite database and the real ToolPluginBindingService so
tests exercise the full stack from router handler down to SQL, with no mocked
service responses.

Tests cover:
    - POST /  (upsert): success, service exception → 400
    - GET /   (list all): success, empty
    - GET /{team_id}: filtered list, empty
    - DELETE /{binding_id}: success → 200, not found → 404
"""

# Standard
import asyncio
from unittest.mock import patch

# Third-Party
from fastapi import HTTPException, status
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base
from mcpgateway.routers.tool_plugin_bindings import (
    delete_tool_plugin_binding,
    delete_tool_plugin_bindings_by_reference,
    list_tool_plugin_bindings,
    list_tool_plugin_bindings_for_team,
    upsert_tool_plugin_bindings,
)
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    """In-memory SQLite session shared across all connections within one test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def user_ctx(db_session):
    """Authenticated admin user context wired to the real DB session."""
    return {
        "email": "admin@example.com",
        "full_name": "Admin User",
        "is_admin": True,
        "db": db_session,
        "permissions": ["tools.manage_plugins", "tools.read"],
    }


# ---------------------------------------------------------------------------
# Canonical full-field configs (must include all schema fields)
# ---------------------------------------------------------------------------

_OLG: dict = {
    "min_chars": 0, "max_chars": 2000, "min_tokens": 0, "max_tokens": None,
    "chars_per_token": 4, "limit_mode": "character", "strategy": "truncate",
    "ellipsis": "\u2026", "word_boundary": False, "max_text_length": 1_000_000,
    "max_structure_size": 10_000, "max_recursion_depth": 100,
}
_RL: dict = {
    "by_user": None, "by_tenant": None, "by_tool": None,
    "algorithm": "fixed_window", "backend": "memory",
    "redis_url": None, "redis_key_prefix": "rl", "redis_fallback": True,
}


def _simple_request() -> ToolPluginBindingRequest:
    """Minimal single-team single-tool POST payload."""
    return ToolPluginBindingRequest(
        teams={
            "team-a": TeamPolicies(
                policies=[
                    PluginPolicyItem(
                        tool_names=["tool_x"],
                        plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                        mode=PluginBindingMode.ENFORCE,
                        priority=50,
                        config=dict(_OLG),
                    )
                ]
            )
        }
    )


def _two_team_request() -> ToolPluginBindingRequest:
    """Two-team two-tool POST payload for list/filter tests."""
    return ToolPluginBindingRequest(
        teams={
            "team-a": TeamPolicies(
                policies=[
                    PluginPolicyItem(
                        tool_names=["tool_x"],
                        plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                        mode=PluginBindingMode.ENFORCE,
                        priority=50,
                        config=dict(_OLG),
                    )
                ]
            ),
            "team-b": TeamPolicies(
                policies=[
                    PluginPolicyItem(
                        tool_names=["tool_y"],
                        plugin_id=PluginId.RATE_LIMITER,
                        mode=PluginBindingMode.PERMISSIVE,
                        priority=30,
                        config={**_RL, "by_user": "60/m", "by_tenant": "600/m"},
                    )
                ]
            ),
        }
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestToolPluginBindingsRouter:
    """Router tests using in-memory SQLite and the real service."""

    @pytest.fixture(autouse=True)
    def setup_rbac_mocks(self):
        """Bypass RBAC decorators for every test in this class."""
        originals = patch_rbac_decorators()
        yield
        restore_rbac_decorators(originals)

    # ------------------------------------------------------------------
    # POST / — upsert_tool_plugin_bindings
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_upsert_success(self, user_ctx, db_session):
        """POST with valid payload inserts a row and returns it in the response."""
        result = await upsert_tool_plugin_bindings(
            request=_simple_request(),
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert isinstance(result, ToolPluginBindingListResponse)
        assert result.total == 1
        binding = result.bindings[0]
        assert binding.team_id == "team-a"
        assert binding.tool_name == "tool_x"
        assert binding.plugin_id == "OUTPUT_LENGTH_GUARD"
        assert binding.mode == "enforce"
        assert binding.priority == 50
        assert binding.created_by == "admin@example.com"

    @pytest.mark.asyncio
    async def test_upsert_idempotent_update(self, user_ctx, db_session):
        """POST twice on the same (team, tool, plugin) updates in place — no duplicate rows."""
        await upsert_tool_plugin_bindings(
            request=_simple_request(),
            current_user_ctx=user_ctx,
            db=db_session,
        )
        updated_request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=99,
                            config={**_OLG, "max_chars": 500, "strategy": "block"},
                        )
                    ]
                )
            }
        )
        result = await upsert_tool_plugin_bindings(
            request=updated_request,
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert result.total == 1
        binding = result.bindings[0]
        assert binding.mode == "permissive"
        assert binding.priority == 99
        assert binding.config["max_chars"] == 500

    @pytest.mark.asyncio
    async def test_upsert_service_value_error_raises_400(self, user_ctx, db_session):
        """Router maps ValueError from the service layer to HTTP 400 Bad Request.

        ValueError signals bad input (e.g. invalid plugin config) — that is a
        client error and 400 is correct. Other exception types are not caught
        and propagate as 500, so only ValueError gets this treatment.
        We patch the service singleton to inject a controlled ValueError since
        there is no real data path that triggers it with a Pydantic-validated payload.
        """
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.upsert_bindings.side_effect = ValueError("invalid plugin config")

            with pytest.raises(HTTPException) as exc_info:
                await upsert_tool_plugin_bindings(
                    request=_simple_request(),
                    current_user_ctx=user_ctx,
                    db=db_session,
                )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "invalid plugin config" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_upsert_unexpected_exception_propagates_as_500(self, user_ctx, db_session):
        """Unexpected exceptions from the service layer are NOT caught by the router.

        Only ValueError is caught and mapped to 400. A RuntimeError (or any other
        non-ValueError exception) propagates uncaught, which FastAPI renders as 500.
        """
        with patch("mcpgateway.routers.tool_plugin_bindings._service") as mock_svc:
            mock_svc.upsert_bindings.side_effect = RuntimeError("unexpected bug")

            with pytest.raises(RuntimeError, match="unexpected bug"):
                await upsert_tool_plugin_bindings(
                    request=_simple_request(),
                    current_user_ctx=user_ctx,
                    db=db_session,
                )

    @pytest.mark.asyncio
    async def test_upsert_non_admin_own_team_succeeds(self, db_session):
        """Non-admin with membership in the target team can create bindings."""
        non_admin_ctx = {
            "email": "member@example.com",
            "full_name": "Team Member",
            "is_admin": False,
            "teams": ["team-a"],
            "db": db_session,
            "permissions": ["tools.manage_plugins"],
        }
        result = await upsert_tool_plugin_bindings(
            request=_simple_request(),
            current_user_ctx=non_admin_ctx,
            db=db_session,
        )
        assert result.total == 1
        assert result.bindings[0].team_id == "team-a"

    @pytest.mark.asyncio
    async def test_upsert_non_admin_foreign_team_raises_403(self, db_session):
        """Non-admin cannot create bindings for a team they don't belong to."""
        non_admin_ctx = {
            "email": "outsider@example.com",
            "full_name": "Outsider",
            "is_admin": False,
            "teams": ["team-b"],
            "db": db_session,
            "permissions": ["tools.manage_plugins"],
        }
        with pytest.raises(HTTPException) as exc_info:
            await upsert_tool_plugin_bindings(
                request=_simple_request(),  # targets team-a
                current_user_ctx=non_admin_ctx,
                db=db_session,
            )
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc_info.value.detail == "Not authorized to configure bindings for team(s): team-a"

    @pytest.mark.asyncio
    async def test_upsert_admin_can_target_any_team(self, user_ctx, db_session):
        """Platform admin (is_admin=True) bypasses team membership check."""
        result = await upsert_tool_plugin_bindings(
            request=_two_team_request(),
            current_user_ctx=user_ctx,  # is_admin=True, no explicit team list
            db=db_session,
        )
        assert result.total == 2

    # ------------------------------------------------------------------
    # GET / — list_tool_plugin_bindings
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_all_empty(self, user_ctx, db_session):
        """GET / returns total=0 when no bindings have been inserted."""
        result = await list_tool_plugin_bindings(
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert isinstance(result, ToolPluginBindingListResponse)
        assert result.total == 0
        assert result.bindings == []

    @pytest.mark.asyncio
    async def test_list_all_returns_all_bindings(self, user_ctx, db_session):
        """GET / returns all bindings across all teams with correct field values."""
        await upsert_tool_plugin_bindings(
            request=_two_team_request(),
            current_user_ctx=user_ctx,
            db=db_session,
        )

        result = await list_tool_plugin_bindings(
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert result.total == 2
        by_team = {b.team_id: b for b in result.bindings}
        assert set(by_team.keys()) == {"team-a", "team-b"}

        team_a = by_team["team-a"]
        assert team_a.tool_name == "tool_x"
        assert team_a.plugin_id == "OUTPUT_LENGTH_GUARD"
        assert team_a.mode == "enforce"
        assert team_a.priority == 50
        assert team_a.config == _OLG
        assert team_a.created_by == "admin@example.com"

        team_b = by_team["team-b"]
        assert team_b.tool_name == "tool_y"
        assert team_b.plugin_id == "RATE_LIMITER"
        assert team_b.mode == "permissive"
        assert team_b.priority == 30
        assert team_b.config == {**_RL, "by_user": "60/m", "by_tenant": "600/m"}
        assert team_b.created_by == "admin@example.com"

    # ------------------------------------------------------------------
    # GET /{team_id} — list_tool_plugin_bindings_for_team
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_by_team_filters_correctly(self, user_ctx, db_session):
        """GET /{team_id} returns only bindings for that team with correct field values."""
        await upsert_tool_plugin_bindings(
            request=_two_team_request(),
            current_user_ctx=user_ctx,
            db=db_session,
        )

        result = await list_tool_plugin_bindings_for_team(
            team_id="team-a",
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert result.total == 1
        binding = result.bindings[0]
        assert binding.team_id == "team-a"
        assert binding.tool_name == "tool_x"
        assert binding.plugin_id == "OUTPUT_LENGTH_GUARD"
        assert binding.mode == "enforce"
        assert binding.priority == 50
        assert binding.config == _OLG
        assert binding.created_by == "admin@example.com"

    @pytest.mark.asyncio
    async def test_list_by_team_empty_for_unknown_team(self, user_ctx, db_session):
        """GET /{team_id} returns empty list for a team with no bindings."""
        await upsert_tool_plugin_bindings(
            request=_simple_request(),
            current_user_ctx=user_ctx,
            db=db_session,
        )

        result = await list_tool_plugin_bindings_for_team(
            team_id="team-unknown",
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert result.total == 0
        assert result.bindings == []

    # ------------------------------------------------------------------
    # DELETE /{binding_id} — delete_tool_plugin_binding
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_success(self, user_ctx, db_session):
        """DELETE removes the binding and returns its details."""
        upsert_result = await upsert_tool_plugin_bindings(
            request=_simple_request(),
            current_user_ctx=user_ctx,
            db=db_session,
        )
        binding_id = upsert_result.bindings[0].id

        result = await delete_tool_plugin_binding(
            binding_id=binding_id,
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert isinstance(result, ToolPluginBindingResponse)
        assert result.id == binding_id
        assert result.team_id == "team-a"
        assert result.tool_name == "tool_x"

        # Confirm it's gone
        after = await list_tool_plugin_bindings(
            current_user_ctx=user_ctx,
            db=db_session,
        )
        assert after.total == 0

    @pytest.mark.asyncio
    async def test_delete_not_found_raises_404(self, user_ctx, db_session):
        """DELETE raises HTTP 404 when the binding ID does not exist."""
        with pytest.raises(HTTPException) as exc_info:
            await delete_tool_plugin_binding(
                binding_id="nonexistent-id",
                current_user_ctx=user_ctx,
                db=db_session,
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert "nonexistent-id" in str(exc_info.value.detail)

    # ------------------------------------------------------------------
    # Structural
    # ------------------------------------------------------------------

    def test_all_handlers_are_coroutines(self):
        """All router handler functions are async coroutine functions."""
        assert asyncio.iscoroutinefunction(upsert_tool_plugin_bindings)
        assert asyncio.iscoroutinefunction(list_tool_plugin_bindings)
        assert asyncio.iscoroutinefunction(list_tool_plugin_bindings_for_team)
        assert asyncio.iscoroutinefunction(delete_tool_plugin_binding)

    # ------------------------------------------------------------------
    # Cache invalidation — reload_plugin_context called after mutations
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_upsert_calls_reload_plugin_context(self, user_ctx, db_session):
        """After a successful upsert the router calls reload_plugin_context with
        the canonical context_id (team_id::tool_name) for every affected binding.
        """
        from unittest.mock import AsyncMock

        with patch(
            "mcpgateway.routers.tool_plugin_bindings.reload_plugin_context",
            new_callable=AsyncMock,
        ) as mock_reload:
            await upsert_tool_plugin_bindings(
                request=_simple_request(),
                current_user_ctx=user_ctx,
                db=db_session,
            )

        mock_reload.assert_awaited_once_with("team-a::tool_x")

    @pytest.mark.asyncio
    async def test_upsert_two_teams_calls_reload_for_each_context(self, user_ctx, db_session):
        """Upsert with two teams calls reload_plugin_context once per unique context_id."""
        from unittest.mock import AsyncMock

        with patch(
            "mcpgateway.routers.tool_plugin_bindings.reload_plugin_context",
            new_callable=AsyncMock,
        ) as mock_reload:
            await upsert_tool_plugin_bindings(
                request=_two_team_request(),
                current_user_ctx=user_ctx,
                db=db_session,
            )

        called_ids = {call.args[0] for call in mock_reload.await_args_list}
        assert called_ids == {"team-a::tool_x", "team-b::tool_y"}

    @pytest.mark.asyncio
    async def test_delete_calls_reload_plugin_context(self, user_ctx, db_session):
        """After a successful delete the router calls reload_plugin_context with
        the canonical context_id for the deleted binding.
        """
        from unittest.mock import AsyncMock

        # Seed a binding first (with real reload so it doesn't interfere)
        upsert_result = await upsert_tool_plugin_bindings(
            request=_simple_request(),
            current_user_ctx=user_ctx,
            db=db_session,
        )
        binding_id = upsert_result.bindings[0].id

        with patch(
            "mcpgateway.routers.tool_plugin_bindings.reload_plugin_context",
            new_callable=AsyncMock,
        ) as mock_reload:
            await delete_tool_plugin_binding(
                binding_id=binding_id,
                current_user_ctx=user_ctx,
                db=db_session,
            )

        mock_reload.assert_awaited_once_with("team-a::tool_x")

    # ------------------------------------------------------------------
    # DELETE / — delete_tool_plugin_bindings_by_reference
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_by_reference_success_multiple_bindings(self, user_ctx, db_session):
        """DELETE ?binding_reference_id= removes all bindings with that reference and returns them."""
        ref_request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x", "tool_y"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            config=dict(_OLG),
                            binding_reference_id="ext-ref-001",
                        )
                    ]
                )
            }
        )
        await upsert_tool_plugin_bindings(
            request=ref_request,
            current_user_ctx=user_ctx,
            db=db_session,
        )

        result = await delete_tool_plugin_bindings_by_reference(
            binding_reference_id="ext-ref-001",
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert isinstance(result, ToolPluginBindingListResponse)
        assert result.total == 2
        assert all(b.binding_reference_id == "ext-ref-001" for b in result.bindings)
        assert {b.tool_name for b in result.bindings} == {"tool_x", "tool_y"}

        # Confirm both rows are gone
        after = await list_tool_plugin_bindings(current_user_ctx=user_ctx, db=db_session)
        assert after.total == 0

    @pytest.mark.asyncio
    async def test_delete_by_reference_no_match_returns_empty(self, user_ctx, db_session):
        """DELETE ?binding_reference_id= with no matching bindings is not an error — returns empty list."""
        result = await delete_tool_plugin_bindings_by_reference(
            binding_reference_id="nonexistent-ref",
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert isinstance(result, ToolPluginBindingListResponse)
        assert result.total == 0
        assert result.bindings == []

    @pytest.mark.asyncio
    async def test_delete_by_reference_only_deletes_matching_ref(self, user_ctx, db_session):
        """DELETE ?binding_reference_id= only removes bindings with that specific reference ID."""
        r1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            config=dict(_OLG),
                            binding_reference_id="ref-alpha",
                        )
                    ]
                )
            }
        )
        r2 = ToolPluginBindingRequest(
            teams={
                "team-b": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_y"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            config=dict(_OLG),
                            binding_reference_id="ref-beta",
                        )
                    ]
                )
            }
        )
        await upsert_tool_plugin_bindings(request=r1, current_user_ctx=user_ctx, db=db_session)
        await upsert_tool_plugin_bindings(request=r2, current_user_ctx=user_ctx, db=db_session)

        deleted = await delete_tool_plugin_bindings_by_reference(
            binding_reference_id="ref-alpha",
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert deleted.total == 1
        assert deleted.bindings[0].binding_reference_id == "ref-alpha"

        # ref-beta binding must still be present
        after = await list_tool_plugin_bindings(current_user_ctx=user_ctx, db=db_session)
        assert after.total == 1
        assert after.bindings[0].binding_reference_id == "ref-beta"

    @pytest.mark.asyncio
    async def test_delete_by_reference_calls_reload_plugin_context(self, user_ctx, db_session):
        """DELETE ?binding_reference_id= calls reload_plugin_context for each deleted binding."""
        from unittest.mock import AsyncMock

        ref_request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x", "tool_y"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            config=dict(_OLG),
                            binding_reference_id="ref-cache-test",
                        )
                    ]
                )
            }
        )
        await upsert_tool_plugin_bindings(
            request=ref_request, current_user_ctx=user_ctx, db=db_session
        )

        with patch(
            "mcpgateway.routers.tool_plugin_bindings.reload_plugin_context",
            new_callable=AsyncMock,
        ) as mock_reload:
            await delete_tool_plugin_bindings_by_reference(
                binding_reference_id="ref-cache-test",
                current_user_ctx=user_ctx,
                db=db_session,
            )

        called_ids = {call.args[0] for call in mock_reload.await_args_list}
        assert called_ids == {"team-a::tool_x", "team-a::tool_y"}

    # ------------------------------------------------------------------
    # GET / and GET /{team_id} — binding_reference_id query filter
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_all_filtered_by_binding_reference_id(self, user_ctx, db_session):
        """GET /?binding_reference_id= returns only bindings with that reference ID."""
        r1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            config=dict(_OLG),
                            binding_reference_id="ref-001",
                        )
                    ]
                )
            }
        )
        r2 = ToolPluginBindingRequest(
            teams={
                "team-b": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_y"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            config=dict(_OLG),
                            binding_reference_id="ref-002",
                        )
                    ]
                )
            }
        )
        await upsert_tool_plugin_bindings(request=r1, current_user_ctx=user_ctx, db=db_session)
        await upsert_tool_plugin_bindings(request=r2, current_user_ctx=user_ctx, db=db_session)

        result = await list_tool_plugin_bindings(
            binding_reference_id="ref-001",
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert result.total == 1
        assert result.bindings[0].binding_reference_id == "ref-001"
        assert result.bindings[0].team_id == "team-a"

    @pytest.mark.asyncio
    async def test_list_by_team_binding_reference_id_takes_precedence(self, user_ctx, db_session):
        """GET /{team_id}?binding_reference_id= uses reference ID and ignores team_id filter."""
        r = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            config=dict(_OLG),
                            binding_reference_id="cross-team-ref",
                        )
                    ]
                )
            }
        )
        await upsert_tool_plugin_bindings(request=r, current_user_ctx=user_ctx, db=db_session)

        # Query with team_id="team-b" but binding_reference_id for team-a's binding —
        # reference ID takes precedence so the team-a binding is still returned.
        result = await list_tool_plugin_bindings_for_team(
            team_id="team-b",
            binding_reference_id="cross-team-ref",
            current_user_ctx=user_ctx,
            db=db_session,
        )

        assert result.total == 1
        assert result.bindings[0].team_id == "team-a"
        assert result.bindings[0].binding_reference_id == "cross-team-ref"
