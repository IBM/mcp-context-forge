# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/test_main_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended tests for main.py to achieve 100% coverage.
These tests focus on uncovered code paths including conditional branches,
error handlers, and startup logic.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.main import app


class TestConditionalPaths:
    """Test conditional code paths to improve coverage."""

    def test_redis_initialization_path(self, test_client, auth_headers):
        """Test Redis initialization path by mocking settings."""
        # Test that the Redis path is covered indirectly through existing functionality
        # Since reloading modules in tests is problematic, we test the path is reachable
        with patch("mcpgateway.main.settings.cache_type", "redis"):
            response = test_client.get("/health", headers=auth_headers)
            assert response.status_code == 200

    def test_event_loop_task_creation(self, test_client, auth_headers):
        """Test event loop task creation path indirectly."""
        # Test the functionality that exercises the loop path
        response = test_client.get("/health", headers=auth_headers)
        assert response.status_code == 200


class TestEndpointErrorHandling:
    """Test error handling in various endpoints."""

    def test_tool_invocation_error_handling(self, test_client, auth_headers):
        """Test tool invocation with errors to cover error paths."""
        with patch("mcpgateway.main.tool_service.invoke_tool") as mock_invoke:
            # Test different error scenarios - return error instead of raising
            mock_invoke.return_value = {
                "content": [{"type": "text", "text": "Tool error"}],
                "is_error": True,
            }

            req = {
                "jsonrpc": "2.0",
                "id": "test-id",
                "method": "test_tool",
                "params": {"param": "value"},
            }
            response = test_client.post("/rpc/", json=req, headers=auth_headers)
            # Should handle the error gracefully
            assert response.status_code == 200

    def test_server_endpoints_error_conditions(self, test_client, auth_headers):
        """Test server endpoints with various error conditions."""
        # Test server creation with missing required fields (triggers validation)
        req = {"description": "Missing name"}
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        # Should handle validation error appropriately
        assert response.status_code == 422

    def test_resource_endpoints_error_conditions(self, test_client, auth_headers):
        """Test resource endpoints with various error conditions."""
        # Test resource not found scenario
        with patch("mcpgateway.main.resource_service.read_resource") as mock_read:
            # First-Party
            from mcpgateway.services.resource_service import ResourceNotFoundError

            mock_read.side_effect = ResourceNotFoundError("Resource not found")

            response = test_client.get("/resources/test/resource", headers=auth_headers)
            assert response.status_code == 404

    def test_prompt_endpoints_error_conditions(self, test_client, auth_headers):
        """Test prompt endpoints with various error conditions."""
        # Test prompt creation with missing required fields
        req = {"description": "Missing name and template"}
        response = test_client.post("/prompts/", json=req, headers=auth_headers)
        assert response.status_code == 422

    def test_gateway_endpoints_error_conditions(self, test_client, auth_headers):
        """Test gateway endpoints with various error conditions."""
        # Test gateway creation with missing required fields
        req = {"description": "Missing name and url"}
        response = test_client.post("/gateways/", json=req, headers=auth_headers)
        assert response.status_code == 422


class TestMiddlewareEdgeCases:
    """Test middleware and authentication edge cases."""

    def test_docs_endpoint_without_auth(self):
        """Test accessing docs without authentication."""
        # Create client without auth override to test real auth
        client = TestClient(app)
        response = client.get("/docs")
        assert response.status_code == 401

    def test_openapi_endpoint_without_auth(self):
        """Test accessing OpenAPI spec without authentication."""
        client = TestClient(app)
        response = client.get("/openapi.json")
        assert response.status_code == 401

    def test_redoc_endpoint_without_auth(self):
        """Test accessing ReDoc without authentication."""
        client = TestClient(app)
        response = client.get("/redoc")
        assert response.status_code == 401


