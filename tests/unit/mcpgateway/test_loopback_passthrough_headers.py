# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_loopback_passthrough_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for passthrough header forwarding in loopback /rpc calls.

Verifies that SSE, WebSocket, and Streamable HTTP affinity loopback calls
correctly forward X-Upstream-Authorization and configured passthrough headers
to the internal /rpc endpoint. See GitHub issue #3640.
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.passthrough_headers import extract_headers_for_loopback


# ---------------------------------------------------------------------------
# Tests for extract_headers_for_loopback utility
# ---------------------------------------------------------------------------
class TestExtractHeadersForLoopback:
    """Test the extract_headers_for_loopback utility function."""

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_extracts_x_upstream_authorization_always(self, mock_settings):
        """X-Upstream-Authorization is always forwarded even when passthrough is disabled."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        headers = {"X-Upstream-Authorization": "Bearer upstream-token", "Accept": "text/html"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer upstream-token"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_case_insensitive_x_upstream_authorization(self, mock_settings):
        """Header matching is case-insensitive."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        headers = {"x-UPSTREAM-authorization": "Bearer tok"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer tok"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_returns_empty_when_no_relevant_headers(self, mock_settings):
        """Returns empty dict when no passthrough-relevant headers present."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        headers = {"Accept": "text/html", "Host": "localhost"}
        result = extract_headers_for_loopback(headers)

        assert result == {}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_returns_empty_for_none_input(self, mock_settings):
        """Returns empty dict for None input."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        result = extract_headers_for_loopback(None)
        assert result == {}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_returns_empty_for_empty_dict(self, mock_settings):
        """Returns empty dict for empty input."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        result = extract_headers_for_loopback({})
        assert result == {}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_forwards_allowlist_headers_when_enabled(self, mock_settings):
        """When passthrough is enabled, configured allowlist headers are also forwarded."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["X-Tenant-Id", "X-Trace-Id"]

        headers = {"X-Tenant-Id": "acme", "X-Trace-Id": "trace-123", "Accept": "text/html"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-tenant-id": "acme", "x-trace-id": "trace-123"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_does_not_forward_allowlist_when_disabled(self, mock_settings):
        """When passthrough is disabled, only x-upstream-authorization is forwarded."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = ["X-Tenant-Id"]

        headers = {"X-Tenant-Id": "acme", "X-Upstream-Authorization": "Bearer tok"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer tok"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_skips_authorization_and_content_type_from_allowlist(self, mock_settings):
        """Authorization and Content-Type are skipped even if in allowlist."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["Authorization", "Content-Type", "X-Tenant-Id"]

        headers = {"Authorization": "Bearer main", "Content-Type": "application/json", "X-Tenant-Id": "acme"}
        result = extract_headers_for_loopback(headers)

        assert "authorization" not in result
        assert "content-type" not in result
        assert result == {"x-tenant-id": "acme"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_combined_upstream_auth_and_allowlist(self, mock_settings):
        """Both X-Upstream-Authorization and allowlist headers are forwarded together."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["X-Tenant-Id"]

        headers = {"X-Upstream-Authorization": "Bearer upstream", "X-Tenant-Id": "acme"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer upstream", "x-tenant-id": "acme"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_none_default_passthrough_headers(self, mock_settings):
        """Handles None default_passthrough_headers gracefully."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = None

        headers = {"X-Upstream-Authorization": "Bearer tok"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer tok"}


# ---------------------------------------------------------------------------
# Tests for SSE generate_response header forwarding
# ---------------------------------------------------------------------------
class TestSSEGenerateResponsePassthroughHeaders:
    """Test that SSE generate_response forwards passthrough headers in loopback calls."""

    @pytest.mark.asyncio
    @patch("mcpgateway.cache.session_registry.ResilientHttpClient")
    @patch("mcpgateway.cache.session_registry.settings")
    async def test_passthrough_headers_forwarded_in_sse_loopback(self, mock_settings, mock_client_cls):
        """Passthrough headers from user dict are included in the /rpc loopback request."""
        # First-Party
        from mcpgateway.cache.session_registry import SessionRegistry

        mock_settings.port = 8000
        mock_settings.federation_timeout = 30
        mock_settings.skip_ssl_verify = False
        mock_settings.mcpgateway_session_affinity_enabled = False
        mock_settings.jwt_issuer = "test"
        mock_settings.jwt_audience = "test"

        # Set up mock HTTP client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        # Set up transport
        transport = MagicMock()
        transport.session_id = "test-session"
        transport.send_message = AsyncMock()

        # User with passthrough headers (as stored by SSE endpoint)
        user = {
            "email": "test@example.com",
            "auth_token": "test-jwt-token",
            "is_admin": False,
            "_passthrough_headers": {
                "x-upstream-authorization": "Bearer upstream-secret",
                "x-tenant-id": "acme",
            },
        }

        registry = SessionRegistry()
        message = {"method": "tools/list", "params": {}, "id": 1}

        await registry.generate_response(message, transport, "server-1", user)

        # Verify the loopback call included passthrough headers
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        sent_headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})

        assert sent_headers.get("x-upstream-authorization") == "Bearer upstream-secret"
        assert sent_headers.get("x-tenant-id") == "acme"
        assert sent_headers.get("Authorization") == "Bearer test-jwt-token"
        assert sent_headers.get("Content-Type") == "application/json"

    @pytest.mark.asyncio
    @patch("mcpgateway.cache.session_registry.ResilientHttpClient")
    @patch("mcpgateway.cache.session_registry.settings")
    async def test_no_passthrough_headers_key_is_safe(self, mock_settings, mock_client_cls):
        """When _passthrough_headers is absent, loopback call still works normally."""
        # First-Party
        from mcpgateway.cache.session_registry import SessionRegistry

        mock_settings.port = 8000
        mock_settings.federation_timeout = 30
        mock_settings.skip_ssl_verify = False
        mock_settings.mcpgateway_session_affinity_enabled = False

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "result": {}, "id": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        transport = MagicMock()
        transport.session_id = "test-session"
        transport.send_message = AsyncMock()

        # User WITHOUT _passthrough_headers (backward compatibility)
        user = {"email": "test@example.com", "auth_token": "test-jwt-token", "is_admin": False}

        registry = SessionRegistry()
        message = {"method": "ping", "params": {}, "id": 1}

        await registry.generate_response(message, transport, None, user)

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        sent_headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})

        assert "x-upstream-authorization" not in sent_headers
        assert sent_headers.get("Authorization") == "Bearer test-jwt-token"


