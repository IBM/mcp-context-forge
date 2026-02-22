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
    async def test_extract_token_scopes_returns_payload(self, middleware):
        """_extract_token_scopes should return decoded payload on success."""
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer test-token"}

        payload = {"sub": "user@example.com", "scopes": {"permissions": ["*"]}}
        with patch("mcpgateway.middleware.token_scoping.verify_jwt_token_cached", new=AsyncMock(return_value=payload)):
            assert await middleware._extract_token_scopes(request) == payload

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
    async def test_extract_token_scopes_accepts_case_insensitive_bearer(self, middleware, scheme):
        """Bearer scheme should be parsed case-insensitively."""
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": f"{scheme} test-token"}

        payload = {"sub": "user@example.com", "scopes": {"permissions": ["*"]}}
        with patch("mcpgateway.middleware.token_scoping.verify_jwt_token_cached", new=AsyncMock(return_value=payload)):
            assert await middleware._extract_token_scopes(request) == payload

    @pytest.mark.asyncio
    async def test_extract_token_scopes_rejects_empty_bearer_token(self, middleware):
        """Bearer authorization with an empty token should be rejected."""
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Bearer "}

        assert await middleware._extract_token_scopes(request) is None

    @pytest.mark.asyncio
    async def test_extract_token_scopes_rejects_non_bearer_scheme(self, middleware):
        """Non-bearer auth schemes must not be treated as JWT bearer tokens."""
        request = MagicMock(spec=Request)
        request.headers = {"Authorization": "Basic abc123"}

        assert await middleware._extract_token_scopes(request) is None

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

    def test_rpc_endpoint_whitelisted_for_server_scoped_tokens(self, middleware):
        """Test that /rpc endpoint is whitelisted for server-scoped tokens."""
        # The /rpc endpoint is required for MCP protocol operations (SSE transport)
        result = middleware._check_server_restriction("/rpc", "server-123")
        assert result == True, "/rpc endpoint should be whitelisted for server-scoped tokens"

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

    def test_permission_restrictions_default_deny_for_unmatched_path(self, middleware):
        """Unmatched paths should default-deny when permissions list is non-empty."""
        assert middleware._check_permission_restrictions("/unmatched/path", "GET", [Permissions.TOOLS_READ]) is False

    def test_permission_restrictions_unmatched_path_public_token(self, middleware):
        """Unmatched paths should still allow empty permissions (public token behavior)."""
        assert middleware._check_permission_restrictions("/unmatched/path", "GET", []) is True

    def test_permission_restrictions_rpc_denied_for_scoped_token(self, middleware):
        """Scoped tokens should not access /rpc directly without explicit mapping."""
        assert middleware._check_permission_restrictions("/rpc", "POST", [Permissions.RESOURCES_READ]) is False

    def test_permission_restrictions_server_mcp_requires_servers_use(self, middleware):
        """Server MCP endpoint should require servers.use permission."""
        assert middleware._check_permission_restrictions("/servers/server-1/mcp", "POST", [Permissions.RESOURCES_READ]) is False
        assert middleware._check_permission_restrictions("/servers/server-1/mcp", "POST", [Permissions.SERVERS_USE]) is True

    def test_check_team_membership_cached_false(self, middleware, monkeypatch):
        """Cached team membership false should deny access."""
        payload = {"sub": "user@example.com", "teams": ["team-1"]}

        cache = MagicMock()
        cache.get_team_membership_valid_sync.return_value = False
        monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: cache)

        result = middleware._check_team_membership(payload, db=MagicMock())
        assert result is False

    def test_check_team_membership_missing_user_email_denies(self, middleware):
        """Team-scoped tokens without a user email should be rejected."""
        payload = {"teams": ["team-1"]}
        assert middleware._check_team_membership(payload) is False

    def test_check_team_membership_db_valid_and_missing(self, middleware, monkeypatch):
        """Validate membership via DB for both valid and missing teams."""
        payload = {"sub": "user@example.com", "teams": ["team-1", "team-2"]}

        cache = MagicMock()
        cache.get_team_membership_valid_sync.return_value = None
        monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: cache)

        # Valid membership case
        db = MagicMock()
        result_proxy = MagicMock()
        result_proxy.scalars.return_value.all.return_value = ["team-1", "team-2"]
        db.execute.return_value = result_proxy

        def _get_db():
            yield db

        monkeypatch.setattr("mcpgateway.db.get_db", _get_db)
        assert middleware._check_team_membership(payload) is True
        cache.set_team_membership_valid_sync.assert_called_with("user@example.com", ["team-1", "team-2"], True)
        db.commit.assert_called_once()
        db.close.assert_called_once()

        # Missing team case
        db = MagicMock()
        result_proxy = MagicMock()
        result_proxy.scalars.return_value.all.return_value = ["team-1"]
        db.execute.return_value = result_proxy

        def _get_db_missing():
            yield db

        monkeypatch.setattr("mcpgateway.db.get_db", _get_db_missing)
        assert middleware._check_team_membership(payload) is False
        cache.set_team_membership_valid_sync.assert_called_with("user@example.com", ["team-1", "team-2"], False)

    def test_check_resource_team_ownership_tool_and_resource(self, middleware):
        """Check tool/resource visibility enforcement."""
        db = MagicMock()
        tool = MagicMock()
        tool.visibility = "team"
        tool.team_id = "team-1"
        db.execute.return_value.scalar_one_or_none.return_value = tool

        assert middleware._check_resource_team_ownership("/tools/abc", ["team-1"], db=db, _user_email="user@example.com") is True
        assert middleware._check_resource_team_ownership("/tools/abc", [], db=db, _user_email="user@example.com") is False

        resource = MagicMock()
        resource.visibility = "private"
        resource.owner_email = "user@example.com"
        db.execute.return_value.scalar_one_or_none.return_value = resource

        assert middleware._check_resource_team_ownership("/resources/abc", ["team-1"], db=db, _user_email="user@example.com") is True

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
    async def test_virtual_mcp_server_permission_pattern(self, middleware):
        """Test that Virtual MCP Server access doesn't require servers.create permission.

        Bug fix: The regex pattern ^/servers(?:$|/) was too broad, matching all paths
        starting with /servers/ including /servers/{id}/mcp. This caused Virtual MCP
        Server access to incorrectly require servers.create permission.

        The fix changes the pattern to ^/servers/?$ to only match exact paths.
        """
        # servers.create should be required ONLY for creating servers (exact path match)
        assert middleware._check_permission_restrictions(
            "/servers", "POST", [Permissions.SERVERS_READ, Permissions.TOOLS_READ]
        ) == False, "POST /servers should require servers.create"

        assert middleware._check_permission_restrictions(
            "/servers/", "POST", [Permissions.SERVERS_READ, Permissions.TOOLS_READ]
        ) == False, "POST /servers/ should require servers.create"

        assert middleware._check_permission_restrictions(
            "/servers", "POST", [Permissions.SERVERS_CREATE]
        ) == True, "POST /servers should succeed with servers.create"

        # Virtual MCP Server access should NOT require servers.create (this is the fix!)
        assert middleware._check_permission_restrictions(
            "/servers/3d7c7ab6a5264dadb8c7f4e04758295b/mcp",
            "POST",
            [Permissions.SERVERS_READ, Permissions.TOOLS_READ]
        ) == False, "POST /servers/{id}/mcp should require servers.use, not servers.read"

        assert middleware._check_permission_restrictions(
            "/servers/abc123/sse",
            "GET",
            [Permissions.SERVERS_USE]
        ) == True, "GET /servers/{id}/sse should require servers.use"
        assert middleware._check_permission_restrictions(
            "/servers/abc123/sse",
            "GET",
            [Permissions.SERVERS_READ]
        ) == False, "GET /servers/{id}/sse should NOT accept servers.read"

        # Other Virtual MCP Server endpoints should also not require servers.create
        assert middleware._check_permission_restrictions(
            "/servers/test-server/mcp/",
            "POST",
            [Permissions.SERVERS_READ, Permissions.TOOLS_READ]
        ) == False, "POST /servers/{id}/mcp/ should require servers.use"

        # Verify that servers.create works for Virtual MCP Server too (backward compatibility)
        assert middleware._check_permission_restrictions(
            "/servers/3d7c7ab6a5264dadb8c7f4e04758295b/mcp",
            "POST",
            [Permissions.SERVERS_CREATE, Permissions.SERVERS_USE, Permissions.SERVERS_READ, Permissions.TOOLS_READ]
        ) == True, "POST /servers/{id}/mcp should succeed when servers.use is present"

    @pytest.mark.asyncio
    async def test_tools_create_pattern_exact_match(self, middleware):
        """Test that tools.create is only required for exact POST /tools, not sub-paths."""
        # POST /tools requires tools.create
        assert middleware._check_permission_restrictions("/tools", "POST", [Permissions.TOOLS_CREATE]) is True
        assert middleware._check_permission_restrictions("/tools/", "POST", [Permissions.TOOLS_CREATE]) is True
        assert middleware._check_permission_restrictions("/tools", "POST", [Permissions.TOOLS_READ]) is False

        # POST /tools/{id}/state requires tools.update, NOT tools.create
        assert middleware._check_permission_restrictions(
            "/tools/tool-123/state", "POST", [Permissions.TOOLS_UPDATE]
        ) is True, "POST /tools/{id}/state should require tools.update"
        assert middleware._check_permission_restrictions(
            "/tools/tool-123/state", "POST", [Permissions.TOOLS_CREATE]
        ) is False, "POST /tools/{id}/state should NOT accept tools.create"

        # POST /tools/{id}/toggle requires tools.update
        assert middleware._check_permission_restrictions(
            "/tools/tool-123/toggle", "POST", [Permissions.TOOLS_UPDATE]
        ) is True, "POST /tools/{id}/toggle should require tools.update"
        assert middleware._check_permission_restrictions(
            "/tools/tool-123/toggle", "POST", [Permissions.TOOLS_CREATE]
        ) is False, "POST /tools/{id}/toggle should NOT accept tools.create"

    @pytest.mark.asyncio
    async def test_resources_create_pattern_exact_match(self, middleware):
        """Test that resources.create is only required for exact POST /resources, not sub-paths."""
        # POST /resources requires resources.create
        assert middleware._check_permission_restrictions("/resources", "POST", [Permissions.RESOURCES_CREATE]) is True
        assert middleware._check_permission_restrictions("/resources/", "POST", [Permissions.RESOURCES_CREATE]) is True
        assert middleware._check_permission_restrictions("/resources", "POST", [Permissions.RESOURCES_READ]) is False

        # POST /resources/{id}/state requires resources.update, NOT resources.create
        assert middleware._check_permission_restrictions(
            "/resources/res-123/state", "POST", [Permissions.RESOURCES_UPDATE]
        ) is True, "POST /resources/{id}/state should require resources.update"
        assert middleware._check_permission_restrictions(
            "/resources/res-123/state", "POST", [Permissions.RESOURCES_CREATE]
        ) is False, "POST /resources/{id}/state should NOT accept resources.create"

        # POST /resources/{id}/toggle requires resources.update
        assert middleware._check_permission_restrictions(
            "/resources/res-123/toggle", "POST", [Permissions.RESOURCES_UPDATE]
        ) is True, "POST /resources/{id}/toggle should require resources.update"

        # POST /resources/subscribe requires resources.read (SSE subscription)
        assert middleware._check_permission_restrictions(
            "/resources/subscribe", "POST", [Permissions.RESOURCES_READ]
        ) is True, "POST /resources/subscribe should require resources.read"
        assert middleware._check_permission_restrictions(
            "/resources/subscribe", "POST", [Permissions.RESOURCES_CREATE]
        ) is False, "POST /resources/subscribe should NOT accept resources.create"

    @pytest.mark.asyncio
    async def test_prompts_create_pattern_exact_match(self, middleware):
        """Test that prompts.create is only required for exact POST /prompts, not sub-paths."""
        # POST /prompts requires prompts.create
        assert middleware._check_permission_restrictions("/prompts", "POST", [Permissions.PROMPTS_CREATE]) is True
        assert middleware._check_permission_restrictions("/prompts/", "POST", [Permissions.PROMPTS_CREATE]) is True
        assert middleware._check_permission_restrictions("/prompts", "POST", [Permissions.PROMPTS_READ]) is False

        # POST /prompts/{id}/state requires prompts.update, NOT prompts.create
        assert middleware._check_permission_restrictions(
            "/prompts/prompt-123/state", "POST", [Permissions.PROMPTS_UPDATE]
        ) is True, "POST /prompts/{id}/state should require prompts.update"
        assert middleware._check_permission_restrictions(
            "/prompts/prompt-123/state", "POST", [Permissions.PROMPTS_CREATE]
        ) is False, "POST /prompts/{id}/state should NOT accept prompts.create"

        # POST /prompts/{id}/toggle requires prompts.update
        assert middleware._check_permission_restrictions(
            "/prompts/prompt-123/toggle", "POST", [Permissions.PROMPTS_UPDATE]
        ) is True, "POST /prompts/{id}/toggle should require prompts.update"

        # POST /prompts/{id} (MCP spec retrieval) requires prompts.read
        assert middleware._check_permission_restrictions(
            "/prompts/prompt-123", "POST", [Permissions.PROMPTS_READ]
        ) is True, "POST /prompts/{id} (MCP spec) should require prompts.read"
        assert middleware._check_permission_restrictions(
            "/prompts/prompt-123", "POST", [Permissions.PROMPTS_CREATE]
        ) is False, "POST /prompts/{id} (MCP spec) should NOT accept prompts.create"

    @pytest.mark.asyncio
    async def test_servers_subresource_permission_patterns(self, middleware):
        """Test that server sub-paths distinguish management (update) from access (read) endpoints."""
        # POST /servers/{id}/state requires servers.update (management)
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/state", "POST", [Permissions.SERVERS_UPDATE]
        ) is True, "POST /servers/{id}/state should require servers.update"
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/state", "POST", [Permissions.SERVERS_CREATE]
        ) is False, "POST /servers/{id}/state should NOT accept servers.create"
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/state", "POST", [Permissions.SERVERS_READ]
        ) is False, "POST /servers/{id}/state should NOT accept servers.read"

        # POST /servers/{id}/toggle requires servers.update (management)
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/toggle", "POST", [Permissions.SERVERS_UPDATE]
        ) is True, "POST /servers/{id}/toggle should require servers.update"
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/toggle", "POST", [Permissions.SERVERS_CREATE]
        ) is False, "POST /servers/{id}/toggle should NOT accept servers.create"

        # POST /servers/{id}/mcp requires servers.use (access endpoint)
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/mcp", "POST", [Permissions.SERVERS_USE]
        ) is True, "POST /servers/{id}/mcp should require servers.use"
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/mcp", "POST", [Permissions.SERVERS_READ]
        ) is False, "POST /servers/{id}/mcp should NOT accept servers.read"

        # GET /servers/{id}/sse requires servers.use (access endpoint)
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/sse", "GET", [Permissions.SERVERS_USE]
        ) is True, "GET /servers/{id}/sse should require servers.use"
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/sse", "GET", [Permissions.SERVERS_READ]
        ) is False, "GET /servers/{id}/sse should NOT accept servers.read"

        # POST /servers/{id}/message requires servers.use (access endpoint)
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/message", "POST", [Permissions.SERVERS_USE]
        ) is True, "POST /servers/{id}/message should require servers.use"
        assert middleware._check_permission_restrictions(
            "/servers/srv-123/message", "POST", [Permissions.SERVERS_READ]
        ) is False, "POST /servers/{id}/message should NOT accept servers.read"

    @pytest.mark.asyncio
    async def test_permission_pattern_consistency(self, middleware):
        """Verify all resource types use consistent create-vs-subresource patterns (gateways convention)."""
        resource_types = [
            ("tools", Permissions.TOOLS_CREATE, Permissions.TOOLS_UPDATE),
            ("resources", Permissions.RESOURCES_CREATE, Permissions.RESOURCES_UPDATE),
            ("prompts", Permissions.PROMPTS_CREATE, Permissions.PROMPTS_UPDATE),
            ("servers", Permissions.SERVERS_CREATE, Permissions.SERVERS_UPDATE),
            ("gateways", Permissions.GATEWAYS_CREATE, Permissions.GATEWAYS_UPDATE),
        ]

        for resource, create_perm, update_perm in resource_types:
            # Exact POST requires create permission
            assert middleware._check_permission_restrictions(
                f"/{resource}", "POST", [create_perm]
            ) is True, f"POST /{resource} should accept {create_perm}"

            # Exact POST rejects read-only
            assert middleware._check_permission_restrictions(
                f"/{resource}", "POST", ["read.only"]
            ) is False, f"POST /{resource} should reject non-create permission"

            # Sub-path POST should NOT require create permission (except servers which uses default-allow)
            if update_perm:
                assert middleware._check_permission_restrictions(
                    f"/{resource}/item-123/state", "POST", [update_perm]
                ) is True, f"POST /{resource}/item-123/state should accept {update_perm}"
                assert middleware._check_permission_restrictions(
                    f"/{resource}/item-123/state", "POST", [create_perm]
                ) is False, f"POST /{resource}/item-123/state should reject {create_perm}"

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

    @pytest.mark.asyncio
    async def test_gateway_permission_patterns(self, middleware):
        """Test that gateway permission patterns correctly distinguish create vs update."""
        # Test GET /gateways requires GATEWAYS_READ
        assert middleware._check_permission_restrictions("/gateways", "GET", [Permissions.GATEWAYS_READ]) is True
        assert middleware._check_permission_restrictions("/gateways/", "GET", [Permissions.GATEWAYS_READ]) is True
        assert middleware._check_permission_restrictions("/gateways/gw-123", "GET", [Permissions.GATEWAYS_READ]) is True

        # Test POST /gateways (exact) requires GATEWAYS_CREATE
        assert middleware._check_permission_restrictions("/gateways", "POST", [Permissions.GATEWAYS_CREATE]) is True
        assert middleware._check_permission_restrictions("/gateways/", "POST", [Permissions.GATEWAYS_CREATE]) is True

        # Test POST to sub-resources requires GATEWAYS_UPDATE (not CREATE)
        assert middleware._check_permission_restrictions("/gateways/gw-123/state", "POST", [Permissions.GATEWAYS_UPDATE]) is True
        assert middleware._check_permission_restrictions("/gateways/gw-123/toggle", "POST", [Permissions.GATEWAYS_UPDATE]) is True
        assert middleware._check_permission_restrictions("/gateways/gw-123/tools/refresh", "POST", [Permissions.GATEWAYS_UPDATE]) is True

        # Test that CREATE permission is NOT sufficient for sub-resource POSTs
        assert middleware._check_permission_restrictions("/gateways/gw-123/state", "POST", [Permissions.GATEWAYS_CREATE]) is False
        assert middleware._check_permission_restrictions("/gateways/gw-123/toggle", "POST", [Permissions.GATEWAYS_CREATE]) is False

        # Test PUT/DELETE require UPDATE/DELETE respectively
        assert middleware._check_permission_restrictions("/gateways/gw-123", "PUT", [Permissions.GATEWAYS_UPDATE]) is True
        assert middleware._check_permission_restrictions("/gateways/gw-123", "DELETE", [Permissions.GATEWAYS_DELETE]) is True

        # Test wrong permissions are rejected
        assert middleware._check_permission_restrictions("/gateways", "GET", [Permissions.TOOLS_READ]) is False
        assert middleware._check_permission_restrictions("/gateways", "POST", [Permissions.GATEWAYS_READ]) is False

    @pytest.mark.asyncio
    async def test_token_permission_patterns(self, middleware):
        """Test that token endpoints enforce the expected token permissions."""
        assert middleware._check_permission_restrictions("/tokens", "GET", [Permissions.TOKENS_READ]) is True
        assert middleware._check_permission_restrictions("/tokens", "GET", [Permissions.TOKENS_CREATE]) is False

        assert middleware._check_permission_restrictions("/tokens", "POST", [Permissions.TOKENS_CREATE]) is True
        assert middleware._check_permission_restrictions("/tokens", "POST", [Permissions.TOKENS_READ]) is False

        assert middleware._check_permission_restrictions("/tokens/teams/team-123", "POST", [Permissions.TOKENS_CREATE]) is True
        assert middleware._check_permission_restrictions("/tokens/teams/team-123", "POST", [Permissions.TOKENS_READ]) is False

        assert middleware._check_permission_restrictions("/tokens/token-123", "PUT", [Permissions.TOKENS_UPDATE]) is True
        assert middleware._check_permission_restrictions("/tokens/token-123", "PUT", [Permissions.TOKENS_READ]) is False

        assert middleware._check_permission_restrictions("/tokens/token-123", "DELETE", [Permissions.TOKENS_REVOKE]) is True
        assert middleware._check_permission_restrictions("/tokens/token-123", "DELETE", [Permissions.TOKENS_UPDATE]) is False

    @pytest.mark.asyncio
    async def test_private_visibility_requires_owner(self, middleware):
        """Test that private visibility enforces owner-only access per RBAC doc."""
        # Create mock DB session directly (passed as db parameter)
        mock_db = MagicMock()

        # Create mock server with private visibility
        # Note: Resource IDs must be UUID hex format (a-f, 0-9) to match _RESOURCE_PATTERNS
        mock_server = MagicMock()
        mock_server.visibility = "private"
        mock_server.owner_email = "owner@example.com"
        mock_server.team_id = "aaaa-bbbb-cccc"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

        # Test: Owner can access their private resource
        result = middleware._check_resource_team_ownership(
            request_path="/servers/a1b2c3d4-e5f6-0000-1111-222233334444",
            token_teams=["aaaa-bbbb-cccc"],
            db=mock_db,
            _user_email="owner@example.com",
        )
        assert result is True, "Owner should access their private resource"

        # Test: Non-owner in same team CANNOT access private resource
        result = middleware._check_resource_team_ownership(
            request_path="/servers/a1b2c3d4-e5f6-0000-1111-222233334444",
            token_teams=["aaaa-bbbb-cccc"],
            db=mock_db,
            _user_email="teammate@example.com",
        )
        assert result is False, "Non-owner teammate should NOT access private resource"

        # Test: Non-owner in different team CANNOT access private resource
        result = middleware._check_resource_team_ownership(
            request_path="/servers/a1b2c3d4-e5f6-0000-1111-222233334444",
            token_teams=["dddd-eeee-ffff"],
            db=mock_db,
            _user_email="outsider@example.com",
        )
        assert result is False, "Non-owner outsider should NOT access private resource"

    @pytest.mark.asyncio
    async def test_team_visibility_allows_team_members(self, middleware):
        """Test that team visibility allows any team member access."""
        mock_db = MagicMock()

        # Create mock server with team visibility
        mock_server = MagicMock()
        mock_server.visibility = "team"
        mock_server.owner_email = "owner@example.com"
        mock_server.team_id = "aaaa-bbbb-cccc"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

        # Test: Team member (non-owner) can access team resource
        result = middleware._check_resource_team_ownership(
            request_path="/servers/a1b2c3d4-e5f6-0000-1111-222233334444",
            token_teams=["aaaa-bbbb-cccc"],
            db=mock_db,
            _user_email="teammate@example.com",
        )
        assert result is True, "Team member should access team resource"

        # Test: Non-team member cannot access team resource
        result = middleware._check_resource_team_ownership(
            request_path="/servers/a1b2c3d4-e5f6-0000-1111-222233334444",
            token_teams=["dddd-eeee-ffff"],
            db=mock_db,
            _user_email="outsider@example.com",
        )
        assert result is False, "Non-team member should NOT access team resource"

    @pytest.mark.asyncio
    async def test_public_visibility_allows_all(self, middleware):
        """Test that public visibility allows all authenticated users."""
        mock_db = MagicMock()

        # Create mock server with public visibility
        mock_server = MagicMock()
        mock_server.visibility = "public"
        mock_server.owner_email = "owner@example.com"
        mock_server.team_id = "aaaa-bbbb-cccc"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

        # Test: Any authenticated user can access public resource
        result = middleware._check_resource_team_ownership(
            request_path="/servers/a1b2c3d4-e5f6-0000-1111-222233334444",
            token_teams=["dddd-eeee-ffff"],
            db=mock_db,
            _user_email="anyone@example.com",
        )
        assert result is True, "Any user should access public resource"

        # Test: Public-only token (empty teams) can access public resource
        result = middleware._check_resource_team_ownership(
            request_path="/servers/a1b2c3d4-e5f6-0000-1111-222233334444",
            token_teams=[],
            db=mock_db,
            _user_email="public-user@example.com",
        )
        assert result is True, "Public-only token should access public resource"

    @pytest.mark.asyncio
    async def test_admin_bypass_skips_team_validation(self, middleware, mock_request):
        """Admin tokens without teams should bypass team validation."""
        mock_request.url.path = "/servers/server-123"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        payload = {"sub": "admin@example.com", "is_admin": True, "scopes": {"permissions": ["*"]}}

        with (
            patch.object(middleware, "_extract_token_scopes", return_value=payload),
            patch.object(middleware, "_check_server_restriction", return_value=True),
            patch.object(middleware, "_check_permission_restrictions", return_value=True),
        ):
            call_next = AsyncMock(return_value="ok")
            result = await middleware(mock_request, call_next)
            assert result == "ok"
            call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_bypass_requires_explicit_null_teams(self, middleware, mock_request):
        """Admin bypass should only activate when teams is explicitly null and is_admin is true."""
        mock_request.url.path = "/tools"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        payload = {"sub": "admin@example.com", "teams": None, "is_admin": True, "scopes": {"permissions": ["*"]}}

        with (
            patch.object(middleware, "_extract_token_scopes", return_value=payload),
            patch.object(middleware, "_check_team_membership") as mock_membership,
            patch.object(middleware, "_check_resource_team_ownership") as mock_ownership,
        ):
            call_next = AsyncMock(return_value="ok")
            assert await middleware(mock_request, call_next) == "ok"
            call_next.assert_called_once()
            mock_membership.assert_not_called()
            mock_ownership.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_token_resolves_teams_from_db(self, middleware, mock_request, monkeypatch):
        """Session tokens should resolve teams via _resolve_teams_from_db and use shared DB for validation."""
        mock_request.url.path = "/tools"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        payload = {"sub": "user@example.com", "token_use": "session", "user": {"is_admin": True}, "scopes": {"permissions": ["*"]}}
        db = MagicMock()

        def _get_db():
            yield db

        monkeypatch.setattr("mcpgateway.db.get_db", _get_db)

        with (
            patch.object(middleware, "_extract_token_scopes", return_value=payload),
            patch.object(middleware, "_check_team_membership", return_value=True),
            patch.object(middleware, "_check_resource_team_ownership", return_value=True),
            patch("mcpgateway.auth._resolve_teams_from_db", new=AsyncMock(return_value=["team-1"])),
        ):
            call_next = AsyncMock(return_value="ok")
            assert await middleware(mock_request, call_next) == "ok"
            call_next.assert_called_once()
            assert db.commit.called
            assert db.close.called

    @pytest.mark.asyncio
    async def test_team_scoped_token_uses_shared_db(self, middleware, mock_request, monkeypatch):
        """Team-scoped tokens should validate membership and resource ownership with shared DB session."""
        mock_request.url.path = "/servers/server-123"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        payload = {"sub": "user@example.com", "teams": ["team-1"], "scopes": {"permissions": ["*"]}}
        db = MagicMock()

        def _get_db():
            yield db

        monkeypatch.setattr("mcpgateway.db.get_db", _get_db)

        with (
            patch.object(middleware, "_extract_token_scopes", return_value=payload),
            patch.object(middleware, "_check_team_membership", return_value=True),
            patch.object(middleware, "_check_resource_team_ownership", return_value=True),
            patch.object(middleware, "_check_server_restriction", return_value=True),
            patch.object(middleware, "_check_permission_restrictions", return_value=True),
        ):
            call_next = AsyncMock(return_value="ok")
            result = await middleware(mock_request, call_next)
            assert result == "ok"
            assert db.commit.called
            assert db.close.called

    @pytest.mark.asyncio
    async def test_public_only_token_rejected_when_membership_invalid(self, middleware, mock_request):
        """Public-only tokens should be rejected when membership check fails."""
        mock_request.url.path = "/servers/server-123"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        payload = {"sub": "user@example.com", "scopes": {"permissions": ["*"]}}

        with (
            patch.object(middleware, "_extract_token_scopes", return_value=payload),
            patch.object(middleware, "_check_team_membership", return_value=False),
        ):
            call_next = AsyncMock()
            response = await middleware(mock_request, call_next)
            assert response.status_code == status.HTTP_403_FORBIDDEN
            call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_ip_restrictions_block(self, middleware, mock_request):
        """IP restrictions should block disallowed requests."""
        mock_request.url.path = "/tools"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        payload = {"sub": "admin@example.com", "is_admin": True, "scopes": {"ip_restrictions": ["10.0.0.0/24"], "permissions": ["*"]}}

        with (
            patch.object(middleware, "_extract_token_scopes", return_value=payload),
            patch.object(middleware, "_check_ip_restrictions", return_value=False),
            patch.object(middleware, "_check_permission_restrictions", return_value=True),
            patch.object(middleware, "_check_server_restriction", return_value=True),
        ):
            call_next = AsyncMock()
            response = await middleware(mock_request, call_next)
            assert response.status_code == status.HTTP_403_FORBIDDEN
            call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_time_restrictions_block(self, middleware, mock_request):
        """Time restrictions should block disallowed requests."""
        mock_request.url.path = "/tools"
        mock_request.method = "GET"
        mock_request.headers = {"Authorization": "Bearer token"}

        payload = {"sub": "admin@example.com", "is_admin": True, "scopes": {"time_restrictions": {"weekdays_only": True}, "permissions": ["*"]}}

        with (
            patch.object(middleware, "_extract_token_scopes", return_value=payload),
            patch.object(middleware, "_check_time_restrictions", return_value=False),
            patch.object(middleware, "_check_permission_restrictions", return_value=True),
            patch.object(middleware, "_check_server_restriction", return_value=True),
        ):
            call_next = AsyncMock()
            response = await middleware(mock_request, call_next)
            assert response.status_code == status.HTTP_403_FORBIDDEN
            call_next.assert_not_called()


