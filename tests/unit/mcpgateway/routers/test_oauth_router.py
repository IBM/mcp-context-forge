# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_oauth_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for OAuth router.
This module tests OAuth endpoints including authorization flow, callbacks, and status endpoints.
"""

# Standard
from datetime import datetime, timezone
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


@pytest.fixture
def mock_db():
    """Create mock database session."""
    db = Mock(spec=Session)
    return db


@pytest.fixture
def mock_request():
    """Create mock FastAPI request."""
    request = Mock(spec=Request)
    request.url = Mock()
    request.url.scheme = "https"
    request.url.netloc = "gateway.example.com"
    request.scope = {"root_path": ""}
    return request


@pytest.fixture
def mock_gateway():
    """Create mock gateway with OAuth config."""
    gateway = Mock(spec=Gateway)
    gateway.id = "gateway123"
    gateway.name = "Test Gateway"
    gateway.url = "https://mcp.example.com"  # MCP server URL
    gateway.team_id = None  # No team restriction - allow all authenticated users
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
def mock_current_user():
    """Create mock current user."""
    user = Mock(spec=EmailUserResponse)
    user.get = Mock(return_value="test@example.com")
    user.email = "test@example.com"
    user.full_name = "Test User"
    user.is_active = True
    user.is_admin = False
    return user


class TestNormalizeResourceUrl:
    """Tests for _normalize_resource_url helper."""

    def test_normalize_resource_url_invalid(self):
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        assert _normalize_resource_url(None) is None
        assert _normalize_resource_url("") is None
        assert _normalize_resource_url("example.com/path") is None

    def test_normalize_resource_url_strips_fragment_and_query(self):
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        result = _normalize_resource_url("https://example.com/path?x=1#frag")
        assert result == "https://example.com/path"

    def test_normalize_resource_url_preserves_query_when_requested(self):
        from mcpgateway.routers.oauth_router import _normalize_resource_url

        result = _normalize_resource_url("https://example.com/path?x=1#frag", preserve_query=True)
        assert result == "https://example.com/path?x=1"


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
        gateway.team_id = None  # No team restriction - allow all authenticated users
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
        mock_gateway.team_id = None  # No team restriction
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
        mock_gateway.team_id = None  # No team restriction
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        # Execute & Assert
        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Gateway is not configured for Authorization Code flow" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_disabled_missing_client_id(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow when issuer exists but DCR auto-registration is disabled."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
            mock_settings.dcr_enabled = False
            mock_settings.dcr_auto_register_on_missing_credentials = False

            from mcpgateway.routers.oauth_router import initiate_oauth_flow

            with pytest.raises(HTTPException) as exc_info:
                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

            assert exc_info.value.status_code == 400
            assert "incomplete" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_normalizes_resource_list(self, mock_db, mock_request, mock_current_user):
        """Test that resource list is normalized and invalid entries removed."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "resource": ["https://api.example.com/path?x=1#frag", "invalid-resource"],
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://auth.example.com/authorize?state=x", "state": "x"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        oauth_config_passed = mock_oauth_manager.initiate_authorization_code_flow.call_args[0][1]
        assert oauth_config_passed["resource"] == ["https://api.example.com/path?x=1"]

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_resource_string_normalized(self, mock_db, mock_request, mock_current_user):
        """Test that resource string is normalized preserving query."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "resource": "https://api.example.com/path?x=1#frag",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://auth.example.com/authorize?state=x", "state": "x"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        oauth_config_passed = mock_oauth_manager.initiate_authorization_code_flow.call_args[0][1]
        assert oauth_config_passed["resource"] == "https://api.example.com/path?x=1"

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_missing_client_id(self, mock_db, mock_request, mock_current_user):
        """Test OAuth flow missing client_id without DCR issuer."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        from mcpgateway.routers.oauth_router import initiate_oauth_flow

        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "missing client_id" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_unexpected_error(self, mock_db, mock_request, mock_current_user):
        """Test DCR path handles unexpected exception."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with (
            patch("mcpgateway.routers.oauth_router.settings") as mock_settings,
            patch("mcpgateway.routers.oauth_router.DcrService") as mock_dcr_class,
        ):
            mock_settings.dcr_enabled = True
            mock_settings.dcr_auto_register_on_missing_credentials = True
            mock_settings.dcr_default_scopes = ["openid"]
            mock_settings.auth_encryption_secret = "secret"

            mock_dcr = Mock()
            mock_dcr.get_or_register_client = AsyncMock(side_effect=Exception("boom"))
            mock_dcr_class.return_value = mock_dcr

            from mcpgateway.routers.oauth_router import initiate_oauth_flow

            with pytest.raises(HTTPException) as exc_info:
                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 500
        assert "Failed to register OAuth client" in str(exc_info.value.detail)

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
    async def test_oauth_callback_resource_string_normalized(self, mock_db, mock_request):
        """Test OAuth callback normalizes string resource value."""
        import base64
        import json

        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Test Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client-id",
            "client_secret": "secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
            "resource": "https://api.example.com/path?x=1#frag",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        token_result = {"user_id": "oauth_user_123", "app_user_email": "test@example.com", "expires_at": "2024-01-01T12:00:00"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(return_value=token_result)
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        oauth_config_passed = mock_oauth_manager.complete_authorization_code_flow.call_args[0][3]
        assert oauth_config_passed["resource"] == "https://api.example.com/path?x=1"

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
    async def test_oauth_callback_unexpected_error(self, mock_db, mock_request, mock_gateway):
        """Test OAuth callback handles unexpected errors."""
        import base64
        import json

        state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com"}
        payload = json.dumps(state_data).encode()
        signature = b"x" * 32
        state = base64.urlsafe_b64encode(payload + signature).decode()

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_manager_class:
            mock_oauth_manager = Mock()
            mock_oauth_manager.complete_authorization_code_flow = AsyncMock(side_effect=RuntimeError("boom"))
            mock_oauth_manager_class.return_value = mock_oauth_manager

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                result = await oauth_callback(code="auth_code_123", state=state, request=mock_request, db=mock_db)

        assert isinstance(result, HTMLResponse)
        assert result.status_code == 500
        assert "OAuth Authorization Failed" in result.body.decode()

    @pytest.mark.asyncio
    async def test_get_oauth_status_success(self, mock_db, mock_gateway, mock_current_user):
        """Test successful OAuth status retrieval."""
        # Setup
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import get_oauth_status

        # Execute (now requires current_user for authentication)
        result = await get_oauth_status("gateway123", mock_current_user, mock_db)

        # Assert
        assert result["oauth_enabled"] is True
        assert result["grant_type"] == "authorization_code"
        assert result["client_id"] == "test_client"
        assert result["scopes"] == ["read", "write"]

    @pytest.mark.asyncio
    async def test_get_oauth_status_no_oauth_config(self, mock_db, mock_current_user):
        """Test OAuth status when gateway has no OAuth config."""
        # Setup
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.oauth_config = None
        mock_gateway.team_id = None  # No team restriction
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        # First-Party
        from mcpgateway.routers.oauth_router import get_oauth_status

        # Execute (now requires current_user for authentication)
        result = await get_oauth_status("gateway123", mock_current_user, mock_db)

        # Assert
        assert result["oauth_enabled"] is False
        assert "Gateway is not configured for OAuth" in result["message"]

    @pytest.mark.asyncio
    async def test_get_oauth_status_gateway_not_found(self, mock_db, mock_current_user):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        from mcpgateway.routers.oauth_router import get_oauth_status

        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_status("gateway123", mock_current_user, mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_oauth_status_non_authorization_code(self, mock_db, mock_current_user):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {"grant_type": "client_credentials", "client_id": "cid"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        from mcpgateway.routers.oauth_router import get_oauth_status

        result = await get_oauth_status("gateway123", mock_current_user, mock_db)

        assert result["grant_type"] == "client_credentials"
        assert "configured for client_credentials" in result["message"]

    @pytest.mark.asyncio
    async def test_get_oauth_status_exception(self, mock_db, mock_current_user):
        mock_db.execute.side_effect = Exception("boom")

        from mcpgateway.routers.oauth_router import get_oauth_status

        with pytest.raises(HTTPException) as exc_info:
            await get_oauth_status("gateway123", mock_current_user, mock_db)

        assert exc_info.value.status_code == 500

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


class TestOAuthRouterAdditionalCoverage:
    """Additional coverage for OAuth router branches."""

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_success(self, mock_db, mock_request, mock_current_user):
        """Test DCR auto-registration path success."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.auth_type = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        class _Registered:
            client_id = "client-123"
            client_secret_encrypted = None

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                return _Registered()

            async def discover_as_metadata(self, _issuer):
                return {"authorization_endpoint": "https://issuer.example.com/auth", "token_endpoint": "https://issuer.example.com/token"}

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
                mock_mgr = Mock()
                mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
                mock_oauth_mgr.return_value = mock_mgr

                with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                    # First-Party
                    from mcpgateway.routers.oauth_router import initiate_oauth_flow

                    with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                        mock_settings.dcr_enabled = True
                        mock_settings.dcr_auto_register_on_missing_credentials = True
                        mock_settings.dcr_default_scopes = ["openid"]

                        result = await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert isinstance(result, RedirectResponse)
        assert mock_gateway.auth_type == "oauth"
        assert mock_gateway.oauth_config["client_id"] == "client-123"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_team_access_denied(self, mock_db, mock_request, mock_current_user):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = "team-1"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "cid",
            "authorization_url": "https://issuer.example.com/auth",
            "token_url": "https://issuer.example.com/token",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        class _User:
            def is_team_member(self, _team_id):
                return False

        class _AuthService:
            async def get_user_by_email(self, _email):
                return _User()

        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=_AuthService()):
            # First-Party
            from mcpgateway.routers.oauth_router import initiate_oauth_flow

            with pytest.raises(HTTPException) as exc_info:
                await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_invalid_resource_list(self, mock_db, mock_request, mock_current_user):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "cid",
            "authorization_url": "https://issuer.example.com/auth",
            "token_url": "https://issuer.example.com/token",
            "resource": ["not-a-url"],
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import initiate_oauth_flow

                with patch("mcpgateway.routers.oauth_router.logger") as mock_logger:
                    result = await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert isinstance(result, RedirectResponse)
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_decrypts_secret(self, mock_db, mock_request, mock_current_user):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.auth_type = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
            "redirect_uri": "https://gateway.example.com/oauth/callback",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        auth_data = {"authorization_url": "https://issuer.example.com/auth"}

        class _Registered:
            client_id = "client-123"
            client_secret_encrypted = "encrypted"

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                return _Registered()

            async def discover_as_metadata(self, _issuer):
                return {"authorization_endpoint": "https://issuer.example.com/auth", "token_endpoint": "https://issuer.example.com/token"}

        class _Encryption:
            async def decrypt_secret_async(self, _value):
                return "decrypted"

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            with patch("mcpgateway.services.encryption_service.get_encryption_service", return_value=_Encryption()):
                with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
                    mock_mgr = Mock()
                    mock_mgr.initiate_authorization_code_flow = AsyncMock(return_value=auth_data)
                    mock_oauth_mgr.return_value = mock_mgr

                    with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                        from mcpgateway.routers.oauth_router import initiate_oauth_flow

                        with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                            mock_settings.dcr_enabled = True
                            mock_settings.dcr_auto_register_on_missing_credentials = True
                            mock_settings.dcr_default_scopes = ["openid"]
                            mock_settings.auth_encryption_secret = "secret"

                            result = await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert isinstance(result, RedirectResponse)
        assert mock_gateway.oauth_config["client_secret"] == "decrypted"

    @pytest.mark.asyncio
    async def test_oauth_callback_invalid_state_json(self, mock_db, mock_request):
        import base64

        payload = b"\x00" * 5
        state_raw = payload + (b"\x00" * 32)
        state = base64.urlsafe_b64encode(state_raw).decode()

        from mcpgateway.routers.oauth_router import oauth_callback

        response = await oauth_callback(code="code", state=state, request=mock_request, db=mock_db)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_oauth_callback_missing_gateway_id_in_state(self, mock_db, mock_request):
        import base64
        import orjson

        payload = orjson.dumps({"foo": "bar"})
        state_raw = payload + (b"0" * 32)
        state = base64.urlsafe_b64encode(state_raw).decode()

        from mcpgateway.routers.oauth_router import oauth_callback

        response = await oauth_callback(code="code", state=state, request=mock_request, db=mock_db)

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_oauth_callback_invalid_resource_list(self, mock_db, mock_request):
        import base64
        import orjson

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "client",
            "resource": ["not-a-url"],
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        payload = orjson.dumps({"gateway_id": "gateway123"})
        state_raw = payload + (b"0" * 32)
        state = base64.urlsafe_b64encode(state_raw).decode()

        result_payload = {"user_id": "u1"}

        with patch("mcpgateway.routers.oauth_router.OAuthManager") as mock_oauth_mgr:
            mock_mgr = Mock()
            mock_mgr.complete_authorization_code_flow = AsyncMock(return_value=result_payload)
            mock_oauth_mgr.return_value = mock_mgr

            with patch("mcpgateway.routers.oauth_router.TokenStorageService"):
                from mcpgateway.routers.oauth_router import oauth_callback

                with patch("mcpgateway.routers.oauth_router.logger") as mock_logger:
                    response = await oauth_callback(code="code", state=state, request=mock_request, db=mock_db)

        assert response.status_code == 200
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_initiate_oauth_flow_dcr_error(self, mock_db, mock_request, mock_current_user):
        """Test DCR error handling path."""
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.name = "Gateway"
        mock_gateway.url = "https://mcp.example.com"
        mock_gateway.team_id = None
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://issuer.example.com",
        }
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        class _FakeDcrService:
            async def get_or_register_client(self, **_kwargs):
                from mcpgateway.services.dcr_service import DcrError

                raise DcrError("boom")

        with patch("mcpgateway.routers.oauth_router.DcrService", return_value=_FakeDcrService()):
            # First-Party
            from mcpgateway.routers.oauth_router import initiate_oauth_flow

            with patch("mcpgateway.routers.oauth_router.settings") as mock_settings:
                mock_settings.dcr_enabled = True
                mock_settings.dcr_auto_register_on_missing_credentials = True

                with pytest.raises(HTTPException) as exc_info:
                    await initiate_oauth_flow("gateway123", mock_request, mock_current_user, mock_db)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_oauth_status_team_access_denied(self, mock_db):
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "gateway123"
        mock_gateway.team_id = "team-1"
        mock_gateway.oauth_config = {"grant_type": "authorization_code", "client_id": "cid"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        class _User:
            def is_team_member(self, _team_id):
                return False

        class _AuthService:
            async def get_user_by_email(self, _email):
                return _User()

        with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=_AuthService()):
            # First-Party
            from mcpgateway.routers.oauth_router import get_oauth_status

            with pytest.raises(HTTPException) as exc_info:
                await get_oauth_status("gateway123", {"email": "user@example.com"}, mock_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_registered_oauth_clients(self, mock_db):
        class _Client:
            id = "c1"
            gateway_id = "g1"
            issuer = "https://issuer"
            client_id = "client"
            redirect_uris = "https://cb1,https://cb2"
            grant_types = ["authorization_code"]
            scope = "openid"
            token_endpoint_auth_method = "client_secret_basic"
            created_at = datetime.now(timezone.utc)
            expires_at = None
            is_active = True

        mock_db.execute.return_value.scalars.return_value.all.return_value = [_Client()]

        # First-Party
        from mcpgateway.routers.oauth_router import list_registered_oauth_clients

        result = await list_registered_oauth_clients(current_user={"email": "admin"}, db=mock_db)

        assert result["total"] == 1
        assert result["clients"][0]["gateway_id"] == "g1"
        assert result["clients"][0]["redirect_uris"] == ["https://cb1", "https://cb2"]

    @pytest.mark.asyncio
    async def test_list_registered_oauth_clients_error(self, mock_db):
        mock_db.execute.side_effect = Exception("boom")

        from mcpgateway.routers.oauth_router import list_registered_oauth_clients

        with pytest.raises(HTTPException) as exc_info:
            await list_registered_oauth_clients(current_user={"email": "admin"}, db=mock_db)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_registered_client_for_gateway_success(self, mock_db):
        class _Client:
            id = "c1"
            gateway_id = "g1"
            issuer = "https://issuer"
            client_id = "client"
            redirect_uris = "https://cb1,https://cb2"
            grant_types = ["authorization_code"]
            scope = "openid"
            token_endpoint_auth_method = "client_secret_basic"
            registration_client_uri = "https://issuer/clients/c1"
            created_at = datetime.now(timezone.utc)
            expires_at = None
            is_active = True

        mock_db.execute.return_value.scalar_one_or_none.return_value = _Client()

        from mcpgateway.routers.oauth_router import get_registered_client_for_gateway

        result = await get_registered_client_for_gateway("gateway123", {"email": "admin"}, mock_db)

        assert result["id"] == "c1"
        assert result["gateway_id"] == "g1"
        assert result["redirect_uris"] == ["https://cb1", "https://cb2"]
        assert result["grant_types"] == ["authorization_code"]

    @pytest.mark.asyncio
    async def test_get_registered_client_for_gateway_not_found(self, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # First-Party
        from mcpgateway.routers.oauth_router import get_registered_client_for_gateway

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", {"email": "admin"}, mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_registered_client_for_gateway_error(self, mock_db):
        mock_db.execute.side_effect = Exception("boom")

        from mcpgateway.routers.oauth_router import get_registered_client_for_gateway

        with pytest.raises(HTTPException) as exc_info:
            await get_registered_client_for_gateway("gateway123", {"email": "admin"}, mock_db)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_delete_registered_client_success(self, mock_db):
        client = Mock()
        client.id = "c1"
        client.issuer = "https://issuer"
        client.gateway_id = "g1"
        mock_db.execute.return_value.scalar_one_or_none.return_value = client

        # First-Party
        from mcpgateway.routers.oauth_router import delete_registered_client

        result = await delete_registered_client("c1", {"email": "admin"}, mock_db)

        assert result["success"] is True
        mock_db.delete.assert_called_once_with(client)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_registered_client_not_found(self, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        from mcpgateway.routers.oauth_router import delete_registered_client

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("missing", {"email": "admin"}, mock_db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_registered_client_error(self, mock_db):
        client = Mock()
        client.id = "c1"
        client.issuer = "https://issuer"
        client.gateway_id = "g1"
        mock_db.execute.return_value.scalar_one_or_none.return_value = client
        mock_db.commit.side_effect = Exception("boom")

        from mcpgateway.routers.oauth_router import delete_registered_client

        with pytest.raises(HTTPException) as exc_info:
            await delete_registered_client("c1", {"email": "admin"}, mock_db)

        assert exc_info.value.status_code == 500
        mock_db.rollback.assert_called_once()
