# -*- coding: utf-8 -*-
"""Tests for configurable JWT authentication header feature.

This module tests the AUTH_HEADER_NAME configuration that allows ContextForge
to use alternative HTTP headers for JWT authentication (e.g., X-MCP-Gateway-Auth)
instead of the standard Authorization header, avoiding collisions with downstream
server authentication.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException
from starlette.requests import Request

# First-Party
from mcpgateway.auth import ConfigurableHTTPBearer
from mcpgateway.config import settings


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