def test_check_resource_team_ownership_prompt_and_gateway():
    """Cover prompt/gateway visibility branches and missing-resource cases."""
    middleware = TokenScopingMiddleware()
    db = MagicMock()

    # Prompt: team visibility with matching team should allow
    prompt = MagicMock()
    prompt.visibility = "team"
    prompt.team_id = "team-1"
    db.execute.return_value.scalar_one_or_none.return_value = prompt
    assert middleware._check_resource_team_ownership("/prompts/a1b2c3d4", ["team-1"], db=db, _user_email="user@example.com") is True

    # Gateway: private visibility with owner match should allow
    gateway = MagicMock()
    gateway.visibility = "private"
    gateway.owner_email = "owner@example.com"
    db.execute.return_value.scalar_one_or_none.return_value = gateway
    assert middleware._check_resource_team_ownership("/gateways/a1b2c3d4", ["team-1"], db=db, _user_email="owner@example.com") is True

    # Resource not found should allow
    db.execute.return_value.scalar_one_or_none.return_value = None
    assert middleware._check_resource_team_ownership("/resources/a1b2c3d4", ["team-1"], db=db, _user_email="user@example.com") is True


def test_check_resource_team_ownership_normalizes_team_dict_and_allows_team_resource():
    """Token team dict format should be normalized and allow matching team resources."""
    middleware = TokenScopingMiddleware()
    db = MagicMock()

    resource = MagicMock()
    resource.visibility = "team"
    resource.team_id = "team-1"
    db.execute.return_value.scalar_one_or_none.return_value = resource

    assert middleware._check_resource_team_ownership("/resources/a1b2c3d4", [{"id": "team-1"}], db=db, _user_email="user@example.com") is True