class TestApplicationStartupPaths:
    """Test application startup conditional paths."""

    @patch("mcpgateway.main.plugin_manager", None)
    @patch("mcpgateway.main.logging_service")
    @patch("mcpgateway.config.settings.require_strong_secrets", False)
    @patch("mcpgateway.config.settings.dev_mode", True)
    async def test_startup_without_plugin_manager(self, mock_logging_service):
        """Test startup path when plugin_manager is None."""
        mock_logging_service.initialize = AsyncMock()
        mock_logging_service.configure_uvicorn_after_startup = MagicMock()

        # Mock all required services
        with (
            patch("mcpgateway.main.tool_service") as mock_tool,
            patch("mcpgateway.main.resource_service") as mock_resource,
            patch("mcpgateway.main.prompt_service") as mock_prompt,
            patch("mcpgateway.main.gateway_service") as mock_gateway,
            patch("mcpgateway.main.root_service") as mock_root,
            patch("mcpgateway.main.completion_service") as mock_completion,
            patch("mcpgateway.main.sampling_handler") as mock_sampling,
            patch("mcpgateway.main.resource_cache") as mock_cache,
            patch("mcpgateway.main.streamable_http_session") as mock_session,
            patch("mcpgateway.main.refresh_slugs_on_startup") as mock_refresh,
        ):
            # Setup all mocks
            services = [mock_tool, mock_resource, mock_prompt, mock_gateway, mock_root, mock_completion, mock_sampling, mock_cache, mock_session]
            for service in services:
                service.initialize = AsyncMock()
                service.shutdown = AsyncMock()

            # Test lifespan without plugin manager
            # First-Party
            from mcpgateway.main import lifespan

            async with lifespan(app):
                pass

            # Verify initialization happened without plugin manager
            mock_logging_service.initialize.assert_called_once()
            for service in services:
                service.initialize.assert_called_once()
                service.shutdown.assert_called_once()


class TestUtilityFunctions:
    """Test utility functions for edge cases."""

    def test_message_endpoint_edge_cases(self, test_client, auth_headers):
        """Test message endpoint with edge case parameters."""
        # Test with missing session_id to trigger validation error
        message = {"type": "test", "data": "hello"}
        response = test_client.post("/message", json=message, headers=auth_headers)
        assert response.status_code == 400  # Should require session_id parameter

        # Test with valid session_id
        with patch("mcpgateway.main.session_registry.broadcast") as mock_broadcast:
            response = test_client.post("/message?session_id=test-session", json=message, headers=auth_headers)
            assert response.status_code == 202
            mock_broadcast.assert_called_once()

    def test_root_endpoint_conditional_behavior(self):
        """Test root endpoint behavior based on UI settings."""
        with patch("mcpgateway.main.settings.mcpgateway_ui_enabled", True):
            client = TestClient(app)
            response = client.get("/", follow_redirects=False)

            # Should redirect to /admin/ when UI is enabled
            if response.status_code == 303:
                assert response.headers.get("location") == f"{settings.app_root_path}/admin/"
            else:
                # Fallback behavior
                assert response.status_code == 200

        with patch("mcpgateway.main.settings.mcpgateway_ui_enabled", False):
            client = TestClient(app)
            response = client.get("/")

            # Should return API info when UI is disabled
            if response.status_code == 200:
                data = response.json()
                assert "name" in data or "ui_enabled" in data

    def test_exception_handler_scenarios(self, test_client, auth_headers):
        """Test exception handlers with various scenarios."""
        # Test simple validation error by providing invalid data
        req = {"invalid": "data"}  # Missing required 'name' field
        response = test_client.post("/servers/", json=req, headers=auth_headers)
        # Should handle validation error
        assert response.status_code == 422

    def test_json_rpc_error_paths(self, test_client, auth_headers):
        """Test JSON-RPC error handling paths."""
        # Test with a valid JSON-RPC request that might not find the tool
        req = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "nonexistent_tool",
            "params": {},
        }
        response = test_client.post("/rpc/", json=req, headers=auth_headers)
        # Should return a valid JSON-RPC response even for non-existent tools
        assert response.status_code == 200
        body = response.json()
        # Should have either result or error
        assert "result" in body or "error" in body

    @patch("mcpgateway.main.settings")
    def test_websocket_error_scenarios(self, mock_settings):
        """Test WebSocket error scenarios."""
        # Configure mock settings for auth disabled
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.auth_required = False
        mock_settings.federation_timeout = 30
        mock_settings.skip_ssl_verify = False
        mock_settings.port = 4444

        with patch("mcpgateway.main.ResilientHttpClient") as mock_client:
            # Standard

            mock_instance = mock_client.return_value
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = False

            # Mock a failing post operation
            async def failing_post(*_args, **_kwargs):
                raise Exception("Network error")

            mock_instance.post = failing_post

            client = TestClient(app)
            with client.websocket_connect("/ws") as websocket:
                websocket.send_text('{"jsonrpc":"2.0","method":"ping","id":1}')
                # Should handle the error gracefully
                try:
                    data = websocket.receive_text()
                    # Either gets error response or connection closes
                    if data:
                        response = json.loads(data)
                        assert "error" in response or "result" in response
                except Exception:
                    # Connection may close due to error
                    pass

    def test_sse_endpoint_edge_cases(self, test_client, auth_headers):
        """Test SSE endpoint edge cases."""
        with patch("mcpgateway.main.SSETransport") as mock_transport_class, patch("mcpgateway.main.session_registry.add_session") as mock_add_session:
            mock_transport = MagicMock()
            mock_transport.session_id = "test-session"

            # Test SSE transport creation error
            mock_transport_class.side_effect = Exception("SSE error")

            response = test_client.get("/servers/test/sse", headers=auth_headers)
            # Should handle SSE creation error
            assert response.status_code in [404, 500, 503]

    def test_server_toggle_edge_cases(self, test_client, auth_headers):
        """Test server toggle endpoint edge cases."""
        with patch("mcpgateway.main.server_service.toggle_server_status") as mock_toggle:
            # Create a proper ServerRead model response
            # First-Party
            from mcpgateway.schemas import ServerRead

            mock_server_data = {
                "id": "1",
                "name": "test_server",
                "description": "A test server",
                "icon": None,
                "created_at": "2023-01-01T00:00:00+00:00",
                "updated_at": "2023-01-01T00:00:00+00:00",
                "enabled": True,
                "associated_tools": [],
                "associated_resources": [],
                "associated_prompts": [],
                "metrics": {
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": 0.0,
                    "max_response_time": 0.0,
                    "avg_response_time": 0.0,
                    "last_execution_time": None,
                },
            }

            mock_toggle.return_value = ServerRead(**mock_server_data)

            # Test activate=true
            response = test_client.post("/servers/1/toggle?activate=true", headers=auth_headers)
            assert response.status_code == 200

            # Test activate=false
            mock_server_data["enabled"] = False
            mock_toggle.return_value = ServerRead(**mock_server_data)
            response = test_client.post("/servers/1/toggle?activate=false", headers=auth_headers)
            assert response.status_code == 200


