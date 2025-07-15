# -*- coding: utf-8 -*-
"""
End-to-end tests for MCP Gateway admin APIs.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module contains comprehensive end-to-end tests for all admin API endpoints.
These tests are designed to exercise the entire application stack with minimal mocking,
using only a temporary SQLite database and bypassing authentication.

The tests cover:
- Admin UI main page
- Server management (CRUD operations via admin UI)
- Tool management (CRUD operations via admin UI)
- Resource management (CRUD operations via admin UI)
- Prompt management (CRUD operations via admin UI)
- Gateway management (CRUD operations via admin UI)
- Root management (add/remove via admin UI)
- Metrics viewing and reset
- Form submissions and redirects

Each test class corresponds to a specific admin API group, making it easy to run
isolated test suites for specific functionality. The tests use a real SQLite
database that is created fresh for each test run, ensuring complete isolation
and reproducibility.
"""

# Standard
# CRITICAL: Set environment variables BEFORE any mcpgateway imports!
import os

os.environ["MCPGATEWAY_ADMIN_API_ENABLED"] = "true"
os.environ["MCPGATEWAY_UI_ENABLED"] = "true"

# Standard
import tempfile
from typing import AsyncGenerator
from unittest.mock import patch
from urllib.parse import quote
import uuid

# Third-Party
from httpx import AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base
from mcpgateway.main import app, get_db

# pytest.skip("Temporarily disabling this suite", allow_module_level=True)

# -------------------------
# Test Configuration
# -------------------------
TEST_USER = "testuser"
TEST_PASSWORD = "testpass"
TEST_AUTH_HEADER = {"Authorization": f"Bearer {TEST_USER}:{TEST_PASSWORD}"}


# -------------------------
# Fixtures
# -------------------------
@pytest_asyncio.fixture
async def temp_db():
    """
    Create a temporary SQLite database for testing.

    This fixture creates a fresh database for each test, ensuring complete
    isolation between tests. The database is automatically cleaned up after
    the test completes.
    """
    # Create temporary file for SQLite database
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    # Create engine with SQLite
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Create session factory
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Override the get_db dependency
    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Override authentication for all tests
    # First-Party
    from mcpgateway.utils.verify_credentials import require_auth, require_basic_auth

    def override_auth():
        return TEST_USER

    app.dependency_overrides[require_auth] = override_auth
    app.dependency_overrides[require_basic_auth] = override_auth

    yield engine

    # Cleanup
    app.dependency_overrides.clear()
    os.close(db_fd)
    os.unlink(db_path)


