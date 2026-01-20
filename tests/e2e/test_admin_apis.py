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
        resp_json = response.json()
        # Handle paginated response
        servers = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
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

        # Set server state
        response = await client.post(f"/admin/servers/{server_id}/state", data={"activate": "false"}, headers=TEST_AUTH_HEADER, follow_redirects=False)
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

    #     # Set tool state
    #     response = await client.post(f"/admin/tools/{tool_id}/state", data={"activate": "false"}, headers=TEST_AUTH_HEADER, follow_redirects=False)
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
        new_team = await team_service.create_team(name=f"Test Team - {uuid.uuid4().hex[:8]}", description="A team for testing", created_by="admin@example.com", visibility="private")
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
# Test Tool Ops Admin APIs
# -------------------------
class TestAdminToolOpsAPIs:
    """Test admin tool-ops management endpoints."""

    async def test_admin_tool_ops_partial_with_team_id(self, client, app_with_temp_db):
        """Test that /admin/tool-ops/partial respects team_id parameter."""
        # First-Party
        from mcpgateway.db import get_db
        from mcpgateway.services.team_management_service import TeamManagementService

        # Get db session from app's dependency overrides or directly from get_db
        # (which uses the patched SessionLocal in tests)
        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create two teams (creator is automatically added as owner)
        team_service = TeamManagementService(db)
        team1 = await team_service.create_team(name=f"Team 1 - {uuid.uuid4().hex[:8]}", description="First team", created_by="admin@example.com", visibility="private")
        team2 = await team_service.create_team(name=f"Team 2 - {uuid.uuid4().hex[:8]}", description="Second team", created_by="admin@example.com", visibility="private")

        # Create tools in different teams
        # Note: tool names get normalized to use hyphens instead of underscores
        tool1_name = f"team1-tool-{uuid.uuid4().hex[:8]}"
        tool2_name = f"team2-tool-{uuid.uuid4().hex[:8]}"
        tool1_data = {
            "name": tool1_name,
            "url": "http://example.com/tool1",
            "description": "Tool in team 1",
            "visibility": "team",
            "team_id": team1.id,
        }
        tool2_data = {
            "name": tool2_name,
            "url": "http://example.com/tool2",
            "description": "Tool in team 2",
            "visibility": "team",
            "team_id": team2.id,
        }

        # Create the tools
        await client.post("/admin/tools/", data=tool1_data, headers=TEST_AUTH_HEADER)
        await client.post("/admin/tools/", data=tool2_data, headers=TEST_AUTH_HEADER)

        # Test filtering by team1 - should only return tool1
        response = await client.get(f"/admin/tool-ops/partial?team_id={team1.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert tool1_name in html
        assert tool2_name not in html

        # Test filtering by team2 - should only return tool2
        response = await client.get(f"/admin/tool-ops/partial?team_id={team2.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert tool2_name in html
        assert tool1_name not in html

        # Test without team_id filter - should return both
        response = await client.get("/admin/tool-ops/partial", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert tool1_name in html
        assert tool2_name in html


# -------------------------
# Test Resource Admin APIs
# -------------------------
class TestAdminResourceAPIs:
    """Test admin resource management endpoints."""

    async def test_admin_add_resource(self, client: AsyncClient, mock_settings):
        """Test adding a resource via the admin UI with new logic."""
        # Define valid form data
        valid_form_data = {
            "uri": f"test://resource1-{uuid.uuid4().hex[:8]}",
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
        resp_json = response.json()
        # Handle paginated response
        prompts = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
        assert prompts == []

    async def test_admin_prompt_lifecycle(self, client: AsyncClient, mock_settings):
        """Test complete prompt lifecycle through admin UI."""
        # Create a prompt via form submission
        form_data = {
            "name": f"test_admin_prompt_{uuid.uuid4().hex[:8]}",
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
        resp_json = response.json()
        # Handle paginated response
        prompts = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
        assert len(prompts) >= 1
        prompt = next((p for p in prompts if p["originalName"] == form_data["name"]), None)
        assert prompt is not None
        prompt_id = prompt["id"]

        # Get individual prompt
        response = await client.get(f"/admin/prompts/{prompt_id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["originalName"] == form_data["name"]

        # Edit prompt
        edit_data = {
            "name": f"updated_admin_prompt_{uuid.uuid4().hex[:8]}",
            "description": "Updated description",
            "template": "Updated {{greeting}}",
            "arguments": '[{"name": "greeting", "description": "Greeting", "required": false}]',
            "visibility": "public",  # Keep public visibility
        }
        response = await client.post(f"/admin/prompts/{prompt_id}/edit", data=edit_data, headers=TEST_AUTH_HEADER, follow_redirects=False)
        assert response.status_code == 200

        # Set prompt state
        response = await client.post(f"/admin/prompts/{prompt_id}/state", data={"activate": "false"}, headers=TEST_AUTH_HEADER, follow_redirects=False)
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
        resp_json = response.json()
        # Handle paginated response
        assert isinstance(resp_json, (list, dict))
        if isinstance(resp_json, dict):
            assert "data" in resp_json

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

    #     response = await client.post(f"/admin/servers/{server_id}/state", data=form_data, headers=TEST_AUTH_HEADER, follow_redirects=False)

    #     assert response.status_code == 303
    #     assert "include_inactive=true" in response.headers["location"]


@pytest.mark.asyncio
class TestTeamFiltering:
    """Test team_id filtering across partial, search, and ids endpoints."""

    async def test_tools_partial_with_team_id(self, client, app_with_temp_db):
        """Test that /admin/tools/partial respects team_id parameter."""
        # First-Party
        from mcpgateway.db import get_db
        from mcpgateway.services.team_management_service import TeamManagementService

        # Get db session from app's dependency overrides or directly from get_db
        # (which uses the patched SessionLocal in tests)
        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create two teams (creator is automatically added as owner)
        team_service = TeamManagementService(db)
        team1 = await team_service.create_team(name=f"Team 1 - {uuid.uuid4().hex[:8]}", description="First team", created_by="admin@example.com", visibility="private")
        team2 = await team_service.create_team(name=f"Team 2 - {uuid.uuid4().hex[:8]}", description="Second team", created_by="admin@example.com", visibility="private")

        # Create tools in different teams
        # Note: tool names get normalized to use hyphens instead of underscores
        tool1_name = f"team1-tool-{uuid.uuid4().hex[:8]}"
        tool2_name = f"team2-tool-{uuid.uuid4().hex[:8]}"
        tool1_data = {
            "name": tool1_name,
            "url": "http://example.com/tool1",
            "description": "Tool in team 1",
            "visibility": "team",
            "team_id": team1.id,
        }
        tool2_data = {
            "name": tool2_name,
            "url": "http://example.com/tool2",
            "description": "Tool in team 2",
            "visibility": "team",
            "team_id": team2.id,
        }

        # Create the tools
        await client.post("/admin/tools/", data=tool1_data, headers=TEST_AUTH_HEADER)
        await client.post("/admin/tools/", data=tool2_data, headers=TEST_AUTH_HEADER)

        # Test filtering by team1 - should only return tool1
        response = await client.get(f"/admin/tools/partial?team_id={team1.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert tool1_name in html
        assert tool2_name not in html

        # Test filtering by team2 - should only return tool2
        response = await client.get(f"/admin/tools/partial?team_id={team2.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert tool2_name in html
        assert tool1_name not in html

        # Test without team_id filter - should return both
        response = await client.get("/admin/tools/partial", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert tool1_name in html
        assert tool2_name in html

    async def test_tools_ids_with_team_id(self, client, app_with_temp_db):
        """Test that /admin/tools/ids respects team_id parameter."""
        # First-Party
        from mcpgateway.db import get_db, Tool as DbTool
        from mcpgateway.services.team_management_service import TeamManagementService

        # Get db session from app's dependency overrides or directly from get_db
        # (which uses the patched SessionLocal in tests)
        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create TWO teams
        team_service = TeamManagementService(db)
        team1 = await team_service.create_team(name=f"Team 1 IDs - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")
        team2 = await team_service.create_team(name=f"Team 2 IDs - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")

        # Create tools in different teams
        team1_tool_id = uuid.uuid4().hex
        team1_tool = DbTool(
            id=team1_tool_id,
            original_name=f"team1_tool_{uuid.uuid4().hex[:8]}",
            url="http://example.com/team1",
            description="Team 1 tool",
            visibility="team",
            team_id=team1.id,
            owner_email="admin@example.com",
            enabled=True,
            input_schema={},
        )
        db.add(team1_tool)

        team2_tool_id = uuid.uuid4().hex
        team2_tool = DbTool(
            id=team2_tool_id,
            original_name=f"team2_tool_{uuid.uuid4().hex[:8]}",
            url="http://example.com/team2",
            description="Team 2 tool",
            visibility="team",
            team_id=team2.id,
            owner_email="admin@example.com",
            enabled=True,
            input_schema={},
        )
        db.add(team2_tool)
        db.commit()

        # Test filtering by team1 - should return ONLY team1 tools (strict team scoping)
        response = await client.get(f"/admin/tools/ids?team_id={team1.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert team1_tool_id in data["tool_ids"]
        assert team2_tool_id not in data["tool_ids"], "team2 tool should NOT appear when filtering by team1"

        # Test without filter - should return both
        response = await client.get("/admin/tools/ids", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert team1_tool_id in data["tool_ids"]
        assert team2_tool_id in data["tool_ids"]

    async def test_tools_search_with_team_id(self, client, app_with_temp_db):
        """Test that /admin/tools/search respects team_id parameter."""
        # First-Party
        from mcpgateway.db import get_db
        from mcpgateway.services.team_management_service import TeamManagementService

        # Get db session from app's dependency overrides or directly from get_db
        # (which uses the patched SessionLocal in tests)
        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create TWO teams (creator is automatically added as owner)
        team_service = TeamManagementService(db)
        team1 = await team_service.create_team(name=f"Search Team 1 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")
        team2 = await team_service.create_team(name=f"Search Team 2 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")

        # Create searchable tools in different teams
        search_term = f"searchable_{uuid.uuid4().hex[:8]}"
        team1_tool_data = {
            "name": f"{search_term}_team1",
            "url": "http://example.com/team1",
            "description": "Searchable team1 tool",
            "visibility": "team",
            "team_id": team1.id,
        }
        team2_tool_data = {
            "name": f"{search_term}_team2",
            "url": "http://example.com/team2",
            "description": "Searchable team2 tool",
            "visibility": "team",
            "team_id": team2.id,
        }

        await client.post("/admin/tools/", data=team1_tool_data, headers=TEST_AUTH_HEADER)
        await client.post("/admin/tools/", data=team2_tool_data, headers=TEST_AUTH_HEADER)

        # Test search with team filter - returns ONLY team1 tools (strict team scoping)
        response = await client.get(f"/admin/tools/search?q={search_term}&team_id={team1.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        tool_names = [tool["name"] for tool in data["tools"]]
        assert team1_tool_data["name"] in tool_names
        assert team2_tool_data["name"] not in tool_names, "team2 tool should NOT appear when filtering by team1"

        # Test search without team filter - returns both
        response = await client.get(f"/admin/tools/search?q={search_term}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        tool_names = [tool["name"] for tool in data["tools"]]
        assert team1_tool_data["name"] in tool_names
        assert team2_tool_data["name"] in tool_names

    async def test_unauthorized_team_access(self, client, app_with_temp_db):
        """Test that users cannot filter by teams they're not members of."""
        # First-Party
        from mcpgateway.db import get_db
        from mcpgateway.services.team_management_service import TeamManagementService

        # Get db session from app's dependency overrides or directly from get_db
        # (which uses the patched SessionLocal in tests)
        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create a team but DON'T add the user to it
        team_service = TeamManagementService(db)
        other_team = await team_service.create_team(name=f"Other Team - {uuid.uuid4().hex[:8]}", description="Test", created_by="other@example.com", visibility="private")

        # Create a tool in that team
        tool_data = {
            "name": f"other_team_tool_{uuid.uuid4().hex[:8]}",
            "url": "http://example.com/other",
            "description": "Tool in other team",
            "visibility": "team",
            "team_id": other_team.id,
            "owner_email": "other@example.com",
        }

        # Manually insert the tool since we can't POST as another user
        from mcpgateway.db import Tool as DbTool

        db_tool = DbTool(
            id=uuid.uuid4().hex,
            original_name=tool_data["name"],
            url=tool_data["url"],
            description=tool_data["description"],
            visibility=tool_data["visibility"],
            team_id=tool_data["team_id"],
            owner_email=tool_data["owner_email"],
            enabled=True,
            input_schema={},  # Required: empty JSON schema
        )
        db.add(db_tool)
        db.commit()

        # Try to filter by the other team - returns empty results (user is not a member)
        response = await client.get(f"/admin/tools/partial?team_id={other_team.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert tool_data["name"] not in html

        # Same for /ids endpoint - the specific tool from other team should not be in results
        response = await client.get(f"/admin/tools/ids?team_id={other_team.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert db_tool.id not in data["tool_ids"], f"Tool from other team should not be accessible: {db_tool.id}"

    async def test_resources_partial_with_team_id(self, client, app_with_temp_db):
        """Test that /admin/resources/partial respects team_id parameter."""
        # First-Party
        from mcpgateway.db import get_db
        from mcpgateway.services.team_management_service import TeamManagementService

        # Get db session from app's dependency overrides or directly from get_db
        # (which uses the patched SessionLocal in tests)
        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create TWO teams (creator is automatically added as owner)
        team_service = TeamManagementService(db)
        team1 = await team_service.create_team(name=f"Resource Team 1 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")
        team2 = await team_service.create_team(name=f"Resource Team 2 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")

        # Create resources in different teams
        team1_resource = {
            "name": f"team1_resource_{uuid.uuid4().hex[:8]}",
            "uri": f"file:///team1-{uuid.uuid4().hex[:8]}",
            "description": "Team 1 resource",
            "visibility": "team",
            "team_id": team1.id,
            "content": "Test content for team1",
        }
        team2_resource = {
            "name": f"team2_resource_{uuid.uuid4().hex[:8]}",
            "uri": f"file:///team2-{uuid.uuid4().hex[:8]}",
            "description": "Team 2 resource",
            "visibility": "team",
            "team_id": team2.id,
            "content": "Test content for team2",
        }

        resp1 = await client.post("/admin/resources", data=team1_resource, headers=TEST_AUTH_HEADER)
        assert resp1.status_code == 200, f"Failed to create team1 resource: {resp1.text}"
        resp2 = await client.post("/admin/resources", data=team2_resource, headers=TEST_AUTH_HEADER)
        assert resp2.status_code == 200, f"Failed to create team2 resource: {resp2.text}"

        # Test with team1 filter - returns ONLY team1 resources (strict team scoping)
        response = await client.get(f"/admin/resources/partial?team_id={team1.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert team1_resource["name"] in html, f"team1_resource not found in HTML. First 500 chars: {html[:500]}"
        assert team2_resource["name"] not in html, "team2 resource should NOT appear when filtering by team1"

    async def test_prompts_partial_with_team_id(self, client, app_with_temp_db):
        """Test that /admin/prompts/partial respects team_id parameter."""
        # First-Party
        from mcpgateway.db import get_db
        from mcpgateway.services.team_management_service import TeamManagementService

        # Get db session from app's dependency overrides or directly from get_db
        # (which uses the patched SessionLocal in tests)
        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create TWO teams (creator is automatically added as owner)
        team_service = TeamManagementService(db)
        team1 = await team_service.create_team(name=f"Prompt Team 1 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")
        team2 = await team_service.create_team(name=f"Prompt Team 2 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")

        # Create prompts in different teams
        team1_prompt = {
            "name": f"team1_prompt_{uuid.uuid4().hex[:8]}",
            "description": "Team 1 prompt",
            "visibility": "team",
            "team_id": team1.id,
            "template": "Hello {{name}}!",
        }
        team2_prompt = {
            "name": f"team2_prompt_{uuid.uuid4().hex[:8]}",
            "description": "Team 2 prompt",
            "visibility": "team",
            "team_id": team2.id,
            "template": "Hello {{name}}!",
        }

        resp1 = await client.post("/admin/prompts", data=team1_prompt, headers=TEST_AUTH_HEADER)
        assert resp1.status_code == 200, f"Failed to create team1 prompt: {resp1.text}"
        resp2 = await client.post("/admin/prompts", data=team2_prompt, headers=TEST_AUTH_HEADER)
        assert resp2.status_code == 200, f"Failed to create team2 prompt: {resp2.text}"

        # Test with team1 filter - returns ONLY team1 prompts (strict team scoping)
        response = await client.get(f"/admin/prompts/partial?team_id={team1.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert team1_prompt["name"] in html
        assert team2_prompt["name"] not in html, "team2 prompt should NOT appear when filtering by team1"

    async def test_servers_partial_with_team_id(self, client, app_with_temp_db):
        """Test that /admin/servers/partial respects team_id parameter."""
        # First-Party
        from mcpgateway.db import get_db
        from mcpgateway.services.team_management_service import TeamManagementService

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create two teams
        team_service = TeamManagementService(db)
        team1 = await team_service.create_team(name=f"Server Team 1 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")
        team2 = await team_service.create_team(name=f"Server Team 2 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")

        # Create servers in different teams
        team1_server = {
            "name": f"team1_server_{uuid.uuid4().hex[:8]}",
            "description": "Team 1 server",
            "visibility": "team",
            "team_id": team1.id,
        }
        team2_server = {
            "name": f"team2_server_{uuid.uuid4().hex[:8]}",
            "description": "Team 2 server",
            "visibility": "team",
            "team_id": team2.id,
        }

        resp1 = await client.post("/admin/servers", data=team1_server, headers=TEST_AUTH_HEADER)
        assert resp1.status_code == 200, f"Failed to create team1 server: {resp1.text}"
        resp2 = await client.post("/admin/servers", data=team2_server, headers=TEST_AUTH_HEADER)
        assert resp2.status_code == 200, f"Failed to create team2 server: {resp2.text}"

        # Test with team1 filter - returns ONLY team1 servers (strict team scoping)
        response = await client.get(f"/admin/servers/partial?team_id={team1.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert team1_server["name"] in html
        assert team2_server["name"] not in html, "team2 server should NOT appear when filtering by team1"

    async def test_gateways_partial_with_team_id(self, client, app_with_temp_db):
        """Test that /admin/gateways/partial respects team_id parameter."""
        # First-Party
        from mcpgateway.db import get_db, Gateway as DbGateway
        from mcpgateway.services.team_management_service import TeamManagementService

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create two teams
        team_service = TeamManagementService(db)
        team1 = await team_service.create_team(name=f"Gateway Team 1 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")
        team2 = await team_service.create_team(name=f"Gateway Team 2 - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")

        # Create gateways directly in DB (gateway creation via form is complex)
        team1_gw_name = f"team1_gw_{uuid.uuid4().hex[:8]}"
        team1_gw_slug = f"team1-gw-{uuid.uuid4().hex[:8]}"
        team1_gw = DbGateway(
            id=uuid.uuid4().hex,
            name=team1_gw_name,
            slug=team1_gw_slug,
            url=f"http://team1.example.com/{uuid.uuid4().hex[:8]}",
            description="Team 1 gateway",
            transport="SSE",
            visibility="team",
            team_id=team1.id,
            owner_email="admin@example.com",
            enabled=True,
            capabilities={},
        )
        db.add(team1_gw)

        team2_gw_name = f"team2_gw_{uuid.uuid4().hex[:8]}"
        team2_gw_slug = f"team2-gw-{uuid.uuid4().hex[:8]}"
        team2_gw = DbGateway(
            id=uuid.uuid4().hex,
            name=team2_gw_name,
            slug=team2_gw_slug,
            url=f"http://team2.example.com/{uuid.uuid4().hex[:8]}",
            description="Team 2 gateway",
            transport="SSE",
            visibility="team",
            team_id=team2.id,
            owner_email="admin@example.com",
            enabled=True,
            capabilities={},
        )
        db.add(team2_gw)
        db.commit()

        # Test with team1 filter - returns ONLY team1 gateways (strict team scoping)
        response = await client.get(f"/admin/gateways/partial?team_id={team1.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        assert team1_gw_name in html
        assert team2_gw_name not in html, "team2 gateway should NOT appear when filtering by team1"

    async def test_visibility_private_not_visible_to_other_team_members(self, client, app_with_temp_db):
        """Test that visibility=private resources are NOT visible to other team members."""
        # First-Party
        from mcpgateway.db import get_db, Tool as DbTool
        from mcpgateway.services.team_management_service import TeamManagementService

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create a team
        team_service = TeamManagementService(db)
        team = await team_service.create_team(name=f"Visibility Test Team - {uuid.uuid4().hex[:8]}", description="Test", created_by="admin@example.com", visibility="private")

        # Create a PRIVATE tool owned by another user in the same team
        private_tool_name = f"private_tool_{uuid.uuid4().hex[:8]}"
        private_tool = DbTool(
            id=uuid.uuid4().hex,
            original_name=private_tool_name,
            url="http://example.com/private",
            description="Private tool owned by other user",
            visibility="private",  # KEY: This should NOT be visible to admin
            team_id=team.id,
            owner_email="other_user@example.com",  # Different owner
            enabled=True,
            input_schema={},
        )
        db.add(private_tool)
        db.commit()

        # Filter by team - admin should NOT see the private tool owned by other_user
        response = await client.get(f"/admin/tools/partial?team_id={team.id}", headers=TEST_AUTH_HEADER)
        assert response.status_code == 200
        html = response.text
        # The private tool should NOT be visible because it's owned by another user
        assert private_tool_name not in html, f"Private tool should NOT be visible to non-owner! Found in: {html[:500]}"


# -------------------------
# Test Graceful Error Handling
# -------------------------
class TestAdminListingGracefulErrorHandling:
    """Test that admin listing endpoints handle entity conversion errors gracefully.

    These tests verify that when one entity (tool/resource/prompt) fails to convert
    to its Pydantic model (e.g., due to corrupted data), the listing operation
    continues with remaining entities instead of failing completely.
    """

    async def test_admin_tools_listing_continues_on_conversion_error(self, client: AsyncClient, app_with_temp_db, mock_settings):
        """Test that /admin/tools returns valid tools even when one fails conversion.

        This test verifies the graceful error handling by mocking convert_tool_to_read
        to fail for one tool while succeeding for others.
        """
        # First-Party
        from mcpgateway.db import get_db, Tool as DbTool
        from mcpgateway.services.tool_service import ToolService
        from unittest.mock import patch

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create valid tools
        valid_tool_1 = DbTool(
            id=uuid.uuid4().hex,
            original_name=f"valid_tool_1_{uuid.uuid4().hex[:8]}",
            url="http://example.com/valid1",
            description="A valid tool",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
            input_schema={"type": "object"},
        )
        corrupted_tool = DbTool(
            id=uuid.uuid4().hex,
            original_name=f"corrupted_tool_{uuid.uuid4().hex[:8]}",
            url="http://example.com/corrupted",
            description="Tool that will fail conversion",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
            input_schema={"type": "object"},
        )
        valid_tool_2 = DbTool(
            id=uuid.uuid4().hex,
            original_name=f"valid_tool_2_{uuid.uuid4().hex[:8]}",
            url="http://example.com/valid2",
            description="Another valid tool",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
            input_schema={"type": "object"},
        )

        db.add(valid_tool_1)
        db.add(corrupted_tool)
        db.add(valid_tool_2)
        db.commit()

        corrupted_tool_id = corrupted_tool.id

        # Store original convert_tool_to_read method
        original_convert = ToolService.convert_tool_to_read

        def mock_convert(self, tool, include_metrics=False, include_auth=True):
            """Mock that raises ValueError for the corrupted tool."""
            if tool.id == corrupted_tool_id:
                raise ValueError("Simulated corrupted data: invalid auth_value")
            return original_convert(self, tool, include_metrics=include_metrics, include_auth=include_auth)

        # Patch the convert method to simulate corruption for one tool
        with patch.object(ToolService, "convert_tool_to_read", mock_convert):
            # Request tools listing
            response = await client.get("/admin/tools", headers=TEST_AUTH_HEADER)

        # Should succeed even with one corrupted tool
        assert response.status_code == 200
        resp_json = response.json()

        # Should have the valid tools in the response but NOT the corrupted one
        tools = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
        tool_names = [t.get("originalName", t.get("original_name", "")) for t in tools]

        assert valid_tool_1.original_name in tool_names
        assert valid_tool_2.original_name in tool_names
        # The corrupted tool should NOT be in the response (it was skipped)
        assert corrupted_tool.original_name not in tool_names

    async def test_admin_tools_partial_returns_200(self, client: AsyncClient, app_with_temp_db, mock_settings):
        """Test that /admin/tools/partial (HTMX endpoint) returns 200 and handles the request gracefully."""
        # Request partial tools listing (used by HTMX for pagination)
        response = await client.get("/admin/tools/partial", headers=TEST_AUTH_HEADER)

        # Should succeed
        assert response.status_code == 200
        # Should return HTML content
        assert "text/html" in response.headers.get("content-type", "")

    async def test_admin_resources_listing_continues_on_conversion_error(self, client: AsyncClient, app_with_temp_db, mock_settings):
        """Test that /admin/resources returns valid resources even when one fails conversion."""
        from mcpgateway.db import get_db, Resource as DbResource
        from mcpgateway.services.resource_service import ResourceService
        from unittest.mock import patch

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create resources
        valid_resource_1 = DbResource(
            id=uuid.uuid4().hex,
            name=f"valid_resource_1_{uuid.uuid4().hex[:8]}",
            uri=f"file:///valid1_{uuid.uuid4().hex[:8]}",
            description="A valid resource",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )
        corrupted_resource = DbResource(
            id=uuid.uuid4().hex,
            name=f"corrupted_resource_{uuid.uuid4().hex[:8]}",
            uri=f"file:///corrupted_{uuid.uuid4().hex[:8]}",
            description="Resource that will fail conversion",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )
        valid_resource_2 = DbResource(
            id=uuid.uuid4().hex,
            name=f"valid_resource_2_{uuid.uuid4().hex[:8]}",
            uri=f"file:///valid2_{uuid.uuid4().hex[:8]}",
            description="Another valid resource",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )

        db.add(valid_resource_1)
        db.add(corrupted_resource)
        db.add(valid_resource_2)
        db.commit()

        corrupted_resource_id = corrupted_resource.id
        original_convert = ResourceService.convert_resource_to_read

        def mock_convert(self, resource, include_metrics=False):
            if resource.id == corrupted_resource_id:
                raise ValueError("Simulated corrupted data")
            return original_convert(self, resource, include_metrics=include_metrics)

        with patch.object(ResourceService, "convert_resource_to_read", mock_convert):
            response = await client.get("/admin/resources", headers=TEST_AUTH_HEADER)

        assert response.status_code == 200
        resp_json = response.json()
        resources = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
        resource_names = [r.get("name", "") for r in resources]

        assert valid_resource_1.name in resource_names
        assert valid_resource_2.name in resource_names
        assert corrupted_resource.name not in resource_names

    async def test_admin_prompts_listing_continues_on_conversion_error(self, client: AsyncClient, app_with_temp_db, mock_settings):
        """Test that /admin/prompts returns valid prompts even when one fails conversion."""
        from mcpgateway.db import get_db, Prompt as DbPrompt
        from mcpgateway.services.prompt_service import PromptService
        from unittest.mock import patch

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create prompts with required fields
        uid1 = uuid.uuid4().hex[:8]
        valid_prompt_1 = DbPrompt(
            id=uuid.uuid4().hex,
            original_name=f"valid_prompt_1_{uid1}",
            custom_name=f"valid_prompt_1_{uid1}",
            custom_name_slug=f"valid-prompt-1-{uid1}",
            name=f"valid_prompt_1_{uid1}",
            description="A valid prompt",
            template="Hello {{ name }}",
            argument_schema={"type": "object"},
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )
        uid2 = uuid.uuid4().hex[:8]
        corrupted_prompt = DbPrompt(
            id=uuid.uuid4().hex,
            original_name=f"corrupted_prompt_{uid2}",
            custom_name=f"corrupted_prompt_{uid2}",
            custom_name_slug=f"corrupted-prompt-{uid2}",
            name=f"corrupted_prompt_{uid2}",
            description="Prompt that will fail conversion",
            template="Hello {{ name }}",
            argument_schema={"type": "object"},
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )
        uid3 = uuid.uuid4().hex[:8]
        valid_prompt_2 = DbPrompt(
            id=uuid.uuid4().hex,
            original_name=f"valid_prompt_2_{uid3}",
            custom_name=f"valid_prompt_2_{uid3}",
            custom_name_slug=f"valid-prompt-2-{uid3}",
            name=f"valid_prompt_2_{uid3}",
            description="Another valid prompt",
            template="Hello {{ name }}",
            argument_schema={"type": "object"},
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )

        db.add(valid_prompt_1)
        db.add(corrupted_prompt)
        db.add(valid_prompt_2)
        db.commit()

        corrupted_prompt_id = corrupted_prompt.id
        original_convert = PromptService.convert_prompt_to_read

        def mock_convert(self, prompt, include_metrics=False):
            if prompt.id == corrupted_prompt_id:
                raise ValueError("Simulated corrupted data")
            return original_convert(self, prompt, include_metrics=include_metrics)

        with patch.object(PromptService, "convert_prompt_to_read", mock_convert):
            response = await client.get("/admin/prompts", headers=TEST_AUTH_HEADER)

        assert response.status_code == 200
        resp_json = response.json()
        prompts = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
        prompt_names = [p.get("name", "") for p in prompts]

        assert valid_prompt_1.name in prompt_names
        assert valid_prompt_2.name in prompt_names
        assert corrupted_prompt.name not in prompt_names

    async def test_admin_servers_listing_continues_on_conversion_error(self, client: AsyncClient, app_with_temp_db, mock_settings):
        """Test that /admin/servers returns valid servers even when one fails conversion."""
        from mcpgateway.db import get_db, Server as DbServer
        from mcpgateway.services.server_service import ServerService
        from unittest.mock import patch

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create servers (Server model uses name, not slug)
        valid_server_1 = DbServer(
            id=uuid.uuid4().hex,
            name=f"valid_server_1_{uuid.uuid4().hex[:8]}",
            description="A valid server",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )
        corrupted_server = DbServer(
            id=uuid.uuid4().hex,
            name=f"corrupted_server_{uuid.uuid4().hex[:8]}",
            description="Server that will fail conversion",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )
        valid_server_2 = DbServer(
            id=uuid.uuid4().hex,
            name=f"valid_server_2_{uuid.uuid4().hex[:8]}",
            description="Another valid server",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )

        db.add(valid_server_1)
        db.add(corrupted_server)
        db.add(valid_server_2)
        db.commit()

        corrupted_server_id = corrupted_server.id
        original_convert = ServerService.convert_server_to_read

        def mock_convert(self, server, include_metrics=False):
            if server.id == corrupted_server_id:
                raise ValueError("Simulated corrupted data")
            return original_convert(self, server, include_metrics=include_metrics)

        with patch.object(ServerService, "convert_server_to_read", mock_convert):
            response = await client.get("/admin/servers", headers=TEST_AUTH_HEADER)

        assert response.status_code == 200
        resp_json = response.json()
        servers = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
        server_names = [s.get("name", "") for s in servers]

        assert valid_server_1.name in server_names
        assert valid_server_2.name in server_names
        assert corrupted_server.name not in server_names

    async def test_admin_gateways_listing_continues_on_conversion_error(self, client: AsyncClient, app_with_temp_db, mock_settings):
        """Test that /admin/gateways returns valid gateways even when one fails conversion."""
        from mcpgateway.db import get_db, Gateway as DbGateway
        from mcpgateway.services.gateway_service import GatewayService
        from unittest.mock import patch

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create gateways
        valid_gateway_1 = DbGateway(
            id=uuid.uuid4().hex,
            name=f"valid_gateway_1_{uuid.uuid4().hex[:8]}",
            slug=f"valid-gateway-1-{uuid.uuid4().hex[:8]}",
            url=f"http://valid1.example.com/{uuid.uuid4().hex[:8]}",
            description="A valid gateway",
            transport="SSE",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
            capabilities={},
        )
        corrupted_gateway = DbGateway(
            id=uuid.uuid4().hex,
            name=f"corrupted_gateway_{uuid.uuid4().hex[:8]}",
            slug=f"corrupted-gateway-{uuid.uuid4().hex[:8]}",
            url=f"http://corrupted.example.com/{uuid.uuid4().hex[:8]}",
            description="Gateway that will fail conversion",
            transport="SSE",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
            capabilities={},
        )
        valid_gateway_2 = DbGateway(
            id=uuid.uuid4().hex,
            name=f"valid_gateway_2_{uuid.uuid4().hex[:8]}",
            slug=f"valid-gateway-2-{uuid.uuid4().hex[:8]}",
            url=f"http://valid2.example.com/{uuid.uuid4().hex[:8]}",
            description="Another valid gateway",
            transport="SSE",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
            capabilities={},
        )

        db.add(valid_gateway_1)
        db.add(corrupted_gateway)
        db.add(valid_gateway_2)
        db.commit()

        corrupted_gateway_id = corrupted_gateway.id
        original_convert = GatewayService.convert_gateway_to_read

        def mock_convert(self, gateway):
            if gateway.id == corrupted_gateway_id:
                raise ValueError("Simulated corrupted data")
            return original_convert(self, gateway)

        with patch.object(GatewayService, "convert_gateway_to_read", mock_convert):
            response = await client.get("/admin/gateways", headers=TEST_AUTH_HEADER)

        assert response.status_code == 200
        resp_json = response.json()
        gateways = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
        gateway_names = [g.get("name", "") for g in gateways]

        assert valid_gateway_1.name in gateway_names
        assert valid_gateway_2.name in gateway_names
        assert corrupted_gateway.name not in gateway_names

    async def test_admin_a2a_listing_continues_on_conversion_error(self, client: AsyncClient, app_with_temp_db, mock_settings):
        """Test that /admin/a2a returns valid A2A agents even when one fails conversion."""
        from mcpgateway.db import get_db, A2AAgent as DbA2AAgent
        from mcpgateway.services.a2a_service import A2AAgentService
        from unittest.mock import patch

        test_db_dependency = app_with_temp_db.dependency_overrides.get(get_db) or get_db
        db = next(test_db_dependency())

        # Create A2A agents
        uid1 = uuid.uuid4().hex[:8]
        valid_agent_1 = DbA2AAgent(
            id=uuid.uuid4().hex,
            name=f"valid_agent_1_{uid1}",
            slug=f"valid-agent-1-{uid1}",
            endpoint_url=f"http://valid1.example.com/{uid1}",
            description="A valid A2A agent",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )
        uid2 = uuid.uuid4().hex[:8]
        corrupted_agent = DbA2AAgent(
            id=uuid.uuid4().hex,
            name=f"corrupted_agent_{uid2}",
            slug=f"corrupted-agent-{uid2}",
            endpoint_url=f"http://corrupted.example.com/{uid2}",
            description="A2A agent that will fail conversion",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )
        uid3 = uuid.uuid4().hex[:8]
        valid_agent_2 = DbA2AAgent(
            id=uuid.uuid4().hex,
            name=f"valid_agent_2_{uid3}",
            slug=f"valid-agent-2-{uid3}",
            endpoint_url=f"http://valid2.example.com/{uid3}",
            description="Another valid A2A agent",
            visibility="public",
            owner_email="admin@example.com",
            enabled=True,
        )

        db.add(valid_agent_1)
        db.add(corrupted_agent)
        db.add(valid_agent_2)
        db.commit()

        corrupted_agent_id = corrupted_agent.id
        original_convert = A2AAgentService.convert_agent_to_read

        def mock_convert(self, agent, include_metrics=False, db=None, team_map=None):
            if agent.id == corrupted_agent_id:
                raise ValueError("Simulated corrupted data")
            return original_convert(self, agent, include_metrics=include_metrics, db=db, team_map=team_map)

        with patch.object(A2AAgentService, "convert_agent_to_read", mock_convert):
            response = await client.get("/admin/a2a", headers=TEST_AUTH_HEADER)

        assert response.status_code == 200
        resp_json = response.json()
        agents = resp_json["data"] if isinstance(resp_json, dict) and "data" in resp_json else resp_json
        agent_names = [a.get("name", "") for a in agents]

        assert valid_agent_1.name in agent_names
        assert valid_agent_2.name in agent_names
        assert corrupted_agent.name not in agent_names


@pytest.mark.asyncio
async def test_observability_endpoints_with_database(client: AsyncClient):
    """Test all observability endpoints work with the database backend.

    This test verifies that the PostgreSQL GROUP BY fix works correctly
    by testing all affected observability endpoints.
    """
    endpoints = [
        "/admin/observability/tools/usage",
        "/admin/observability/tools/errors",
        "/admin/observability/tools/chains",
        "/admin/observability/prompts/usage",
        "/admin/observability/prompts/errors",
        "/admin/observability/resources/usage",
        "/admin/observability/resources/errors",
    ]

    for endpoint in endpoints:
        response = await client.get(endpoint, headers=TEST_AUTH_HEADER)
        assert response.status_code == 200, f"{endpoint} failed with status {response.status_code}: {response.text}"
        data = response.json()
        assert isinstance(data, dict), f"{endpoint} should return a dict"
        # Verify response structure based on endpoint
        if "tools" in endpoint:
            assert "tools" in data or "chains" in data, f"{endpoint} missing expected key"
        elif "prompts" in endpoint:
            assert "prompts" in data, f"{endpoint} missing 'prompts' key"
        elif "resources" in endpoint:
            assert "resources" in data, f"{endpoint} missing 'resources' key"


# Run tests with pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
