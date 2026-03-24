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
from mcpgateway.utils.passthrough_headers import (
    extract_headers_for_loopback,
    filter_loopback_skip_headers,
    safe_extract_and_filter_for_loopback,
    safe_extract_headers_for_loopback,
)


# ---------------------------------------------------------------------------
# Tests for filter_loopback_skip_headers utility
# ---------------------------------------------------------------------------
class TestFilterLoopbackSkipHeaders:
    """Test the defense-in-depth filter applied at loopback merge sites."""

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_strips_proxy_user_header(self, mock_settings):
        """Deny-path: proxy_user_header is stripped even if present in passthrough dict."""
        mock_settings.proxy_user_header = "X-Authenticated-User"

        headers = {
            "x-authenticated-user": "attacker@evil.com",
            "x-upstream-authorization": "Bearer upstream",
            "x-tenant-id": "acme",
        }
        result = filter_loopback_skip_headers(headers)

        assert "x-authenticated-user" not in result
        assert result == {"x-upstream-authorization": "Bearer upstream", "x-tenant-id": "acme"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_strips_custom_proxy_user_header(self, mock_settings):
        """Deny-path: custom proxy_user_header name is also stripped."""
        mock_settings.proxy_user_header = "X-Custom-Identity"

        headers = {"x-custom-identity": "spoofed", "x-tenant-id": "acme"}
        result = filter_loopback_skip_headers(headers)

        assert "x-custom-identity" not in result
        assert result == {"x-tenant-id": "acme"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_strips_static_skip_headers(self, mock_settings):
        """All static skip headers are removed."""
        mock_settings.proxy_user_header = "X-Authenticated-User"

        headers = {
            "authorization": "Bearer tok",
            "content-type": "application/json",
            "mcp-session-id": "sess-1",
            "x-mcp-session-id": "sess-2",
            "x-forwarded-internally": "true",
            "x-tenant-id": "acme",
        }
        result = filter_loopback_skip_headers(headers)

        assert result == {"x-tenant-id": "acme"}


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

        assert not result

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_returns_empty_for_none_input(self, mock_settings):
        """Returns empty dict for None input."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        result = extract_headers_for_loopback(None)
        assert not result

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_returns_empty_for_empty_dict(self, mock_settings):
        """Returns empty dict for empty input."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        result = extract_headers_for_loopback({})
        assert not result

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_forwards_allowlist_headers_when_enabled(self, mock_settings, mock_cache, _mock_sl):
        """When passthrough is enabled, configured allowlist headers are also forwarded."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["X-Tenant-Id", "X-Trace-Id"]
        mock_cache.get.return_value = frozenset(["X-Tenant-Id", "X-Trace-Id"])

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

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_skips_authorization_and_content_type_from_allowlist(self, mock_settings, mock_cache, _mock_sl):
        """Authorization and Content-Type are skipped even if in allowlist."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["Authorization", "Content-Type", "X-Tenant-Id"]
        mock_cache.get.return_value = frozenset(["Authorization", "Content-Type", "X-Tenant-Id"])

        headers = {"Authorization": "Bearer main", "Content-Type": "application/json", "X-Tenant-Id": "acme"}
        result = extract_headers_for_loopback(headers)

        assert "authorization" not in result
        assert "content-type" not in result
        assert result == {"x-tenant-id": "acme"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_combined_upstream_auth_and_allowlist(self, mock_settings, mock_cache, _mock_sl):
        """Both X-Upstream-Authorization and allowlist headers are forwarded together."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["X-Tenant-Id"]
        mock_cache.get.return_value = frozenset(["X-Tenant-Id"])

        headers = {"X-Upstream-Authorization": "Bearer upstream", "X-Tenant-Id": "acme"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer upstream", "x-tenant-id": "acme"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_none_default_passthrough_headers(self, mock_settings, mock_cache, _mock_sl):
        """Handles None default_passthrough_headers gracefully."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = None
        mock_cache.get.return_value = frozenset()

        headers = {"X-Upstream-Authorization": "Bearer tok"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer tok"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_never_returns_authorization_regardless_of_config(self, mock_settings, mock_cache, _mock_sl):
        """Deny-path: authorization is never returned, even with passthrough enabled."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["Authorization", "X-Tenant-Id"]
        mock_cache.get.return_value = frozenset(["Authorization", "X-Tenant-Id"])

        headers = {"Authorization": "Bearer secret", "X-Tenant-Id": "acme"}
        result = extract_headers_for_loopback(headers)

        assert "authorization" not in result
        assert result == {"x-tenant-id": "acme"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_never_returns_content_type_regardless_of_config(self, mock_settings, mock_cache, _mock_sl):
        """Deny-path: content-type is never returned, even with passthrough enabled."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["Content-Type"]
        mock_cache.get.return_value = frozenset(["Content-Type"])

        headers = {"Content-Type": "text/plain"}
        result = extract_headers_for_loopback(headers)

        assert "content-type" not in result
        assert not result

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_never_returns_authorization_when_passthrough_disabled(self, mock_settings):
        """Deny-path: authorization is not returned even when passthrough is disabled."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        headers = {"Authorization": "Bearer secret", "X-Upstream-Authorization": "Bearer up"}
        result = extract_headers_for_loopback(headers)

        assert "authorization" not in result
        assert result == {"x-upstream-authorization": "Bearer up"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_never_returns_gateway_internal_headers(self, mock_settings, mock_cache, _mock_sl):
        """Deny-path: gateway-internal headers (including mcp-session-id) are never returned."""
        mock_settings.enable_header_passthrough = True
        allowlist = frozenset(["Mcp-Session-Id", "X-Mcp-Session-Id", "X-Forwarded-Internally", "X-Tenant-Id"])
        mock_cache.get.return_value = allowlist

        headers = {
            "Mcp-Session-Id": "session-abc",
            "X-Mcp-Session-Id": "session-123",
            "X-Forwarded-Internally": "true",
            "X-Tenant-Id": "acme",
        }
        result = extract_headers_for_loopback(headers)

        assert "mcp-session-id" not in result
        assert "x-mcp-session-id" not in result
        assert "x-forwarded-internally" not in result
        assert result == {"x-tenant-id": "acme"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_never_returns_proxy_user_header(self, mock_settings, mock_cache, _mock_sl):
        """Deny-path: proxy_user_header is never returned, even if in the allowlist."""
        mock_settings.enable_header_passthrough = True
        mock_settings.proxy_user_header = "X-Authenticated-User"
        mock_cache.get.return_value = frozenset(["X-Authenticated-User", "X-Tenant-Id"])

        headers = {"X-Authenticated-User": "attacker@evil.com", "X-Tenant-Id": "acme"}
        result = extract_headers_for_loopback(headers)

        assert "x-authenticated-user" not in result
        assert result == {"x-tenant-id": "acme"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_never_returns_custom_proxy_user_header(self, mock_settings, mock_cache, _mock_sl):
        """Deny-path: custom proxy_user_header is blocked regardless of name."""
        mock_settings.enable_header_passthrough = True
        mock_settings.proxy_user_header = "X-Custom-Proxy-User"
        mock_cache.get.return_value = frozenset(["X-Custom-Proxy-User", "X-Tenant-Id"])

        headers = {"X-Custom-Proxy-User": "attacker@evil.com", "X-Tenant-Id": "acme"}
        result = extract_headers_for_loopback(headers)

        assert "x-custom-proxy-user" not in result
        assert result == {"x-tenant-id": "acme"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_uses_cached_allowlist(self, mock_settings, mock_cache, _mock_sl):
        """Allowlist is resolved via _loopback_allowlist_cache."""
        mock_settings.enable_header_passthrough = True
        mock_cache.get.return_value = frozenset(["X-Tenant-Id"])

        headers = {"X-Tenant-Id": "acme", "Accept": "text/html"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-tenant-id": "acme"}
        mock_cache.get.assert_called_once()

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_includes_gateway_specific_passthrough_headers(self, mock_settings, mock_cache, _mock_sl):
        """Headers allowed only by gateway-specific config are preserved for /rpc."""
        mock_settings.enable_header_passthrough = True
        # Cache returns merged set including gateway-specific headers
        mock_cache.get.return_value = frozenset(["X-Custom-Auth", "X-Org-Id"])

        headers = {"X-Custom-Auth": "secret", "X-Org-Id": "org-1", "Accept": "text/html"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-custom-auth": "secret", "x-org-id": "org-1"}

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_merges_global_and_gateway_allowlists(self, mock_settings, mock_cache, _mock_sl):
        """Union of global and gateway-specific headers are all preserved."""
        mock_settings.enable_header_passthrough = True
        # Cache already contains the merged global + gateway set
        mock_cache.get.return_value = frozenset(["X-Tenant-Id", "X-Custom-Auth"])

        headers = {"X-Tenant-Id": "acme", "X-Custom-Auth": "secret"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-tenant-id": "acme", "x-custom-auth": "secret"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_sanitizes_header_values(self, mock_settings):
        """Header values are sanitized (CRLF stripped) for defense-in-depth."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        headers = {"X-Upstream-Authorization": "Bearer tok\r\nInjected: header"}
        result = extract_headers_for_loopback(headers)

        value = result.get("x-upstream-authorization", "")
        assert "\r" not in value
        assert "\n" not in value

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_settings_error_still_forwards_upstream_auth(self, mock_settings):
        """If settings access fails, x-upstream-authorization is still forwarded."""
        type(mock_settings).enable_header_passthrough = property(lambda self: (_ for _ in ()).throw(RuntimeError("settings broken")))

        headers = {"X-Upstream-Authorization": "Bearer tok"}
        result = extract_headers_for_loopback(headers)

        assert result == {"x-upstream-authorization": "Bearer tok"}


# ---------------------------------------------------------------------------
# Tests for header override ordering in SSE generate_response
# ---------------------------------------------------------------------------
class TestSSEHeaderOverrideOrdering:
    """Verify passthrough headers cannot overwrite internal Authorization JWT."""

    @pytest.mark.asyncio
    @patch("mcpgateway.cache.session_registry.ResilientHttpClient")
    @patch("mcpgateway.cache.session_registry.settings")
    async def test_passthrough_cannot_overwrite_internal_jwt(self, mock_settings, mock_client_cls):
        """Even if _passthrough_headers contains Authorization (title-case), the internal JWT wins."""
        # First-Party
        from mcpgateway.cache.session_registry import SessionRegistry

        mock_settings.port = 8000
        mock_settings.federation_timeout = 30
        mock_settings.skip_ssl_verify = False
        mock_settings.mcpgateway_session_affinity_enabled = False
        mock_settings.jwt_issuer = "test"
        mock_settings.jwt_audience = "test"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        transport = MagicMock()
        transport.session_id = "test-session"
        transport.send_message = AsyncMock()

        # Adversarial: _passthrough_headers tries to inject Authorization
        user = {
            "email": "test@example.com",
            "auth_token": "internal-jwt-token",
            "is_admin": False,
            "_passthrough_headers": {
                "Authorization": "Bearer injected-token",
                "x-upstream-authorization": "Bearer upstream",
            },
        }

        registry = SessionRegistry()
        message = {"method": "tools/list", "params": {}, "id": 1}

        await registry.generate_response(message, transport, "server-1", user)

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        sent_headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})

        # Internal JWT must NOT be overwritten by the injected token.
        # Verify exactly one Authorization-cased key exists and it holds the internal JWT.
        auth_keys = [k for k in sent_headers if k.lower() == "authorization"]
        assert len(auth_keys) == 1, f"Expected exactly one Authorization key, found: {auth_keys}"
        assert sent_headers[auth_keys[0]] == "Bearer internal-jwt-token"
        assert sent_headers.get("x-upstream-authorization") == "Bearer upstream"


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

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_websocket_headers_with_passthrough_enabled(self, mock_settings, mock_cache, _mock_sl):
        """WebSocket headers with passthrough feature enabled."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["X-Tenant-Id"]
        mock_cache.get.return_value = frozenset(["X-Tenant-Id"])

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


# ---------------------------------------------------------------------------
# Tests for _LoopbackAllowlistCache
# ---------------------------------------------------------------------------
class TestLoopbackAllowlistCache:
    """Test TTL caching, invalidation, and DB refresh of _LoopbackAllowlistCache."""

    def _make_cache(self, ttl: float = 60.0):
        """Create a fresh cache instance."""
        # First-Party
        from mcpgateway.utils.passthrough_headers import _LoopbackAllowlistCache  # pylint: disable=import-outside-toplevel

        return _LoopbackAllowlistCache(ttl_seconds=ttl)

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_first_call_queries_db(self, mock_gcc):
        """First .get() call queries global config and gateway table."""
        mock_gcc.get_passthrough_headers.return_value = ["X-Tenant-Id"]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        cache = self._make_cache()
        result = cache.get(mock_db)

        assert result == frozenset(["X-Tenant-Id"])
        mock_gcc.get_passthrough_headers.assert_called_once()
        mock_db.query.assert_called_once()

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_second_call_uses_cache(self, mock_gcc):
        """Second .get() within TTL returns cached result without DB query."""
        mock_gcc.get_passthrough_headers.return_value = ["X-Tenant-Id"]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        cache = self._make_cache(ttl=300.0)
        first = cache.get(mock_db)
        second = cache.get(mock_db)

        assert first == second
        # DB should only be hit once
        assert mock_gcc.get_passthrough_headers.call_count == 1

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_merges_gateway_specific_headers(self, mock_gcc):
        """Cache merges global and gateway-specific passthrough headers."""
        mock_gcc.get_passthrough_headers.return_value = ["X-Tenant-Id"]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            (["X-Custom-Auth"],),
            (["X-Org-Id", "X-Tenant-Id"],),  # overlap with global
        ]

        cache = self._make_cache()
        result = cache.get(mock_db)

        assert result == frozenset(["X-Tenant-Id", "X-Custom-Auth", "X-Org-Id"])

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_invalidate_forces_refresh(self, mock_gcc):
        """invalidate() causes next .get() to re-query the DB."""
        mock_gcc.get_passthrough_headers.return_value = ["X-Tenant-Id"]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        cache = self._make_cache(ttl=300.0)
        cache.get(mock_db)
        assert mock_gcc.get_passthrough_headers.call_count == 1

        cache.invalidate()

        # After invalidation, next .get() should hit DB again
        mock_gcc.get_passthrough_headers.return_value = ["X-Tenant-Id", "X-New-Header"]
        cache.get(mock_db)
        assert mock_gcc.get_passthrough_headers.call_count == 2

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_ttl_expiry_triggers_refresh(self, mock_gcc):
        """Expired TTL causes .get() to re-query the DB."""
        mock_gcc.get_passthrough_headers.return_value = ["X-Tenant-Id"]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        # Use a TTL of 0 so it expires immediately
        cache = self._make_cache(ttl=0)
        cache.get(mock_db)
        cache.get(mock_db)

        # Both calls should have hit DB because TTL is 0
        assert mock_gcc.get_passthrough_headers.call_count == 2

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_handles_none_gateway_headers(self, mock_gcc):
        """Gateway rows with None passthrough_headers are skipped gracefully."""
        mock_gcc.get_passthrough_headers.return_value = ["X-Tenant-Id"]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            (None,),
            ([],),
            (["X-Custom"],),
        ]

        cache = self._make_cache()
        result = cache.get(mock_db)

        assert result == frozenset(["X-Tenant-Id", "X-Custom"])

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_returns_empty_frozenset_when_no_headers_configured(self, mock_gcc):
        """Returns empty frozenset when no headers are configured anywhere."""
        mock_gcc.get_passthrough_headers.return_value = []

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        cache = self._make_cache()
        result = cache.get(mock_db)

        assert result == frozenset()
        assert isinstance(result, frozenset)

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_stale_fallback_on_db_failure(self, mock_gcc):
        """On DB failure after successful population, returns stale cache and extends TTL."""
        mock_gcc.get_passthrough_headers.return_value = ["X-Tenant-Id"]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        cache = self._make_cache(ttl=0)  # Immediate expiry
        first = cache.get(mock_db)

        assert first == frozenset(["X-Tenant-Id"])

        # Simulate DB failure on next refresh
        mock_gcc.get_passthrough_headers.side_effect = Exception("DB down")

        second = cache.get(mock_db)

        # Stale value returned instead of raising
        assert second == first

    @patch("mcpgateway.utils.passthrough_headers.global_config_cache")
    def test_raises_on_db_failure_with_no_stale_cache(self, mock_gcc):
        """On DB failure with no prior cache, exception propagates."""
        mock_gcc.get_passthrough_headers.side_effect = Exception("DB down")

        mock_db = MagicMock()

        cache = self._make_cache()

        with pytest.raises(Exception, match="DB down"):
            cache.get(mock_db)


# ---------------------------------------------------------------------------
# Tests for _loopback_skip_set edge cases
# ---------------------------------------------------------------------------
class TestLoopbackSkipSet:
    """Test the _loopback_skip_set helper for proxy_user_header handling."""

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_returns_base_set_when_proxy_already_in_skip(self, mock_settings):
        """When proxy_user_header is already in the skip set, return the base frozenset."""
        # First-Party
        from mcpgateway.utils.passthrough_headers import _LOOPBACK_SKIP_HEADERS, _loopback_skip_set  # pylint: disable=import-outside-toplevel

        mock_settings.proxy_user_header = "Authorization"  # already in _LOOPBACK_SKIP_HEADERS
        result = _loopback_skip_set()

        assert result is _LOOPBACK_SKIP_HEADERS


# ---------------------------------------------------------------------------
# Tests for filter_loopback_skip_headers sanitization
# ---------------------------------------------------------------------------
class TestFilterLoopbackSkipHeadersSanitization:
    """Test that filter_loopback_skip_headers sanitizes values."""

    @patch("mcpgateway.utils.passthrough_headers.sanitize_header_value")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_drops_header_on_sanitization_failure(self, mock_settings, mock_sanitize):
        """Headers whose values fail sanitization are dropped with a warning."""
        mock_settings.proxy_user_header = "X-Authenticated-User"
        mock_sanitize.side_effect = ValueError("CRLF injection detected")

        result = filter_loopback_skip_headers({"x-tenant-id": "bad\r\nvalue"})

        assert not result

    @patch("mcpgateway.utils.passthrough_headers.sanitize_header_value")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_keeps_good_headers_drops_bad(self, mock_settings, mock_sanitize):
        """Good headers survive while bad ones are dropped."""
        mock_settings.proxy_user_header = "X-Authenticated-User"
        mock_sanitize.side_effect = lambda v: v if "\r" not in v else (_ for _ in ()).throw(ValueError("bad"))

        result = filter_loopback_skip_headers({"x-tenant-id": "clean", "x-other": "bad\r\n"})

        assert result == {"x-tenant-id": "clean"}
        assert "x-other" not in result


# ---------------------------------------------------------------------------
# Tests for extract_headers_for_loopback sanitization error paths
# ---------------------------------------------------------------------------
class TestExtractHeadersSanitizationErrors:
    """Test sanitization error handling in extract_headers_for_loopback."""

    @patch("mcpgateway.utils.passthrough_headers.sanitize_header_value")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_drops_upstream_auth_on_sanitization_failure(self, mock_settings, mock_sanitize):
        """x-upstream-authorization is dropped when sanitization fails."""
        mock_settings.enable_header_passthrough = False
        mock_sanitize.side_effect = ValueError("CRLF injection detected")

        result = extract_headers_for_loopback({"X-Upstream-Authorization": "Bearer bad\r\nEvil: header"})

        assert "x-upstream-authorization" not in result
        assert not result

    @patch("mcpgateway.db.SessionLocal")
    @patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache")
    @patch("mcpgateway.utils.passthrough_headers.sanitize_header_value")
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_skips_allowlist_header_on_sanitization_failure(self, mock_settings, mock_sanitize, mock_cache, _mock_sl):
        """Individual allowlist headers that fail sanitization are skipped."""
        mock_settings.enable_header_passthrough = True
        mock_cache.get.return_value = frozenset(["X-Tenant-Id"])
        mock_sanitize.side_effect = ValueError("CRLF injection")

        result = extract_headers_for_loopback({"X-Tenant-Id": "bad\r\nvalue"})

        assert "x-tenant-id" not in result


# ---------------------------------------------------------------------------
# Tests for safe_extract_headers_for_loopback
# ---------------------------------------------------------------------------
class TestSafeExtractHeadersForLoopback:
    """Test the safe wrapper around extract_headers_for_loopback."""

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_returns_headers_on_success(self, mock_settings):
        """Happy path: returns extracted headers."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []

        result = safe_extract_headers_for_loopback({"X-Upstream-Authorization": "Bearer tok"}, "SSE")

        assert result == {"x-upstream-authorization": "Bearer tok"}

    @patch("mcpgateway.utils.passthrough_headers.extract_headers_for_loopback")
    def test_returns_empty_on_failure(self, mock_extract):
        """Returns {} when extract_headers_for_loopback raises."""
        mock_extract.side_effect = RuntimeError("settings broken")

        result = safe_extract_headers_for_loopback({"X-Upstream-Authorization": "Bearer tok"}, "SSE")

        assert result == {}

    @patch("mcpgateway.utils.passthrough_headers.extract_headers_for_loopback")
    def test_returns_empty_on_failure_websocket(self, mock_extract):
        """Returns {} for WebSocket transport on failure."""
        mock_extract.side_effect = RuntimeError("config error")

        result = safe_extract_headers_for_loopback({"X-Upstream-Authorization": "Bearer tok"}, "WebSocket")

        assert result == {}


# ---------------------------------------------------------------------------
# Tests for safe_extract_and_filter_for_loopback
# ---------------------------------------------------------------------------
class TestSafeExtractAndFilterForLoopback:
    """Test the combined safe extract + filter helper."""

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_returns_filtered_headers_on_success(self, mock_settings):
        """Happy path: returns extracted and filtered headers."""
        mock_settings.enable_header_passthrough = False
        mock_settings.default_passthrough_headers = []
        mock_settings.proxy_user_header = "X-Authenticated-User"

        result = safe_extract_and_filter_for_loopback({"X-Upstream-Authorization": "Bearer tok", "Authorization": "Bearer gw"})

        assert result == {"x-upstream-authorization": "Bearer tok"}
        assert "authorization" not in result

    @patch("mcpgateway.utils.passthrough_headers.extract_headers_for_loopback")
    def test_returns_empty_on_extract_failure(self, mock_extract):
        """Returns {} when extract raises."""
        mock_extract.side_effect = RuntimeError("broken")

        result = safe_extract_and_filter_for_loopback({"X-Upstream-Authorization": "Bearer tok"})

        assert result == {}

    @patch("mcpgateway.utils.passthrough_headers.filter_loopback_skip_headers")
    @patch("mcpgateway.utils.passthrough_headers.extract_headers_for_loopback")
    def test_returns_empty_on_filter_failure(self, mock_extract, mock_filter):
        """Returns {} when filter raises."""
        mock_extract.return_value = {"x-upstream-authorization": "Bearer tok"}
        mock_filter.side_effect = RuntimeError("broken")

        result = safe_extract_and_filter_for_loopback({"X-Upstream-Authorization": "Bearer tok"})

        assert result == {}


# ---------------------------------------------------------------------------
# Tests for gateway service cache invalidation
# ---------------------------------------------------------------------------
class TestInvalidatePassthroughHeaderCaches:
    """Test the invalidate_passthrough_header_caches helper."""

    def test_invalidates_both_caches(self):
        """Both global config cache and loopback allowlist cache are invalidated."""
        # First-Party
        from mcpgateway.utils.passthrough_headers import invalidate_passthrough_header_caches  # pylint: disable=import-outside-toplevel

        with patch("mcpgateway.utils.passthrough_headers.global_config_cache") as mock_gcc, patch("mcpgateway.utils.passthrough_headers._loopback_allowlist_cache") as mock_lac:
            invalidate_passthrough_header_caches()

            mock_gcc.invalidate.assert_called_once()
            mock_lac.invalidate.assert_called_once()
