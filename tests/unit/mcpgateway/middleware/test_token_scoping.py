# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_token_scoping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for token scoping middleware security fixes.

This module tests the token scoping middleware, particularly the security fixes for:
- Issue 4: Admin endpoint whitelist removal
- Issue 5: Canonical permission mapping alignment
"""

# Standard
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import Request, status
import pytest

# First-Party
from mcpgateway.db import Permissions
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware


class TestTokenScopingMiddleware:
    """Test token scoping middleware functionality."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        return TokenScopingMiddleware()

    @pytest.fixture
    def mock_request(self):
        """Create mock request object."""
        request = MagicMock(spec=Request)
        request.url.path = "/test"
        request.method = "GET"
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        # Set up state as a simple object that can hold attributes
        # This is needed for the idempotency guard in __call__
        request.state = MagicMock()
        request.state._token_scoping_done = False
        return request

    @pytest.mark.asyncio
    async def test_admin_endpoint_not_in_general_whitelist(self, middleware, mock_request):
        """Test that /admin is no longer whitelisted for server-scoped tokens (Issue 4 fix)."""
        mock_request.url.path = "/admin/users"

        # Test server restriction check - /admin should NOT be in general endpoints
        result = middleware._check_server_restriction("/admin/users", "server-123")
        assert result == False, "Admin endpoints should not bypass server scoping restrictions"

    @pytest.mark.asyncio
    async def test_health_endpoints_still_whitelisted(self, middleware, mock_request):
        """Test that health/metrics endpoints remain whitelisted."""
        whitelist_paths = ["/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/"]

        for path in whitelist_paths:
            result = middleware._check_server_restriction(path, "server-123")
            assert result == True, f"Path {path} should remain whitelisted"

    @pytest.mark.asyncio
    async def test_canonical_permissions_used_in_map(self, middleware):
        """Test that permission map uses canonical Permissions constants (Issue 5 fix)."""
        # Test tools permissions use canonical constants
        result = middleware._check_permission_restrictions("/tools", "GET", [Permissions.TOOLS_READ])
        assert result == True, "Should accept canonical TOOLS_READ permission"

        result = middleware._check_permission_restrictions("/tools", "POST", [Permissions.TOOLS_CREATE])
        assert result == True, "Should accept canonical TOOLS_CREATE permission"

        # Test that old non-canonical permissions would not work
        result = middleware._check_permission_restrictions("/tools", "POST", ["tools.write"])
        assert result == False, "Should reject non-canonical 'tools.write' permission"

    @pytest.mark.asyncio
    async def test_admin_permissions_use_canonical_constants(self, middleware):
        """Test that admin endpoints use canonical admin permissions."""
        result = middleware._check_permission_restrictions("/admin", "GET", [Permissions.ADMIN_USER_MANAGEMENT])
        assert result == True, "Should accept canonical ADMIN_USER_MANAGEMENT permission"

        result = middleware._check_permission_restrictions("/admin/users", "POST", [Permissions.ADMIN_USER_MANAGEMENT])
        assert result == True, "Should accept canonical ADMIN_USER_MANAGEMENT for admin operations"

        # Test that old non-canonical admin permissions would not work
        result = middleware._check_permission_restrictions("/admin", "GET", ["admin.read"])
        assert result == False, "Should reject non-canonical 'admin.read' permission"

    @pytest.mark.asyncio
    async def test_server_scoped_token_blocked_from_admin(self, middleware, mock_request):
        """Test that server-scoped tokens are blocked from admin endpoints (security fix)."""
        mock_request.url.path = "/admin/users"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        # Mock token extraction to return server-scoped token
        with patch.object(middleware, "_extract_token_scopes") as mock_extract:
            mock_extract.return_value = {"scopes": {"server_id": "specific-server"}}

            # Mock call_next (the next middleware or request handler)
            call_next = AsyncMock()

            # Perform the request, which should return a JSONResponse instead of raising HTTPException
            response = await middleware(mock_request, call_next)

            # Ensure response is a JSONResponse and parse its content
            content = json.loads(response.body)  # Parse response content to dictionary

            # Check that the response is a JSONResponse with status 403 and the correct detail
            assert response.status_code == status.HTTP_403_FORBIDDEN
            assert "not authorized for this server" in content.get("detail")
            call_next.assert_not_called()  # Ensure the next handler is not called

    @pytest.mark.asyncio
    async def test_permission_restricted_token_blocked_from_admin(self, middleware, mock_request):
        """Test that permission-restricted tokens are blocked from admin endpoints."""
        mock_request.url.path = "/admin/users"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        # Mock token extraction to return permission-scoped token without admin permissions
        with patch.object(middleware, "_extract_token_scopes") as mock_extract:
            mock_extract.return_value = {"scopes": {"permissions": [Permissions.TOOLS_READ]}}

            # Mock call_next (the next middleware or request handler)
            call_next = AsyncMock()

            # Perform the request, which should return a JSONResponse instead of raising HTTPException
            response = await middleware(mock_request, call_next)

            # Ensure response is a JSONResponse and parse its content
            content = json.loads(response.body)  # Parse response content to dictionary

            # Check that the response is a JSONResponse with status 403 and the correct detail
            assert response.status_code == status.HTTP_403_FORBIDDEN
            assert "Insufficient permissions for this operation" in content.get("detail")
            call_next.assert_not_called()  # Ensure the next handler is not called

    @pytest.mark.asyncio
    async def test_admin_token_allowed_to_admin_endpoints(self, middleware, mock_request):
        """Test that tokens with admin permissions can access admin endpoints."""
        mock_request.url.path = "/admin/users"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        # Mock token extraction to return admin-scoped token
        with patch.object(middleware, "_extract_token_scopes") as mock_extract:
            mock_extract.return_value = {"permissions": [Permissions.ADMIN_USER_MANAGEMENT]}

            call_next = AsyncMock()
            call_next.return_value = "success"

            # Should allow access
            result = await middleware(mock_request, call_next)
            assert result == "success"
            call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_wildcard_permissions_allow_all_access(self, middleware, mock_request):
        """Test that wildcard permissions allow access to any endpoint."""
        mock_request.url.path = "/admin/users"
        mock_request.method = "POST"
        mock_request.headers = {"Authorization": "Bearer token"}

        # Mock token extraction to return wildcard permissions
        with patch.object(middleware, "_extract_token_scopes") as mock_extract:
            mock_extract.return_value = {"permissions": ["*"]}

            call_next = AsyncMock()
            call_next.return_value = "success"

            # Should allow access
            result = await middleware(mock_request, call_next)
            assert result == "success"
            call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_token_scopes_bypasses_middleware(self, middleware, mock_request):
        """Test that requests without token scopes bypass the middleware."""
        mock_request.url.path = "/admin/users"
        mock_request.headers = {}  # No Authorization header

        call_next = AsyncMock()
        call_next.return_value = "success"

        # Should bypass middleware entirely
        result = await middleware(mock_request, call_next)
        assert result == "success"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_whitelisted_paths_bypass_middleware(self, middleware):
        """Test that whitelisted paths bypass all scoping checks."""
        whitelisted_paths = ["/health", "/metrics", "/docs", "/auth/email/login"]

        for path in whitelisted_paths:
            mock_request = MagicMock(spec=Request)
            mock_request.url.path = path

            call_next = AsyncMock()
            call_next.return_value = "success"

            result = await middleware(mock_request, call_next)
            assert result == "success", f"Whitelisted path {path} should bypass middleware"
            call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_regex_pattern_precision_tools(self, middleware):
        """Test that regex patterns match path segments precisely."""
        # Test exact /tools path matches for GET (should require TOOLS_READ)
        assert middleware._check_permission_restrictions("/tools", "GET", [Permissions.TOOLS_READ]) == True
        assert middleware._check_permission_restrictions("/tools/", "GET", [Permissions.TOOLS_READ]) == True
        assert middleware._check_permission_restrictions("/tools/abc", "GET", [Permissions.TOOLS_READ]) == True

        # Test that GET /tools requires TOOLS_READ permission specifically
        assert middleware._check_permission_restrictions("/tools", "GET", [Permissions.TOOLS_CREATE]) == False
        # Note: Empty permissions list returns True due to "no restrictions" logic
        assert middleware._check_permission_restrictions("/tools", "GET", []) == True

        # Test POST /tools requires TOOLS_CREATE permission specifically
        assert middleware._check_permission_restrictions("/tools", "POST", [Permissions.TOOLS_CREATE]) == True
        assert middleware._check_permission_restrictions("/tools", "POST", [Permissions.TOOLS_READ]) == False

        # Test specific tool ID patterns for PUT/DELETE
        assert middleware._check_permission_restrictions("/tools/tool-123", "PUT", [Permissions.TOOLS_UPDATE]) == True
        assert middleware._check_permission_restrictions("/tools/tool-123", "DELETE", [Permissions.TOOLS_DELETE]) == True

        # Test wrong permissions for tool operations
        assert middleware._check_permission_restrictions("/tools/tool-123", "PUT", [Permissions.TOOLS_READ]) == False
        assert middleware._check_permission_restrictions("/tools/tool-123", "DELETE", [Permissions.TOOLS_UPDATE]) == False

    @pytest.mark.asyncio
    async def test_regex_pattern_precision_admin(self, middleware):
        """Test that admin regex patterns require correct permissions."""
        # Test exact /admin path requires ADMIN_USER_MANAGEMENT
        assert middleware._check_permission_restrictions("/admin", "GET", [Permissions.ADMIN_USER_MANAGEMENT]) == True
        assert middleware._check_permission_restrictions("/admin/", "GET", [Permissions.ADMIN_USER_MANAGEMENT]) == True

        # Test admin operations require admin permissions
        assert middleware._check_permission_restrictions("/admin/users", "POST", [Permissions.ADMIN_USER_MANAGEMENT]) == True
        assert middleware._check_permission_restrictions("/admin/teams", "PUT", [Permissions.ADMIN_USER_MANAGEMENT]) == True

        # Test that non-admin permissions are rejected for admin paths
        assert middleware._check_permission_restrictions("/admin", "GET", [Permissions.TOOLS_READ]) == False
        assert middleware._check_permission_restrictions("/admin/users", "POST", [Permissions.RESOURCES_CREATE]) == False

        # Test that empty permissions list returns True (no restrictions policy)
        assert middleware._check_permission_restrictions("/admin", "GET", []) == True

    @pytest.mark.asyncio
    async def test_regex_pattern_precision_servers(self, middleware):
        """Test that server path patterns require correct permissions."""
        # Test exact /servers path requires SERVERS_READ
        assert middleware._check_permission_restrictions("/servers", "GET", [Permissions.SERVERS_READ]) == True
        assert middleware._check_permission_restrictions("/servers/", "GET", [Permissions.SERVERS_READ]) == True

        # Test specific server operations require correct permissions
        assert middleware._check_permission_restrictions("/servers/server-123", "PUT", [Permissions.SERVERS_UPDATE]) == True
        assert middleware._check_permission_restrictions("/servers/server-123", "DELETE", [Permissions.SERVERS_DELETE]) == True

        # Test nested server paths for tools/resources
        assert middleware._check_permission_restrictions("/servers/srv-1/tools", "GET", [Permissions.TOOLS_READ]) == True
        assert middleware._check_permission_restrictions("/servers/srv-1/tools/tool-1/call", "POST", [Permissions.TOOLS_EXECUTE]) == True
        assert middleware._check_permission_restrictions("/servers/srv-1/resources", "GET", [Permissions.RESOURCES_READ]) == True

        # Test wrong permissions for server operations
        assert middleware._check_permission_restrictions("/servers", "GET", [Permissions.TOOLS_READ]) == False
        assert middleware._check_permission_restrictions("/servers/server-123", "PUT", [Permissions.SERVERS_READ]) == False

    @pytest.mark.asyncio
    async def test_regex_pattern_segment_boundaries(self, middleware):
        """Test that regex patterns respect path segment boundaries."""
        # Test that similar-but-different paths use default allow (proving pattern precision)
        # These paths don't match any specific pattern, so they get default allow
        edge_case_paths = ["/toolshed", "/adminpanel", "/resourcesful", "/promptsystem", "/serversocket"]

        for path in edge_case_paths:
            # These should return True due to default allow (proving they don't falsely match patterns)
            result = middleware._check_permission_restrictions(path, "GET", [])
            assert result == True, f"Unmatched path {path} should get default allow"

        # Test that exact patterns still work correctly
        exact_matches = [
            ("/tools", "GET", [Permissions.TOOLS_READ], True),
            ("/admin", "GET", [Permissions.ADMIN_USER_MANAGEMENT], True),
            ("/resources", "GET", [Permissions.RESOURCES_READ], True),
            ("/prompts", "POST", [Permissions.PROMPTS_CREATE], True),
            ("/servers", "POST", [Permissions.SERVERS_CREATE], True),
        ]

        for path, method, permissions, expected in exact_matches:
            result = middleware._check_permission_restrictions(path, method, permissions)
            assert result == expected, f"Exact match {path} {method} should return {expected}"

    @pytest.mark.asyncio
    async def test_server_id_extraction_precision(self, middleware):
        """Test that server ID extraction is precise and doesn't overmatch."""
        # Test valid server ID extraction
        patterns_to_test = [
            ("/servers/srv-123", "srv-123", True),
            ("/servers/srv-123/", "srv-123", True),
            ("/servers/srv-123/tools", "srv-123", True),
            ("/sse/websocket-server", "websocket-server", True),
            ("/sse/websocket-server?param=value", "websocket-server", True),
            ("/ws/ws-server-1", "ws-server-1", True),
            ("/ws/ws-server-1?token=abc", "ws-server-1", True),
        ]

        for path, expected_server_id, should_match in patterns_to_test:
            result = middleware._check_server_restriction(path, expected_server_id)
            assert result == should_match, f"Path {path} with server_id {expected_server_id} should return {should_match}"

        # Test cases that should NOT match (different server IDs)
        negative_cases = [
            ("/servers/srv-123", "srv-456", False),
            ("/sse/websocket-server", "different-server", False),
            ("/ws/ws-server-1", "ws-server-2", False),
        ]

        for path, wrong_server_id, should_match in negative_cases:
            result = middleware._check_server_restriction(path, wrong_server_id)
            assert result == should_match, f"Path {path} with wrong server_id {wrong_server_id} should return {should_match}"
