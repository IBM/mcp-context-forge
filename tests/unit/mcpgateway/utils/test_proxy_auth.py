# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_proxy_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for proxy authentication functionality.

Tests the new MCP_CLIENT_AUTH_ENABLED and proxy authentication features.
"""

# Standard
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
            jwt_secret_key = "test-secret"
            jwt_algorithm = "HS256"
            basic_auth_user = "admin"
            basic_auth_password = "password"
            auth_required = True
            mcp_client_auth_enabled = True
            trust_proxy_auth = False
            proxy_user_header = "X-Authenticated-User"
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

        with patch.object(vc, "settings", mock_settings):
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

        with patch.object(vc, "settings", mock_settings):
            # Should return anonymous and log warning (warning logged in config)
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_proxy_auth_with_header(self, mock_settings, mock_request):
        """Test proxy authentication with user header."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        with patch.object(vc, "settings", mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == {"sub": "proxy-user", "source": "proxy", "token": None}

    @pytest.mark.asyncio
    async def test_proxy_auth_without_header(self, mock_settings, mock_request):
        """Test proxy authentication without user header returns anonymous."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_request.headers = {}  # No proxy header

        with patch.object(vc, "settings", mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"

    @pytest.mark.asyncio
    async def test_custom_proxy_header(self, mock_settings, mock_request):
        """Test proxy authentication with custom header name."""
        mock_settings.mcp_client_auth_enabled = False
        mock_settings.trust_proxy_auth = True
        mock_settings.proxy_user_header = "X-Remote-User"
        mock_request.headers = {"X-Remote-User": "custom-user"}

        with patch.object(vc, "settings", mock_settings):
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
        with patch.object(vc, "settings", mock_settings):
            result = await vc.require_auth(mock_request, None, None)
            assert result == "anonymous"  # No token provided, auth not required

    @pytest.mark.asyncio
    async def test_backwards_compatibility(self, mock_settings, mock_request):
        """Test that existing AUTH_REQUIRED behavior is preserved."""
        mock_settings.mcp_client_auth_enabled = True  # Default
        mock_settings.auth_required = False

        with patch.object(vc, "settings", mock_settings):
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
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        # Create a valid JWT token
        token = jwt.encode({"sub": "jwt-user"}, mock_settings.jwt_secret_key, algorithm="HS256")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with patch.object(vc, "settings", mock_settings):
            # When MCP client auth is disabled, proxy takes precedence
            result = await vc.require_auth(mock_request, creds, None)
            assert result == {"sub": "proxy-user", "source": "proxy", "token": None}


class TestRBACProxyAuthentication:
    """Test cases for RBAC middleware proxy authentication functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing."""

        class MockSettings:
            jwt_secret_key = "test-secret"
            jwt_algorithm = "HS256"
            basic_auth_user = "admin"
            basic_auth_password = "password"
            auth_required = False
            mcp_client_auth_enabled = False
            trust_proxy_auth = True
            proxy_user_header = "X-Authenticated-User"
            require_token_expiration = False
            docs_allow_basic_auth = False
            platform_admin_email = "admin@example.com"
            app_root_path = ""

        return MockSettings()

    @pytest.fixture
    def mock_request(self):
        """Create a mock request object."""
        request = Mock(spec=Request)
        request.headers = {}
        request.cookies = {}
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.state = Mock()
        request.state.request_id = "test-request-id"
        request.state.team_id = None
        return request

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return Mock()

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_with_header(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware accepts proxy authentication with header."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        # Mock the database query to return None (user not found in DB)
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch.object(rbac, "settings", mock_settings):
            result = await rbac.get_current_user_with_permissions(mock_request, None, None, mock_db)
            assert result["email"] == "proxy-user"
            assert result["auth_method"] == "proxy"
            assert result["is_admin"] is False
            # Verify plugin context fields are included for cross-hook sharing
            assert "plugin_context_table" in result
            assert "plugin_global_context" in result

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_without_header(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware returns anonymous when no proxy header."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_request.headers = {}

        with patch.object(rbac, "settings", mock_settings):
            result = await rbac.get_current_user_with_permissions(mock_request, None, None, mock_db)
            assert result["email"] == "anonymous"
            assert result["auth_method"] == "anonymous"
            assert result["is_admin"] is False

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_disabled_without_trust(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware returns anonymous when proxy auth not trusted."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_settings.trust_proxy_auth = False
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        with patch.object(rbac, "settings", mock_settings):
            result = await rbac.get_current_user_with_permissions(mock_request, None, None, mock_db)
            assert result["email"] == "anonymous"
            assert result["auth_method"] == "anonymous"

    @pytest.mark.asyncio
    async def test_rbac_standard_jwt_when_mcp_auth_enabled(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware uses JWT when MCP client auth is enabled."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_settings.mcp_client_auth_enabled = True
        mock_settings.auth_required = False
        mock_request.headers = {"X-Authenticated-User": "proxy-user"}

        with patch.object(rbac, "settings", mock_settings):
            # Should ignore proxy header and use JWT flow (returns platform admin when auth not required)
            result = await rbac.get_current_user_with_permissions(mock_request, None, None, mock_db)
            assert result["email"] == mock_settings.platform_admin_email
            assert result["auth_method"] == "disabled"

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_preserves_plugin_context(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware preserves plugin context for cross-hook sharing."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_request.headers = {"X-Authenticated-User": "proxy-user"}
        # Simulate plugin context set by HttpAuthMiddleware
        mock_request.state.plugin_context_table = {"test_plugin": {"key": "value"}}
        mock_request.state.plugin_global_context = Mock()

        with patch.object(rbac, "settings", mock_settings):
            result = await rbac.get_current_user_with_permissions(mock_request, None, None, mock_db)
            # Verify plugin contexts are passed through for HTTP_AUTH_CHECK_PERMISSION hooks
            assert result["plugin_context_table"] == {"test_plugin": {"key": "value"}}
            assert result["plugin_global_context"] is not None

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_missing_header_returns_401_when_auth_required(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware returns 401 when proxy header missing and auth_required=true."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_settings.auth_required = True
        mock_request.headers = {}  # No proxy header

        with patch.object(rbac, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await rbac.get_current_user_with_permissions(mock_request, None, None, mock_db)
            assert exc_info.value.status_code == 401
            assert "Proxy authentication header required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_missing_header_redirects_browser_when_auth_required(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware redirects browser when proxy header missing and auth_required=true."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_settings.auth_required = True
        mock_request.headers = {"accept": "text/html"}  # Browser request, no proxy header

        with patch.object(rbac, "settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                await rbac.get_current_user_with_permissions(mock_request, None, None, mock_db)
            assert exc_info.value.status_code == 302
            assert "/admin/login" in exc_info.value.headers.get("Location", "")

    @pytest.mark.asyncio
    async def test_rbac_proxy_auth_looks_up_admin_status(self, mock_settings, mock_request, mock_db):
        """Test RBAC middleware looks up is_admin from database for proxy users."""
        # First-Party
        from mcpgateway.middleware import rbac

        mock_request.headers = {"X-Authenticated-User": "admin@example.com"}

        # Mock the platform_admin_email check
        mock_settings.platform_admin_email = "admin@example.com"

        with patch.object(rbac, "settings", mock_settings):
            result = await rbac.get_current_user_with_permissions(mock_request, None, None, mock_db)
            assert result["email"] == "admin@example.com"
            assert result["is_admin"] is True  # Matches platform_admin_email
            assert result["auth_method"] == "proxy"


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
        with patch("mcpgateway.main.settings") as mock_settings:
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
        token = jwt.encode({"sub": "test-user"}, "test-secret", algorithm="HS256")
        websocket.query_params = {"token": token}
        websocket.headers = {}
        websocket.accept = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=Exception("Test complete"))

        # Mock settings
        with patch("mcpgateway.main.settings") as mock_settings:
            mock_settings.mcp_client_auth_enabled = True
            mock_settings.auth_required = True
            mock_settings.port = 8000

            # Mock verify_jwt_token to succeed
            with patch("mcpgateway.main.verify_jwt_token", new=AsyncMock(return_value={"sub": "test-user"})):
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
        websocket.headers = {"X-Authenticated-User": "proxy-user"}
        websocket.accept = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=Exception("Test complete"))

        # Mock settings for proxy auth
        with patch("mcpgateway.main.settings") as mock_settings:
            mock_settings.mcp_client_auth_enabled = False
            mock_settings.trust_proxy_auth = True
            mock_settings.proxy_user_header = "X-Authenticated-User"
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