# ---------------------------------------------------------------------------
# Tests for WebSocket passthrough header forwarding
# ---------------------------------------------------------------------------
class TestWebSocketPassthroughHeaders:
    """Test that WebSocket transport captures and forwards passthrough headers."""

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_extract_headers_for_loopback_with_websocket_headers(self, mock_settings):
        """Simulates extracting passthrough headers from a WebSocket handshake."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        # Simulate WebSocket handshake headers
        ws_headers = {
            "upgrade": "websocket",
            "connection": "Upgrade",
            "authorization": "Bearer ws-token",
            "x-upstream-authorization": "Bearer upstream-ws-token",
            "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ==",
        }

        result = extract_headers_for_loopback(ws_headers)

        assert result == {"x-upstream-authorization": "Bearer upstream-ws-token"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_websocket_headers_with_passthrough_enabled(self, mock_settings):
        """WebSocket headers with passthrough feature enabled."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["X-Tenant-Id"]

        ws_headers = {
            "authorization": "Bearer ws-token",
            "x-upstream-authorization": "Bearer upstream",
            "x-tenant-id": "acme",
        }

        result = extract_headers_for_loopback(ws_headers)

        assert result == {"x-upstream-authorization": "Bearer upstream", "x-tenant-id": "acme"}


# ---------------------------------------------------------------------------
# Tests for Streamable HTTP affinity path passthrough
# ---------------------------------------------------------------------------
class TestStreamableHTTPAffinityPassthrough:
    """Test that Streamable HTTP affinity loopback forwards passthrough headers."""

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_extract_from_streamable_http_headers(self, mock_settings):
        """Simulates header extraction from Streamable HTTP request for affinity loopback."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        headers = {
            "content-type": "application/json",
            "authorization": "Bearer client-token",
            "x-upstream-authorization": "Bearer upstream-token",
            "mcp-session-id": "session-123",
        }

        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer upstream-token"}


# ---------------------------------------------------------------------------
# Integration-style test: SSE endpoint stores headers in user_with_token
# ---------------------------------------------------------------------------
class TestSSEEndpointHeaderCapture:
    """Test that the SSE endpoint correctly captures passthrough headers into user_with_token."""

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_extract_captures_upstream_auth_from_sse_request(self, mock_settings):
        """Simulates SSE endpoint capturing headers from the connection request."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        # Simulate request.headers as a dict (as done in the SSE endpoint)
        request_headers = {
            "host": "localhost:8000",
            "authorization": "Bearer gateway-token",
            "x-upstream-authorization": "Bearer upstream-secret",
            "accept": "text/event-stream",
            "connection": "keep-alive",
        }

        passthrough = extract_headers_for_loopback(request_headers)

        # Build user_with_token as the SSE endpoint does
        user_with_token = {
            "email": "user@example.com",
            "auth_token": "gateway-token",
            "token_teams": None,
            "is_admin": False,
            "_passthrough_headers": passthrough,
        }

        assert user_with_token["_passthrough_headers"] == {"x-upstream-authorization": "Bearer upstream-secret"}
