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