def test_check_resource_team_ownership_owns_session_commits_and_closes(monkeypatch):
    """When middleware owns the DB session, it should commit and close in the finally block."""
    middleware = TokenScopingMiddleware()
    db = MagicMock()

    resource = MagicMock()
    resource.visibility = "public"
    db.execute.return_value.scalar_one_or_none.return_value = resource

    def _get_db():
        yield db

    monkeypatch.setattr("mcpgateway.db.get_db", _get_db)

    assert middleware._check_resource_team_ownership("/resources/a1b2c3d4", ["team-1"], _user_email="user@example.com") is True
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_check_resource_team_ownership_public_only_token_denied_for_team_prompt():
    """Public-only tokens should not be able to access team/private prompts."""
    middleware = TokenScopingMiddleware()
    db = MagicMock()

    prompt = MagicMock()
    prompt.visibility = "team"
    prompt.team_id = "team-1"
    db.execute.return_value.scalar_one_or_none.return_value = prompt

    assert middleware._check_resource_team_ownership("/prompts/a1b2c3d4", [], db=db, _user_email="user@example.com") is False


def test_check_resource_team_ownership_prompt_unknown_visibility_denies():
    """Unknown prompt visibility should fail securely (deny)."""
    middleware = TokenScopingMiddleware()
    db = MagicMock()

    prompt = MagicMock()
    prompt.visibility = "mystery"
    prompt.team_id = "team-1"
    db.execute.return_value.scalar_one_or_none.return_value = prompt

    assert middleware._check_resource_team_ownership("/prompts/a1b2c3d4", ["team-1"], db=db, _user_email="user@example.com") is False


