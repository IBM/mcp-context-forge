# -*- coding: utf-8 -*-
"""Tests for configurable JWT authentication header feature.

This module tests the AUTH_HEADER_NAME configuration that allows ContextForge
to use alternative HTTP headers for JWT authentication (e.g., X-MCP-Gateway-Auth)
instead of the standard Authorization header, avoiding collisions with downstream
server authentication.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException
from starlette.requests import Request

# First-Party
from mcpgateway.auth import ConfigurableHTTPBearer
from mcpgateway.config import Settings, settings
from mcpgateway.utils.verify_credentials import (
    _resolve_auth_header_name,
    get_auth_bearer_token_from_request,
    get_auth_header_value,
)


class TestConfigurableHTTPBearer:
    """Test suite for ConfigurableHTTPBearer class."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock request object."""
        request = MagicMock(spec=Request)
        request.headers = {}
        return request

    @pytest.mark.asyncio
    async def test_default_authorization_header(self, mock_request):
        """Test that default Authorization header is used when not configured."""
        with patch.object(settings, "auth_header_name", "Authorization"):
            bearer = ConfigurableHTTPBearer(auto_error=False)
            mock_request.headers = {"authorization": "Bearer test-token-123"}

            result = await bearer(mock_request)

            assert result is not None
            assert result.scheme == "Bearer"
            assert result.credentials == "test-token-123"

    @pytest.mark.asyncio
    async def test_custom_auth_header(self, mock_request):
        """Test that custom authentication header is used when configured."""
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            bearer = ConfigurableHTTPBearer(auto_error=False)
            mock_request.headers = {"x-mcp-gateway-auth": "Bearer custom-token-456"}

            result = await bearer(mock_request)

            assert result is not None
            assert result.scheme == "Bearer"
            assert result.credentials == "custom-token-456"

    @pytest.mark.asyncio
    async def test_missing_credentials_no_auto_error(self, mock_request):
        """Test that None is returned when credentials are missing and auto_error=False."""
        with patch.object(settings, "auth_header_name", "Authorization"):
            bearer = ConfigurableHTTPBearer(auto_error=False)
            mock_request.headers = {}

            result = await bearer(mock_request)

            assert result is None

    @pytest.mark.asyncio
    async def test_missing_credentials_with_auto_error(self, mock_request):
        """Test that HTTPException is raised when credentials are missing and auto_error=True."""
        with patch.object(settings, "auth_header_name", "Authorization"):
            bearer = ConfigurableHTTPBearer(auto_error=True)
            mock_request.headers = {}

            with pytest.raises(HTTPException) as exc_info:
                await bearer(mock_request)

            assert exc_info.value.status_code == 403
            assert "Not authenticated" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_scheme(self, mock_request):
        """Test that invalid authentication scheme is rejected."""
        with patch.object(settings, "auth_header_name", "Authorization"):
            bearer = ConfigurableHTTPBearer(auto_error=True)
            mock_request.headers = {"authorization": "Basic dXNlcjpwYXNz"}

            with pytest.raises(HTTPException) as exc_info:
                await bearer(mock_request)

            assert exc_info.value.status_code == 403
            assert "Invalid authentication credentials" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_case_insensitive_header_lookup(self, mock_request):
        """Test that header lookup is case-insensitive."""
        with patch.object(settings, "auth_header_name", "X-Custom-Auth"):
            bearer = ConfigurableHTTPBearer(auto_error=False)
            # Header name in different case
            mock_request.headers = {"x-custom-auth": "Bearer token-789"}

            result = await bearer(mock_request)

            assert result is not None
            assert result.credentials == "token-789"

    @pytest.mark.asyncio
    async def test_authorization_passthrough_with_custom_header(self, mock_request):
        """Test that Authorization header is preserved when using custom auth header."""
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            bearer = ConfigurableHTTPBearer(auto_error=False)
            # Both headers present - custom for gateway auth, Authorization for downstream
            mock_request.headers = {
                "x-mcp-gateway-auth": "Bearer gateway-token",
                "authorization": "Bearer downstream-token",
            }

            result = await bearer(mock_request)

            # Should extract from custom header
            assert result is not None
            assert result.credentials == "gateway-token"
            # Authorization header should still be present in request
            assert "authorization" in mock_request.headers
            assert mock_request.headers["authorization"] == "Bearer downstream-token"


