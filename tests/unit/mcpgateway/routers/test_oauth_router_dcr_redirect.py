# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_oauth_router_dcr_redirect.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for graceful DCR error handling with redirect in OAuth router.
"""

# Standard
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway
from mcpgateway.routers.oauth_router import initiate_oauth_flow
from mcpgateway.services.dcr_service import DcrError


class TestOAuthRouterDcrRedirect:
    """Test graceful error handling for DCR failures in OAuth flow."""

    @pytest.mark.asyncio
    @patch("mcpgateway.routers.oauth_router.resolve_root_path")
    @patch("mcpgateway.routers.oauth_router.settings")
    @patch("mcpgateway.routers.oauth_router._enforce_gateway_access")
    @patch("mcpgateway.routers.oauth_router.DcrService")
    async def test_initiate_oauth_flow_dcr_error_redirects_to_admin(
        self, mock_dcr_service_cls, mock_enforce_access, mock_settings, mock_resolve_root
    ):
        """Test that DCR error redirects to Admin UI instead of returning raw JSON."""
        # Setup mocks
        mock_request = Mock(spec=Request)
        mock_request.url = Mock()
        mock_request.url.path = "/oauth/authorize/test-gw-123"

        mock_db = Mock(spec=Session)

        # Mock gateway with OAuth config but no client_id
        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "test-gw-123"
        mock_gateway.name = "Atlassian Server"
        mock_gateway.url = "https://api.atlassian.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://auth.atlassian.com",
            "redirect_uri": "http://localhost:4444/oauth/callback",
            # No client_id - will trigger DCR
        }

        mock_db.execute = Mock()
        mock_db.execute.return_value.scalar_one_or_none = Mock(return_value=mock_gateway)

        mock_current_user = {"email": "test@example.com", "is_admin": False}

        # Mock DCR service to raise DcrError
        mock_dcr = Mock()
        mock_dcr.get_or_register_client = AsyncMock(
            side_effect=DcrError(
                "AS https://auth.atlassian.com does not support Dynamic Client Registration (no registration_endpoint)"
            )
        )
        mock_dcr_service_cls.return_value = mock_dcr

        # Mock settings
        mock_settings.dcr_enabled = True
        mock_settings.dcr_auto_register_on_missing_credentials = True

        # Mock resolve_root_path
        mock_resolve_root.return_value = "/admin/gateways?error=test&gateway_id=test-gw-123"

        # Call endpoint
        response = await initiate_oauth_flow(
            gateway_id="test-gw-123",
            request=mock_request,
            current_user=mock_current_user,
            db=mock_db
        )

        # Verify redirect response
        assert isinstance(response, RedirectResponse)
        assert response.status_code == 303
        assert "/admin/gateways" in response.headers["location"]
        assert "error=" in response.headers["location"]
        assert "gateway_id=test-gw-123" in response.headers["location"]

        # Verify resolve_root_path was called
        mock_resolve_root.assert_called_once()

    @pytest.mark.asyncio
    @patch("mcpgateway.routers.oauth_router.resolve_root_path")
    @patch("mcpgateway.routers.oauth_router.settings")
    @patch("mcpgateway.routers.oauth_router._enforce_gateway_access")
    @patch("mcpgateway.routers.oauth_router.DcrService")
    async def test_initiate_oauth_flow_dcr_network_error_redirects(
        self, mock_dcr_service_cls, mock_enforce_access, mock_settings, mock_resolve_root
    ):
        """Test that DCR network errors redirect gracefully."""
        mock_request = Mock(spec=Request)
        mock_request.url = Mock()
        mock_request.url.path = "/oauth/authorize/test-gw-456"

        mock_db = Mock(spec=Session)

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "test-gw-456"
        mock_gateway.name = "Test Server"
        mock_gateway.url = "https://api.example.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://auth.example.com",
            "redirect_uri": "http://localhost:4444/oauth/callback",
        }

        mock_db.execute = Mock()
        mock_db.execute.return_value.scalar_one_or_none = Mock(return_value=mock_gateway)

        mock_current_user = {"email": "test@example.com", "is_admin": False}

        # Mock DCR service to raise network error
        mock_dcr = Mock()
        mock_dcr.get_or_register_client = AsyncMock(
            side_effect=DcrError("Failed to discover AS metadata: Connection timeout")
        )
        mock_dcr_service_cls.return_value = mock_dcr

        # Mock settings
        mock_settings.dcr_enabled = True
        mock_settings.dcr_auto_register_on_missing_credentials = True

        # Mock resolve_root_path
        mock_resolve_root.return_value = "/admin/gateways?error=test&gateway_id=test-gw-456"

        response = await initiate_oauth_flow(
            gateway_id="test-gw-456",
            request=mock_request,
            current_user=mock_current_user,
            db=mock_db
        )

        # Verify redirect
        assert isinstance(response, RedirectResponse)
        assert response.status_code == 303
        assert "/admin/gateways" in response.headers["location"]
        assert "error=" in response.headers["location"]

        # Verify resolve_root_path was called
        mock_resolve_root.assert_called_once()

    @pytest.mark.asyncio
    @patch("mcpgateway.routers.oauth_router.protect_oauth_config_for_storage")
    @patch("mcpgateway.services.encryption_service.get_encryption_service")
    @patch("mcpgateway.routers.oauth_router.settings")
    @patch("mcpgateway.routers.oauth_router._enforce_gateway_access")
    @patch("mcpgateway.routers.oauth_router.DcrService")
    @patch("mcpgateway.routers.oauth_router.OAuthManager")
    @patch("mcpgateway.routers.oauth_router.TokenStorageService")
    async def test_initiate_oauth_flow_dcr_success_continues_flow(
        self, mock_token_storage_cls, mock_oauth_manager_cls, mock_dcr_service_cls,
        mock_enforce_access, mock_settings, mock_encryption_service, mock_protect_oauth
    ):
        """Test that successful DCR continues OAuth flow normally."""
        mock_request = Mock(spec=Request)
        mock_request.url = Mock()
        mock_request.url.path = "/oauth/authorize/test-gw-789"

        mock_db = Mock(spec=Session)

        mock_gateway = Mock(spec=Gateway)
        mock_gateway.id = "test-gw-789"
        mock_gateway.name = "Valid DCR Server"
        mock_gateway.url = "https://api.valid.com"
        mock_gateway.oauth_config = {
            "grant_type": "authorization_code",
            "issuer": "https://auth.valid.com",
            "redirect_uri": "http://localhost:4444/oauth/callback",
        }

        mock_db.execute = Mock()
        mock_db.execute.return_value.scalar_one_or_none = Mock(return_value=mock_gateway)
        mock_db.commit = Mock()

        mock_current_user = {"email": "test@example.com", "is_admin": False}

        # Mock successful DCR registration
        mock_registered_client = Mock()
        mock_registered_client.client_id = "auto-registered-client-id"
        mock_registered_client.client_secret_encrypted = "encrypted-secret"

        mock_dcr = Mock()
        mock_dcr.get_or_register_client = AsyncMock(return_value=mock_registered_client)
        mock_dcr.discover_as_metadata = AsyncMock(
            return_value={
                "issuer": "https://auth.valid.com",
                "authorization_endpoint": "https://auth.valid.com/authorize",
                "token_endpoint": "https://auth.valid.com/token",
                "registration_endpoint": "https://auth.valid.com/register",
            }
        )
        mock_dcr_service_cls.return_value = mock_dcr

        # Mock encryption service
        mock_encryption = Mock()
        mock_encryption.decrypt_secret_async = AsyncMock(return_value="decrypted-secret")
        mock_encryption_service.return_value = mock_encryption

        # Mock OAuth manager
        mock_oauth = Mock()
        mock_oauth.initiate_authorization_code_flow = AsyncMock(
            return_value={"authorization_url": "https://auth.valid.com/authorize?state=xyz"}
        )
        mock_oauth_manager_cls.return_value = mock_oauth

        # Mock protect_oauth_config_for_storage
        mock_protect_oauth.return_value = {}

        # Mock settings
        mock_settings.dcr_enabled = True
        mock_settings.dcr_auto_register_on_missing_credentials = True
        mock_settings.auth_encryption_secret = "test-secret"

        response = await initiate_oauth_flow(
            gateway_id="test-gw-789",
            request=mock_request,
            current_user=mock_current_user,
            db=mock_db
        )

        # Verify OAuth flow continues (redirect to authorization URL)
        assert isinstance(response, RedirectResponse)
        assert "auth.valid.com/authorize" in response.headers["location"]

        # Verify DCR was called
        mock_dcr.get_or_register_client.assert_called_once()

        # Verify gateway was updated with credentials
        mock_db.commit.assert_called()