def test_check_resource_team_ownership_gateway_team_allows_matching_team():
    """Team-scoped gateways should allow access for matching team tokens."""
    middleware = TokenScopingMiddleware()
    db = MagicMock()

    gateway = MagicMock()
    gateway.visibility = "team"
    gateway.team_id = "team-1"
    db.execute.return_value.scalar_one_or_none.return_value = gateway

    assert middleware._check_resource_team_ownership("/gateways/a1b2c3d4", ["team-1"], db=db, _user_email="user@example.com") is True


def test_check_resource_team_ownership_gateway_private_denies_non_owner():
    """Private gateways should deny access when requester is not the owner."""
    middleware = TokenScopingMiddleware()
    db = MagicMock()

    gateway = MagicMock()
    gateway.visibility = "private"
    gateway.owner_email = "owner@example.com"
    gateway.team_id = "team-1"
    db.execute.return_value.scalar_one_or_none.return_value = gateway

    assert middleware._check_resource_team_ownership("/gateways/a1b2c3d4", ["team-1"], db=db, _user_email="other@example.com") is False


def test_check_resource_team_ownership_unknown_resource_type_denies(monkeypatch):
    """Unknown resource types should be denied by default."""
    # Standard
    import re

    # First-Party
    from mcpgateway.middleware import token_scoping as token_scoping_module

    middleware = TokenScopingMiddleware()
    db = MagicMock()

    monkeypatch.setattr(token_scoping_module, "_RESOURCE_PATTERNS", [(re.compile(r"/weird/?([a-f0-9\\-]+)"), "weird")])
    assert middleware._check_resource_team_ownership("/weird/a1b2c3d4", ["team-1"], db=db, _user_email="user@example.com") is False


