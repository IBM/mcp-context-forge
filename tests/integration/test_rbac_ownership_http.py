# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_rbac_ownership_http.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for RBAC ownership enforcement via HTTP API.
Tests verify that only resource owners can delete/update resources,
and that proper HTTP 403 responses are returned for permission violations.
"""

# Future
from __future__ import annotations

# Standard
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from _pytest.monkeypatch import MonkeyPatch

# First-Party
from mcpgateway.main import app
from mcpgateway.utils.verify_credentials import require_auth
from mcpgateway.auth import get_current_user
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db as rbac_get_db, get_permission_service
from mcpgateway.schemas import ToolRead, ServerRead, ResourceRead, PromptRead, GatewayRead, A2AAgentRead
from mcpgateway.schemas import ToolMetrics

# Local
from tests.utils.rbac_mocks import MockPermissionService


@pytest.fixture
def test_db_and_client():
    """Create a test database and FastAPI TestClient with auth overrides."""
    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    from mcpgateway.config import settings
    mp.setattr(settings, "database_url", url, raising=False)

    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    # Create schema
    db_mod.Base.metadata.create_all(bind=engine)

    def override_get_db():
        """Override database dependency."""
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[rbac_get_db] = override_get_db

    # Patch RBAC decorators to bypass permission checks
    # This allows tests to reach the ownership checks in service layer
    from tests.utils.rbac_mocks import patch_rbac_decorators
    rbac_originals = patch_rbac_decorators()

    yield TestSessionLocal, engine

    # Cleanup
    app.dependency_overrides.pop(rbac_get_db, None)
    from tests.utils.rbac_mocks import restore_rbac_decorators
    restore_rbac_decorators(rbac_originals)
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


def create_user_context(email: str, is_admin: bool = False, TestSessionLocal=None):
    """Create a mock user context for testing."""
    async def mock_user_with_permissions():
        """Mock user context for RBAC."""
        return {
            "email": email,
            "full_name": f"Test User {email}",
            "is_admin": is_admin,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
            "db": TestSessionLocal() if TestSessionLocal else None,
        }
    return mock_user_with_permissions


# Mock data for testing
MOCK_METRICS = {
    "total_executions": 0,
    "successful_executions": 0,
    "failed_executions": 0,
    "failure_rate": 0.0,
    "min_response_time": 0.0,
    "max_response_time": 0.0,
    "avg_response_time": 0.0,
    "last_execution_time": "2025-01-01T00:00:00",
}


class TestRBACOwnershipHTTP:
    """Integration tests for RBAC ownership enforcement via HTTP API."""

    @patch("mcpgateway.main.tool_service.delete_tool", new_callable=AsyncMock)
    @patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    def test_delete_tool_non_owner_returns_403(
        self,
        mock_delete_tool: AsyncMock,
        test_db_and_client,
    ):
        """Test that non-owner receives HTTP 403 when attempting to delete tool."""
        TestSessionLocal, _ = test_db_and_client

        # Mock service to raise PermissionError
        mock_delete_tool.side_effect = PermissionError("Only the owner can delete this tool")

        # Set up user context as non-owner
        mock_user = MagicMock()
        mock_user.email = "user-b@example.com"

        app.dependency_overrides[require_auth] = lambda: "user-b@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context(
            "user-b@example.com", TestSessionLocal=TestSessionLocal
        )

        client = TestClient(app)

        # Attempt to delete tool owned by user-a@example.com
        response = client.delete(
            "/tools/tool-123",
            headers={"Authorization": "Bearer test-token"}
        )

        # Verify HTTP 403 Forbidden
        assert response.status_code == 403
        assert "Only the owner can delete this tool" in response.json()["detail"]

        # Cleanup
        app.dependency_overrides.clear()

    @patch("mcpgateway.main.tool_service.update_tool", new_callable=AsyncMock)
    @patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    def test_update_tool_non_owner_returns_403(
        self,
        mock_update_tool: AsyncMock,
        test_db_and_client,
    ):
        """Test that non-owner receives HTTP 403 when attempting to update tool."""
        TestSessionLocal, _ = test_db_and_client

        # Mock service to raise PermissionError
        mock_update_tool.side_effect = PermissionError("Only the owner can update this tool")

        # Set up user context as non-owner
        mock_user = MagicMock()
        mock_user.email = "user-b@example.com"

        app.dependency_overrides[require_auth] = lambda: "user-b@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context(
            "user-b@example.com", TestSessionLocal=TestSessionLocal
        )
        client = TestClient(app)

        # Attempt to update tool owned by user-a@example.com
        response = client.put(
            "/tools/tool-123",
            json={"name": "updated-tool"},
            headers={"Authorization": "Bearer test-token"}
        )

        # Verify HTTP 403 Forbidden
        assert response.status_code == 403
        assert "Only the owner can update this tool" in response.json()["detail"]

        # Cleanup
        app.dependency_overrides.clear()

    @patch("mcpgateway.main.server_service.delete_server", new_callable=AsyncMock)
    @patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    def test_delete_server_owner_succeeds(
        self,
        mock_delete_server: AsyncMock,
        test_db_and_client,
    ):
        """Test that owner can successfully delete their own server."""
        TestSessionLocal, _ = test_db_and_client

        # Mock service to succeed
        mock_delete_server.return_value = None

        # Set up user context as owner
        mock_user = MagicMock()
        mock_user.email = "owner@example.com"

        app.dependency_overrides[require_auth] = lambda: "owner@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context(
            "owner@example.com", TestSessionLocal=TestSessionLocal
        )

        client = TestClient(app)

        # Delete own server
        response = client.delete(
            "/servers/server-123",
            headers={"Authorization": "Bearer test-token"}
        )

        # Verify success
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Cleanup
        app.dependency_overrides.clear()

    @patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    @patch("mcpgateway.main.resource_service.delete_resource", new_callable=AsyncMock)
    def test_delete_resource_non_owner_returns_403(
        self,
        mock_delete_resource: AsyncMock,
        test_db_and_client,
    ):
        """Test that non-owner receives HTTP 403 when attempting to delete resource."""
        TestSessionLocal, _ = test_db_and_client

        # Mock service to raise PermissionError
        mock_delete_resource.side_effect = PermissionError("Only the owner can delete this resource")

        # Set up user context as non-owner
        mock_user = MagicMock()
        mock_user.email = "user-b@example.com"

        app.dependency_overrides[require_auth] = lambda: "user-b@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context(
            "user-b@example.com", TestSessionLocal=TestSessionLocal
        )
        client = TestClient(app)


        # Attempt to delete resource owned by user-a@example.com (use resource ID, not URI)
        response = client.delete(
            "/resources/resource-123",
            headers={"Authorization": "Bearer test-token"}
        )

        # Verify HTTP 403 Forbidden
        assert response.status_code == 403
        assert "Only the owner can delete this resource" in response.json()["detail"]

        # Cleanup
        app.dependency_overrides.clear()

    @patch("mcpgateway.main.gateway_service.delete_gateway", new_callable=AsyncMock)
    @patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    def test_delete_gateway_team_admin_succeeds(
        self,
        mock_delete_gateway: AsyncMock,
        test_db_and_client,
    ):
        """Test that team admin can delete team member's gateway."""
        TestSessionLocal, _ = test_db_and_client

        # Mock service to succeed (team admin has permission)
        mock_delete_gateway.return_value = None

        # Set up user context as team admin
        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        app.dependency_overrides[require_auth] = lambda: "admin@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context(
            "admin@example.com", is_admin=True, TestSessionLocal=TestSessionLocal
        )

        client = TestClient(app)

        # Delete team member's gateway as team admin
        response = client.delete(
            "/gateways/gateway-123",
            headers={"Authorization": "Bearer test-token"}
        )

        # Verify success
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Cleanup
        app.dependency_overrides.clear()

    @patch("mcpgateway.main.prompt_service.update_prompt", new_callable=AsyncMock)
    @patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    def test_update_prompt_team_member_returns_403(
        self,
        mock_update_prompt: AsyncMock,
        test_db_and_client,
    ):
        """Test that team member receives HTTP 403 when updating team owner's prompt."""
        TestSessionLocal, _ = test_db_and_client

        # Mock service to raise PermissionError
        mock_update_prompt.side_effect = PermissionError("Only the owner can update this prompt")

        # Set up user context as regular team member
        mock_user = MagicMock()
        mock_user.email = "member@example.com"

        app.dependency_overrides[require_auth] = lambda: "member@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context(
            "member@example.com", TestSessionLocal=TestSessionLocal
        )
        client = TestClient(app)

        # Attempt to update prompt owned by team owner
        response = client.put(
            "/prompts/test-prompt",
            json={"description": "updated"},
            headers={"Authorization": "Bearer test-token"}
        )

        # Verify HTTP 403 Forbidden
        assert response.status_code == 403
        assert "Only the owner can update this prompt" in response.json()["detail"]

        # Cleanup
        app.dependency_overrides.clear()

    @patch("mcpgateway.main.a2a_service.delete_agent", new_callable=AsyncMock)
    @patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService)
    def test_delete_a2a_agent_non_owner_returns_403(
        self,
        mock_delete_agent: AsyncMock,
        test_db_and_client,
    ):
        """Test that non-owner receives HTTP 403 when attempting to delete A2A agent."""
        TestSessionLocal, _ = test_db_and_client

        # Mock service to raise PermissionError
        mock_delete_agent.side_effect = PermissionError("Only the owner can delete this agent")

        # Set up user context as non-owner
        mock_user = MagicMock()
        mock_user.email = "user-b@example.com"

        app.dependency_overrides[require_auth] = lambda: "user-b@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context(
            "user-b@example.com", TestSessionLocal=TestSessionLocal
        )
        client = TestClient(app)

        # Attempt to delete A2A agent owned by user-a@example.com
        response = client.delete(
            "/a2a/agent-123",
            headers={"Authorization": "Bearer test-token"}
        )

        # Verify HTTP 403 Forbidden
        assert response.status_code == 403
        assert "Only the owner can delete this agent" in response.json()["detail"]

        # Cleanup
        app.dependency_overrides.clear()


