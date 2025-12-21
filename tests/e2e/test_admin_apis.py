# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_admin_apis.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end tests for MCP Gateway admin APIs.
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
os.environ["MCPGATEWAY_A2A_ENABLED"] = "false"  # Disable A2A for e2e tests

# Standard
import logging  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from urllib.parse import quote  # noqa: E402
import uuid  # noqa: E402

# Third-Party
from httpx import AsyncClient  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402


logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")


# pytest.skip("Temporarily disabling this suite", allow_module_level=True)


# -------------------------
# Test Configuration
# -------------------------
def create_test_jwt_token():
    """Create a proper JWT token for testing with required audience and issuer."""
    # Standard
    import datetime

    # Third-Party
    import jwt

    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=60)
    payload = {
        "sub": "admin@example.com",
        "email": "admin@example.com",
        "iat": int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        "exp": int(expire.timestamp()),
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
        "teams": [],  # Empty teams list allows access to public resources and own private resources
    }

    # Use the test JWT secret key
    return jwt.encode(payload, "my-test-key", algorithm="HS256")


TEST_JWT_TOKEN = create_test_jwt_token()
TEST_AUTH_HEADER = {"Authorization": f"Bearer {TEST_JWT_TOKEN}"}

# Local
# Test user for the updated authentication system
from tests.utils.rbac_mocks import create_mock_email_user  # noqa: E402

TEST_USER = create_mock_email_user(email="admin@example.com", full_name="Test Admin", is_admin=True, is_active=True)


# -------------------------
# Fixtures
# -------------------------
@pytest_asyncio.fixture
async def client(app_with_temp_db):
    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.db import get_db
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.utils.create_jwt_token import get_jwt_token
    from mcpgateway.utils.verify_credentials import require_admin_auth

    # Local
    from tests.utils.rbac_mocks import create_mock_user_context

    # Get the actual test database session from the app
    test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db

    def get_test_db_session():
        """Get the actual test database session."""
        if callable(test_db_dependency):
            return next(test_db_dependency())
        return test_db_dependency

    # Create mock user context with actual test database session
    test_db_session = get_test_db_session()
    test_user_context = create_mock_user_context(email="admin@example.com", full_name="Test Admin", is_admin=True)
    test_user_context["db"] = test_db_session

    # Mock admin authentication function
    async def mock_require_admin_auth():
        """Mock admin auth that returns admin email."""
        return "admin@example.com"

    # Mock JWT token function
    async def mock_get_jwt_token():
        """Mock JWT token function."""
        return TEST_JWT_TOKEN

    # Mock all authentication dependencies
    app_with_temp_db.dependency_overrides[get_current_user] = lambda: TEST_USER
    app_with_temp_db.dependency_overrides[get_current_user_with_permissions] = lambda: test_user_context
    app_with_temp_db.dependency_overrides[require_admin_auth] = mock_require_admin_auth
    app_with_temp_db.dependency_overrides[get_jwt_token] = mock_get_jwt_token
    # Keep the existing get_db override from app_with_temp_db

    # Third-Party
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app_with_temp_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Clean up dependency overrides (except get_db which belongs to app_with_temp_db)
    app_with_temp_db.dependency_overrides.pop(get_current_user, None)
    app_with_temp_db.dependency_overrides.pop(get_current_user_with_permissions, None)
    app_with_temp_db.dependency_overrides.pop(require_admin_auth, None)
    app_with_temp_db.dependency_overrides.pop(get_jwt_token, None)