def test_check_resource_team_ownership_tool_private_and_unknown():
    middleware = TokenScopingMiddleware()

    # Private tool: owner allowed, non-owner denied
    db = MagicMock()
    tool = MagicMock()
    tool.visibility = "private"
    tool.owner_email = "owner@example.com"
    db.execute.return_value.scalar_one_or_none.return_value = tool
    assert middleware._check_resource_team_ownership("/tools/a1b2c3d4", ["team-1"], db=db, _user_email="owner@example.com") is True
    assert middleware._check_resource_team_ownership("/tools/a1b2c3d4", ["team-1"], db=db, _user_email="other@example.com") is False

    # Unknown visibility denies
    tool.visibility = "mystery"
    assert middleware._check_resource_team_ownership("/tools/a1b2c3d4", ["team-1"], db=db, _user_email="owner@example.com") is False


def test_check_resource_team_ownership_resource_branches():
    middleware = TokenScopingMiddleware()

    # Public resource allows
    db = MagicMock()
    resource = MagicMock()
    resource.visibility = "public"
    db.execute.return_value.scalar_one_or_none.return_value = resource
    assert middleware._check_resource_team_ownership("/resources/a1b2c3d4", ["team-1"], db=db, _user_email="user@example.com") is True

    # Public-only token denied for team resource
    resource.visibility = "team"
    resource.team_id = "team-1"
    assert middleware._check_resource_team_ownership("/resources/a1b2c3d4", [], db=db, _user_email="user@example.com") is False

    # Team mismatch denied
    assert middleware._check_resource_team_ownership("/resources/a1b2c3d4", ["team-2"], db=db, _user_email="user@example.com") is False

    # Private resource denied for non-owner
    resource.visibility = "private"
    resource.owner_email = "owner@example.com"
    assert middleware._check_resource_team_ownership("/resources/a1b2c3d4", ["team-1"], db=db, _user_email="other@example.com") is False

    # Unknown visibility denies
    resource.visibility = "mystery"
    assert middleware._check_resource_team_ownership("/resources/a1b2c3d4", ["team-1"], db=db, _user_email="user@example.com") is False