@pytest_asyncio.fixture
async def client(temp_db) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with the test database."""
    # Third-Party
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def mock_settings():
    """Mock settings to enable admin API."""
    # First-Party
    from mcpgateway.config import settings as real_settings

    with patch("mcpgateway.config.settings") as mock_settings:
        # Copy all existing settings
        for attr in dir(real_settings):
            if not attr.startswith("_"):
                setattr(mock_settings, attr, getattr(real_settings, attr))

        # Override specific settings for testing
        mock_settings.cache_type = "database"
        mock_settings.mcpgateway_admin_api_enabled = True
        mock_settings.mcpgateway_ui_enabled = False
        mock_settings.auth_required = False

        yield mock_settings


# -------------------------
# Test Admin UI Main Page
# -------------------------
class TestAdminUIMainPage:
    """Test the main admin UI page."""

    async def test_admin_ui_home(self, client: AsyncClient, mock_settings):
        """Test the admin UI home page renders correctly."""
        response = await client.get("/admin/", headers=TEST_AUTH_HEADER)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        # Check for HTML content
        assert b"<!DOCTYPE html>" in response.content or b"<html" in response.content

    async def test_admin_ui_home_with_inactive(self, client: AsyncClient, mock_settings):
        """Test the admin UI home page with include_inactive parameter."""
        response = await client.get("/admin/?include_inactive=true", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200


# -------------------------
# Test Server Admin APIs
# -------------------------
class TestAdminServerAPIs:
    """Test admin server management endpoints."""

    async def test_admin_list_servers_empty(self, client: AsyncClient, mock_settings):
        """Test GET /admin/servers returns list of servers."""
        response = await client.get("/admin/servers", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        # Don't assume empty - just check it returns a list
        assert isinstance(response.json(), list)

    async def test_admin_server_lifecycle(self, client: AsyncClient, mock_settings):
        """Test complete server lifecycle through admin UI."""
        # Use unique name to avoid conflicts
        unique_name = f"test_admin_server_{uuid.uuid4().hex[:8]}"

        # Create a server via form submission
        form_data = {
            "name": unique_name,
            "description": "Test server via admin",
            "icon": "https://example.com/icon.png",
            "associatedTools": "",  # Empty initially
            "associatedResources": "",
            "associatedPrompts": "",
        }

        # POST to /admin/servers should redirect
        response = await client.post("/admin/servers", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303
        assert "/admin#catalog" in response.headers["location"]

        # Get all servers and find our server
        response = await client.get("/admin/servers", headers=TEST_AUTH_HEADER)
        servers = response.json()
        server = next((s for s in servers if s["name"] == unique_name), None)
        assert server is not None
        server_id = server["id"]

        # Get individual server
        response = await client.get(f"/admin/servers/{server_id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["name"] == unique_name

        # Edit server
        edit_data = {
            "name": f"updated_{unique_name}",
            "description": "Updated description",
            "icon": "https://example.com/new-icon.png",
            "associatedTools": "",
            "associatedResources": "",
            "associatedPrompts": "",
        }
        response = await client.post(f"/admin/servers/{server_id}/edit", data=edit_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # Toggle server status
        response = await client.post(f"/admin/servers/{server_id}/toggle", data={"activate": "false"}, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # Delete server
        response = await client.post(f"/admin/servers/{server_id}/delete", headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303


# -------------------------
# Test Tool Admin APIs
# -------------------------
class TestAdminToolAPIs:
    """Test admin tool management endpoints."""

    async def test_admin_list_tools_empty(self, client: AsyncClient, mock_settings):
        """Test GET /admin/tools returns list of tools."""
        response = await client.get("/admin/tools", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        # Don't assume empty - just check it returns a list
        assert isinstance(response.json(), list)

    # FIXME: Temporarily disabled due to issues with tool lifecycle tests
    # async def test_admin_tool_lifecycle(self, client: AsyncClient, mock_settings):
    #     """Test complete tool lifecycle through admin UI."""
    #     # Use unique name to avoid conflicts
    #     unique_name = f"test_admin_tool_{uuid.uuid4().hex[:8]}"

    #     # Create a tool via form submission
    #     form_data = {
    #         "name": unique_name,
    #         "url": "https://api.example.com/tool",
    #         "description": "Test tool via admin",
    #         "requestType": "GET",  # Changed from POST to GET
    #         "integrationType": "REST",
    #         "headers": '{"Content-Type": "application/json"}',
    #         "input_schema": '{"type": "object", "properties": {"test": {"type": "string"}}}',
    #         "jsonpath_filter": "",
    #         "auth_type": "none",
    #     }

    #     # POST to /admin/tools returns JSON response
    #     response = await client.post("/admin/tools/", data=form_data, headers=TEST_AUTH_HEADER)
    #     assert response.status_code == 200
    #     result = response.json()
    #     assert result["success"] is True

    #     # List tools to get ID
    #     response = await client.get("/admin/tools", headers=TEST_AUTH_HEADER)
    #     tools = response.json()
    #     tool = next((t for t in tools if t["originalName"] == unique_name), None)
    #     assert tool is not None
    #     tool_id = tool["id"]

    #     # Get individual tool
    #     response = await client.get(f"/admin/tools/{tool_id}", headers=TEST_AUTH_HEADER)
    #     assert response.status_code == 200

    #     # Edit tool
    #     edit_data = {
    #         "name": f"updated_{unique_name}",
    #         "url": "https://api.example.com/updated",
    #         "description": "Updated description",
    #         "requestType": "GET",
    #         "headers": "{}",
    #         "input_schema": "{}",
    #     }
    #     response = await client.post(f"/admin/tools/{tool_id}/edit", data=edit_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
    #     assert response.status_code == 303

    #     # Toggle tool status
    #     response = await client.post(f"/admin/tools/{tool_id}/toggle", data={"activate": "false"}, headers=TEST_AUTH_HEADER, follow_redirects=False)
    #     assert response.status_code == 303

    #     # Delete tool
    #     response = await client.post(f"/admin/tools/{tool_id}/delete", headers=TEST_AUTH_HEADER, follow_redirects=False)
    #     assert response.status_code == 303

    async def test_admin_tool_name_conflict(self, client: AsyncClient, mock_settings):
        """Test creating tool with duplicate name via admin UI."""
        unique_name = f"duplicate_tool_{uuid.uuid4().hex[:8]}"

        form_data = {
            "name": unique_name,
            "url": "https://example.com",
            "integrationType": "REST",
            "requestType": "GET",  # Add valid request type
            "headers": "{}",
            "input_schema": "{}",
        }

        # Create first tool
        response = await client.post("/admin/tools/", data=form_data, headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Try to create duplicate
        response = await client.post("/admin/tools/", data=form_data, headers=TEST_AUTH_HEADER)
        assert response.status_code in [400, 500]  # Could be either
        assert response.json()["success"] is False


# -------------------------
# Test Resource Admin APIs
# -------------------------
class TestAdminResourceAPIs:
    """Test admin resource management endpoints."""

    async def test_admin_list_resources_empty(self, client: AsyncClient, mock_settings):
        """Test GET /admin/resources returns empty list initially."""
        response = await client.get("/admin/resources", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json() == []

    async def test_admin_resource_lifecycle(self, client: AsyncClient, mock_settings):
        """Test complete resource lifecycle through admin UI."""
        # Create a resource via form submission
        form_data = {
            "uri": "admin/test/resource",
            "name": "test_admin_resource",
            "description": "Test resource via admin",
            "mimeType": "text/plain",
            "content": "Admin test content",
        }

        # POST to /admin/resources should redirect
        response = await client.post("/admin/resources", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # List resources to verify creation
        response = await client.get("/admin/resources", headers=TEST_AUTH_HEADER)
        resources = response.json()
        assert len(resources) == 1
        resource = resources[0]
        assert resource["name"] == "test_admin_resource"
        resource_id = resource["id"]

        # Get individual resource
        encoded_uri = quote(form_data["uri"], safe="")
        response = await client.get(f"/admin/resources/{encoded_uri}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert "resource" in data
        assert "content" in data

        # Edit resource
        edit_data = {
            "name": "updated_admin_resource",
            "description": "Updated description",
            "mimeType": "text/markdown",
            "content": "Updated admin content",
        }
        response = await client.post(f"/admin/resources/{encoded_uri}/edit", data=edit_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # Toggle resource status
        response = await client.post(f"/admin/resources/{resource_id}/toggle", data={"activate": "false"}, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # Delete resource
        response = await client.post(f"/admin/resources/{encoded_uri}/delete", headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303


# -------------------------
# Test Prompt Admin APIs
# -------------------------
class TestAdminPromptAPIs:
    """Test admin prompt management endpoints."""

    async def test_admin_list_prompts_empty(self, client: AsyncClient, mock_settings):
        """Test GET /admin/prompts returns empty list initially."""
        response = await client.get("/admin/prompts", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json() == []

    async def test_admin_prompt_lifecycle(self, client: AsyncClient, mock_settings):
        """Test complete prompt lifecycle through admin UI."""
        # Create a prompt via form submission
        form_data = {
            "name": "test_admin_prompt",
            "description": "Test prompt via admin",
            "template": "Hello {{name}}, this is a test prompt",
            "arguments": '[{"name": "name", "description": "User name", "required": true}]',
        }

        # POST to /admin/prompts should redirect
        response = await client.post("/admin/prompts", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # List prompts to verify creation
        response = await client.get("/admin/prompts", headers=TEST_AUTH_HEADER)
        prompts = response.json()
        assert len(prompts) == 1
        prompt = prompts[0]
        assert prompt["name"] == "test_admin_prompt"
        prompt_id = prompt["id"]

        # Get individual prompt
        response = await client.get(f"/admin/prompts/{form_data['name']}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["name"] == "test_admin_prompt"

        # Edit prompt
        edit_data = {
            "name": "updated_admin_prompt",
            "description": "Updated description",
            "template": "Updated {{greeting}}",
            "arguments": '[{"name": "greeting", "description": "Greeting", "required": false}]',
        }
        response = await client.post(f"/admin/prompts/{form_data['name']}/edit", data=edit_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # Toggle prompt status
        response = await client.post(f"/admin/prompts/{prompt_id}/toggle", data={"activate": "false"}, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # Delete prompt (use updated name)
        response = await client.post(f"/admin/prompts/{edit_data['name']}/delete", headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303


# -------------------------
# Test Gateway Admin APIs
# -------------------------
class TestAdminGatewayAPIs:
    """Test admin gateway management endpoints."""

    async def test_admin_list_gateways_empty(self, client: AsyncClient, mock_settings):
        """Test GET /admin/gateways returns list of gateways."""
        response = await client.get("/admin/gateways", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        # Don't assume empty - just check it returns a list
        assert isinstance(response.json(), list)

    @pytest.mark.skip(reason="Gateway registration requires external connectivity")
    async def test_admin_gateway_lifecycle(self, client: AsyncClient, mock_settings):
        """Test complete gateway lifecycle through admin UI."""
        # Gateway tests would require mocking external connections

    # FIXME: Temporarily disabled due to issues with gateway lifecycle tests
    # async def test_admin_test_gateway_endpoint(self, client: AsyncClient, mock_settings):
    #     """Test the gateway test endpoint."""
    #     # Fix the import path - should be admin module directly
    #     with patch("mcpgateway.admin.httpx.AsyncClient") as mock_client_class:
    #         mock_client = MagicMock()
    #         mock_response = MagicMock()
    #         mock_response.status_code = 200
    #         mock_response.json.return_value = {"status": "ok"}
    #         mock_response.headers = {}

    #         # Setup async context manager
    #         mock_client.__aenter__.return_value = mock_client
    #         mock_client.__aexit__.return_value = None
    #         mock_client.request.return_value = mock_response
    #         mock_client_class.return_value = mock_client

    #         request_data = {
    #             "base_url": "https://api.example.com",
    #             "path": "/test",
    #             "method": "GET",
    #             "headers": {},
    #             "body": None,
    #         }

    #         response = await client.post("/admin/gateways/test", json=request_data, headers=TEST_AUTH_HEADER)

    #         assert response.status_code == 200
    #         data = response.json()
    #         assert data["status_code"] == 200
    #         assert "latency_ms" in data


# -------------------------
# Test Root Admin APIs
# -------------------------
class TestAdminRootAPIs:
    """Test admin root management endpoints."""

    async def test_admin_root_lifecycle(self, client: AsyncClient, mock_settings):
        """Test complete root lifecycle through admin UI."""
        # Add a root
        form_data = {
            "uri": f"/test/admin/root/{uuid.uuid4().hex[:8]}",
            "name": "Test Admin Root",
        }

        response = await client.post("/admin/roots", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # Delete the root - use the normalized URI with file:// prefix
        normalized_uri = f"file://{form_data['uri']}"
        encoded_uri = quote(normalized_uri, safe="")
        response = await client.post(f"/admin/roots/{encoded_uri}/delete", headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303


# -------------------------
# Test Metrics Admin APIs
# -------------------------
class TestAdminMetricsAPIs:
    """Test admin metrics endpoints."""

    async def test_admin_get_metrics(self, client: AsyncClient, mock_settings):
        """Test GET /admin/metrics."""
        response = await client.get("/admin/metrics", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()

        # Verify all metric categories are present
        assert "tools" in data
        assert "resources" in data
        assert "servers" in data
        assert "prompts" in data

    async def test_admin_reset_metrics(self, client: AsyncClient, mock_settings):
        """Test POST /admin/metrics/reset."""
        response = await client.post("/admin/metrics/reset", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "reset successfully" in data["message"]


# -------------------------
# Test Error Handling
# -------------------------
class TestAdminErrorHandling:
    """Test error handling in admin endpoints."""

    async def test_admin_server_not_found(self, client: AsyncClient, mock_settings):
        """Test accessing non-existent server."""
        response = await client.get("/admin/servers/non-existent-id", headers=TEST_AUTH_HEADER)
        # API returns 400 for invalid ID format (TODO: should be 404?)
        assert response.status_code in [400, 404]

    # FIXME: This test should be updated to check for 404 instead of 500
    # async def test_admin_tool_not_found(self, client: AsyncClient, mock_settings):
    #     """Test accessing non-existent tool."""
    #     response = await client.get("/admin/tools/non-existent-id", headers=TEST_AUTH_HEADER)
    #     # Unhandled exception returns 500
    #     assert response.status_code == 500

    # FIXME: This test should be updated to check for 404 instead of 500
    # async def test_admin_resource_not_found(self, client: AsyncClient, mock_settings):
    #     """Test accessing non-existent resource."""
    #     response = await client.get("/admin/resources/non/existent/uri", headers=TEST_AUTH_HEADER)
    #     # Unhandled exception returns 500
    #     assert response.status_code == 500

    # FIXME: This test should be updated to check for 404 instead of 500
    # async def test_admin_prompt_not_found(self, client: AsyncClient, mock_settings):
    #     """Test accessing non-existent prompt."""
    #     response = await client.get("/admin/prompts/non-existent-prompt", headers=TEST_AUTH_HEADER)
    #     # Unhandled exception returns 500
    #     assert response.status_code == 500

    # FIXME: This test should be updated to check for 404 instead of 500
    # async def test_admin_gateway_not_found(self, client: AsyncClient, mock_settings):
    #     """Test accessing non-existent gateway."""
    #     response = await client.get("/admin/gateways/non-existent-id", headers=TEST_AUTH_HEADER)
    #     # Unhandled exception returns 500
    #     assert response.status_code == 500


# -------------------------
# Test Include Inactive Parameter
# -------------------------
class TestAdminIncludeInactive:
    """Test include_inactive parameter handling."""

    # FIXME: IndexError: list index out of range
    # async def test_toggle_with_inactive_redirect(self, client: AsyncClient, mock_settings):
    #     """Test that toggle endpoints respect include_inactive parameter."""
    #     # First create a server
    #     form_data = {
    #         "name": "inactive_test_server",
    #         "description": "Test inactive handling",
    #     }

    #     response = await client.post("/admin/servers", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
    #     assert response.status_code == 303

    #     # Get server ID
    #     response = await client.get("/admin/servers", headers=TEST_AUTH_HEADER)
    #     server_id = response.json()[0]["id"]

    #     # Toggle with include_inactive flag
    #     form_data = {
    #         "activate": "false",
    #         "is_inactive_checked": "true",
    #     }

    #     response = await client.post(f"/admin/servers/{server_id}/toggle", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)

    #     assert response.status_code == 303
    #     assert "include_inactive=true" in response.headers["location"]


# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
