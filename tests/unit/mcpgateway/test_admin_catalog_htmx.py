# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_catalog_htmx.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for HTMX functionality in catalog server registration endpoint.
Uses TestClient with proper auth mocking via module-level fixture.
"""

# Standard
import os

# Set UI base path to /ui before importing mcpgateway modules
os.environ["MCPGATEWAY_UI_BASE_PATH"] = "/ui"

from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.schemas import CatalogServerRegisterResponse


@pytest.fixture(scope="module")
def client():
    """Create a TestClient with mocked authentication (module-scoped to avoid lifecycle issues)."""
    # Import here to avoid module-level import issues
    from mcpgateway.main import app
    from mcpgateway.auth import get_current_user
    from mcpgateway.config import settings
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.services.permission_service import PermissionService
    from mcpgateway.db import EmailUser

    # Disable auth_required so AdminAuthMiddleware skips its check
    original_auth_required = settings.auth_required
    settings.auth_required = False

    # Mock user object
    mock_user = EmailUser(
        email="test_user@example.com",
        full_name="Test User",
        is_admin=True,
        is_active=True,
        auth_provider="test",
    )

    # Mock security_logger
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    # Override auth dependencies
    app.dependency_overrides[get_current_user] = lambda credentials=None, db=None: mock_user

    def mock_get_current_user_with_permissions(request=None, credentials=None, jwt_token=None):
        return {"email": "test_user@example.com", "full_name": "Test User", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "test"}

    app.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions

    # Mock permission service
    if not hasattr(PermissionService, "_original_check_permission"):
        PermissionService._original_check_permission = PermissionService.check_permission

    async def mock_check_permission(self, user_email: str, permission: str, resource_type=None, resource_id=None, team_id=None, ip_address=None, user_agent=None) -> bool:
        return True

    PermissionService.check_permission = mock_check_permission

    # Avoid StreamableHTTPSessionManager reuse errors during repeated lifespan runs
    streamable_init = patch("mcpgateway.main.streamable_http_session.initialize", new_callable=AsyncMock)
    streamable_shutdown = patch("mcpgateway.main.streamable_http_session.shutdown", new_callable=AsyncMock)
    streamable_init.start()
    streamable_shutdown.start()

    # Avoid SharedHttpClient shutdown errors when other tests monkeypatch the singleton
    from mcpgateway.services.http_client_service import SharedHttpClient
    shared_client = MagicMock()
    shared_client.close = AsyncMock()
    original_shared_instance = SharedHttpClient._instance
    SharedHttpClient._instance = shared_client
    shared_get_instance = patch("mcpgateway.services.http_client_service.SharedHttpClient.get_instance", new=AsyncMock(return_value=shared_client))
    shared_shutdown = patch("mcpgateway.services.http_client_service.SharedHttpClient.shutdown", new=AsyncMock())
    shared_get_instance.start()
    shared_shutdown.start()

    with TestClient(app) as test_client:
        yield test_client

    # Cleanup
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_user_with_permissions, None)
    sec_patcher.stop()
    streamable_init.stop()
    streamable_shutdown.stop()
    shared_get_instance.stop()
    shared_shutdown.stop()
    SharedHttpClient._instance = original_shared_instance
    if hasattr(PermissionService, "_original_check_permission"):
        PermissionService.check_permission = PermissionService._original_check_permission
    settings.auth_required = original_auth_required


def test_register_catalog_server_htmx_success(client):
    """Test HTMX request returns HTML for successful registration."""
    mock_result = CatalogServerRegisterResponse(
        success=True,
        server_id="test-id",
        message="Successfully registered Test Server with 5 tools discovered",
        error=None,
        oauth_required=False,
    )

    with patch("mcpgateway.admin.catalog_service.register_catalog_server", new_callable=AsyncMock, return_value=mock_result), \
         patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = client.post(
            "/ui/mcp-registry/test-server/register",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Registered Successfully" in response.text
    assert "bg-green-600" in response.text
    assert "disabled" in response.text
    assert "HX-Trigger-After-Swap" in response.headers
    assert "catalogRegistrationSuccess" in response.headers["HX-Trigger-After-Swap"]


def test_register_catalog_server_htmx_oauth(client):
    """Test HTMX request returns HTML for OAuth server requiring configuration."""
    mock_result = CatalogServerRegisterResponse(
        success=True,
        server_id="oauth-id",
        message="Successfully registered OAuth Server - OAuth configuration required before activation",
        error=None,
        oauth_required=True,
    )

    with patch("mcpgateway.admin.catalog_service.register_catalog_server", new_callable=AsyncMock, return_value=mock_result), \
         patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = client.post(
            "/ui/mcp-registry/oauth-server/register",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "OAuth Config Required" in response.text
    assert "bg-yellow-600" in response.text
    assert "disabled" in response.text
    # OAuth registrations trigger refresh - template shows yellow state from requires_oauth_config
    assert "HX-Trigger-After-Swap" in response.headers
    assert "catalogRegistrationSuccess" in response.headers["HX-Trigger-After-Swap"]


def test_register_catalog_server_htmx_error(client):
    """Test HTMX request returns HTML for failed registration with retry button."""
    mock_result = CatalogServerRegisterResponse(
        success=False,
        server_id="",
        message="Registration failed",
        error="Server is offline or unreachable",
        oauth_required=False,
    )

    with patch("mcpgateway.admin.catalog_service.register_catalog_server", new_callable=AsyncMock, return_value=mock_result), \
         patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = client.post(
            "/ui/mcp-registry/failed-server/register",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Failed - Click to Retry" in response.text
    assert "bg-red-600" in response.text
    assert "hx-post" in response.text
    assert "Server is offline or unreachable" in response.text
    assert "HX-Trigger-After-Swap" not in response.headers


def test_register_catalog_server_json_response(client):
    """Test non-HTMX request returns JSON response."""
    mock_result = CatalogServerRegisterResponse(
        success=True,
        server_id="test-id",
        message="Successfully registered Test Server",
        error=None,
        oauth_required=False,
    )

    with patch("mcpgateway.admin.catalog_service.register_catalog_server", new_callable=AsyncMock, return_value=mock_result), \
         patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True

        response = client.post("/ui/mcp-registry/test-server/register")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["server_id"] == "test-id"
    assert "Successfully registered" in data["message"]


def test_register_catalog_server_htmx_with_api_key(client):
    """Test HTMX request with API key registration."""
    mock_result = CatalogServerRegisterResponse(
        success=True,
        server_id="api-id",
        message="Successfully registered API Server with 3 tools discovered",
        error=None,
        oauth_required=False,
    )

    with patch("mcpgateway.admin.catalog_service.register_catalog_server", new_callable=AsyncMock, return_value=mock_result), \
         patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = client.post(
            "/ui/mcp-registry/api-server/register",
            headers={"HX-Request": "true"},
            json={"server_id": "api-server", "name": "API Server", "api_key": "secret-key"},
        )

    assert response.status_code == 200
    assert "Registered Successfully" in response.text
    assert "bg-green-600" in response.text
    assert "HX-Trigger-After-Swap" in response.headers


def test_register_catalog_server_htmx_error_escaping(client):
    """Test that error messages with quotes are properly escaped in HTML."""
    mock_result = CatalogServerRegisterResponse(
        success=False,
        server_id="",
        message="Registration failed",
        error='Server returned "Invalid credentials" error',
        oauth_required=False,
    )

    with patch("mcpgateway.admin.catalog_service.register_catalog_server", new_callable=AsyncMock, return_value=mock_result), \
         patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = ""

        response = client.post(
            "/ui/mcp-registry/failed-server/register",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "Failed - Click to Retry" in response.text
    assert "&quot;" in response.text
    assert "Server returned &quot;Invalid credentials&quot; error" in response.text


def test_register_catalog_server_htmx_retry_button_attributes(client):
    """Test that retry button has correct HTMX attributes."""
    mock_result = CatalogServerRegisterResponse(
        success=False,
        server_id="",
        message="Registration failed",
        error="Connection timeout",
        oauth_required=False,
    )

    with patch("mcpgateway.admin.catalog_service.register_catalog_server", new_callable=AsyncMock, return_value=mock_result), \
         patch("mcpgateway.admin.settings") as mock_settings:
        mock_settings.mcpgateway_catalog_enabled = True
        mock_settings.app_root_path = "/api"
        mock_settings.mcpgateway_ui_base_path = "/ui"

        response = client.post(
            "/ui/mcp-registry/timeout-server/register",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    html_content = response.text
    assert 'hx-post="/api/ui/mcp-registry/timeout-server/register"' in html_content
    assert 'hx-target="#timeout-server-button-container"' in html_content
    assert 'hx-swap="innerHTML"' in html_content
    assert 'hx-disabled-elt="this"' in html_content
    assert "hx-on::before-request" in html_content
    assert "hx-on::response-error" in html_content
    assert "HX-Trigger-After-Swap" not in response.headers
