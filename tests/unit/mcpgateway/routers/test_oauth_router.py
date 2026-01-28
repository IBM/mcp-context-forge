# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_oauth_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for OAuth router.
This module tests OAuth endpoints including authorization flow, callbacks, and status endpoints.
"""

# Standard
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway
from mcpgateway.schemas import EmailUserResponse
from mcpgateway.services.oauth_manager import OAuthError


class TestOAuthRouter:
    """Test cases for OAuth router endpoints."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = Mock(spec=Session)
        return db

    @pytest.fixture
    def mock_request(self):
        """Create mock FastAPI request."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.scheme = "https"
        request.url.netloc = "gateway.example.com"
        request.scope = {"root_path": ""}
        return request

    @pytest.fixture
    def mock_gateway(self):
        """Create mock gateway with OAuth config."""
        gateway = Mock(spec=Gateway)
        gateway.id = "gateway123"
        gateway.name = "Test Gateway"
        gateway.url = "https://mcp.example.com"  # MCP server URL
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test_client",
            "client_secret": "test_secret",
            "authorization_url": "https://oauth.example.com/authorize",
            "token_url": "https://oauth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "scopes": ["read", "write"],
        }
        return gateway

    @pytest.fixture
    def mock_current_user(self):
        """Create mock current user."""
        user = Mock(spec=EmailUserResponse)
        user.get = Mock(return_value="test@example.com")
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_active = True
        user.is_admin = False
        return user

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_success(self, mock_db, mock_request, mock_gateway, mock_current_user):
        """Test successful OAuth flow initiation."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://oauth.example.com/authorize?client_id=test_client&response_type=code&state=gateway123_abc123", "state": "gateway123_abc123"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService") as mock_token_storage_class:
                mock_token_storage = Mock()
                mock_token_storage_class.return_value = mock_token_storage

                # Import the function to test
                # First-Party
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                # Execute
                result = await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

                # Assert
                assert isinstance(result, RedirectResponse)
                assert result.status_code == 307  # Temporary redirect
                assert result.headers["location"] == auth_data["authorization_url"]

                mock_oauth_manager_class.assert_called_once_with(token_storage=mock_token_storage)

                # Verify the oauth_config includes the resource parameter (RFC 8707)
                call_args = mock_oauth_manager.initiate_authorization_code_flow.call_args
                assert call_args[0][0] == "gateway123"
                assert call_args[1]["app_user_email"] == mock_current_user.get("email")
                # oauth_config should have resource set to gateway.url
                oauth_config_passed = call_args[0][1]
                assert oauth_config_passed["resource"] == mock_gateway.url

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_gateway_not_found(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow initiation with non-existent gateway."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # First-Party
        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        # Execute & Assert
        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("nonexistent", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 404
        assert "Gateway not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_no_oauth_config(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow initiation with gateway that has no OAuth config."""
        # Setup
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.oauth_config = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        # Execute & Assert
        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Gateway is not configured for OAuth" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_wrong_grant_type(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow initiation with wrong grant type."""
        # Setup
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.oauth_config = {"grant_type": "client_credentials"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        # Execute & Assert
        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Gateway is not configured for Authorization Code flow" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_oauth_manager_error(self, mock_db, mock_request, mock_gateway, mock_current_user):
        """Test OAuth flow initiation when OAuth manager throws error."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(side_effect=OAuthError("OAuth service unavailable"))
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # First-Party
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                # Execute & Assert
                with pytest.raises(HTTPException) as exc_info:
                    await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

                assert exc_info.value.status_code == 500
                assert "Failed to initiate OAuth flow" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_oauth_callback_success(self, mock_db, mock_request, mock_gateway):
        """Test successful OAuth callback handling."""
        # Standard
        import base64
        import json

        # Setup state with new format (payload + 32-byte signature)
        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com", "nonce": "abc123"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32  # Mock 32-byte signature
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        token_result = {"user_id": "oauth_user_123", "app_user_email": "test@example.com", "expires_at": "2024-01-01T12:00:00"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # First-Party
                from mcpgateway.routers.oauth_router import oauth_callback

                # Execute
                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

                # Assert
                assert isinstance(result, HTMLResponse)
                assert "✅ OAuth Authorization Successful" in result.body.decode()
                assert "oauth_user_123" in result.body.decode()

                # Verify the oauth_config includes the resource parameter (RFC 8707)
                call_args = mock_oauth_manager.complete_authorization_code_flow.call_args
                oauth_config_passed = call_args[0][3]  # 4th positional arg is credentials
                assert oauth_config_passed["resource"] == "https://mcp.example.com"  # Normalized URL

    @pytest.mark.asyncio
    async def test_oauth_callback_legacy_state_format(self, mock_db, mock_request, mock_gateway):
        """Test OAuth callback handling with legacy state format."""
        # Setup - legacy state format
        state = "gateway123_abc123"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        token_result = {"user_id": "oauth_user_123", "app_user_email": "test@example.com", "expires_at": "2024-01-01T12:00:00"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # First-Party
                from mcpgateway.routers.oauth_router import oauth_callback

                # Execute
                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

                # Assert
                assert isinstance(result, HTMLResponse)
                assert "✅ OAuth Authorization Successful" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_invalid_state(self, mock_db, mock_request):
        """Test OAuth callback with invalid state parameter."""
        # First-Party
        from mcpgateway.routers.oauth_router import oauth_callback

        # Execute
        result = await oauth_callback(code="auth_code_123", state="invalid", request=mock_request, db=mock_db)

        # Assert
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Invalid state parameter" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_state_too_short(self, mock_db, mock_request):
        """Test OAuth callback with state that's too short to contain signature."""
        # Standard
        import base64

        # Setup - create state with less than 32 bytes total
        short_payload = b"short"
        state = base64.urlsafe_b64encode(short_payload).decode()

        # First-Party
        from mcpgateway.routers.oauth_router import oauth_callback

        # Execute
        result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        # Assert
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Invalid state parameter" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_gateway_not_found(self, mock_db, mock_request):
        """Test OAuth callback when gateway is not found."""
        # Standard
        import base64
        import json

        # Setup
        state_data = {"gateway_id": "nonexistent", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32  # Mock 32-byte signature
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # First-Party
        from mcpgateway.routers.oauth_router import oauth_callback

        # Execute
        result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        # Assert
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 404
        assert "Gateway not found" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_no_oauth_config(self, mock_db, mock_request):
        """Test OAuth callback when gateway has no OAuth config."""
        # Standard
        import base64
        import json

        # Setup
        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32  # Mock 32-byte signature
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.oauth_config = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import oauth_callback

        # Execute
        result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        # Assert
        assert isinstance(result, HTMLResponse)
        assert result.status_code == 400
        assert "Gateway has no OAuth configuration" in result.body.decode()

    @pytest.mark.asyncio
    async def test_oauth_callback_oauth_error(self, mock_db, mock_request, mock_gateway):
        """Test OAuth callback when OAuth manager throws OAuthError."""
        # Standard
        import base64
        import json

        # Setup
        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32  # Mock 32-byte signature
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(side_effect=OAuthError("Invalid authorization code"))
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                # First-Party
                from mcpgateway.routers.oauth_router import oauth_callback

                # Execute
                result = await oauth_callback(code="invalid_code", state=state, request=mock_request, db=mock_db)

                # Assert
                assert isinstance(result, HTMLResponse)
                assert result.status_code == 400
                assert "❌ OAuth Authorization Failed" in result.body.decode()
                assert "Invalid authorization code" in result.body.decode()

    @pytest.mark.asyncio
    async def test_get_oauth_status_success(self, mock_db, mock_gateway):
        """Test successful OAuth status retrieval."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import get_oauth_status

        # Execute
        result = await get_oauth_status("gateway123", mock_db)

        # Assert
        assert result["oauth_enabled"] is True
        assert result["grant_type"] == "authorization_code"
        assert result["client_id"] == "test_client"
        assert result["scopes"] == ["read", "write"]

    @pytest.mark.asyncio
    async def test_get_oauth_status_no_oauth_config(self, mock_db):
        """Test OAuth status when gateway has no OAuth config."""
        # Setup
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.oauth_config = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import get_oauth_status

        # Execute
        result = await get_oauth_status("gateway123", mock_db)

        # Assert
        assert result["oauth_enabled"] is False
        assert "Gateway is not configured for OAuth" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_success(self, mock_db, mock_current_user):
        """Test successful tools fetching after OAuth."""
        # Setup
        mock_tools_result = {"tools": [{"name": "tool1", "description": "Test tool 1"}, {"name": "tool2", "description": "Test tool 2"}, {"name": "tool3", "description": "Test tool 3"}]}

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(return_value=mock_tools_result)
            mock_gateway_service_class.return_value = mock_gateway_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            # Execute
            result = await fetch_tools_after_oauth("gateway123", mock_current_user, mock_db)

            # Assert
            assert result["success"] is True
            assert "Successfully fetched and created 3 tools" in result["message"]
            mock_gateway_service.fetch_tools_after_oauth.assert_called_once_with(mock_db, "gateway123", mock_current_user.get("email"))

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_no_tools(self, mock_db, mock_current_user):
        """Test tools fetching after OAuth when no tools are returned."""
        # Setup
        mock_tools_result = {"tools": []}

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(return_value=mock_tools_result)
            mock_gateway_service_class.return_value = mock_gateway_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            # Execute
            result = await fetch_tools_after_oauth("gateway123", mock_current_user, mock_db)

            # Assert
            assert result["success"] is True
            assert "Successfully fetched and created 0 tools" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_service_error(self, mock_db, mock_current_user):
        """Test tools fetching when GatewayService throws error."""
        # Setup
        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(side_effect=Exception("Failed to connect to MCP server"))
            mock_gateway_service_class.return_value = mock_gateway_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            # Execute & Assert
            with pytest.raises(HTTPException) as exc_info:
                await fetch_tools_after_oauth("gateway123", mock_current_user, mock_db)

            assert exc_info.value.status_code == 500
            assert "Failed to fetch tools" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_malformed_result(self, mock_db, mock_current_user):
        """Test tools fetching when service returns malformed result."""
        # Setup
        mock_tools_result = {"message": "Success"}  # Missing "tools" key

        with patch("mcpgateway.services.gateway_service.GatewayService") as mock_gateway_service_class:
            mock_gateway_service = Mock()
            mock_gateway_service.fetch_tools_after_oauth = AsyncMock(return_value=mock_tools_result)
            mock_gateway_service_class.return_value = mock_gateway_service

            # First-Party
            from mcpgateway.routers.oauth_router import fetch_tools_after_oauth

            # Execute
            result = await fetch_tools_after_oauth("gateway123", mock_current_user, mock_db)

            # Assert
            assert result["success"] is True
            assert "Successfully fetched and created 0 tools" in result["message"]


class TestRFC8707ResourceNormalization:
    """Test cases for RFC 8707 resource URL normalization."""

    def test_normalize_resource_url_removes_fragment(self):
        """Test that URL fragments are removed per RFC 8707."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        url = "https://mcp.example.com/api#section"
        assert _normalize_resource_url(url) == "https://mcp.example.com/api"

    def test_normalize_resource_url_removes_query(self):
        """Test that URL query strings are removed per RFC 8707."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        url = "https://mcp.example.com/api?token=abc"
        assert _normalize_resource_url(url) == "https://mcp.example.com/api"

    def test_normalize_resource_url_removes_both(self):
        """Test that both fragment and query are removed."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        url = "https://mcp.example.com/api?token=abc#section"
        assert _normalize_resource_url(url) == "https://mcp.example.com/api"

    def test_normalize_resource_url_clean_url_unchanged(self):
        """Test that clean URLs remain unchanged."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        url = "https://mcp.example.com/api"
        assert _normalize_resource_url(url) == "https://mcp.example.com/api"

    def test_normalize_resource_url_preserves_path(self):
        """Test that URL paths are preserved."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        url = "https://mcp.example.com/api/v1/tools"
        assert _normalize_resource_url(url) == "https://mcp.example.com/api/v1/tools"

    def test_normalize_resource_url_handles_empty(self):
        """Test that empty/None URLs return None."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        assert _normalize_resource_url("") is None
        assert _normalize_resource_url(None) is None

    def test_normalize_resource_url_rejects_relative_uri(self):
        """Test that relative URIs (no scheme) return None per RFC 8707."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        # RFC 8707: resource MUST be an absolute URI
        assert _normalize_resource_url("mcp.example.com/api") is None
        assert _normalize_resource_url("/api/v1") is None

    def test_normalize_resource_url_supports_urns(self):
        """Test that URN-style absolute URIs are supported per RFC 8707."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        # RFC 8707 allows any absolute URI, including URNs
        assert _normalize_resource_url("urn:example:app") == "urn:example:app"
        assert _normalize_resource_url("urn:ietf:params:oauth:token-type:jwt") == "urn:ietf:params:oauth:token-type:jwt"

    def test_normalize_resource_url_supports_file_uri(self):
        """Test that file:// URIs are supported."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        assert _normalize_resource_url("file:///path/to/resource") == "file:///path/to/resource"

    def test_normalize_resource_url_preserve_query_flag(self):
        """Test that preserve_query=True keeps query component."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        url = "https://api.example.com/v1?tenant=acme"
        # Default: strip query
        assert _normalize_resource_url(url) == "https://api.example.com/v1"
        # With preserve_query: keep query
        assert _normalize_resource_url(url, preserve_query=True) == "https://api.example.com/v1?tenant=acme"

    def test_normalize_resource_url_always_strips_fragment(self):
        """Test that fragments are always stripped even with preserve_query=True."""
        # First-Party
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        url = "https://api.example.com/v1?tenant=acme#section"
        # Fragment is always removed (RFC 8707 MUST NOT)
        assert _normalize_resource_url(url, preserve_query=True) == "https://api.example.com/v1?tenant=acme"