@pytest_asyncio.fixture
async def mock_settings():
    """Mock settings to enable admin API."""
    # First-Party
    from mcpgateway.config import settings as real_settings

    _mock = MagicMock(wrap=real_settings)  # noqa: F841

    # Override specific settings for testing
    _mock.cache_type = "database"
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
        # Don't assume empty - accept either the legacy list response
        # or the newer paginated dict response with 'data' key.
        resp_json = response.json()
        assert isinstance(resp_json, (list, dict))
        if isinstance(resp_json, dict):
            assert "data" in resp_json and isinstance(resp_json["data"], list)

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
            "visibility": "public",  # Make public to allow access with public-only token
        }

        # POST to /admin/servers should redirect
        response = await client.post("/admin/servers", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 200
        # assert "/admin#catalog" in response.headers["location"]

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
            "visibility": "public",  # Keep public visibility
        }
        response = await client.post(f"/admin/servers/{server_id}/edit", data=edit_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 200

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
        # Don't assume empty - accept either the legacy list response
        # or the newer paginated dict response with 'data' key.
        resp_json = response.json()
        assert isinstance(resp_json, (list, dict))
        if isinstance(resp_json, dict):
            assert "data" in resp_json and isinstance(resp_json["data"], list)

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
        """Test creating tool with duplicate name via admin UI for private, team, and public scopes."""
        import uuid

        unique_name = f"duplicate_tool_{uuid.uuid4().hex[:8]}"
        # create a real team and use its ID
        from mcpgateway.services.team_management_service import TeamManagementService

        # Get db session from test fixture context
        # The client fixture sets test_user_context["db"]
        db = None
        if hasattr(client, "_default_params") and "db" in client._default_params:
            db = client._default_params["db"]
        else:
            # Fallback: import get_db and use it directly if available
            try:
                from mcpgateway.db import get_db

                db = next(get_db())
            except Exception:
                pass
        assert db is not None, "Test database session not found. Ensure your test fixture exposes db."
        team_service = TeamManagementService(db)
        new_team = await team_service.create_team(name="Test Team", description="A team for testing", created_by="admin@example.com", visibility="private")
        # Private scope (owner-level)
        form_data_private = {
            "name": unique_name,
            "url": "https://example.com",
            "integrationType": "REST",
            "requestType": "GET",
            "headers": "{}",
            "input_schema": "{}",
            "visibility": "private",
            "user_email": "admin@example.com",
            "team_id": new_team.id,
        }
        response = await client.post("/admin/tools/", data=form_data_private, headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["success"] is True
        # Try to create duplicate private tool (same name, same owner)
        response = await client.post("/admin/tools/", data=form_data_private, headers=TEST_AUTH_HEADER)
        assert response.status_code == 409
        assert response.json()["success"] is False

        # Team scope:
        real_team_id = new_team.id
        form_data_team = {
            "name": unique_name + "_team",
            "url": "https://example.com",
            "integrationType": "REST",
            "requestType": "GET",
            "headers": "{}",
            "input_schema": "{}",
            "visibility": "team",
            "team_id": real_team_id,
            "user_email": "admin@example.com",
        }
        print("DEBUG: form_data_team before request:", form_data_team, "team_id type:", type(form_data_team["team_id"]))
        response = await client.post("/admin/tools/", data=form_data_team, headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["success"] is True
        # Try to create duplicate team tool (same name, same team)
        response = await client.post("/admin/tools/", data=form_data_team, headers=TEST_AUTH_HEADER)
        # If uniqueness is enforced at the application level, expect 409 error
        assert response.status_code == 409
        assert response.json()["success"] is False

        # Public scope
        form_data_public = {
            "name": unique_name + "_public",
            "url": "https://example.com",
            "integrationType": "REST",
            "requestType": "GET",
            "headers": "{}",
            "input_schema": "{}",
            "visibility": "public",
            "user_email": "admin@example.com",
            "team_id": new_team.id,
        }
        response = await client.post("/admin/tools/", data=form_data_public, headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["success"] is True
        # Try to create duplicate public tool (same name, public)
        response = await client.post("/admin/tools/", data=form_data_public, headers=TEST_AUTH_HEADER)
        assert response.status_code == 409
        assert response.json()["success"] is False


# -------------------------
# Test Resource Admin APIs
# -------------------------
class TestAdminResourceAPIs:
    """Test admin resource management endpoints."""

    async def test_admin_add_resource(self, client: AsyncClient, mock_settings):
        """Test adding a resource via the admin UI with new logic."""
        # Define valid form data
        valid_form_data = {
            "uri": "test://resource1",
            "name": "Test Resource",
            "description": "A test resource",
            "mimeType": "text/plain",
            "content": "Sample content",
        }

        # Test successful resource creation
        response = await client.post("/admin/resources", data=valid_form_data, headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert "message" in result and "Add resource registered successfully!" in result["message"]

        # Test missing required fields
        invalid_form_data = {
            "name": "Test Resource",
            "description": "A test resource",
            # Missing 'uri', 'mimeType', and 'content'
        }
        response = await client.post("/admin/resources", data=invalid_form_data, headers=TEST_AUTH_HEADER)
        assert response.status_code == 500

        # Test ValidationError (422)
        invalid_validation_data = {
            "uri": "",
            "name": "",
            "description": "",
            "mimeType": "",
            "content": "",
        }
        response = await client.post("/admin/resources", data=invalid_validation_data, headers=TEST_AUTH_HEADER)
        assert response.status_code == 422

        # Test duplicate URI
        response = await client.post("/admin/resources", data=valid_form_data, headers=TEST_AUTH_HEADER)
        assert response.status_code == 409


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
            "visibility": "public",  # Make public to allow access with public-only token
        }

        # POST to /admin/prompts should redirect
        response = await client.post("/admin/prompts", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 200

        # List prompts to verify creation
        response = await client.get("/admin/prompts", headers=TEST_AUTH_HEADER)
        prompts = response.json()
        assert len(prompts) == 1
        prompt = prompts[0]
        assert prompt["name"] == "test_admin_prompt"
        prompt_id = prompt["id"]

        # Get individual prompt
        response = await client.get(f"/admin/prompts/{prompt_id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["name"] == "test_admin_prompt"

        # Edit prompt
        edit_data = {
            "name": "updated_admin_prompt",
            "description": "Updated description",
            "template": "Updated {{greeting}}",
            "arguments": '[{"name": "greeting", "description": "Greeting", "required": false}]',
            "visibility": "public",  # Keep public visibility
        }
        response = await client.post(f"/admin/prompts/{prompt_id}/edit", data=edit_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 200

        # Toggle prompt status
        response = await client.post(f"/admin/prompts/{prompt_id}/toggle", data={"activate": "false"}, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 303

        # Delete prompt (use updated name)
        response = await client.post(f"/admin/prompts/{prompt_id}/delete", headers=TEST_AUTH_HEADER, follow_redirects=False)
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