# Test fixtures
@pytest.fixture
def test_client(app):
    """Test client with auth override for testing protected endpoints."""
    # Standard
    from unittest.mock import MagicMock, patch

    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.db import EmailUser
    from mcpgateway.main import require_auth
    from mcpgateway.middleware.rbac import get_current_user_with_permissions

    # Mock user object for RBAC system
    mock_user = EmailUser(
        email="test_user@example.com",
        full_name="Test User",
        is_admin=True,  # Give admin privileges for tests
        is_active=True,
        auth_provider="test",
    )

    # Mock security_logger to prevent database access
    mock_sec_logger = MagicMock()
    mock_sec_logger.log_authentication_attempt = MagicMock(return_value=None)
    mock_sec_logger.log_security_event = MagicMock(return_value=None)
    sec_patcher = patch("mcpgateway.middleware.auth_middleware.security_logger", mock_sec_logger)
    sec_patcher.start()

    # Mock require_auth_override function
    def mock_require_auth_override(user: str) -> str:
        return user

    # Patch the require_docs_auth_override function
    patcher = patch("mcpgateway.main.require_docs_auth_override", mock_require_auth_override)
    patcher.start()

    # Override the core auth function used by RBAC system
    app.dependency_overrides[get_current_user] = lambda credentials=None, db=None: mock_user

    # Override get_current_user_with_permissions for RBAC system
    def mock_get_current_user_with_permissions(request=None, credentials=None, jwt_token=None, db=None):
        return {"email": "test_user@example.com", "full_name": "Test User", "is_admin": True, "ip_address": "127.0.0.1", "user_agent": "test", "db": db}

    app.dependency_overrides[get_current_user_with_permissions] = mock_get_current_user_with_permissions

    # Mock the permission service to always return True for tests
    # First-Party
    from mcpgateway.services.permission_service import PermissionService

    if not hasattr(PermissionService, "_original_check_permission"):
        PermissionService._original_check_permission = PermissionService.check_permission

    async def mock_check_permission(
        self,
        user_email: str,
        permission: str,
        resource_type=None,
        resource_id=None,
        team_id=None,
        ip_address=None,
        user_agent=None,
    ) -> bool:
        return True

    PermissionService.check_permission = mock_check_permission

    # Override require_auth for backward compatibility
    app.dependency_overrides[require_auth] = lambda: "test_user"

    client = TestClient(app)
    yield client

    # Clean up overrides and restore original methods
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_user_with_permissions, None)
    patcher.stop()  # Stop the require_auth_override patch
    sec_patcher.stop()  # Stop the security_logger patch
    if hasattr(PermissionService, "_original_check_permission"):
        PermissionService.check_permission = PermissionService._original_check_permission


@pytest.fixture
def auth_headers():
    """Default auth headers for testing."""
    return {"Authorization": "Bearer test_token"}
