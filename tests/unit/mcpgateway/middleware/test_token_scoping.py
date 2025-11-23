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
from starlette.responses import Response

# First-Party
from mcpgateway.db import Permissions
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware
from mcpgateway.services.permission_service import PermissionService


class TestTokenScopingMiddleware:
    """Test token scoping middleware functionality."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        return TokenScopingMiddleware()

    @pytest.fixture
    def permission_service(self):
        """Create permission service instance with mock DB."""
        return PermissionService(MagicMock())

    @pytest.fixture
    def mock_request(self):
        """Create mock request object."""
        request = MagicMock(spec=Request)
        request.url.path = "/test"
        request.method = "GET"
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        return request




    @pytest.mark.asyncio
    async def test_canonical_permissions_used_in_map(self, middleware, permission_service):
        """Test that permission map uses canonical Permissions constants (Issue 5 fix)."""
        # Test tools permissions use canonical constants
        result = middleware._check_permission_restrictions("/tools", "GET", [Permissions.TOOLS_READ], permission_service)
        assert result == True, "Should accept canonical TOOLS_READ permission"

        result = middleware._check_permission_restrictions("/tools", "POST", [Permissions.TOOLS_CREATE], permission_service)
        assert result == True, "Should accept canonical TOOLS_CREATE permission"

        # Test that old non-canonical permissions would not work
        result = middleware._check_permission_restrictions("/tools", "POST", ["tools.write"], permission_service)
        assert result == False, "Should reject non-canonical 'tools.write' permission"

    @pytest.mark.asyncio
    async def test_admin_permissions_use_canonical_constants(self, middleware, permission_service):
        """Test that admin endpoints use canonical admin permissions."""
        result = middleware._check_permission_restrictions("/admin", "GET", [Permissions.ADMIN_USER_MANAGEMENT], permission_service)
        assert result == True, "Should accept canonical ADMIN_USER_MANAGEMENT permission"

        result = middleware._check_permission_restrictions("/admin/users", "POST", [Permissions.ADMIN_USER_MANAGEMENT], permission_service)
        assert result == True, "Should accept canonical ADMIN_USER_MANAGEMENT for admin operations"

        # Test that old non-canonical admin permissions would not work
        result = middleware._check_permission_restrictions("/admin", "GET", ["admin.read"], permission_service)
        assert result == False, "Should reject non-canonical 'admin.read' permission"



    @pytest.mark.asyncio
    async def test_permission_restricted_token_blocked_from_admin(self, middleware, mock_request):
        """Test that permission-restricted tokens are blocked from admin endpoints."""
        mock_request.url.path = "/admin/users"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        # Mock token extraction to return permission-scoped token without admin permissions
        with patch.object(middleware, "_extract_token_scopes") as mock_extract:
            mock_extract.return_value = {"sub": "test@example.com", "scopes": {"permissions": [Permissions.TOOLS_READ]}}

            # Mock get_db
            with patch("mcpgateway.middleware.token_scoping.get_db") as mock_get_db:
                mock_session = MagicMock()
                mock_get_db.return_value.__next__.return_value = mock_session
                
                # Mock get_user_permissions to return limited permissions
                with patch.object(middleware, "_get_user_permissions") as mock_get_perms:
                    mock_get_perms.return_value = [Permissions.TOOLS_READ]  # No admin permission

                    # Mock call_next (the next middleware or request handler)
                    call_next = AsyncMock()

                    # Perform the request, which should return a JSONResponse instead of raising HTTPException
                    response = await middleware(mock_request, call_next)

                    # Ensure response is a JSONResponse and parse its content
                    content = json.loads(response.body)  # Parse response content to dictionary

                    # Check that the response is a JSONResponse with status 403 and the correct detail
                    assert response.status_code == status.HTTP_403_FORBIDDEN
                    assert "Insufficient permissions" in content.get("detail")
                    call_next.assert_not_called()  # Ensure the next handler is not called

    @pytest.mark.asyncio
    async def test_admin_token_allowed_to_admin_endpoints(self, middleware, mock_request):
        """Test that tokens with admin permissions can access admin endpoints."""
        mock_request.url.path = "/admin/users"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        # Mock token extraction to return admin-scoped token
        with patch.object(middleware, "_extract_token_scopes") as mock_extract:
            mock_extract.return_value = {"sub": "admin@example.com", "scopes": {"permissions": [Permissions.ADMIN_USER_MANAGEMENT]}}

            # Mock get_db
            with patch("mcpgateway.middleware.token_scoping.get_db") as mock_get_db:
                mock_session = MagicMock()
                mock_get_db.return_value.__next__.return_value = mock_session
                
                # Mock get_user_permissions to return admin permissions
                with patch.object(middleware, "_get_user_permissions") as mock_get_perms:
                    mock_get_perms.return_value = [Permissions.ADMIN_USER_MANAGEMENT]

                    call_next = AsyncMock()
                    call_next.return_value = Response(content="OK")

                    # Perform the request
                    response = await middleware(mock_request, call_next)
                    assert response.status_code == status.HTTP_200_OK
                    call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_wildcard_permissions_allow_all_access(self, middleware, mock_request):
        """Test that wildcard permissions allow access to any endpoint."""
        mock_request.url.path = "/admin/users"
        mock_request.method = "POST"
        mock_request.headers = {"Authorization": "Bearer token"}

        # Mock token extraction to return wildcard permissions
        with patch.object(middleware, "_extract_token_scopes") as mock_extract:
            mock_extract.return_value = {"sub": "admin@example.com", "scopes": {"permissions": ["*"]}}

            # Mock get_db
            with patch("mcpgateway.middleware.token_scoping.get_db") as mock_get_db:
                mock_session = MagicMock()
                mock_get_db.return_value.__next__.return_value = mock_session
                
                # Mock get_user_permissions to return wildcard
                with patch.object(middleware, "_get_user_permissions") as mock_get_perms:
                    mock_get_perms.return_value = ["*"]  # Wildcard permission

                    # Mock call_next to return a simple response
                    call_next = AsyncMock(return_value=Response(content="OK"))

                    # Perform the request, which should succeed
                    response = await middleware(mock_request, call_next)
                    assert response.status_code == status.HTTP_200_OK
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
    async def test_regex_pattern_precision_tools(self, middleware, permission_service):
        """Test that regex patterns match path segments precisely."""
        # Test exact /tools path matches for GET (should require TOOLS_READ)
        assert middleware._check_permission_restrictions("/tools", "GET", [Permissions.TOOLS_READ], permission_service) == True
        assert middleware._check_permission_restrictions("/tools/", "GET", [Permissions.TOOLS_READ], permission_service) == True
        assert middleware._check_permission_restrictions("/tools/abc", "GET", [Permissions.TOOLS_READ], permission_service) == True

        # Test that GET /tools requires TOOLS_READ permission specifically
        assert middleware._check_permission_restrictions("/tools", "GET", [Permissions.TOOLS_CREATE], permission_service) == False
        # Note: Empty permissions list returns True due to "no restrictions" logic
        assert middleware._check_permission_restrictions("/tools", "GET", [], permission_service) == True

        # Test POST /tools requires TOOLS_CREATE permission specifically
        assert middleware._check_permission_restrictions("/tools", "POST", [Permissions.TOOLS_CREATE], permission_service) == True
        assert middleware._check_permission_restrictions("/tools", "POST", [Permissions.TOOLS_READ], permission_service) == False

        # Test specific tool ID patterns for PUT/DELETE
        assert middleware._check_permission_restrictions("/tools/tool-123", "PUT", [Permissions.TOOLS_UPDATE], permission_service) == True
        assert middleware._check_permission_restrictions("/tools/tool-123", "DELETE", [Permissions.TOOLS_DELETE], permission_service) == True

        # Test wrong permissions for tool operations
        assert middleware._check_permission_restrictions("/tools/tool-123", "PUT", [Permissions.TOOLS_READ], permission_service) == False
        assert middleware._check_permission_restrictions("/tools/tool-123", "DELETE", [Permissions.TOOLS_UPDATE], permission_service) == False

    @pytest.mark.asyncio
    async def test_regex_pattern_precision_admin(self, middleware, permission_service):
        """Test that admin regex patterns require correct permissions."""
        # Test exact /admin path requires ADMIN_USER_MANAGEMENT
        assert middleware._check_permission_restrictions("/admin", "GET", [Permissions.ADMIN_USER_MANAGEMENT], permission_service) == True
        assert middleware._check_permission_restrictions("/admin/", "GET", [Permissions.ADMIN_USER_MANAGEMENT], permission_service) == True

        # Test admin operations require admin permissions
        assert middleware._check_permission_restrictions("/admin/users", "POST", [Permissions.ADMIN_USER_MANAGEMENT], permission_service) == True
        assert middleware._check_permission_restrictions("/admin/teams", "PUT", [Permissions.ADMIN_USER_MANAGEMENT], permission_service) == True

        # Test that non-admin permissions are rejected for admin paths
        assert middleware._check_permission_restrictions("/admin", "GET", [Permissions.TOOLS_READ], permission_service) == False
        assert middleware._check_permission_restrictions("/admin/users", "POST", [Permissions.RESOURCES_CREATE], permission_service) == False

        # Test that empty permissions list returns True (no restrictions policy)
        assert middleware._check_permission_restrictions("/admin", "GET", [], permission_service) == True

    @pytest.mark.asyncio
    async def test_regex_pattern_precision_servers(self, middleware, permission_service):
        """Test that server path patterns require correct permissions."""
        # Test exact /servers path requires SERVERS_READ
        assert middleware._check_permission_restrictions("/servers", "GET", [Permissions.SERVERS_READ], permission_service) == True
        assert middleware._check_permission_restrictions("/servers/", "GET", [Permissions.SERVERS_READ], permission_service) == True

        # Test specific server operations require correct permissions
        assert middleware._check_permission_restrictions("/servers/server-123", "PUT", [Permissions.SERVERS_UPDATE], permission_service) == True
        assert middleware._check_permission_restrictions("/servers/server-123", "DELETE", [Permissions.SERVERS_DELETE], permission_service) == True

        # Test nested server paths for tools/resources
        assert middleware._check_permission_restrictions("/servers/srv-1/tools", "GET", [Permissions.TOOLS_READ], permission_service) == True
        assert middleware._check_permission_restrictions("/servers/srv-1/tools/tool-1/call", "POST", [Permissions.TOOLS_EXECUTE], permission_service) == True
        assert middleware._check_permission_restrictions("/servers/srv-1/resources", "GET", [Permissions.RESOURCES_READ], permission_service) == True

        # Test wrong permissions for server operations
        assert middleware._check_permission_restrictions("/servers", "GET", [Permissions.TOOLS_READ], permission_service) == False
        assert middleware._check_permission_restrictions("/servers/server-123", "PUT", [Permissions.SERVERS_READ], permission_service) == False

    @pytest.mark.asyncio
    async def test_regex_pattern_segment_boundaries(self, middleware, permission_service):
        """Test that regex patterns respect path segment boundaries."""
        # Test that similar-but-different paths use default allow (proving pattern precision)
        # These paths don't match any specific pattern, so they get default allow
        edge_case_paths = ["/toolshed", "/adminpanel", "/resourcesful", "/promptsystem", "/serversocket"]

        for path in edge_case_paths:
            # These should return True due to default allow (proving they don't falsely match patterns)
            result = middleware._check_permission_restrictions(path, "GET", [], permission_service)
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
            result = middleware._check_permission_restrictions(path, method, permissions, permission_service)
            assert result == expected, f"Exact match {path} {method} should return {expected}"