class TestWebSocketTokenExtraction:
    """Test suite for WebSocket token extraction with custom header."""

    def test_extract_from_custom_header(self):
        """Test extracting token from custom WebSocket header."""
        from mcpgateway.utils.verify_credentials import extract_websocket_bearer_token

        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            headers = {"x-mcp-gateway-auth": "Bearer ws-token-123"}
            token = extract_websocket_bearer_token(None, headers)

            assert token == "ws-token-123"

    def test_extract_from_default_header(self):
        """Test extracting token from default Authorization header."""
        from mcpgateway.utils.verify_credentials import extract_websocket_bearer_token

        with patch.object(settings, "auth_header_name", "Authorization"):
            headers = {"authorization": "Bearer default-token-456"}
            token = extract_websocket_bearer_token(None, headers)

            assert token == "default-token-456"

    def test_case_insensitive_extraction(self):
        """Test case-insensitive header extraction."""
        from mcpgateway.utils.verify_credentials import extract_websocket_bearer_token

        with patch.object(settings, "auth_header_name", "X-Custom-Auth"):
            # Mixed case header
            headers = {"X-Custom-Auth": "Bearer mixed-case-token"}
            token = extract_websocket_bearer_token(None, headers)

            assert token == "mixed-case-token"


class TestSharedAuthHelpers:
    """Tests for the shared header-extraction helpers used by every auth path."""

    def test_resolve_auth_header_name_default(self):
        """Missing/None setting falls back to ``Authorization``."""
        with patch.object(settings, "auth_header_name", "Authorization"):
            assert _resolve_auth_header_name() == "Authorization"

    def test_resolve_auth_header_name_strips_whitespace(self):
        """Whitespace is stripped; empty values fall back to default."""
        with patch.object(settings, "auth_header_name", "   "):
            assert _resolve_auth_header_name() == "Authorization"

    def test_resolve_auth_header_name_handles_non_string(self):
        """Non-string mocked settings fall back to default rather than raising."""
        with patch.object(settings, "auth_header_name", MagicMock()):
            assert _resolve_auth_header_name() == "Authorization"

    def test_get_auth_header_value_lowercase_lookup(self):
        """Starlette-normalized lowercase headers resolve correctly."""
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            assert get_auth_header_value({"x-mcp-gateway-auth": "Bearer t"}) == "Bearer t"

    def test_get_auth_header_value_case_preserving_dict(self):
        """Plain dict with original casing also resolves."""
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            assert get_auth_header_value({"X-MCP-Gateway-Auth": "Bearer t"}) == "Bearer t"

    def test_get_auth_header_value_missing(self):
        """Returns None when the header is absent."""
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            assert get_auth_header_value({"authorization": "Bearer downstream"}) is None

    def test_get_auth_bearer_token_from_request(self):
        """Extracts bearer token from configured header on a request-like object."""
        request = MagicMock(spec=Request)
        request.headers = {"x-mcp-gateway-auth": "Bearer gw-token"}
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            assert get_auth_bearer_token_from_request(request) == "gw-token"

    def test_get_auth_bearer_token_rejects_non_bearer(self):
        """Non-Bearer schemes return None even when the configured header is present."""
        request = MagicMock(spec=Request)
        request.headers = {"x-mcp-gateway-auth": "Basic dXNlcjpwYXNz"}
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            assert get_auth_bearer_token_from_request(request) is None

    def test_get_auth_bearer_token_case_insensitive_scheme(self):
        """Bearer scheme is matched case-insensitively (matches ConfigurableHTTPBearer)."""
        request = MagicMock(spec=Request)
        request.headers = {"x-mcp-gateway-auth": "BEARER tok"}
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            assert get_auth_bearer_token_from_request(request) == "tok"

    def test_gateway_token_not_extracted_from_authorization_when_custom_set(self):
        """Critical: a downstream-bound Authorization header must NOT be read as the gateway token."""
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer downstream-token"}
        with patch.object(settings, "auth_header_name", "X-MCP-Gateway-Auth"):
            assert get_auth_bearer_token_from_request(request) is None
            assert get_auth_header_value(request.headers) is None