def test_check_resource_team_ownership_exception_returns_false():
    middleware = TokenScopingMiddleware()
    db = MagicMock()
    db.execute.side_effect = RuntimeError("boom")
    assert middleware._check_resource_team_ownership("/tools/a1b2c3d4", ["team-1"], db=db, _user_email="user@example.com") is False


def _make_request(path: str = "/servers/server-123") -> MagicMock:
    request = MagicMock(spec=Request)
    request.url.path = path
    request.method = "GET"
    request.headers = {"Authorization": "Bearer token"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.state = MagicMock()
    request.state._token_scoping_done = False
    return request


@pytest.mark.asyncio
async def test_team_scoped_membership_denied(monkeypatch):
    middleware = TokenScopingMiddleware()
    mock_request = _make_request()

    payload = {"sub": "user@example.com", "teams": ["team-1"], "scopes": {"permissions": ["*"]}}
    db = MagicMock()

    def _get_db():
        yield db

    monkeypatch.setattr("mcpgateway.db.get_db", _get_db)

    with (
        patch.object(middleware, "_extract_token_scopes", return_value=payload),
        patch.object(middleware, "_check_team_membership", return_value=False),
    ):
        call_next = AsyncMock()
        response = await middleware(mock_request, call_next)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        call_next.assert_not_called()


@pytest.mark.asyncio
async def test_team_scoped_resource_denied(monkeypatch):
    middleware = TokenScopingMiddleware()
    mock_request = _make_request()

    payload = {"sub": "user@example.com", "teams": ["team-1"], "scopes": {"permissions": ["*"]}}
    db = MagicMock()

    def _get_db():
        yield db

    monkeypatch.setattr("mcpgateway.db.get_db", _get_db)

    with (
        patch.object(middleware, "_extract_token_scopes", return_value=payload),
        patch.object(middleware, "_check_team_membership", return_value=True),
        patch.object(middleware, "_check_resource_team_ownership", return_value=False),
    ):
        call_next = AsyncMock()
        response = await middleware(mock_request, call_next)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        call_next.assert_not_called()


@pytest.mark.asyncio
async def test_public_only_resource_denied():
    middleware = TokenScopingMiddleware()
    mock_request = _make_request()

    payload = {"sub": "user@example.com", "scopes": {"permissions": ["*"]}}

    with (
        patch.object(middleware, "_extract_token_scopes", return_value=payload),
        patch.object(middleware, "_check_team_membership", return_value=True),
        patch.object(middleware, "_check_resource_team_ownership", return_value=False),
    ):
        call_next = AsyncMock()
        response = await middleware(mock_request, call_next)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        call_next.assert_not_called()
