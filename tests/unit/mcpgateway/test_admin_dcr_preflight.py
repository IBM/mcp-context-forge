# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_dcr_preflight.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for pre-flight DCR validation in admin gateway endpoints.
"""

# Standard
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import pytest
from fastapi import Request
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.admin import admin_add_gateway, admin_edit_gateway
from mcpgateway.services.dcr_service import DcrError


class TestAdminDcrPreflightValidation:
    """Test pre-flight DCR validation in gateway save/update endpoints."""

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.settings")
    @patch("mcpgateway.admin.MetadataCapture")
    @patch("mcpgateway.admin.gateway_service")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.get_encryption_service")
    async def test_add_gateway_dcr_unsupported_returns_400(
        self, mock_encryption_service, mock_team_service_cls, mock_gateway_service, mock_metadata, mock_settings
    ):
        """Test that adding a gateway with issuer but no client_id checks DCR support."""
        # Setup mocks
        mock_request = Mock(spec=Request)
        mock_request.form = AsyncMock(
            return_value={
                "name": "Atlassian Server",
                "url": "https://api.atlassian.com",
                "description": "Test",
                "transport": "SSE",
                "oauth_issuer": "https://auth.atlassian.com",
                "oauth_grant_type": "authorization_code",
                "oauth_redirect_uri": "http://localhost:4444/oauth/callback",
                # No client_id or client_secret - should trigger DCR check
            }
        )
        mock_request.client = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"content-type": "multipart/form-data"}

        mock_db = Mock(spec=Session)
        mock_user = {"email": "test@example.com", "is_admin": False}

        mock_team_service = Mock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_cls.return_value = mock_team_service

        # Mock settings
        mock_settings.dcr_enabled = True
        mock_settings.dcr_auto_register_on_missing_credentials = True

        # Mock DCR service to return metadata without registration_endpoint
        with patch("mcpgateway.services.dcr_service.DcrService") as mock_dcr_cls:
            mock_dcr = Mock()
            mock_dcr.discover_as_metadata = AsyncMock(
                return_value={
                    "issuer": "https://auth.atlassian.com",
                    "authorization_endpoint": "https://auth.atlassian.com/authorize",
                    "token_endpoint": "https://auth.atlassian.com/oauth/token",
                    # No registration_endpoint - Atlassian doesn't support DCR
                }
            )
            mock_dcr_cls.return_value = mock_dcr

            # Call endpoint
            response = await admin_add_gateway(mock_request, db=mock_db, user=mock_user)

            # Verify response
            assert response.status_code == 400
            content = response.body.decode()
            assert "OAuth Configuration Incomplete" in content
            assert "auth.atlassian.com" in content
            assert "does not support automatic client registration" in content
            assert "Dynamic Client Registration / RFC 7591" in content
            assert "developer.atlassian.com" in content
            assert response.headers.get("content-type") == "application/json"

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.settings")
    @patch("mcpgateway.admin.MetadataCapture")
    @patch("mcpgateway.admin.gateway_service")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.get_encryption_service")
    async def test_add_gateway_dcr_discovery_failure_returns_400(
        self, mock_encryption_service, mock_team_service_cls, mock_gateway_service, mock_metadata, mock_settings
    ):
        """Test that DCR discovery failure returns actionable error."""
        mock_request = Mock(spec=Request)
        mock_request.form = AsyncMock(
            return_value={
                "name": "Test Server",
                "url": "https://api.example.com",
                "description": "Test",
                "transport": "SSE",
                "oauth_issuer": "https://invalid-issuer.example.com",
                "oauth_grant_type": "authorization_code",
                "oauth_redirect_uri": "http://localhost:4444/oauth/callback",
            }
        )
        mock_request.client = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"content-type": "multipart/form-data"}

        mock_db = Mock(spec=Session)
        mock_user = {"email": "test@example.com", "is_admin": False}

        mock_team_service = Mock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_cls.return_value = mock_team_service

        # Mock settings
        mock_settings.dcr_enabled = True
        mock_settings.dcr_auto_register_on_missing_credentials = True

        # Mock DCR service to raise DcrError
        with patch("mcpgateway.services.dcr_service.DcrService") as mock_dcr_cls:
            mock_dcr = Mock()
            mock_dcr.discover_as_metadata = AsyncMock(
                side_effect=DcrError("Failed to discover AS metadata: Connection timeout")
            )
            mock_dcr_cls.return_value = mock_dcr

            # Call endpoint
            response = await admin_add_gateway(mock_request, db=mock_db, user=mock_user)

            # Verify response
            assert response.status_code == 400
            content = response.body.decode()
            assert "Failed to validate OAuth configuration" in content
            assert "Connection timeout" in content
            assert "verify the issuer URL is correct" in content

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.settings")
    @patch("mcpgateway.admin.MetadataCapture")
    @patch("mcpgateway.admin.gateway_service")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.get_encryption_service")
    async def test_edit_gateway_dcr_unsupported_returns_400(
        self, mock_encryption_service, mock_team_service_cls, mock_gateway_service, mock_metadata, mock_settings
    ):
        """Test that editing a gateway with issuer but no client_id checks DCR support."""
        mock_request = Mock(spec=Request)
        mock_request.form = AsyncMock(
            return_value={
                "name": "Atlassian Server",
                "url": "https://api.atlassian.com",
                "description": "Test",
                "transport": "SSE",
                "oauth_issuer": "https://auth.atlassian.com",
                "oauth_grant_type": "authorization_code",
                "oauth_redirect_uri": "http://localhost:4444/oauth/callback",
            }
        )
        mock_request.client = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"content-type": "multipart/form-data"}

        mock_db = Mock(spec=Session)
        mock_db.get = Mock(return_value=None)  # No existing gateway team_id
        mock_user = {"email": "test@example.com", "is_admin": False}

        mock_team_service = Mock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_cls.return_value = mock_team_service

        # Mock settings
        mock_settings.dcr_enabled = True
        mock_settings.dcr_auto_register_on_missing_credentials = True

        # Mock DCR service
        with patch("mcpgateway.services.dcr_service.DcrService") as mock_dcr_cls:
            mock_dcr = Mock()
            mock_dcr.discover_as_metadata = AsyncMock(
                return_value={
                    "issuer": "https://auth.atlassian.com",
                    "authorization_endpoint": "https://auth.atlassian.com/authorize",
                    "token_endpoint": "https://auth.atlassian.com/oauth/token",
                }
            )
            mock_dcr_cls.return_value = mock_dcr

            # Call endpoint
            response = await admin_edit_gateway("test-gw-123", mock_request, db=mock_db, user=mock_user)

            # Verify response
            assert response.status_code == 400
            content = response.body.decode()
            assert "OAuth Configuration Incomplete" in content
            assert "auth.atlassian.com" in content

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.settings")
    @patch("mcpgateway.admin.MetadataCapture")
    @patch("mcpgateway.admin.gateway_service")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.get_encryption_service")
    async def test_edit_gateway_dcr_discovery_failure_returns_400(
        self, mock_encryption_service, mock_team_service_cls, mock_gateway_service, mock_metadata, mock_settings
    ):
        """Test that DCR discovery failure in edit returns actionable error."""
        mock_request = Mock(spec=Request)
        mock_request.form = AsyncMock(
            return_value={
                "name": "Test Server",
                "url": "https://api.example.com",
                "description": "Test",
                "transport": "SSE",
                "oauth_issuer": "https://invalid-issuer.example.com",
                "oauth_grant_type": "authorization_code",
                "oauth_redirect_uri": "http://localhost:4444/oauth/callback",
            }
        )
        mock_request.client = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"content-type": "multipart/form-data"}

        mock_db = Mock(spec=Session)
        mock_db.get = Mock(return_value=None)  # No existing gateway team_id
        mock_user = {"email": "test@example.com", "is_admin": False}

        mock_team_service = Mock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_cls.return_value = mock_team_service

        # Mock settings
        mock_settings.dcr_enabled = True
        mock_settings.dcr_auto_register_on_missing_credentials = True

        # Mock DCR service to raise DcrError
        with patch("mcpgateway.services.dcr_service.DcrService") as mock_dcr_cls:
            mock_dcr = Mock()
            mock_dcr.discover_as_metadata = AsyncMock(
                side_effect=DcrError("Failed to discover AS metadata: Connection timeout")
            )
            mock_dcr_cls.return_value = mock_dcr

            # Call endpoint
            response = await admin_edit_gateway("test-gw-456", mock_request, db=mock_db, user=mock_user)

            # Verify response
            assert response.status_code == 400
            content = response.body.decode()
            assert "Failed to validate OAuth configuration" in content
            assert "Connection timeout" in content
            assert "verify the issuer URL is correct" in content

    @pytest.mark.asyncio
    @patch("mcpgateway.admin.settings")
    @patch("mcpgateway.admin.MetadataCapture")
    @patch("mcpgateway.admin.gateway_service")
    @patch("mcpgateway.admin.TeamManagementService")
    @patch("mcpgateway.admin.get_encryption_service")
    async def test_add_gateway_with_client_id_skips_dcr_check(
        self, mock_encryption_service, mock_team_service_cls, mock_gateway_service, mock_metadata, mock_settings
    ):
        """Test that providing client_id skips DCR pre-flight check."""
        mock_request = Mock(spec=Request)
        mock_request.form = AsyncMock(
            return_value={
                "name": "Atlassian Server",
                "url": "https://api.atlassian.com",
                "description": "Test",
                "transport": "SSE",
                "oauth_issuer": "https://auth.atlassian.com",
                "oauth_grant_type": "authorization_code",
                "oauth_redirect_uri": "http://localhost:4444/oauth/callback",
                "oauth_client_id": "manual-client-id",
                "oauth_client_secret": "manual-secret",
            }
        )
        mock_request.client = Mock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"content-type": "multipart/form-data"}

        mock_db = Mock(spec=Session)
        mock_user = {"email": "test@example.com", "is_admin": False}

        mock_team_service = Mock()
        mock_team_service.verify_team_for_user = AsyncMock(return_value=None)
        mock_team_service_cls.return_value = mock_team_service

        mock_encryption = Mock()
        mock_encryption.encrypt_secret_async = AsyncMock(return_value="encrypted-secret")
        mock_encryption_service.return_value = mock_encryption

        mock_gateway_service.register_gateway = AsyncMock(
            return_value=Mock(skipped_tools=[])
        )

        # Mock settings
        mock_settings.dcr_enabled = True
        mock_settings.dcr_auto_register_on_missing_credentials = True
        mock_settings.auth_encryption_secret = "test-secret"

        # Mock metadata
        mock_metadata.extract_creation_metadata.return_value = {
            "created_by": "test@example.com",
            "created_from_ip": "127.0.0.1",
            "created_via": "admin_ui",
            "created_user_agent": None,
        }

        # Call endpoint - should NOT trigger DCR check
        response = await admin_add_gateway(mock_request, db=mock_db, user=mock_user)

        # Verify success (no DCR check was performed)
        assert response.status_code == 200
        content = response.body.decode()
        assert "success" in content.lower()
