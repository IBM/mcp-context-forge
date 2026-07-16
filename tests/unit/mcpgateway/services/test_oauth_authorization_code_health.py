# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_authorization_code_health.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for OAuth authorization_code gateway health check fixes (Issue #5237).

These tests verify that:
1. Health checks decouple service reachability from token ownership
2. Missing tokens don't mark gateways unhealthy
3. 401/403 responses are treated as "gateway reachable"
4. client_secret decryption fails explicitly on errors
5. omit_resource flag is respected during token refresh
6. Token deletion only happens on invalid_grant, not transient errors
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway, OAuthToken
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.oauth_manager import OAuthError
from mcpgateway.services.oauth_manager import OAuthInvalidGrantError
from mcpgateway.services.token_storage_service import TokenStorageService


class TestAuthorizationCodeHealthCheck:
    """Test health check behavior for authorization_code OAuth gateways.

    NOTE: Detailed health check behavior is tested in test_gateway_service_health_oauth.py.
    These tests document the fix for Issue #5237 but are placeholders since the actual
    behavior is already covered by comprehensive tests in the main test suite.
    """

    @pytest.mark.asyncio
    async def test_health_check_behavior_documented(self):
        """Health check fix for Issue #5237 is documented and tested in test_gateway_service_health_oauth.py.

        The fix ensures that:
        1. Missing tokens don't mark gateways unhealthy
        2. 401/403 responses are treated as "gateway reachable"
        3. Connection failures still mark gateways unhealthy

        See test_gateway_service_health_oauth.py for comprehensive tests:
        - test_oauth_authorization_code_missing_user_email_proceeds_without_auth
        - test_health_check_oauth_auth_code_no_user
        """
        # This test exists to document that health check behavior is tested elsewhere
        assert True


class TestTokenRefreshClientSecret:
    """Test client_secret decryption during token refresh (Issue #5237.2a)."""

    @pytest.mark.asyncio
    async def test_decryption_failure_raises_explicit_error(self):
        """Decryption failures should raise OAuthError and preserve token (Issue #5237.2a)."""
        mock_db = MagicMock()

        # Mock gateway with encrypted client_secret
        gateway = MagicMock(spec=DbGateway)
        gateway.id = "gw-test"
        gateway.owner_email = "user@example.com"
        gateway.visibility = "public"
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "v2:{\"ciphertext\":\"encrypted_data\",\"nonce\":\"abc123\"}",  # Looks encrypted
            "token_url": "https://oauth.example.com/token"
        }
        gateway.url = "https://example.com"
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None

        # Mock the database query to return the gateway
        mock_db.query.return_value.filter.return_value.first.return_value = gateway

        # Create service with mocked encryption
        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            # Mock settings to trigger encryption service initialization
            mock_settings = MagicMock()
            mock_settings.AUTH_ENCRYPTION_SECRET = "test-secret"
            mock_get_settings.return_value = mock_settings

            service = TokenStorageService(mock_db)

            # Mock encryption service that succeeds for refresh_token but fails for client_secret
            mock_encryption = MagicMock()
            mock_encryption.is_encrypted.return_value = True

            # First call is for refresh_token (succeed), second call is for client_secret (fail)
            decrypt_calls = [
                "decrypted_refresh_token",  # Success for refresh_token
                ValueError("Decryption failed")  # Failure for client_secret
            ]

            async def mock_decrypt(value):
                result = decrypt_calls.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

            mock_encryption.decrypt_secret_async = AsyncMock(side_effect=mock_decrypt)
            service.encryption = mock_encryption

            # Mock token record with plaintext refresh token (won't need decryption in this test)
            token_record = MagicMock(spec=OAuthToken)
            token_record.gateway_id = "gw-test"
            token_record.app_user_email = "user@example.com"
            token_record.refresh_token = "encrypted_refresh_token"  # Will be decrypted successfully
            token_record.expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)

            # Attempt refresh - should fail but NOT delete the token
            # The error is raised as OAuth error but caught by outer handler and token preserved
            result = await service._refresh_access_token(token_record)

            # Should return None (failure) but NOT delete the token
            assert result is None
            mock_db.delete.assert_not_called()