class TestAuthHeaderNameValidator:
    """Tests for the Pydantic validator on Settings.auth_header_name."""

    def test_default_value(self):
        """Default value passes validation."""
        s = Settings(auth_header_name="Authorization")
        assert s.auth_header_name == "Authorization"

    def test_custom_token_accepted(self):
        """A standard custom header token is accepted."""
        s = Settings(auth_header_name="X-MCP-Gateway-Auth")
        assert s.auth_header_name == "X-MCP-Gateway-Auth"

    def test_strips_whitespace(self):
        """Surrounding whitespace is stripped."""
        s = Settings(auth_header_name="  X-Custom-Auth  ")
        assert s.auth_header_name == "X-Custom-Auth"

    def test_empty_falls_back_to_default(self):
        """Empty/whitespace-only values fall back to ``Authorization`` rather than failing."""
        s = Settings(auth_header_name="   ")
        assert s.auth_header_name == "Authorization"

    @pytest.mark.parametrize(
        "bad_value",
        [
            "X Bad Header",  # contains space
            "X-Bad\r\nInjected",  # CRLF injection attempt
            "X-Bad\x00",  # NUL byte
            "X-Bad:Header",  # colon (separator)
            "X-Bad/Header",  # slash (separator)
        ],
    )
    def test_rejects_invalid_token_chars(self, bad_value):
        """Header-injection / RFC 7230 violations are rejected at config time."""
        with pytest.raises(ValueError):
            Settings(auth_header_name=bad_value)


class TestLoopbackSkipSet:
    """Regression tests for the passthrough loopback skip set.

    The configured AUTH_HEADER_NAME must always be in the skip set so that a
    client-supplied passthrough header can never overwrite the gateway-internal
    JWT on the loopback /rpc call.
    """

    def test_default_authorization_in_skip_set(self):
        """The default Authorization header is in the loopback skip set."""
        from mcpgateway.utils.passthrough_headers import _loopback_skip_set

        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
            mock_settings.proxy_user_header = "X-Authenticated-User"
            mock_settings.auth_header_name = "Authorization"
            assert "authorization" in _loopback_skip_set()

    def test_custom_auth_header_in_skip_set(self):
        """A customized AUTH_HEADER_NAME is added to the loopback skip set."""
        from mcpgateway.utils.passthrough_headers import _loopback_skip_set

        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
            mock_settings.proxy_user_header = "X-Authenticated-User"
            mock_settings.auth_header_name = "X-MCP-Gateway-Auth"
            skip = _loopback_skip_set()
            assert "x-mcp-gateway-auth" in skip
            assert "authorization" in skip

    def test_skip_set_handles_non_string_setting(self):
        """Non-string mocked setting falls back gracefully (no crash)."""
        from mcpgateway.utils.passthrough_headers import _loopback_skip_set

        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
            mock_settings.proxy_user_header = "X-Authenticated-User"
            mock_settings.auth_header_name = MagicMock()
            assert "authorization" in _loopback_skip_set()


class TestPluginAuthHeaderProtection:
    """Tests for the plugin pre-request hook auth-header protection guard."""

    @pytest.mark.asyncio
    async def test_authorization_protected_when_custom_auth_header_set(self):
        """A plugin must NOT be able to override a client-supplied Authorization header
        even when AUTH_HEADER_NAME is customized — preserves the threat model.
        """
        from mcpgateway.middleware.http_auth_middleware import run_pre_request_hooks

        plugin_manager = MagicMock()
        plugin_manager.has_hooks_for.return_value = True

        modified_payload = MagicMock()
        modified_payload.root = {
            "authorization": "Bearer EVIL-PLUGIN-TOKEN",
            "x-mcp-gateway-auth": "Bearer EVIL-GATEWAY-TOKEN",
            "x-trace-id": "abc",
        }
        pre_result = MagicMock()
        pre_result.modified_payload = modified_payload

        async def _invoke_hook(*args, **kwargs):
            return pre_result, None

        plugin_manager.invoke_hook = _invoke_hook
        from cpex.framework import HttpHookType as _Hook

        plugin_manager.has_hooks_for = lambda hook_type: hook_type == _Hook.HTTP_PRE_REQUEST

        original_headers = {
            "authorization": "Bearer CLIENT-DOWNSTREAM-TOKEN",
            "x-mcp-gateway-auth": "Bearer CLIENT-GATEWAY-TOKEN",
        }

        with patch("mcpgateway.middleware.http_auth_middleware.settings") as mock_settings:
            mock_settings.plugins_can_override_auth_headers = False
            mock_settings.auth_header_name = "X-MCP-Gateway-Auth"

            merged, _, _ = await run_pre_request_hooks(
                plugin_manager=plugin_manager,
                headers=original_headers,
                path="/mcp",
                method="POST",
            )

        # Both headers must be stripped from the plugin's modified payload — the client values must remain.
        assert merged["authorization"] == "Bearer CLIENT-DOWNSTREAM-TOKEN"
        assert merged["x-mcp-gateway-auth"] == "Bearer CLIENT-GATEWAY-TOKEN"
        # Non-auth headers from the plugin should still be merged
        assert merged.get("x-trace-id") == "abc"
