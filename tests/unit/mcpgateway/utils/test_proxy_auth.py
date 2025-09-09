# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_proxy_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for proxy authentication functionality.

Tests the new MCP_CLIENT_AUTH_ENABLED and proxy authentication features.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
import pytest

# First-Party
from mcpgateway.utils import verify_credentials as vc


class TestProxyAuthentication:
    """Test cases for proxy authentication functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing."""
        class MockSettings:
            jwt_secret_key = 'test-secret'
            jwt_algorithm = 'HS256'
            basic_auth_user = 'admin'
            basic_auth_password = 'password'
            auth_required = True
            mcp_client_auth_enabled = True
            trust_proxy_auth = False
            proxy_user_header = 'X-Authenticated-User'
            require_token_expiration = False
            docs_allow_basic_auth = False

        return MockSettings()

    @pytest.fixture
    def mock_request(self):
        """Create a mock request object."""
        request = Mock(spec=Request)
        request.headers = {}
        request.cookies = {}  # Empty cookies dict, not Mock
        return request

    @pytest.mark.asyncio
    async def test_standard_jwt_auth_enabled(self, mock_settings, mock_request):
        """Test standard JWT authentication when MCP client auth is enabled."""
        mock_settings.mcp_client_auth_enabled = True
        mock_settings.auth_required = True

        with patch.object(vc, 'settings', mock_settings):
            # Test with no credentials should raise exception
            with pytest.raises(HTTPException) as exc_info:
                await vc.require_auth(mock_request, None, None)
            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "Not authenticated"

    @pytest.mark.asyncio
    async def test_proxy_auth_disabled_without_trust(self, mock_settings, mock_request):
        """Test that disabling MCP client auth without trust returns anonymous."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = False
        mock_settings.auth_required = True

        with patch.object(vc, 'settings', mock_settings):
            # Should return anonymous and log warning (warning logged in config)
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_proxy_auth_with_header(self, mock_settings, mock_request):
        """Test proxy authentication with user header."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_request.headers = {'X-Authenticated-User': 'proxy-user'}

        with patch.object(vc, 'settings', mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == {"sub": "proxy-user", "source": "proxy", "token": None}

    @pytest.mark.asyncio
    async def test_proxy_auth_without_header(self, mock_settings, mock_request):
        """Test proxy authentication without user header returns anonymous."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_request.headers = {}  # No proxy header

        with patch.object(vc, 'settings', mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_custom_proxy_header(self, mock_settings, mock_request):
        """Test proxy authentication with custom header name."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.proxy_user_header = 'X-Remote-User'
        mock_request.headers = {'X-Remote-User': 'custom-user'}

        with patch.object(vc, 'settings', mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == {"sub": "custom-user", "source": "proxy", "token": None}

    @pytest.mark.asyncio
    async def test_jwt_auth_with_proxy_enabled(self, mock_settings, mock_request):
        """Test that JWT auth still works when proxy auth is configured."""
        mock_settings.mcp_client_auth_enabled = True
        mock_settings.trust_proxy_auth = True
        mock_settings.auth_required = False  # Allow anonymous

        # Even with proxy trust enabled, if MCP client auth is enabled,
        # it should use standard JWT flow
        with patch.object(vc, 'settings', mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"  # No token provided, auth not required

    @pytest.mark.asyncio
    async def test_backwards_compatibility(self, mock_settings, mock_request):
        """Test that existing AUTH_REQUIRED behavior is preserved."""
        mock_settings.mcp_client_auth_enabled = True  # Default
        mock_settings.auth_required = False

        with patch.object(vc, 'settings', mock_settings):
            # Should return anonymous when auth not required
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_mixed_auth_scenario(self, mock_settings, mock_request):
        """Test scenario with both proxy header and JWT token."""
        # Third-Party
        import jwt

        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_request.headers = {'X-Authenticated-User': 'proxy-user'}

        # Create a valid JWT token
        token = jwt.encode({'sub': 'jwt-user'}, mock_settings.jwt_secret_key, algorithm='HS256')
        creds = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)

        with patch.object(vc, 'settings', mock_settings):
            # When MCP client auth is disabled, proxy takes precedence
            result = await vc.require_auth(mock_request, creds, None)
            assert result == {"sub": "proxy-user", "source": "proxy", "token": None}


class TestWebSocketAuthentication:
    """Test cases for WebSocket authentication."""

    @pytest.mark.asyncio
    async def test_websocket_auth_required(self):
        """Test that WebSocket requires authentication when enabled."""
        # Standard
        from unittest.mock import AsyncMock

        # Third-Party
        from fastapi import WebSocket

        # Create mock WebSocket
        websocket = AsyncMock(spec=WebSocket)
        websocket.query_params = {}
        websocket.headers = {}
        websocket.close = AsyncMock()

        # Mock settings with auth required
        with patch('mcpgateway.main.settings') as mock_settings:
            mock_settings.mcp_client_auth_enabled = True
            mock_settings.auth_required = True
            mock_settings.trust_proxy_auth = False

            # Import and call the websocket_endpoint function
            # First-Party
            from mcpgateway.main import websocket_endpoint

            # Should close connection due to missing auth
            await websocket_endpoint(websocket)
            websocket.close.assert_called_once_with(code=1008, reason="Authentication required")

    @pytest.mark.asyncio
    async def test_websocket_with_token_query_param(self):
        """Test WebSocket authentication with token in query parameters."""
        # Standard
        from unittest.mock import AsyncMock

        # Third-Party
        from fastapi import WebSocket
        import jwt

        # Create mock WebSocket
        websocket = AsyncMock(spec=WebSocket)
        token = jwt.encode({'sub': 'test-user'}, 'test-secret', algorithm='HS256')
        websocket.query_params = {"token": token}
        websocket.headers = {}
        websocket.accept = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=Exception("Test complete"))

        # Mock settings
        with patch('mcpgateway.main.settings') as mock_settings:
            mock_settings.mcp_client_auth_enabled = True
            mock_settings.auth_required = True
            mock_settings.port = 8000

            # Mock verify_jwt_token to succeed
            with patch('mcpgateway.main.verify_jwt_token', new=AsyncMock(return_value={'sub': 'test-user'})):
                # First-Party
                from mcpgateway.main import websocket_endpoint

                try:
                    await websocket_endpoint(websocket)
                except Exception as e:
                    if str(e) != "Test complete":
                        raise

                # Should accept connection
                websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_with_proxy_auth(self):
        """Test WebSocket authentication with proxy headers."""
        # Standard
        from unittest.mock import AsyncMock

        # Third-Party
        from fastapi import WebSocket

        # Create mock WebSocket
        websocket = AsyncMock(spec=WebSocket)
        websocket.query_params = {}
        websocket.headers = {'X-Authenticated-User': 'proxy-user'}
        websocket.accept = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=Exception("Test complete"))

        # Mock settings for proxy auth
        with patch('mcpgateway.main.settings') as mock_settings:
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.proxy_user_header = 'X-Authenticated-User'
            mock_settings.auth_required = False
            mock_settings.port = 8000

            # First-Party
            from mcpgateway.main import websocket_endpoint

            try:
                await websocket_endpoint(websocket)
            except Exception as e:
                if str(e) != "Test complete":
                    raise

            # Should accept connection with proxy auth
            websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_streamable_http_auth_with_proxy_header(self):
        """streamable_http_auth should allow request when proxy header present and auth disabled."""
        # from types import SimpleNamespace
        # from starlette.datastructures import Headers
        from mcpgateway.transports.streamablehttp_transport import streamable_http_auth

        # Build ASGI scope
        scope = {
            "type": "http",
            "path": "/servers/123/mcp",
            "headers": [(b"x-authenticated-user", b"proxy-user")],
        }
        # Patch settings dynamically
        with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.proxy_user_header = "X-Authenticated-User"
            mock_settings.jwt_secret_key = "secret"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_required = False

            allowed = await streamable_http_auth(scope, AsyncMock(), AsyncMock())
            assert allowed is True

    @pytest.mark.asyncio
    async def test_streamable_http_auth_no_header_denied_when_required(self):
        """Should deny when proxy header missing and auth_required true."""
        from mcpgateway.transports.streamablehttp_transport import streamable_http_auth
        scope = {
            "type": "http",
            "path": "/servers/123/mcp",
            "headers": [],
        }
        with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.proxy_user_header = "X-Authenticated-User"
            mock_settings.jwt_secret_key = "secret"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_required = True
            send = AsyncMock()
            ok = await streamable_http_auth(scope, AsyncMock(), send)
            # When denied, function returns False and send called with 401 response
            assert ok is False
            assert any(isinstance(call.args[0], dict) and call.args[0].get("status") == 401 for call in send.mock_calls)