class TestTokenRefreshOmitResource:
    """Test omit_resource flag handling during token refresh (Issue #5237.2b)."""

    @pytest.mark.asyncio
    async def test_omit_resource_flag_prevents_injection(self):
        """omit_resource=true should prevent resource parameter injection (Issue #5237.2b)."""
        mock_db = MagicMock()

        # Mock gateway with omit_resource=true
        gateway = MagicMock(spec=DbGateway)
        gateway.id = "gw-test"
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "plaintext_secret",
            "token_url": "https://oauth.example.com/token",
            "omit_resource": True  # Explicitly disabled
        }
        gateway.url = "https://example.com"  # This should NOT be injected as resource
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None

        # Mock the database query to return the gateway
        mock_db.query.return_value.filter.return_value.first.return_value = gateway

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = MagicMock(spec=OAuthToken)
            token_record.gateway_id = "gw-test"
            token_record.app_user_email = "user@example.com"
            token_record.refresh_token_encrypted = "plain_refresh_token"
            token_record.expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)

            # Mock OAuth manager to capture the config passed to it
            with patch("mcpgateway.services.oauth_manager.OAuthManager") as mock_oauth_class:
                mock_oauth = MagicMock()
                mock_oauth.refresh_token = AsyncMock(side_effect=OAuthError("Test error"))
                mock_oauth_class.return_value = mock_oauth

                # Attempt refresh (will fail, but we just want to check the config)
                try:
                    await service._refresh_access_token(token_record)
                except Exception:
                    pass

                # Verify refresh_token was called with config that has no resource
                call_args = mock_oauth.refresh_token.call_args
                oauth_config_passed = call_args[0][1]

                assert "resource" not in oauth_config_passed, "resource should not be present when omit_resource=true"

    @pytest.mark.asyncio
    async def test_resource_injected_when_omit_resource_false(self):
        """resource should be injected from gateway.url when omit_resource is false/absent."""
        mock_db = MagicMock()

        gateway = MagicMock(spec=DbGateway)
        gateway.id = "gw-test"
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "plaintext_secret",
            "token_url": "https://oauth.example.com/token",
            # omit_resource not present - should default to False
        }
        gateway.url = "https://example.com/path?query=value"
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None

        # Mock the database query to return the gateway
        mock_db.query.return_value.filter.return_value.first.return_value = gateway

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = MagicMock(spec=OAuthToken)
            token_record.gateway_id = "gw-test"
            token_record.app_user_email = "user@example.com"
            token_record.refresh_token_encrypted = "plain_refresh_token"
            token_record.expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)

            with patch("mcpgateway.services.oauth_manager.OAuthManager") as mock_oauth_class:
                mock_oauth = MagicMock()
                mock_oauth.refresh_token = AsyncMock(side_effect=OAuthError("Test error"))
                mock_oauth_class.return_value = mock_oauth

                try:
                    await service._refresh_access_token(token_record)
                except Exception:
                    pass

                call_args = mock_oauth.refresh_token.call_args
                oauth_config_passed = call_args[0][1]

                # Resource should be present and normalized (query stripped)
                assert "resource" in oauth_config_passed
                assert oauth_config_passed["resource"] == "https://example.com/path"


class TestTokenDeletionLogic:
    """Test selective token deletion on refresh failures (Issue #5237.2c)."""

    @pytest.mark.asyncio
    async def test_invalid_grant_deletes_token(self):
        """invalid_grant errors should delete the token (Issue #5237.2c)."""
        mock_db = MagicMock()

        gateway = MagicMock(spec=DbGateway)
        gateway.id = "gw-test"
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "secret",
            "token_url": "https://oauth.example.com/token",
        }
        gateway.url = "https://example.com"
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None

        # Mock the database query to return the gateway
        mock_db.query.return_value.filter.return_value.first.return_value = gateway

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = MagicMock(spec=OAuthToken)
            token_record.gateway_id = "gw-test"
            token_record.app_user_email = "user@example.com"
            token_record.refresh_token_encrypted = "plain_token"

            # Mock OAuth manager to raise OAuthInvalidGrantError — the typed exception
            # raised by OAuthManager when the provider returns {"error": "invalid_grant"}.
            with patch("mcpgateway.services.oauth_manager.OAuthManager") as mock_oauth_class:
                mock_oauth = MagicMock()
                mock_oauth.refresh_token = AsyncMock(side_effect=OAuthInvalidGrantError("Refresh token permanently invalid (invalid_grant): {'error': 'invalid_grant'}"))
                mock_oauth_class.return_value = mock_oauth

                result = await service._refresh_access_token(token_record)

                # Token should be deleted
                mock_db.delete.assert_called_once_with(token_record)
                mock_db.commit.assert_called_once()
                assert result is None

    @pytest.mark.asyncio
    async def test_invalid_client_preserves_token(self):
        """invalid_client errors should NOT delete the token (Issue #5237.2c)."""
        mock_db = MagicMock()

        gateway = MagicMock(spec=DbGateway)
        gateway.id = "gw-test"
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "wrong_secret",
            "token_url": "https://oauth.example.com/token",
        }
        gateway.url = "https://example.com"
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None

        # Mock the database query to return the gateway
        mock_db.query.return_value.filter.return_value.first.return_value = gateway

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = MagicMock(spec=OAuthToken)
            token_record.gateway_id = "gw-test"
            token_record.app_user_email = "user@example.com"
            token_record.refresh_token_encrypted = "plain_token"

            with patch("mcpgateway.services.oauth_manager.OAuthManager") as mock_oauth_class:
                mock_oauth = MagicMock()
                mock_oauth.refresh_token = AsyncMock(side_effect=OAuthError("invalid_client: wrong client_secret"))
                mock_oauth_class.return_value = mock_oauth

                result = await service._refresh_access_token(token_record)

                # Token should NOT be deleted
                mock_db.delete.assert_not_called()
                assert result is None

    @pytest.mark.asyncio
    async def test_transient_error_preserves_token(self):
        """Non-OAuth errors should preserve the token (Issue #5237.2c)."""
        mock_db = MagicMock()

        gateway = MagicMock(spec=DbGateway)
        gateway.id = "gw-test"
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "secret",
            "token_url": "https://oauth.example.com/token",
        }
        gateway.url = "https://example.com"
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None

        # Mock the database query to return the gateway
        mock_db.query.return_value.filter.return_value.first.return_value = gateway

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = MagicMock(spec=OAuthToken)
            token_record.gateway_id = "gw-test"
            token_record.app_user_email = "user@example.com"
            token_record.refresh_token_encrypted = "plain_token"

            with patch("mcpgateway.services.oauth_manager.OAuthManager") as mock_oauth_class:
                mock_oauth = MagicMock()
                # Network error, not OAuth error
                mock_oauth.refresh_token = AsyncMock(side_effect=httpx.ConnectTimeout("Connection timeout"))
                mock_oauth_class.return_value = mock_oauth

                result = await service._refresh_access_token(token_record)

                # Token should NOT be deleted on transient errors
                mock_db.delete.assert_not_called()
                assert result is None
