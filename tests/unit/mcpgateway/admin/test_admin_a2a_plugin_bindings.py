# -*- coding: utf-8 -*-
"""Unit tests for the A2A agent plugin binding admin UI endpoints.

Tests exercise the admin handlers directly (no TestClient), mocking only
`get_plugin_service()` and template rendering. Database operations use a
real in-memory SQLite session so the full service+DB stack is exercised.

Tests cover:
    - GET /a2a/plugin-bindings/partial: renders HTML, error state
    - POST /a2a/plugin-bindings: create binding from form data, validation
    - POST /a2a/plugin-bindings/{binding_id}/delete: delete, not found, forbidden
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.admin import (
    admin_create_a2a_plugin_binding,
    admin_delete_a2a_plugin_binding,
    get_a2a_plugin_bindings_partial,
)
from mcpgateway.db import Base
from mcpgateway.services.a2a_agent_plugin_binding_service import (
    A2AAgentPluginBindingService,
)

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
        "permissions": ["admin.plugins"],
    }


@pytest.fixture
def mock_request():
    """Mock FastAPI Request with a TemplateResponse spy."""

    def _template_response(request, name, context):
        return MagicMock(
            status_code=200,
            template_name=name,
            context=context,
            headers={},
            body=b"",
        )

    req = MagicMock()
    req.app.state.templates.TemplateResponse = _template_response
    req.app.state.plugin_service = MagicMock()
    req.app.state.plugin_service.get_all_plugins.return_value = []
    return req


@pytest.fixture(autouse=True)
def _patch_get_plugin_service():
    """Patch get_plugin_service() to return a predictable mock."""
    mock_svc = MagicMock()
    mock_svc.get_all_plugins.return_value = []
    with patch("mcpgateway.admin.get_plugin_service", return_value=mock_svc):
        yield


class TestA2APluginBindingsAdmin:
    @pytest.fixture(autouse=True)
    def setup_rbac_mocks(self):
        originals = patch_rbac_decorators()
        yield
        restore_rbac_decorators(originals)

    # ------------------------------------------------------------------
    # GET /a2a/plugin-bindings/partial
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_partial_renders(self, mock_request, user_ctx, db_session):
        response = await get_a2a_plugin_bindings_partial(
            request=mock_request,
            team_id=None,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 200
        assert response.template_name == "a2a_agent_plugin_bindings_partial.html"
        assert "bindings" in response.context
        assert response.context["bindings"] == []

    @pytest.mark.asyncio
    async def test_partial_with_team_filter(self, mock_request, user_ctx, db_session):
        svc = A2AAgentPluginBindingService()
        svc.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={"enabled": True},
            on_error=None,
            caller_email="admin@example.com",
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

        response = await get_a2a_plugin_bindings_partial(
            request=mock_request,
            team_id="team-a",
            db=db_session,
            user=user_ctx,
        )
        bindings = response.context["bindings"]
        assert len(bindings) == 1
        assert bindings[0].team_id == "team-a"
        assert bindings[0].agent_name == "agent_x"

    @pytest.mark.asyncio
    async def test_partial_agent_names(self, mock_request, user_ctx, db_session):
        # First-Party
        from mcpgateway.db import A2AAgent

        # Seed some A2A agents
        for name in ("alpha-agent", "beta-agent"):
            agent = A2AAgent(
                name=name,
                team_id="team-a",
                agent_type="sdk",
                endpoint_url="http://localhost:9999",
                enabled=True,
                visibility="public",
            )
            db_session.add(agent)
        db_session.commit()

        response = await get_a2a_plugin_bindings_partial(
            request=mock_request,
            team_id=None,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 200
        assert "agent_names" in response.context
        agent_names = list(response.context["agent_names"])
        assert "alpha-agent" in agent_names
        assert "beta-agent" in agent_names

    # ------------------------------------------------------------------
    # POST /a2a/plugin-bindings — create
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_success(self, mock_request, user_ctx, db_session):
        mock_request.form = AsyncMock(
            return_value={
                "team_id": "team-a",
                "agent_name": "agent_x",
                "plugin_id": "OutputLengthGuardPlugin",
                "mode": "enforce",
                "priority": "50",
                "on_error": "",
                "config": '{"enabled": true}',
            }
        )
        response = await admin_create_a2a_plugin_binding(
            request=mock_request,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 200
        assert response.template_name == "a2a_agent_plugin_bindings_partial.html"

        # Verify it was persisted
        svc = A2AAgentPluginBindingService()
        bindings, total = svc.list_bindings(db_session)
        assert total == 1
        assert len(bindings) == 1
        assert bindings[0].agent_name == "agent_x"

    @pytest.mark.asyncio
    async def test_create_validation_missing_fields(self, mock_request, user_ctx, db_session):
        mock_request.form = AsyncMock(
            return_value={
                "team_id": "",
                "agent_name": "agent_x",
                "plugin_id": "",
                "mode": "enforce",
                "priority": "50",
                "on_error": "",
                "config": "{}",
            }
        )
        response = await admin_create_a2a_plugin_binding(
            request=mock_request,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 400
        body = response.body.decode()
        assert "required" in body

    @pytest.mark.asyncio
    async def test_create_invalid_json_config(self, mock_request, user_ctx, db_session):
        mock_request.form = AsyncMock(
            return_value={
                "team_id": "team-a",
                "agent_name": "agent_x",
                "plugin_id": "OutputLengthGuardPlugin",
                "mode": "enforce",
                "priority": "50",
                "on_error": "",
                "config": "{invalid json}",
            }
        )
        response = await admin_create_a2a_plugin_binding(
            request=mock_request,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 400

        # Bad JSON should not create a binding
        svc = A2AAgentPluginBindingService()
        bindings, total = svc.list_bindings(db_session)
        assert total == 0

    @pytest.mark.asyncio
    async def test_create_invalid_priority(self, mock_request, user_ctx, db_session):
        """Non-integer priority returns 400."""
        mock_request.form = AsyncMock(
            return_value={
                "team_id": "team-a",
                "agent_name": "agent_x",
                "plugin_id": "OutputLengthGuardPlugin",
                "mode": "enforce",
                "priority": "not-a-number",
                "on_error": "",
                "config": "{}",
            }
        )
        response = await admin_create_a2a_plugin_binding(
            request=mock_request,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 400
        body = response.body.decode()
        assert "Invalid priority" in body

    @pytest.mark.asyncio
    async def test_create_invalid_mode(self, mock_request, user_ctx, db_session):
        """Mode not in {enforce, report, disabled} returns 400."""
        mock_request.form = AsyncMock(
            return_value={
                "team_id": "team-a",
                "agent_name": "agent_x",
                "plugin_id": "OutputLengthGuardPlugin",
                "mode": "invalid-mode",
                "priority": "50",
                "on_error": "",
                "config": "{}",
            }
        )
        response = await admin_create_a2a_plugin_binding(
            request=mock_request,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 400
        body = response.body.decode()
        assert "Invalid mode" in body

    @pytest.mark.asyncio
    async def test_create_invalid_on_error(self, mock_request, user_ctx, db_session):
        """on_error not in {fail, ignore, disable, None} returns 400."""
        mock_request.form = AsyncMock(
            return_value={
                "team_id": "team-a",
                "agent_name": "agent_x",
                "plugin_id": "OutputLengthGuardPlugin",
                "mode": "enforce",
                "priority": "50",
                "on_error": "bad-value",
                "config": "{}",
            }
        )
        response = await admin_create_a2a_plugin_binding(
            request=mock_request,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 400
        body = response.body.decode()
        assert "Invalid on_error" in body

    # ------------------------------------------------------------------
    # POST /a2a/plugin-bindings/{binding_id}/delete
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_request, user_ctx, db_session):
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
        )
        bindings, _ = svc.list_bindings(db_session)
        binding = bindings[0]

        response = await admin_delete_a2a_plugin_binding(
            request=mock_request,
            binding_id=binding.id,
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 200
        assert response.template_name == "a2a_agent_plugin_bindings_partial.html"

        # Verify deletion
        _, remaining_total = svc.list_bindings(db_session)
        assert remaining_total == 0

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_request, user_ctx, db_session):
        response = await admin_delete_a2a_plugin_binding(
            request=mock_request,
            binding_id="00000000-0000-0000-0000-000000000000",
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 404
        body = response.body.decode()
        assert "Not found" in body

    @pytest.mark.asyncio
    async def test_delete_forbidden(self, mock_request, user_ctx, db_session):
        """Delete handler returns 403 when A2AAgentPluginBindingForbiddenError is raised."""
        # First-Party
        from mcpgateway.services.a2a_agent_plugin_binding_service import A2AAgentPluginBindingForbiddenError

        with patch.object(
            A2AAgentPluginBindingService,
            "delete_binding",
            side_effect=A2AAgentPluginBindingForbiddenError("cross-team access"),
        ):
            response = await admin_delete_a2a_plugin_binding(
                request=mock_request,
                binding_id="00000000-0000-0000-0000-000000000001",
                db=db_session,
                user=user_ctx,
            )
        assert response.status_code == 403
        body = response.body.decode()
        assert "Forbidden" in body

    @pytest.mark.asyncio
    async def test_delete_generic_error(self, mock_request, user_ctx, db_session):
        """Delete handler returns 500 on unexpected errors."""
        with patch.object(
            A2AAgentPluginBindingService,
            "delete_binding",
            side_effect=RuntimeError("unexpected failure"),
        ):
            response = await admin_delete_a2a_plugin_binding(
                request=mock_request,
                binding_id="00000000-0000-0000-0000-000000000002",
                db=db_session,
                user=user_ctx,
            )
        assert response.status_code == 500
        body = response.body.decode()
        assert "Error" in body

    @pytest.mark.asyncio
    async def test_delete_invalid_uuid(self, mock_request, user_ctx, db_session):
        """Malformed binding_id returns 400."""
        response = await admin_delete_a2a_plugin_binding(
            request=mock_request,
            binding_id="not-a-uuid",
            db=db_session,
            user=user_ctx,
        )
        assert response.status_code == 400
        body = response.body.decode()
        assert "Invalid binding ID format" in body

    @pytest.mark.asyncio
    async def test_delete_team_scope_enforcement(self, mock_request, db_session):
        """Non-admin user can only delete bindings for their own teams."""
        svc = A2AAgentPluginBindingService()

        # Create bindings for team-a and team-b
        binding_a_id = svc.upsert_binding(
            db=db_session,
            team_id="team-a",
            agent_name="agent_x",
            plugin_id="OutputLengthGuardPlugin",
            mode="enforce",
            priority=50,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        ).id
        binding_b_id = svc.upsert_binding(
            db=db_session,
            team_id="team-b",
            agent_name="agent_y",
            plugin_id="RateLimiterPlugin",
            mode="permissive",
            priority=30,
            config={},
            on_error=None,
            caller_email="admin@example.com",
        ).id

        non_admin_ctx = {
            "email": "dev@team-a.com",
            "full_name": "Dev User",
            "is_admin": False,
            "token_teams": ["team-a"],
            "db": db_session,
            "permissions": ["admin.plugins"],
        }

        # Should succeed for team-a
        response = await admin_delete_a2a_plugin_binding(
            request=mock_request,
            binding_id=binding_a_id,
            db=db_session,
            user=non_admin_ctx,
        )
        assert response.status_code == 200

        # Should fail with 403 for team-b
        response = await admin_delete_a2a_plugin_binding(
            request=mock_request,
            binding_id=binding_b_id,
            db=db_session,
            user=non_admin_ctx,
        )
        assert response.status_code == 403
        body = response.body.decode()
        assert "Forbidden" in body

    # ------------------------------------------------------------------
    # Error paths — partial render, create
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_partial_render_error(self, mock_request, user_ctx, db_session):
        """Partial rendering returns 500 when list_bindings raises."""
        with patch.object(
            A2AAgentPluginBindingService,
            "list_bindings",
            side_effect=RuntimeError("db connection lost"),
        ):
            response = await get_a2a_plugin_bindings_partial(
                request=mock_request,
                team_id=None,
                db=db_session,
                user=user_ctx,
            )
        assert response.status_code == 500
        body = response.body.decode()
        assert "Error loading" in body

    @pytest.mark.asyncio
    async def test_create_service_error(self, mock_request, user_ctx, db_session):
        """Create handler returns 500 when upsert_binding raises."""
        mock_request.form = AsyncMock(
            return_value={
                "team_id": "team-a",
                "agent_name": "agent_x",
                "plugin_id": "OutputLengthGuardPlugin",
                "mode": "enforce",
                "priority": "50",
                "on_error": "",
                "config": "{}",
            }
        )
        with patch.object(
            A2AAgentPluginBindingService,
            "upsert_binding",
            side_effect=RuntimeError("persistence failure"),
        ):
            response = await admin_create_a2a_plugin_binding(
                request=mock_request,
                db=db_session,
                user=user_ctx,
            )
        assert response.status_code == 500
        body = response.body.decode()
        assert "Error" in body
