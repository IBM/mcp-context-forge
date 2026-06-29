# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_token_scoping_reverse_proxy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for TokenScopingMiddleware reverse proxy endpoint handling.
"""

# Standard

# Third-Party
import pytest

# First-Party
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware


class TestTokenScopingReverseProxy:
    """Test reverse proxy endpoint handling in TokenScopingMiddleware."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance."""
        return TokenScopingMiddleware()

    def test_reverse_proxy_allowed_with_server_scoped_token(self, middleware):
        """Test that /reverse-proxy endpoints are allowed even with server-scoped tokens.
        
        This is a regression test for the issue where server-scoped tokens
        were being rejected when connecting to the reverse proxy endpoint.
        """
        # Server-scoped token should allow /reverse-proxy endpoints
        assert middleware._check_server_restriction("/reverse-proxy/ws", "some-server-id") is True
        assert middleware._check_server_restriction("/reverse-proxy/sessions", "some-server-id") is True
        assert middleware._check_server_restriction("/reverse-proxy", "some-server-id") is True

    def test_reverse_proxy_allowed_without_server_restriction(self, middleware):
        """Test that /reverse-proxy endpoints work without server restrictions."""
        # No server restriction (None) should always allow
        assert middleware._check_server_restriction("/reverse-proxy/ws", None) is True
        assert middleware._check_server_restriction("/reverse-proxy/sessions", None) is True

    def test_server_scoped_token_still_restricts_server_endpoints(self, middleware):
        """Test that server-scoped tokens still restrict server-specific endpoints."""
        # Server-scoped token should only allow matching server endpoints
        assert middleware._check_server_restriction("/servers/abc123/tools", "abc123") is True
        assert middleware._check_server_restriction("/servers/xyz789/tools", "abc123") is False
        assert middleware._check_server_restriction("/sse/abc123", "abc123") is True
        assert middleware._check_server_restriction("/sse/xyz789", "abc123") is False

    def test_other_general_endpoints_still_allowed(self, middleware):
        """Test that other general endpoints remain allowed with server-scoped tokens."""
        server_id = "some-server-id"
        
        # These should all be allowed regardless of server_id restriction
        assert middleware._check_server_restriction("/health", server_id) is True
        assert middleware._check_server_restriction("/metrics", server_id) is True
        assert middleware._check_server_restriction("/docs", server_id) is True
        assert middleware._check_server_restriction("/mcp", server_id) is True
        assert middleware._check_server_restriction("/", server_id) is True

    def test_unmatched_paths_denied_with_server_restriction(self, middleware):
        """Test that unmatched paths are still denied with server restrictions."""
        # Random paths should be denied when server_id is present
        assert middleware._check_server_restriction("/random/path", "some-server-id") is False

    def test_reverse_proxy_permission_check(self, middleware):
        """Test that reverse proxy endpoints are not explicitly mapped in permission patterns.
        
        Since /reverse-proxy endpoints are not in _PERMISSION_PATTERNS, they fall through
        to default deny behavior (return False) unless wildcard permission is present.
        This is expected behavior - reverse proxy access is controlled at the router level
        via @require_permission decorators, not at the middleware level.
        """
        # Test with wildcard permission - should allow
        assert middleware._check_permission_restrictions("/reverse-proxy/ws", "GET", ["*"]) is True
        
        # Test with specific permissions - should deny (no pattern match, default deny)
        assert middleware._check_permission_restrictions("/reverse-proxy/ws", "GET", ["servers.manage"]) is False
        assert middleware._check_permission_restrictions("/reverse-proxy/sse", "GET", ["servers.manage"]) is False
        assert middleware._check_permission_restrictions("/reverse-proxy/ws", "GET", ["servers.create", "servers.update"]) is False
        assert middleware._check_permission_restrictions("/reverse-proxy/ws", "GET", ["tools.read"]) is False

        assert middleware._check_server_restriction("/api/v1/users", "some-server-id") is False

# Made with Bob