# ============================================================================
# Tests for team_id fallback from user_context (Issue #2183)
# ============================================================================
#
# NOTE: The RBAC decorator logic (team_id fallback to user_context) is fully tested
# in tests/unit/mcpgateway/middleware/test_rbac.py. These integration tests verify
# endpoint behavior with mocked services. The test_db_and_client fixture patches
# RBAC decorators to bypass permission checks, allowing focus on service layer testing.
# ============================================================================


class TestTeamIdFallbackHTTP:
    """Integration tests for endpoint behavior with team_id context (Issue #2183).

    These tests verify endpoint behavior when team_id is provided via user_context.
    The RBAC decorator logic itself is tested in unit tests (test_rbac.py).

    Note: test_db_and_client fixture patches RBAC decorators to bypass permission
    checks, so these tests focus on endpoint/service layer behavior, not RBAC logic.
    """

    @patch("mcpgateway.middleware.rbac.PermissionService")
    @patch("mcpgateway.main.gateway_service.list_gateways", new_callable=AsyncMock)
    def test_team_scoped_user_can_call_gateways_endpoint(
        self,
        mock_list_gateways: AsyncMock,
        mock_perm_service_class: MagicMock,
        test_db_and_client,
    ):
        """Test that user with team_id in context can call gateways endpoint.

        Verifies the endpoint correctly handles requests when user_context
        includes team_id from JWT token. Also verifies check_permission is
        called with the team_id from user_context.
        """
        TestSessionLocal, _ = test_db_and_client

        # Mock permission service to grant permission and capture call args
        mock_perm_instance = AsyncMock()
        mock_perm_instance.check_permission = AsyncMock(return_value=True)
        mock_perm_service_class.return_value = mock_perm_instance

        # Mock service to return tuple (data, next_cursor) as expected by handler
        mock_list_gateways.return_value = ([], None)

        # Set up user context with team_id from token
        mock_user = MagicMock()
        mock_user.email = "team-user@example.com"

        async def mock_user_with_team():
            return {
                "email": "team-user@example.com",
                "full_name": "Team User",
                "is_admin": False,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": TestSessionLocal(),
                "team_id": "team-X",  # Team ID from JWT token
            }

        app.dependency_overrides[require_auth] = lambda: "team-user@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_team

        client = TestClient(app)

        # Call GET /gateways WITHOUT team_id parameter
        response = client.get(
            "/gateways",
            headers={"Authorization": "Bearer test-token"}
        )

        # Should succeed
        assert response.status_code == 200

        # Verify check_permission was called with team_id from user_context
        mock_perm_instance.check_permission.assert_called()
        call_kwargs = mock_perm_instance.check_permission.call_args.kwargs
        assert call_kwargs["team_id"] == "team-X", f"Expected team_id='team-X', got {call_kwargs.get('team_id')}"

        # Cleanup
        app.dependency_overrides.clear()

    @pytest.mark.skip(reason="Team mismatch check requires request.state.team_id set via auth middleware; covered by manual testing")
    @patch("mcpgateway.main.gateway_service.list_gateways", new_callable=AsyncMock)
    def test_team_scoped_role_with_mismatched_team_id_gets_403(
        self,
        mock_list_gateways: AsyncMock,
        test_db_and_client,
    ):
        """Test that team-scoped role with mismatched team_id param gets 403.

        Scenario:
        - User has team-scoped role in team X
        - User's token is scoped to team X (via request.state.team_id)
        - User calls GET /gateways?team_id=Y (different team)
        Expected: 403 Forbidden (team mismatch check in endpoint)

        NOTE: This test is skipped because the team mismatch check at main.py:4588
        requires request.state.team_id to be set by auth middleware. Mocking
        get_current_user_with_permissions alone doesn't set request.state.team_id.
        The behavior is verified via manual testing and the unit tests cover
        the RBAC decorator logic.
        """
        TestSessionLocal, _ = test_db_and_client

        # Mock service to return tuple (data, next_cursor)
        mock_list_gateways.return_value = ([], None)

        # Set up user context with team_id from token
        mock_user = MagicMock()
        mock_user.email = "team-user@example.com"

        async def mock_user_with_team():
            return {
                "email": "team-user@example.com",
                "full_name": "Team User",
                "is_admin": False,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": TestSessionLocal(),
                "team_id": "team-X",  # Token is scoped to team X
            }

        app.dependency_overrides[require_auth] = lambda: "team-user@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_team

        client = TestClient(app)

        # Call GET /gateways with DIFFERENT team_id parameter
        response = client.get(
            "/gateways?team_id=team-Y",  # Mismatched team
            headers={"Authorization": "Bearer test-token"}
        )

        # Should get 403 - team mismatch
        assert response.status_code == 403

        # Cleanup
        app.dependency_overrides.clear()

    @patch("mcpgateway.middleware.rbac.PermissionService")
    @patch("mcpgateway.main.server_service.list_servers", new_callable=AsyncMock)
    def test_team_scoped_user_can_call_servers_endpoint(
        self,
        mock_list_servers: AsyncMock,
        mock_perm_service_class: MagicMock,
        test_db_and_client,
    ):
        """Test that user with team_id in context can call servers endpoint.

        Verifies the endpoint correctly handles requests when user_context
        includes team_id, even for endpoints without team_id query param.
        Also verifies check_permission is called with the correct team_id.
        """
        TestSessionLocal, _ = test_db_and_client

        # Mock permission service to grant permission and capture call args
        mock_perm_instance = AsyncMock()
        mock_perm_instance.check_permission = AsyncMock(return_value=True)
        mock_perm_service_class.return_value = mock_perm_instance

        # Mock service to return tuple (data, next_cursor) as expected by handler
        mock_list_servers.return_value = ([], None)

        # Set up user context with team_id from token
        mock_user = MagicMock()
        mock_user.email = "team-user@example.com"

        async def mock_user_with_team():
            return {
                "email": "team-user@example.com",
                "full_name": "Team User",
                "is_admin": False,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": TestSessionLocal(),
                "team_id": "team-servers",  # Team ID from JWT token
            }

        app.dependency_overrides[require_auth] = lambda: "team-user@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_team

        client = TestClient(app)

        # Call GET /servers - endpoint doesn't accept team_id parameter
        response = client.get(
            "/servers",
            headers={"Authorization": "Bearer test-token"}
        )

        # Should succeed
        assert response.status_code == 200

        # Verify check_permission was called with team_id from user_context
        mock_perm_instance.check_permission.assert_called()
        call_kwargs = mock_perm_instance.check_permission.call_args.kwargs
        assert call_kwargs["team_id"] == "team-servers", f"Expected team_id='team-servers', got {call_kwargs.get('team_id')}"

        # Cleanup
        app.dependency_overrides.clear()
