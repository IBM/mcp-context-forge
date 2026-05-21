# -*- coding: utf-8 -*-
"""Unit tests for the A2A agent plugin bindings router.

Uses an in-memory SQLite database and the real A2AAgentPluginBindingService so
tests exercise the full stack from router handler down to SQL, with no mocked
service responses.

Tests cover:
    - POST / (upsert): success, validation errors
    - GET / (list all): success, empty
    - GET /{team_id}: filtered list, empty
    - DELETE /{binding_id}: success, not found, forbidden (non-admin foreign team)
    - DELETE / (by reference): non-admin scoped to own teams
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base
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
def db_session():
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
    return {
        "email": "admin@example.com",
        "full_name": "Admin User",
        "is_admin": True,
        "token_teams": None,
        "db": db_session,
        "permissions": ["tools.manage_plugins", "tools.read"],
    }


def _make_request(agent_name="agent_x", plugin_id="OutputLengthGuardPlugin", mode="enforce", priority=50, config=None, on_error=None):
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
    def setup_rbac_mocks(self):
        originals = patch_rbac_decorators()
        yield
        restore_rbac_decorators(originals)

    # ------------------------------------------------------------------
    # POST / — upsert
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_upsert_success(self, user_ctx, db_session):
        request = _make_request()
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

    @pytest.mark.asyncio
    async def test_upsert_idempotent_update(self, user_ctx, db_session):
        request = _make_request()
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
    async def test_upsert_wildcard_agent(self, user_ctx, db_session):
        request = _make_request(agent_name="*", plugin_id="RateLimiterPlugin")
        result = await upsert_a2a_agent_plugin_binding(
            request=request,
            current_user_ctx=user_ctx,
            db=db_session,
            team_id="team-a",
        )
        assert result.agent_name == "*"

    @pytest.mark.asyncio
    async def test_upsert_forbidden_team(self, user_ctx, db_session):
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
    async def test_upsert_value_error(self, user_ctx, db_session):
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
    async def test_list_all_empty(self, user_ctx, db_session):
        result = await list_a2a_agent_plugin_bindings(
            current_user_ctx=user_ctx,
            db=db_session,
        )
        assert isinstance(result, A2AAgentPluginBindingListResponse)
        assert result.total == 0
        assert result.bindings == []

    @pytest.mark.asyncio
    async def test_list_all(self, user_ctx, db_session):
        for team in ("team-a", "team-b"):
            await upsert_a2a_agent_plugin_binding(
                request=_make_request(agent_name=f"agent_{team}"),
                current_user_ctx=user_ctx,
                db=db_session,
                team_id=team,
            )
        result = await list_a2a_agent_plugin_bindings(
            current_user_ctx=user_ctx,
            db=db_session,
        )
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_list_all_filtered_by_reference(self, user_ctx, db_session):
        # First-Party
        from mcpgateway.services.a2a_agent_plugin_binding_service import A2AAgentPluginBindingService

        svc = A2AAgentPluginBindingService()
        svc.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        svc.upsert_binding(
            db=db_session,
            team_id="team-b",
            agent_name="agent_y",
            plugin_id="RateLimiterPlugin",
            mode="permissive",
            priority=30,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        )
        result = await list_a2a_agent_plugin_bindings(
            current_user_ctx=user_ctx,
            db=db_session,
            binding_reference_id="ref-001",
        )
        assert result.total == 1

    # ------------------------------------------------------------------
    # GET /{team_id} — list by team
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_by_team(self, user_ctx, db_session):
        for team in ("team-a", "team-b"):
            await upsert_a2a_agent_plugin_binding(
                request=_make_request(agent_name=f"agent_{team}"),
                current_user_ctx=user_ctx,
                db=db_session,
                team_id=team,
            )
        result = await list_a2a_agent_plugin_bindings_for_team(
            team_id="team-a",
            current_user_ctx=user_ctx,
            db=db_session,
        )
        assert result.total == 1
        assert result.bindings[0].team_id == "team-a"

    @pytest.mark.asyncio
    async def test_list_by_team_empty(self, user_ctx, db_session):
        result = await list_a2a_agent_plugin_bindings_for_team(
            team_id="team-nonexistent",
            current_user_ctx=user_ctx,
            db=db_session,
        )
        assert result.total == 0

    # ------------------------------------------------------------------
    # DELETE /{binding_id} — delete by UUID
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_by_id_success(self, user_ctx, db_session):
        created = await upsert_a2a_agent_plugin_binding(
            request=_make_request(),
            current_user_ctx=user_ctx,
            db=db_session,
            team_id="team-a",
        )
        deleted = await delete_a2a_agent_plugin_binding(
            binding_id=created.id,
            current_user_ctx=user_ctx,
            db=db_session,
        )
        assert isinstance(deleted, A2AAgentPluginBindingResponse)
        assert deleted.id == created.id

        result = await list_a2a_agent_plugin_bindings(current_user_ctx=user_ctx, db=db_session)
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_delete_by_id_not_found(self, user_ctx, db_session):
        # Third-Party
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await delete_a2a_agent_plugin_binding(
                binding_id="nonexistent",
                current_user_ctx=user_ctx,
                db=db_session,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_by_id_forbidden_non_admin(self, user_ctx, db_session):
        created = await upsert_a2a_agent_plugin_binding(
            request=_make_request(),
            current_user_ctx=user_ctx,
            db=db_session,
            team_id="team-a",
        )
        # Third-Party
        from fastapi import HTTPException

        user_ctx_b = {**user_ctx, "is_admin": False, "token_teams": {"team-b"}}
        with pytest.raises(HTTPException) as exc:
            await delete_a2a_agent_plugin_binding(
                binding_id=created.id,
                current_user_ctx=user_ctx_b,
                db=db_session,
            )
        assert exc.value.status_code == 403

    # ------------------------------------------------------------------
    # DELETE / — delete by external reference ID
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_by_reference_success(self, user_ctx, db_session):
        # First-Party
        from mcpgateway.services.a2a_agent_plugin_binding_service import A2AAgentPluginBindingService

        svc = A2AAgentPluginBindingService()
        svc.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        deleted = await delete_a2a_agent_plugin_bindings_by_reference(
            binding_reference_id="ref-001",
            current_user_ctx=user_ctx,
            db=db_session,
        )
        assert isinstance(deleted, A2AAgentPluginBindingListResponse)
        assert deleted.total == 1
        assert deleted.bindings[0].agent_name == "agent_x"

    @pytest.mark.asyncio
    async def test_delete_by_reference_scoped_to_team(self, user_ctx, db_session):
        # First-Party
        from mcpgateway.services.a2a_agent_plugin_binding_service import A2AAgentPluginBindingService

        svc = A2AAgentPluginBindingService()
        svc.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        svc.upsert_binding(
            db=db_session,
            team_id="team-b",
            agent_name="agent_y",
            plugin_id="RateLimiterPlugin",
            mode="permissive",
            priority=30,
            config={},
            on_error=None,
            caller_email="admin@example.com",
            binding_reference_id="ref-001",
        )
        user_ctx_a = {**user_ctx, "is_admin": False, "token_teams": {"team-a"}}
        deleted = await delete_a2a_agent_plugin_bindings_by_reference(
            binding_reference_id="ref-001",
            current_user_ctx=user_ctx_a,
            db=db_session,
        )
        assert deleted.total == 1
        assert deleted.bindings[0].team_id == "team-a"

        remaining = await list_a2a_agent_plugin_bindings(current_user_ctx=user_ctx, db=db_session)
        assert remaining.total == 1
        assert remaining.bindings[0].team_id == "team-b"
