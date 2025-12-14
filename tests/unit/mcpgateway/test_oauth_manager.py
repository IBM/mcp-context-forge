# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_oauth_manager.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for OAuth Manager and Token Storage Service.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import aiohttp
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.db import OAuthToken
from mcpgateway.services.oauth_manager import OAuthError, OAuthManager
from mcpgateway.services.token_storage_service import TokenStorageService
from mcpgateway.services.encryption_service import EncryptionService


class TestOAuthManager:
    """Test cases for OAuthManager class."""

    def test_init(self):
        """Test OAuthManager initialization."""
        manager = OAuthManager(request_timeout=45, max_retries=5)
        assert manager.request_timeout == 45
        assert manager.max_retries == 5

    def test_init_defaults(self):
        """Test OAuthManager initialization with defaults."""
        manager = OAuthManager()
        assert manager.request_timeout == 30
        assert manager.max_retries == 3

    @pytest.mark.asyncio
    async def test_get_access_token_client_credentials_success(self):
        """Test successful client credentials flow."""
        manager = OAuthManager()
        credentials = {"grant_type": "client_credentials", "client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "scopes": ["read", "write"]}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            # Create mock session instance
            mock_session_instance = MagicMock()

            # Create mock post method
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            # Create mock response
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"access_token": "test_token_123"})
            mock_response.raise_for_status = MagicMock()

            # Async context manager for response
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            # Post returns response
            mock_post.return_value = mock_response

            # Session instance context manager
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session_instance

            result = await manager.get_access_token(credentials)
            assert result == "test_token_123"

    @pytest.mark.asyncio
    async def test_get_access_token_password_flow_success(self):
        """Test successful password grant flow (Resource Owner Password Credentials)."""
        manager = OAuthManager()
        credentials = {
            "grant_type": "password",
            "client_id": "test_client",
            "client_secret": "test_secret",
            "token_url": "https://keycloak.example.com/auth/realms/myrealm/protocol/openid-connect/token",
            "username": "systemadmin@system.com",
            "password": "test_password",
            "scopes": ["openid", "profile"],
        }

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            # Create mock session instance
            mock_session_instance = MagicMock()

            # Create mock post method
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            # Create mock response
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json = AsyncMock(return_value={"access_token": "password_token_456", "token_type": "Bearer", "expires_in": 3600})
            mock_response.raise_for_status = MagicMock()

            # Async context manager for response
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            # Post returns response
            mock_post.return_value = mock_response

            # Session instance context manager
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session_instance

            result = await manager.get_access_token(credentials)
            assert result == "password_token_456"

            # Verify the request was made with correct form data
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://keycloak.example.com/auth/realms/myrealm/protocol/openid-connect/token"
            assert call_args[1]["data"]["grant_type"] == "password"
            assert call_args[1]["data"]["username"] == "systemadmin@system.com"
            assert call_args[1]["data"]["password"] == "test_password"
            assert call_args[1]["data"]["client_id"] == "test_client"

    @pytest.mark.asyncio
    async def test_get_access_token_password_flow_missing_credentials(self):
        """Test password grant flow fails when username or password is missing."""
        manager = OAuthManager()
        credentials = {
            "grant_type": "password",
            "client_id": "test_client",
            "token_url": "https://keycloak.example.com/token",
            # Missing username and password
        }

        with pytest.raises(OAuthError, match="Username and password are required"):
            await manager.get_access_token(credentials)

    @pytest.mark.asyncio
    async def test_get_access_token_password_flow_form_urlencoded_response(self):
        """Test password grant flow with form-urlencoded response."""
        manager = OAuthManager()
        credentials = {
            "grant_type": "password",
            "token_url": "https://oauth.example.com/token",
            "username": "user@example.com",
            "password": "secret",
        }

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
            mock_response.text = AsyncMock(return_value="access_token=encoded_token_789&token_type=Bearer&expires_in=7200")
            mock_response.raise_for_status = MagicMock()

            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response

            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session_instance

            result = await manager.get_access_token(credentials)
            assert result == "encoded_token_789"

    @pytest.mark.asyncio
    async def test_get_access_token_unsupported_grant_type(self):
        """Test error handling for unsupported grant type."""
        manager = OAuthManager()
        credentials = {"grant_type": "unsupported", "client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token"}

        with pytest.raises(ValueError, match="Unsupported grant type: unsupported"):
            await manager.get_access_token(credentials)

    @pytest.mark.asyncio
    async def test_get_authorization_url_success(self):
        """Test successful authorization URL generation."""
        manager = OAuthManager()
        credentials = {"client_id": "test_client", "redirect_uri": "https://gateway.example.com/callback", "authorization_url": "https://oauth.example.com/authorize", "scopes": ["read", "write"]}

        result = await manager.get_authorization_url(credentials)

        assert "authorization_url" in result
        assert "state" in result
        assert "https://oauth.example.com/authorize" in result["authorization_url"]
        assert result["state"] is not None

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_success(self):
        """Test successful code exchange for token."""
        manager = OAuthManager()
        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"access_token": "exchanged_token_456"})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response

            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            result = await manager.exchange_code_for_token(credentials, "auth_code_123", "state_456")
            assert result == "exchanged_token_456"

    def test_oauth_error_inheritance(self):
        """Test that OAuthError inherits from Exception."""
        error = OAuthError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"

    @pytest.mark.asyncio
    async def test_get_access_token_authorization_code_fallback_success(self):
        """Test authorization code flow with client credentials fallback."""
        manager = OAuthManager()
        credentials = {"grant_type": "authorization_code", "client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "scopes": ["read", "write"]}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"access_token": "fallback_token"})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            result = await manager.get_access_token(credentials)
            assert result == "fallback_token"

    @pytest.mark.asyncio
    async def test_get_access_token_authorization_code_fallback_failure(self):
        """Test authorization code flow with client credentials fallback failure."""
        manager = OAuthManager(max_retries=1)  # Reduce retries for faster test execution
        credentials = {"grant_type": "authorization_code", "client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 401
            mock_response.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=401, message="Unauthorized"))
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with pytest.raises(OAuthError, match="Authorization code flow cannot be used"):
                await manager.get_access_token(credentials)

    @pytest.mark.asyncio
    async def test_client_credentials_flow_with_encrypted_secret(self):
        """Test client credentials flow with encrypted client secret."""
        manager = OAuthManager()

        # Create a long secret that would be considered encrypted
        encrypted_secret = "a" * 60  # Longer than 50 chars

        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token", "scopes": ["read", "write"]}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_encryption:
                mock_encryption = Mock()
                mock_encryption.decrypt_secret.return_value = "decrypted_secret"
                mock_get_encryption.return_value = mock_encryption

                with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                    mock_session_instance = MagicMock()
                    mock_post = MagicMock()
                    mock_session_instance.post = mock_post

                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.json = AsyncMock(return_value={"access_token": "decrypted_token"})
                    mock_response.raise_for_status = MagicMock()
                    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_response.__aexit__ = AsyncMock(return_value=None)

                    mock_post.return_value = mock_response
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await manager._client_credentials_flow(credentials)
                    assert result == "decrypted_token"
                    mock_encryption.decrypt_secret.assert_called_once_with(encrypted_secret)

    @pytest.mark.asyncio
    async def test_client_credentials_flow_encryption_error(self):
        """Test client credentials flow when decryption fails."""
        manager = OAuthManager()

        encrypted_secret = "a" * 60  # Long secret

        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            # Should fallback to using encrypted secret directly
            with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                mock_session_instance = MagicMock()
                mock_post = MagicMock()
                mock_session_instance.post = mock_post

                mock_response = MagicMock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value={"access_token": "direct_token"})
                mock_response.raise_for_status = MagicMock()
                mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                mock_response.__aexit__ = AsyncMock(return_value=None)

                mock_post.return_value = mock_response
                mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                mock_session_class.return_value = mock_session_instance

                result = await manager._client_credentials_flow(credentials)
                assert result == "direct_token"

    @pytest.mark.asyncio
    async def test_client_credentials_flow_decryption_returns_none(self):
        """Test client credentials flow when decryption returns None (line 108)."""
        manager = OAuthManager()

        encrypted_secret = "a" * 60  # Long secret

        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_encryption:
                mock_encryption = Mock()
                # Decryption returns None - line 108
                mock_encryption.decrypt_secret.return_value = None
                mock_get_encryption.return_value = mock_encryption

                with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                    mock_session_instance = MagicMock()
                    mock_post = MagicMock()
                    mock_session_instance.post = mock_post

                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.headers = {"content-type": "application/json"}
                    mock_response.json = AsyncMock(return_value={"access_token": "fallback_token"})
                    mock_response.raise_for_status = MagicMock()
                    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_response.__aexit__ = AsyncMock(return_value=None)

                    mock_post.return_value = mock_response
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await manager._client_credentials_flow(credentials)
                    assert result == "fallback_token"
                    mock_encryption.decrypt_secret.assert_called_once_with(encrypted_secret)

    @pytest.mark.asyncio
    async def test_client_credentials_flow_form_encoded_response(self):
        """Test client credentials flow with form-encoded response (lines 133-138)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
            # Form-encoded response that hits lines 133-138
            mock_response.text = AsyncMock(return_value="access_token=test_form_token&token_type=bearer&expires_in=3600")
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            result = await manager._client_credentials_flow(credentials)
            assert result == "test_form_token"

    @pytest.mark.asyncio
    async def test_client_credentials_flow_json_parse_failure(self):
        """Test client credentials flow when JSON parsing fails (lines 143-147)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            # JSON parsing fails, should fallback to text parsing (lines 143-147)
            mock_response.json = AsyncMock(side_effect=ValueError("Invalid JSON"))
            mock_response.text = AsyncMock(return_value="malformed response but contains access_token=fallback_token")
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            # This should raise an error because access_token won't be parsed from raw response
            with pytest.raises(OAuthError, match="No access_token in response"):
                await manager._client_credentials_flow(credentials)

    @pytest.mark.asyncio
    async def test_client_credentials_flow_missing_access_token(self):
        """Test client credentials flow when response missing access_token (line 150)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            # Response without access_token - line 150
            mock_response.json = AsyncMock(return_value={"token_type": "bearer", "expires_in": 3600})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with pytest.raises(OAuthError, match="No access_token in response"):
                await manager._client_credentials_flow(credentials)

    @pytest.mark.asyncio
    async def test_client_credentials_flow_final_fallback_error(self):
        """Test client credentials flow final fallback error (line 162)."""
        manager = OAuthManager(max_retries=0)  # Zero retries to force fallback

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            # Mock a non-ClientError exception that doesn't get caught in the retry loop
            mock_post.side_effect = RuntimeError("Unexpected error")
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            # This should reach the final fallback error on line 162
            with pytest.raises(OAuthError, match="Failed to obtain access token after all retry attempts"):
                await manager._client_credentials_flow(credentials)

    @pytest.mark.asyncio
    async def test_client_credentials_flow_with_retries(self):
        """Test client credentials flow with retry logic."""
        manager = OAuthManager(max_retries=3)

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            # First two calls fail, third succeeds
            fail_response = MagicMock()
            fail_response.status = 500
            fail_response.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=500, message="Server Error"))
            fail_response.__aenter__ = AsyncMock(return_value=fail_response)
            fail_response.__aexit__ = AsyncMock(return_value=None)

            success_response = MagicMock()
            success_response.status = 200
            success_response.json = AsyncMock(return_value={"access_token": "retry_success_token"})
            success_response.raise_for_status = MagicMock()
            success_response.__aenter__ = AsyncMock(return_value=success_response)
            success_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.side_effect = [fail_response, fail_response, success_response]
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with patch("asyncio.sleep") as mock_sleep:
                result = await manager._client_credentials_flow(credentials)
                assert result == "retry_success_token"
                assert mock_sleep.call_count == 2  # Should sleep before retries

    @pytest.mark.asyncio
    async def test_client_credentials_flow_max_retries_exceeded(self):
        """Test client credentials flow when all retries are exhausted."""
        manager = OAuthManager(max_retries=1)

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            fail_response = MagicMock()
            fail_response.status = 500
            fail_response.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=500, message="Server Error"))
            fail_response.__aenter__ = AsyncMock(return_value=fail_response)
            fail_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = fail_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with patch("asyncio.sleep"):
                with pytest.raises(OAuthError, match="Failed to obtain access token after 1 attempts"):
                    await manager._client_credentials_flow(credentials)

    @pytest.mark.asyncio
    async def test_initiate_authorization_code_flow_success(self):
        """Test successful initiation of authorization code flow with PKCE."""
        # Third-Party
        from pydantic import SecretStr

        # Mock settings to provide proper secret for HMAC
        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = SecretStr("test-secret-key-for-hmac")
            mock_get_settings.return_value = mock_settings

            mock_token_storage = Mock()
            manager = OAuthManager(token_storage=mock_token_storage)

            gateway_id = "gateway123"
            credentials = {"client_id": "test_client", "authorization_url": "https://oauth.example.com/authorize", "redirect_uri": "https://gateway.example.com/callback", "scopes": ["read", "write"]}

            result = await manager.initiate_authorization_code_flow(gateway_id, credentials, app_user_email="test@example.com")

            # With PKCE, the authorization URL now includes code_challenge and code_challenge_method
            assert "authorization_url" in result
            assert "state" in result
            assert "gateway_id" in result
            assert result["gateway_id"] == "gateway123"

            # Verify PKCE parameters are in the URL
            assert "code_challenge=" in result["authorization_url"]
            assert "code_challenge_method=S256" in result["authorization_url"]

    @pytest.mark.asyncio
    async def test_complete_authorization_code_flow_success(self):
        """Test successful completion of authorization code flow."""
        # Standard
        import base64
        import hashlib
        import hmac
        import json
        from unittest.mock import patch

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = SecretStr("test-secret-key")
            mock_get_settings.return_value = mock_settings

            mock_token_storage = Mock()
            manager = OAuthManager(token_storage=mock_token_storage)

            gateway_id = "gateway123"
            code = "auth_code_123"
            # Create state with new format and HMAC signature
            # Standard
            from datetime import datetime, timezone

            state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com", "nonce": "state456", "timestamp": datetime.now(timezone.utc).isoformat()}
            state_json = json.dumps(state_data, separators=(",", ":"))
            state_bytes = state_json.encode()

            # Create HMAC signature using the mocked secret
            secret_key = b"test-secret-key"
            signature = hmac.new(secret_key, state_bytes, hashlib.sha256).digest()

            # Combine state and signature
            state_with_sig = state_bytes + signature
            state = base64.urlsafe_b64encode(state_with_sig).decode()

            credentials = {"client_id": "test_client"}

            token_response = {"access_token": "access123", "refresh_token": "refresh123", "expires_in": 3600}

            # Store the state with code_verifier (PKCE) to make it valid
            await manager._store_authorization_state(gateway_id, state, code_verifier="test_code_verifier_123")

            with patch.object(manager, "_exchange_code_for_tokens") as mock_exchange:
                mock_exchange.return_value = token_response

                with patch.object(manager, "_extract_user_id") as mock_extract_user:
                    mock_extract_user.return_value = "user123"

                    with patch.object(mock_token_storage, "store_tokens", new_callable=AsyncMock) as mock_store_tokens:
                        mock_token_record = Mock()
                        mock_token_record.expires_at = None
                        mock_store_tokens.return_value = mock_token_record

                        result = await manager.complete_authorization_code_flow(gateway_id, code, state, credentials)

                        expected = {"user_id": "user123", "expires_at": None, "success": True}  # None because we set it to None in mock
                        assert result["user_id"] == expected["user_id"]
                        assert result["success"] == expected["success"]
                        assert result["expires_at"] == expected["expires_at"]

                        # PKCE: Now includes code_verifier parameter
                        mock_exchange.assert_called_once_with(credentials, code, code_verifier="test_code_verifier_123")
                        mock_extract_user.assert_called_once_with(token_response, credentials)
                        mock_store_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_authorization_code_flow_invalid_state(self):
        """Test authorization code flow completion with invalid state."""
        # Standard
        import base64
        import json

        mock_token_storage = Mock()
        manager = OAuthManager(token_storage=mock_token_storage)

        # Create state with mismatched gateway ID
        state_data = {"gateway_id": "wrong_gateway", "app_user_email": "test@example.com", "nonce": "state456"}
        state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/oauth/callback"}

        with pytest.raises(OAuthError):
            await manager.complete_authorization_code_flow("gateway123", "code", state, credentials)

    @pytest.mark.asyncio
    async def test_get_access_token_for_user_success(self):
        """Test getting access token for specific user."""
        mock_token_storage = Mock()
        mock_token_storage.get_user_token = AsyncMock(return_value="user_token_123")

        manager = OAuthManager(token_storage=mock_token_storage)

        result = await manager.get_access_token_for_user("gateway123", "test@example.com")

        assert result == "user_token_123"
        mock_token_storage.get_user_token.assert_called_once_with("gateway123", "test@example.com")

    @pytest.mark.asyncio
    async def test_get_access_token_for_user_not_found(self):
        """Test getting access token when user token not found."""
        mock_token_storage = Mock()
        mock_token_storage.get_user_token = AsyncMock(return_value=None)

        manager = OAuthManager(token_storage=mock_token_storage)

        result = await manager.get_access_token_for_user("gateway123", "test@example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_access_token_for_user_no_token_storage(self):
        """Test getting access token when no token storage is available."""
        manager = OAuthManager()  # No token_storage

        # Note: app_user_email is now used as the user identifier
        result = await manager.get_access_token_for_user("gateway123", "user@example.com")

        assert result is None

    def test_generate_state_format(self):
        """Test state generation format with HMAC signature."""
        # Standard
        import base64
        import hashlib
        import hmac
        import json
        from unittest.mock import Mock, patch

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = SecretStr("test-secret-key")
            mock_get_settings.return_value = mock_settings

            manager = OAuthManager()

            state = manager._generate_state("gateway123", "test@example.com")

            # State is now base64 encoded JSON with HMAC signature
            state_with_sig = base64.urlsafe_b64decode(state.encode())

            # Split state and signature (HMAC-SHA256 is 32 bytes)
            state_bytes = state_with_sig[:-32]
            received_signature = state_with_sig[-32:]

            # Verify HMAC signature
            secret_key = b"test-secret-key"  # Use the same secret we mocked
            expected_signature = hmac.new(secret_key, state_bytes, hashlib.sha256).digest()
            assert hmac.compare_digest(received_signature, expected_signature)

            # Parse and verify state data
            state_json = state_bytes.decode()
            decoded = json.loads(state_json)
            assert decoded["gateway_id"] == "gateway123"
            assert decoded["app_user_email"] == "test@example.com"
            assert "nonce" in decoded
            assert "timestamp" in decoded

            # Should generate different states each time (different nonce)
            state2 = manager._generate_state("gateway123", "test@example.com")
            assert state != state2

    @pytest.mark.asyncio
    async def test_store_authorization_state(self):
        """Test authorization state storage with expiration."""
        manager = OAuthManager()

        # Store a state
        await manager._store_authorization_state("gateway123", "state123")

        # Verify it can be validated
        result = await manager._validate_authorization_state("gateway123", "state123")
        assert result is True

        # Verify single-use: second validation should fail
        result = await manager._validate_authorization_state("gateway123", "state123")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_authorization_state_not_found(self):
        """Test authorization state validation for non-existent state."""
        manager = OAuthManager()

        # Try to validate a state that was never stored
        result = await manager._validate_authorization_state("gateway123", "nonexistent")
        assert result is False

    def test_create_authorization_url(self):
        """Test authorization URL creation."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "authorization_url": "https://oauth.example.com/authorize", "redirect_uri": "https://gateway.example.com/callback", "scopes": ["read", "write"]}
        state = "test_state"

        auth_url, returned_state = manager._create_authorization_url(credentials, state)

        assert returned_state == state
        assert "https://oauth.example.com/authorize" in auth_url
        assert "client_id=test_client" in auth_url
        assert "redirect_uri=" in auth_url
        assert "scope=read+write" in auth_url
        assert "state=test_state" in auth_url
        assert "response_type=code" in auth_url

    def test_create_authorization_url_no_scopes(self):
        """Test authorization URL creation without scopes."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "authorization_url": "https://oauth.example.com/authorize", "redirect_uri": "https://gateway.example.com/callback"}
        state = "test_state"

        auth_url, returned_state = manager._create_authorization_url(credentials, state)

        assert returned_state == state
        assert "scope=" not in auth_url  # No scope parameter when no scopes provided

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_success(self):
        """Test successful code exchange for tokens."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}
        code = "auth_code_123"

        expected_response = {"access_token": "access123", "refresh_token": "refresh123", "expires_in": 3600}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=expected_response)
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            result = await manager._exchange_code_for_tokens(credentials, code)

            assert result == expected_response

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_error(self):
        """Test code exchange when server returns error."""
        manager = OAuthManager(max_retries=1)  # Reduce retries for faster test execution

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}
        code = "invalid_code"

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 400
            mock_response.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=400, message="Bad Request"))
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with pytest.raises(OAuthError, match="Failed to exchange code for token after"):
                await manager._exchange_code_for_tokens(credentials, code)

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_decryption_returns_none(self):
        """Test _exchange_code_for_tokens when decryption returns None (lines 431-439)."""
        manager = OAuthManager()

        encrypted_secret = "a" * 60  # Long secret
        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_encryption:
                mock_encryption = Mock()
                # Decryption returns None - lines 438-439
                mock_encryption.decrypt_secret.return_value = None
                mock_get_encryption.return_value = mock_encryption

                with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                    mock_session_instance = MagicMock()
                    mock_post = MagicMock()
                    mock_session_instance.post = mock_post

                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.headers = {"content-type": "application/json"}
                    mock_response.json = AsyncMock(return_value={"access_token": "internal_exchange_token"})
                    mock_response.raise_for_status = MagicMock()
                    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_response.__aexit__ = AsyncMock(return_value=None)

                    mock_post.return_value = mock_response
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await manager._exchange_code_for_tokens(credentials, "auth_code")
                    assert result["access_token"] == "internal_exchange_token"
                    mock_encryption.decrypt_secret.assert_called_once_with(encrypted_secret)

    def test_extract_user_id_from_sub(self):
        """Test user ID extraction from token response 'sub' field."""
        manager = OAuthManager()

        token_response = {"sub": "user123", "access_token": "token"}
        credentials = {}

        result = manager._extract_user_id(token_response, credentials)
        assert result == "user123"

    def test_extract_user_id_from_user_id(self):
        """Test user ID extraction from token response 'user_id' field."""
        manager = OAuthManager()

        token_response = {"user_id": "user456", "access_token": "token"}
        credentials = {}

        result = manager._extract_user_id(token_response, credentials)
        assert result == "user456"

    def test_extract_user_id_from_id(self):
        """Test user ID extraction from token response 'id' field."""
        manager = OAuthManager()

        token_response = {"id": "user789", "access_token": "token"}
        credentials = {}

        result = manager._extract_user_id(token_response, credentials)
        assert result == "user789"

    def test_extract_user_id_fallback_to_client_id(self):
        """Test user ID extraction fallback to client_id."""
        manager = OAuthManager()

        token_response = {"access_token": "token"}
        credentials = {"client_id": "fallback_client"}

        result = manager._extract_user_id(token_response, credentials)
        assert result == "fallback_client"

    def test_extract_user_id_fallback_to_default(self):
        """Test user ID extraction fallback to default."""
        manager = OAuthManager()

        token_response = {"access_token": "token"}
        credentials = {}

        result = manager._extract_user_id(token_response, credentials)
        assert result == "unknown_user"

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_decryption_returns_none(self):
        """Test exchange code for token when decryption returns None (lines 209-219)."""
        manager = OAuthManager()

        encrypted_secret = "a" * 60  # Long secret
        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_encryption:
                mock_encryption = Mock()
                # Decryption returns None - lines 216-217
                mock_encryption.decrypt_secret.return_value = None
                mock_get_encryption.return_value = mock_encryption

                with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                    mock_session_instance = MagicMock()
                    mock_post = MagicMock()
                    mock_session_instance.post = mock_post

                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.headers = {"content-type": "application/json"}
                    mock_response.json = AsyncMock(return_value={"access_token": "exchange_token"})
                    mock_response.raise_for_status = MagicMock()
                    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_response.__aexit__ = AsyncMock(return_value=None)

                    mock_post.return_value = mock_response
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await manager.exchange_code_for_token(credentials, "auth_code", "state")
                    assert result == "exchange_token"
                    mock_encryption.decrypt_secret.assert_called_once_with(encrypted_secret)

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_form_encoded_response(self):
        """Test exchange code for token with form-encoded response (lines 241-246)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
            # Form-encoded response that hits lines 241-246
            mock_response.text = AsyncMock(return_value="access_token=exchange_form_token&refresh_token=refresh123")
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            result = await manager.exchange_code_for_token(credentials, "auth_code", "state")
            assert result == "exchange_form_token"

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_json_parse_failure(self):
        """Test exchange code for token when JSON parsing fails (lines 251-255)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            # JSON parsing fails, should fallback to text parsing (lines 251-255)
            mock_response.json = AsyncMock(side_effect=ValueError("Invalid JSON"))
            mock_response.text = AsyncMock(return_value="malformed exchange response")
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            # This should raise an error because access_token won't be found in raw response
            with pytest.raises(OAuthError, match="No access_token in response"):
                await manager.exchange_code_for_token(credentials, "auth_code", "state")

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_missing_access_token(self):
        """Test exchange code for token when response missing access_token (line 258)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            # Response without access_token - line 258
            mock_response.json = AsyncMock(return_value={"refresh_token": "refresh123", "expires_in": 3600})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with pytest.raises(OAuthError, match="No access_token in response"):
                await manager.exchange_code_for_token(credentials, "auth_code", "state")

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_retry_logic(self):
        """Test exchange code for token retry logic with backoff (lines 263-267)."""
        manager = OAuthManager(max_retries=2)

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            # First call fails with ClientError
            fail_response = MagicMock()
            fail_response.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=500, message="Server Error"))
            fail_response.__aenter__ = AsyncMock(return_value=fail_response)
            fail_response.__aexit__ = AsyncMock(return_value=None)

            # Second call succeeds
            success_response = MagicMock()
            success_response.status = 200
            success_response.headers = {"content-type": "application/json"}
            success_response.json = AsyncMock(return_value={"access_token": "retry_success_token"})
            success_response.raise_for_status = MagicMock()
            success_response.__aenter__ = AsyncMock(return_value=success_response)
            success_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.side_effect = [fail_response, success_response]
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with patch("asyncio.sleep") as mock_sleep:
                result = await manager.exchange_code_for_token(credentials, "auth_code", "state")
                assert result == "retry_success_token"
                # Should sleep once before retry (lines 263-267)
                mock_sleep.assert_called_once_with(1)  # 2^0 = 1

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_max_retries_exceeded(self):
        """Test exchange code for token when all retries are exhausted (lines 265-266)."""
        manager = OAuthManager(max_retries=1)

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            fail_response = MagicMock()
            fail_response.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=500, message="Server Error"))
            fail_response.__aenter__ = AsyncMock(return_value=fail_response)
            fail_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = fail_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with patch("asyncio.sleep"):
                with pytest.raises(OAuthError, match="Failed to exchange code for token after 1 attempts"):
                    await manager.exchange_code_for_token(credentials, "auth_code", "state")

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_final_fallback_error(self):
        """Test exchange code for token final fallback error (line 270)."""
        manager = OAuthManager(max_retries=0)  # Zero retries to force fallback

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            # Mock a non-ClientError exception that doesn't get caught in the retry loop
            mock_post.side_effect = RuntimeError("Unexpected error")
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            # This should reach the final fallback error on line 270
            with pytest.raises(OAuthError, match="Failed to exchange code for token after all retry attempts"):
                await manager.exchange_code_for_token(credentials, "auth_code", "state")

    @pytest.mark.asyncio
    async def test_complete_authorization_code_flow_no_token_storage(self):
        """Test complete authorization code flow without token storage with PKCE."""
        # Standard
        import base64
        import hashlib
        import hmac
        import json

        # Third-Party
        from pydantic import SecretStr

        # Mock settings to provide proper secret for HMAC
        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = SecretStr("test-secret-key-for-hmac")
            mock_get_settings.return_value = mock_settings

            manager = OAuthManager()  # No token storage

            gateway_id = "gateway123"
            code = "auth_code_123"

            # Create state with HMAC signature using the mocked secret
            # Standard
            from datetime import datetime, timezone

            state_data = {"gateway_id": "gateway123", "app_user_email": "test@example.com", "nonce": "state456", "timestamp": datetime.now(timezone.utc).isoformat()}
            state_json = json.dumps(state_data, separators=(",", ":"))
            state_bytes = state_json.encode()

            # Create HMAC signature using the same secret
            secret_key = b"test-secret-key-for-hmac"
            signature = hmac.new(secret_key, state_bytes, hashlib.sha256).digest()

            # Combine state and signature
            state_with_sig = state_bytes + signature
            state = base64.urlsafe_b64encode(state_with_sig).decode()

            credentials = {"client_id": "test_client", "token_url": "https://oauth.example.com/token", "redirect_uri": "http://localhost:4444/callback"}

            token_response = {"access_token": "access123", "refresh_token": "refresh123", "expires_in": 3600}

            # Mock state validation to return state data with code_verifier
            with patch.object(manager, "_validate_and_retrieve_state") as mock_validate:
                mock_validate.return_value = {"state": state, "gateway_id": gateway_id, "code_verifier": "test_verifier_abc123"}

                with patch.object(manager, "_exchange_code_for_tokens") as mock_exchange:
                    mock_exchange.return_value = token_response

                    with patch.object(manager, "_extract_user_id") as mock_extract_user:
                        mock_extract_user.return_value = "user123"

                        # This should work without token storage
                        result = await manager.complete_authorization_code_flow(gateway_id, code, state, credentials)

                        expected = {"success": True, "user_id": "user123", "expires_at": None}  # No token storage means no expiration tracking
                        assert result == expected

                        # PKCE: Now includes code_verifier parameter
                        mock_exchange.assert_called_once_with(credentials, code, code_verifier="test_verifier_abc123")
                        mock_extract_user.assert_called_once_with(token_response, credentials)

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_decryption_success(self):
        """Test _exchange_code_for_tokens when decryption succeeds (lines 435-437)."""
        manager = OAuthManager()

        encrypted_secret = "a" * 60  # Long secret
        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_encryption:
                mock_encryption = Mock()
                # Decryption succeeds - lines 435-437
                mock_encryption.decrypt_secret.return_value = "decrypted_secret"
                mock_get_encryption.return_value = mock_encryption

                with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                    mock_session_instance = MagicMock()
                    mock_post = MagicMock()
                    mock_session_instance.post = mock_post

                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.headers = {"content-type": "application/json"}
                    mock_response.json = AsyncMock(return_value={"access_token": "success_token"})
                    mock_response.raise_for_status = MagicMock()
                    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_response.__aexit__ = AsyncMock(return_value=None)

                    mock_post.return_value = mock_response
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await manager._exchange_code_for_tokens(credentials, "auth_code")
                    assert result["access_token"] == "success_token"
                    mock_encryption.decrypt_secret.assert_called_once_with(encrypted_secret)

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_decryption_exception(self):
        """Test _exchange_code_for_tokens when decryption throws exception (lines 440-441)."""
        manager = OAuthManager()

        encrypted_secret = "a" * 60  # Long secret
        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_encryption:
                mock_encryption = Mock()
                # Decryption throws exception - lines 440-441
                mock_encryption.decrypt_secret.side_effect = ValueError("Decryption failed")
                mock_get_encryption.return_value = mock_encryption

                with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                    mock_session_instance = MagicMock()
                    mock_post = MagicMock()
                    mock_session_instance.post = mock_post

                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.headers = {"content-type": "application/json"}
                    mock_response.json = AsyncMock(return_value={"access_token": "exception_token"})
                    mock_response.raise_for_status = MagicMock()
                    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_response.__aexit__ = AsyncMock(return_value=None)

                    mock_post.return_value = mock_response
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await manager._exchange_code_for_tokens(credentials, "auth_code")
                    assert result["access_token"] == "exception_token"
                    mock_encryption.decrypt_secret.assert_called_once_with(encrypted_secret)

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_form_encoded_response(self):
        """Test _exchange_code_for_tokens with form-encoded response (lines 463-468)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/x-www-form-urlencoded"}
            # Form-encoded response that hits lines 463-468
            mock_response.text = AsyncMock(return_value="access_token=internal_form_token&refresh_token=refresh123&expires_in=3600")
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            result = await manager._exchange_code_for_tokens(credentials, "auth_code")
            assert result["access_token"] == "internal_form_token"
            assert result["refresh_token"] == "refresh123"

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_json_parse_failure(self):
        """Test _exchange_code_for_tokens when JSON parsing fails (lines 473-477)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            # JSON parsing fails, should fallback to text parsing (lines 473-477)
            mock_response.json = AsyncMock(side_effect=ValueError("Invalid JSON"))
            mock_response.text = AsyncMock(return_value="malformed internal response")
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            # This should raise an error because access_token won't be found in raw response
            with pytest.raises(OAuthError, match="No access_token in response"):
                await manager._exchange_code_for_tokens(credentials, "auth_code")

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_missing_access_token(self):
        """Test _exchange_code_for_tokens when response missing access_token (line 480)."""
        manager = OAuthManager()

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            # Response without access_token - line 480
            mock_response.json = AsyncMock(return_value={"refresh_token": "refresh123", "expires_in": 3600})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with pytest.raises(OAuthError, match="No access_token in response"):
                await manager._exchange_code_for_tokens(credentials, "auth_code")

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_final_fallback_error(self):
        """Test _exchange_code_for_tokens final fallback error (line 492)."""
        manager = OAuthManager(max_retries=0)  # Zero retries to force fallback

        credentials = {"client_id": "test_client", "client_secret": "test_secret", "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            # Mock a non-ClientError exception that doesn't get caught in the retry loop
            mock_post.side_effect = RuntimeError("Unexpected error")
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            # This should reach the final fallback error on line 492
            with pytest.raises(OAuthError, match="Failed to exchange code for token after all retry attempts"):
                await manager._exchange_code_for_tokens(credentials, "auth_code")

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_decryption_success(self):
        """Test exchange code for token when decryption succeeds (lines 213-215)."""
        manager = OAuthManager()

        encrypted_secret = "a" * 60  # Long secret
        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_encryption:
                mock_encryption = Mock()
                # Decryption succeeds - lines 213-215
                mock_encryption.decrypt_secret.return_value = "decrypted_secret"
                mock_get_encryption.return_value = mock_encryption

                with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                    mock_session_instance = MagicMock()
                    mock_post = MagicMock()
                    mock_session_instance.post = mock_post

                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.headers = {"content-type": "application/json"}
                    mock_response.json = AsyncMock(return_value={"access_token": "exchange_success_token"})
                    mock_response.raise_for_status = MagicMock()
                    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_response.__aexit__ = AsyncMock(return_value=None)

                    mock_post.return_value = mock_response
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await manager.exchange_code_for_token(credentials, "auth_code", "state")
                    assert result == "exchange_success_token"
                    mock_encryption.decrypt_secret.assert_called_once_with(encrypted_secret)

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_decryption_exception(self):
        """Test exchange code for token when decryption throws exception (lines 218-219)."""
        manager = OAuthManager()

        encrypted_secret = "a" * 60  # Long secret
        credentials = {"client_id": "test_client", "client_secret": encrypted_secret, "token_url": "https://oauth.example.com/token", "redirect_uri": "https://gateway.example.com/callback"}

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.oauth_manager.get_encryption_service") as mock_get_encryption:
                mock_encryption = Mock()
                # Decryption throws exception - lines 218-219
                mock_encryption.decrypt_secret.side_effect = ValueError("Decryption failed")
                mock_get_encryption.return_value = mock_encryption

                with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
                    mock_session_instance = MagicMock()
                    mock_post = MagicMock()
                    mock_session_instance.post = mock_post

                    mock_response = MagicMock()
                    mock_response.status = 200
                    mock_response.headers = {"content-type": "application/json"}
                    mock_response.json = AsyncMock(return_value={"access_token": "exchange_exception_token"})
                    mock_response.raise_for_status = MagicMock()
                    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
                    mock_response.__aexit__ = AsyncMock(return_value=None)

                    mock_post.return_value = mock_response
                    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
                    mock_session_instance.__aexit__ = AsyncMock(return_value=None)
                    mock_session_class.return_value = mock_session_instance

                    result = await manager.exchange_code_for_token(credentials, "auth_code", "state")
                    assert result == "exchange_exception_token"
                    mock_encryption.decrypt_secret.assert_called_once_with(encrypted_secret)

    @pytest.mark.asyncio
    async def test_refresh_token_success(self):
        """Test successful token refresh."""
        manager = OAuthManager()

        credentials = {"token_url": "https://oauth.example.com/token", "client_id": "test_client", "client_secret": "test_secret"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"access_token": "new_access_token", "refresh_token": "new_refresh_token", "expires_in": 7200})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            result = await manager.refresh_token("old_refresh_token", credentials)

            assert result == {"access_token": "new_access_token", "refresh_token": "new_refresh_token", "expires_in": 7200}

            # Verify the correct data was sent
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://oauth.example.com/token"
            assert call_args[1]["data"]["grant_type"] == "refresh_token"
            assert call_args[1]["data"]["refresh_token"] == "old_refresh_token"
            assert call_args[1]["data"]["client_id"] == "test_client"

    @pytest.mark.asyncio
    async def test_refresh_token_with_client_secret(self):
        """Test token refresh with client secret included."""
        manager = OAuthManager()

        credentials = {"token_url": "https://oauth.example.com/token", "client_id": "test_client", "client_secret": "test_secret"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"access_token": "new_token"})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            await manager.refresh_token("refresh_token", credentials)

            # Verify client secret was included
            call_args = mock_post.call_args
            assert call_args[1]["data"]["client_secret"] == "test_secret"

    @pytest.mark.asyncio
    async def test_refresh_token_error_handling(self):
        """Test token refresh error handling."""
        manager = OAuthManager()

        credentials = {"token_url": "https://oauth.example.com/token", "client_id": "test_client"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 400
            mock_response.json = AsyncMock(return_value={"error": "invalid_grant"})
            mock_response.text = AsyncMock(return_value='{"error": "invalid_grant"}')
            mock_response.raise_for_status = MagicMock(side_effect=aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=400))
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with pytest.raises(OAuthError) as exc_info:
                await manager.refresh_token("invalid_token", credentials)

            assert "Refresh token invalid or expired" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_refresh_token_missing_access_token(self):
        """Test token refresh when access_token is missing from response."""
        manager = OAuthManager()

        credentials = {"token_url": "https://oauth.example.com/token", "client_id": "test_client"}

        with patch("mcpgateway.services.oauth_manager.aiohttp.ClientSession") as mock_session_class:
            mock_session_instance = MagicMock()
            mock_post = MagicMock()
            mock_session_instance.post = mock_post

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"expires_in": 3600})  # Missing access_token
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_post.return_value = mock_response
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session_instance

            with pytest.raises(OAuthError) as exc_info:
                await manager.refresh_token("refresh_token", credentials)

            assert "No access_token in refresh response" in str(exc_info.value)


class TestTokenStorageService:
    """Test cases for TokenStorageService class."""

    def test_init_with_encryption(self):
        """Test TokenStorageService initialization with encryption."""
        mock_db = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_secret_key"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.token_storage_service.get_encryption_service") as mock_get_enc:
                mock_encryption = Mock()
                mock_get_enc.return_value = mock_encryption

                service = TokenStorageService(mock_db)

                assert service.db == mock_db
                assert service.encryption == mock_encryption
                mock_get_enc.assert_called_once_with("test_secret_key")

    def test_init_without_encryption(self):
        """Test TokenStorageService initialization without encryption."""
        mock_db = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption available")

            service = TokenStorageService(mock_db)

            assert service.db == mock_db
            assert service.encryption is None

    def test_init_attribute_error(self):
        """Test TokenStorageService initialization with AttributeError."""
        mock_db = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = AttributeError("Missing attribute")

            service = TokenStorageService(mock_db)

            assert service.db == mock_db
            assert service.encryption is None

    @pytest.mark.asyncio
    async def test_store_tokens_new_record_with_encryption(self):
        """Test storing new OAuth tokens with encryption."""
        mock_db = Mock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        mock_encryption = Mock()
        mock_encryption.encrypt_secret.side_effect = ["encrypted_access", "encrypted_refresh"]

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_secret"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.token_storage_service.get_encryption_service") as mock_get_enc:
                mock_get_enc.return_value = mock_encryption

                service = TokenStorageService(mock_db)

                # Mock datetime.now for consistent testing
                fixed_time = datetime(2025, 1, 1, 12, 0, 0)
                with patch("mcpgateway.services.token_storage_service.datetime") as mock_dt:
                    mock_dt.now.return_value = fixed_time
                    mock_dt.now.return_value = fixed_time

                    result = await service.store_tokens(
                        gateway_id="gateway123",
                        user_id="user123",
                        app_user_email="test@example.com",
                        access_token="access_token_123",
                        refresh_token="refresh_token_123",
                        expires_in=3600,
                        scopes=["read", "write"],
                    )

                    # Verify encryption calls
                    mock_encryption.encrypt_secret.assert_any_call("access_token_123")
                    mock_encryption.encrypt_secret.assert_any_call("refresh_token_123")

                    # Verify database operations
                    mock_db.add.assert_called_once()
                    mock_db.commit.assert_called_once()

                    # Get the OAuthToken that was added
                    added_token = mock_db.add.call_args[0][0]
                    assert added_token.gateway_id == "gateway123"
                    assert added_token.user_id == "user123"
                    assert added_token.access_token == "encrypted_access"
                    assert added_token.refresh_token == "encrypted_refresh"
                    assert added_token.scopes == ["read", "write"]

    @pytest.mark.asyncio
    async def test_store_tokens_new_record_without_encryption(self):
        """Test storing new OAuth tokens without encryption."""
        mock_db = Mock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            fixed_time = datetime(2025, 1, 1, 12, 0, 0)
            with patch("mcpgateway.services.token_storage_service.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_time
                mock_dt.now.return_value = fixed_time

                result = await service.store_tokens(
                    gateway_id="gateway123",
                    user_id="user123",
                    app_user_email="test@example.com",
                    access_token="access_token_123",
                    refresh_token="refresh_token_123",
                    expires_in=3600,
                    scopes=["read", "write"],
                )

                # Verify database operations
                mock_db.add.assert_called_once()
                mock_db.commit.assert_called_once()

                # Get the OAuthToken that was added
                added_token = mock_db.add.call_args[0][0]
                assert added_token.gateway_id == "gateway123"
                assert added_token.user_id == "user123"
                assert added_token.access_token == "access_token_123"
                assert added_token.refresh_token == "refresh_token_123"
                assert added_token.scopes == ["read", "write"]

    @pytest.mark.asyncio
    async def test_store_tokens_update_existing_record(self):
        """Test updating existing OAuth tokens."""
        mock_db = Mock()

        # Create existing token record
        existing_token = OAuthToken(
            gateway_id="gateway123",
            user_id="user123",
            access_token="old_access",
            refresh_token="old_refresh",
            expires_at=datetime(2025, 1, 1, 10, 0, 0),
            scopes=["read"],
            created_at=datetime(2025, 1, 1, 9, 0, 0),
            updated_at=datetime(2025, 1, 1, 9, 0, 0),
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = existing_token

        mock_encryption = Mock()
        mock_encryption.encrypt_secret.side_effect = ["encrypted_access", "encrypted_refresh"]

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_secret"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.token_storage_service.get_encryption_service") as mock_get_enc:
                mock_get_enc.return_value = mock_encryption

                service = TokenStorageService(mock_db)

                fixed_time = datetime(2025, 1, 1, 12, 0, 0)
                with patch("mcpgateway.services.token_storage_service.datetime") as mock_dt:
                    mock_dt.now.return_value = fixed_time
                    mock_dt.now.return_value = fixed_time

                    result = await service.store_tokens(
                        gateway_id="gateway123",
                        user_id="user123",
                        app_user_email="test@example.com",
                        access_token="new_access_token",
                        refresh_token="new_refresh_token",
                        expires_in=3600,
                        scopes=["read", "write", "admin"],
                    )

                    # Verify existing token was updated
                    assert existing_token.access_token == "encrypted_access"
                    assert existing_token.refresh_token == "encrypted_refresh"
                    assert existing_token.scopes == ["read", "write", "admin"]
                    assert existing_token.updated_at == fixed_time

                    # Verify no new record was added
                    mock_db.add.assert_not_called()
                    mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_tokens_without_refresh_token(self):
        """Test storing tokens without refresh token."""
        mock_db = Mock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        mock_encryption = Mock()
        mock_encryption.encrypt_secret.return_value = "encrypted_access"

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_secret"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.token_storage_service.get_encryption_service") as mock_get_enc:
                mock_get_enc.return_value = mock_encryption

                service = TokenStorageService(mock_db)

                fixed_time = datetime(2025, 1, 1, 12, 0, 0)
                with patch("mcpgateway.services.token_storage_service.datetime") as mock_dt:
                    mock_dt.now.return_value = fixed_time
                    mock_dt.now.return_value = fixed_time

                    result = await service.store_tokens(
                        gateway_id="gateway123", user_id="user123", app_user_email="test@example.com", access_token="access_token_123", refresh_token=None, expires_in=3600, scopes=["read"]
                    )

                    # Verify only access token was encrypted
                    mock_encryption.encrypt_secret.assert_called_once_with("access_token_123")

                    added_token = mock_db.add.call_args[0][0]
                    assert added_token.access_token == "encrypted_access"
                    assert added_token.refresh_token is None

    @pytest.mark.asyncio
    async def test_store_tokens_database_error(self):
        """Test error handling during token storage."""
        mock_db = Mock()
        mock_db.execute.side_effect = Exception("Database error")

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            with pytest.raises(OAuthError, match="Token storage failed: Database error"):
                await service.store_tokens(
                    gateway_id="gateway123", user_id="user123", app_user_email="test@example.com", access_token="access_token_123", refresh_token="refresh_token_123", expires_in=3600, scopes=["read"]
                )

            mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_valid_token_success_with_encryption(self):
        """Test getting valid token with encryption."""
        mock_db = Mock()

        # Create valid token record
        future_time = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="encrypted_token", refresh_token="encrypted_refresh", expires_at=future_time, scopes=["read", "write"])
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        mock_encryption = Mock()
        mock_encryption.decrypt_secret.return_value = "decrypted_access_token"

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_settings = Mock()
            mock_settings.auth_encryption_secret = "test_secret"
            mock_get_settings.return_value = mock_settings

            with patch("mcpgateway.services.token_storage_service.get_encryption_service") as mock_get_enc:
                mock_get_enc.return_value = mock_encryption

                service = TokenStorageService(mock_db)

                result = await service.get_user_token("gateway123", "test@example.com")

                assert result == "decrypted_access_token"
                mock_encryption.decrypt_secret.assert_called_once_with("encrypted_token")

    @pytest.mark.asyncio
    async def test_get_valid_token_success_without_encryption(self):
        """Test getting valid token without encryption."""
        mock_db = Mock()

        future_time = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="plain_access_token", refresh_token="plain_refresh", expires_at=future_time, scopes=["read", "write"])
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.get_user_token("gateway123", "test@example.com")

            assert result == "plain_access_token"

    @pytest.mark.asyncio
    async def test_get_valid_token_not_found(self):
        """Test getting token when no record exists."""
        mock_db = Mock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.get_user_token("gateway123", "test@example.com")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_token_expired_with_refresh(self):
        """Test getting expired token with refresh token available."""
        mock_db = Mock()

        # Create expired token record
        past_time = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="expired_token", refresh_token="refresh_token", expires_at=past_time, scopes=["read", "write"])
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            # Mock the _refresh_access_token method
            with patch.object(service, "_refresh_access_token") as mock_refresh:
                mock_refresh.return_value = "new_access_token"

                result = await service.get_user_token("gateway123", "test@example.com")

                assert result == "new_access_token"
                mock_refresh.assert_called_once_with(token_record)

    @pytest.mark.asyncio
    async def test_get_valid_token_expired_no_refresh(self):
        """Test getting expired token without refresh token."""
        mock_db = Mock()

        past_time = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="expired_token", refresh_token=None, expires_at=past_time, scopes=["read", "write"])
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.get_user_token("gateway123", "test@example.com")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_token_near_expiry(self):
        """Test getting token near expiry (within threshold)."""
        mock_db = Mock()

        # Token expires in 2 minutes, threshold is 5 minutes (300 seconds)
        near_expiry = datetime.now(tz=timezone.utc) + timedelta(minutes=2)
        token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="near_expiry_token", refresh_token="refresh_token", expires_at=near_expiry, scopes=["read", "write"])
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            # Mock the _refresh_access_token method
            with patch.object(service, "_refresh_access_token") as mock_refresh:
                mock_refresh.return_value = "refreshed_token"

                result = await service.get_user_token("gateway123", "test@example.com", threshold_seconds=300)

                assert result == "refreshed_token"
                mock_refresh.assert_called_once_with(token_record)

    @pytest.mark.asyncio
    async def test_get_valid_token_exception(self):
        """Test exception handling in get_valid_token."""
        mock_db = Mock()
        mock_db.execute.side_effect = Exception("Database error")

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.get_user_token("gateway123", "test@example.com")

            assert result is None

    @pytest.mark.asyncio
    async def test_refresh_access_token_success(self):
        """Test successful token refresh in TokenStorageService."""
        # First-Party
        from mcpgateway.db import Gateway

        mock_db = Mock()

        # Create a mock gateway with OAuth config
        mock_gateway = Gateway(id="gateway123", name="Test Gateway", oauth_config={"token_url": "https://oauth.example.com/token", "client_id": "test_client", "client_secret": "test_secret"})
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway
        mock_db.commit = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = OAuthToken(
                gateway_id="gateway123",
                user_id="user123",
                app_user_email="test@example.com",
                access_token="expired_token",
                refresh_token="old_refresh_token",
                expires_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
            )

            # Mock the OAuthManager refresh_token method
            with patch("mcpgateway.services.oauth_manager.OAuthManager") as mock_oauth_manager_class:
                mock_manager = mock_oauth_manager_class.return_value
                mock_manager.refresh_token = AsyncMock(return_value={"access_token": "new_access_token", "refresh_token": "new_refresh_token", "expires_in": 7200})

                result = await service._refresh_access_token(token_record)

                assert result == "new_access_token"
                assert token_record.access_token == "new_access_token"
                assert token_record.refresh_token == "new_refresh_token"
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_access_token_no_refresh_token(self):
        """Test refresh when no refresh token is available."""
        mock_db = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = OAuthToken(
                gateway_id="gateway123",
                user_id="user123",
                access_token="expired_token",
                refresh_token=None,
                expires_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),  # No refresh token
            )

            result = await service._refresh_access_token(token_record)

            assert result is None

    @pytest.mark.asyncio
    async def test_refresh_access_token_no_gateway(self):
        """Test refresh when gateway is not found."""
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = None  # Gateway not found

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = OAuthToken(
                gateway_id="gateway123", user_id="user123", access_token="expired_token", refresh_token="refresh_token", expires_at=datetime.now(tz=timezone.utc) - timedelta(hours=1)
            )

            result = await service._refresh_access_token(token_record)

            assert result is None

    @pytest.mark.asyncio
    async def test_refresh_access_token_invalid_token(self):
        """Test refresh with invalid refresh token."""
        # First-Party
        from mcpgateway.db import Gateway

        mock_db = Mock()
        mock_db.delete = Mock()
        mock_db.commit = Mock()

        # Create a mock gateway with OAuth config
        mock_gateway = Gateway(id="gateway123", name="Test Gateway", oauth_config={"token_url": "https://oauth.example.com/token", "client_id": "test_client", "client_secret": "test_secret"})
        mock_db.query.return_value.filter.return_value.first.return_value = mock_gateway

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = OAuthToken(
                gateway_id="gateway123",
                user_id="user123",
                app_user_email="test@example.com",
                access_token="expired_token",
                refresh_token="invalid_refresh_token",
                expires_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
            )

            # Mock the OAuthManager refresh_token method to raise an error
            with patch("mcpgateway.services.oauth_manager.OAuthManager") as mock_oauth_manager_class:
                mock_manager = mock_oauth_manager_class.return_value
                mock_manager.refresh_token = AsyncMock(side_effect=Exception("Refresh token invalid or expired"))

                result = await service._refresh_access_token(token_record)

                assert result is None
                # Should delete the invalid token
                mock_db.delete.assert_called_once_with(token_record)
                mock_db.commit.assert_called_once()

    def test_is_token_expired_no_expires_at(self):
        """Test _is_token_expired with no expiration date."""
        mock_db = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="token", expires_at=None)

            result = service._is_token_expired(token_record)

            assert result is False

    def test_is_token_expired_past_expiry(self):
        """Test _is_token_expired with past expiration."""
        mock_db = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            past_time = datetime.now(tz=timezone.utc) - timedelta(hours=1)
            token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="token", expires_at=past_time)

            result = service._is_token_expired(token_record)

            assert result is True

    def test_is_token_expired_within_threshold(self):
        """Test _is_token_expired with token expiring within threshold."""
        mock_db = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            # Token expires in 2 minutes, threshold is 5 minutes
            near_expiry = datetime.now(tz=timezone.utc) + timedelta(minutes=2)
            token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="token", expires_at=near_expiry)

            result = service._is_token_expired(token_record, threshold_seconds=300)

            assert result is True

    def test_is_token_expired_beyond_threshold(self):
        """Test _is_token_expired with token valid beyond threshold."""
        mock_db = Mock()

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            # Token expires in 10 minutes, threshold is 5 minutes
            future_time = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
            token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="token", expires_at=future_time)

            result = service._is_token_expired(token_record, threshold_seconds=300)

            assert result is False

    @pytest.mark.asyncio
    async def test_get_token_info_success(self):
        """Test getting token information successfully."""
        mock_db = Mock()

        created_time = datetime(2025, 1, 1, 10, 0, 0)
        updated_time = datetime(2025, 1, 1, 11, 0, 0)
        expires_time = datetime(2025, 1, 1, 15, 0, 0)

        token_record = OAuthToken(
            gateway_id="gateway123",
            user_id="user123",
            app_user_email="test@example.com",
            access_token="token",
            token_type="Bearer",
            expires_at=expires_time,
            scopes=["read", "write"],
            created_at=created_time,
            updated_at=updated_time,
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            # Mock is_expired check to return False
            with patch.object(service, "_is_token_expired") as mock_is_expired:
                mock_is_expired.return_value = False

                result = await service.get_token_info("gateway123", "test@example.com")

                expected = {
                    "user_id": "user123",
                    "app_user_email": "test@example.com",
                    "token_type": "Bearer",
                    "expires_at": "2025-01-01T15:00:00",
                    "scopes": ["read", "write"],
                    "created_at": "2025-01-01T10:00:00",
                    "updated_at": "2025-01-01T11:00:00",
                    "is_expired": False,
                }

                assert result == expected
                mock_is_expired.assert_called_once_with(token_record, 0)

    @pytest.mark.asyncio
    async def test_get_token_info_not_found(self):
        """Test getting token info when token doesn't exist."""
        mock_db = Mock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.get_token_info("gateway123", "user123")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_token_info_with_none_expires_at(self):
        """Test getting token info with None expires_at."""
        mock_db = Mock()

        token_record = OAuthToken(
            gateway_id="gateway123",
            user_id="user123",
            access_token="token",
            token_type="Bearer",
            expires_at=None,
            scopes=["read"],
            created_at=datetime(2025, 1, 1, 10, 0, 0),
            updated_at=datetime(2025, 1, 1, 11, 0, 0),
        )
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            with patch.object(service, "_is_token_expired") as mock_is_expired:
                mock_is_expired.return_value = True

                result = await service.get_token_info("gateway123", "test@example.com")

                assert result["expires_at"] is None
                assert result["is_expired"] is True

    @pytest.mark.asyncio
    async def test_get_token_info_exception(self):
        """Test exception handling in get_token_info."""
        mock_db = Mock()
        mock_db.execute.side_effect = Exception("Database error")

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.get_token_info("gateway123", "user123")

            assert result is None

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_success(self):
        """Test successfully revoking user tokens."""
        mock_db = Mock()

        token_record = OAuthToken(gateway_id="gateway123", user_id="user123", access_token="token")
        mock_db.execute.return_value.scalar_one_or_none.return_value = token_record

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.revoke_user_tokens("gateway123", "user123")

            assert result is True
            mock_db.delete.assert_called_once_with(token_record)
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_not_found(self):
        """Test revoking tokens when no tokens exist."""
        mock_db = Mock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.revoke_user_tokens("gateway123", "user123")

            assert result is False
            mock_db.delete.assert_not_called()
            mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_user_tokens_exception(self):
        """Test exception handling in revoke_user_tokens."""
        mock_db = Mock()
        mock_db.execute.side_effect = Exception("Database error")

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.revoke_user_tokens("gateway123", "user123")

            assert result is False
            mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_success(self):
        """Test successfully cleaning up expired tokens."""
        mock_db = Mock()

        # Create list of expired tokens
        expired_token1 = OAuthToken(gateway_id="gateway1", user_id="user1")
        expired_token2 = OAuthToken(gateway_id="gateway2", user_id="user2")
        expired_tokens = [expired_token1, expired_token2]

        mock_db.execute.return_value.scalars.return_value.all.return_value = expired_tokens

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            with patch("mcpgateway.services.token_storage_service.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0, 0)
                mock_dt.now.return_value = datetime(2025, 1, 1, 12, 0, 0)

                result = await service.cleanup_expired_tokens(max_age_days=30)

                assert result == 2
                assert mock_db.delete.call_count == 2
                mock_db.delete.assert_any_call(expired_token1)
                mock_db.delete.assert_any_call(expired_token2)
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_none_found(self):
        """Test cleanup when no expired tokens exist."""
        mock_db = Mock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.cleanup_expired_tokens(max_age_days=30)

            assert result == 0
            mock_db.delete.assert_not_called()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_exception(self):
        """Test exception handling in cleanup_expired_tokens."""
        mock_db = Mock()
        mock_db.execute.side_effect = Exception("Database error")

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_get_settings.side_effect = ImportError("No encryption")

            service = TokenStorageService(mock_db)

            result = await service.cleanup_expired_tokens(max_age_days=30)

            assert result == 0
            mock_db.rollback.assert_called_once()


class TestEncryptionService:
    """Test cases for EncryptionService class."""

    def test_init(self):
        """Test EncryptionService initialization."""
        encryption = EncryptionService(SecretStr("test_secret_key"))
        assert encryption.encryption_secret == b"test_secret_key"

    def test_encrypt_secret_success(self):
        """Test successful secret encryption."""
        encryption = EncryptionService(SecretStr("test_secret_key"))
        plaintext = "my_secret_token_123"

        encrypted = encryption.encrypt_secret(plaintext)

        # Should be a base64-encoded string
        assert isinstance(encrypted, str)
        assert len(encrypted) > len(plaintext)  # Encrypted data should be longer

        # Should be able to decrypt back to original
        decrypted = encryption.decrypt_secret(encrypted)
        assert decrypted == plaintext

    def test_encrypt_secret_different_keys_different_output(self):
        """Test that different keys produce different encrypted output."""
        encryption1 = EncryptionService(SecretStr("key1"))
        encryption2 = EncryptionService(SecretStr("key2"))
        plaintext = "same_secret"

        encrypted1 = encryption1.encrypt_secret(plaintext)
        encrypted2 = encryption2.encrypt_secret(plaintext)

        # Different keys should produce different encrypted output
        assert encrypted1 != encrypted2

    def test_encrypt_secret_same_key_different_output(self):
        """Test that same key produces different encrypted output due to nonce."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "same_secret"

        encrypted1 = encryption.encrypt_secret(plaintext)
        encrypted2 = encryption.encrypt_secret(plaintext)

        # Same plaintext with same key should produce different output (due to nonce)
        assert encrypted1 != encrypted2

        # But both should decrypt to the same plaintext
        assert encryption.decrypt_secret(encrypted1) == plaintext
        assert encryption.decrypt_secret(encrypted2) == plaintext

    def test_encrypt_secret_empty_string(self):
        """Test encrypting empty string."""
        encryption = EncryptionService(SecretStr("test_key"))

        encrypted = encryption.encrypt_secret("")
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == ""

    def test_encrypt_secret_unicode_characters(self):
        """Test encrypting string with unicode characters."""
        encryption = EncryptionService(SecretStr("test_key"))
        plaintext = "🔐 secret with émojis and spéciàl chars ñ"

        encrypted = encryption.encrypt_secret(plaintext)
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == plaintext

    def test_encrypt_secret_exception_handling(self):
        """Test exception handling in encrypt_secret."""
        encryption = EncryptionService(SecretStr("test_key"))

        with patch.object(encryption, "derive_key_argon2id", side_effect=Exception("Encryption failed")):
            with pytest.raises(Exception, match="Encryption failed"):
                encryption.encrypt_secret("test")

    def test_decrypt_secret_success(self):
        """Test successful secret decryption."""
        encryption = EncryptionService(SecretStr("test_secret_key"))
        plaintext = "original_secret"

        # First encrypt
        encrypted = encryption.encrypt_secret(plaintext)

        # Then decrypt
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == plaintext

    def test_decrypt_secret_invalid_data(self):
        """Test decryption with invalid encrypted data."""
        encryption = EncryptionService(SecretStr("test_key"))

        result = encryption.decrypt_secret("invalid_encrypted_data")

        assert result is None

    def test_decrypt_secret_wrong_key(self):
        """Test decryption with wrong key."""
        encryption1 = EncryptionService(SecretStr("key1"))
        encryption2 = EncryptionService(SecretStr("key2"))

        # Encrypt with one key
        encrypted = encryption1.encrypt_secret("secret")

        # Try to decrypt with different key
        result = encryption2.decrypt_secret(encrypted)

        assert result is None

    def test_decrypt_secret_corrupted_data(self):
        """Test decryption with corrupted base64 data."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Create valid encrypted data then corrupt it
        encrypted = encryption.encrypt_secret("test")
        corrupted = encrypted[:-5] + "XXXXX"  # Corrupt the end

        result = encryption.decrypt_secret(corrupted)

        assert result is None

    def test_decrypt_secret_malformed_base64(self):
        """Test decryption with malformed base64."""
        encryption = EncryptionService(SecretStr("test_key"))

        result = encryption.decrypt_secret("not_valid_base64!@#")

        assert result is None

    def test_decrypt_secret_empty_string(self):
        """Test decryption with empty string."""
        encryption = EncryptionService(SecretStr("test_key"))

        result = encryption.decrypt_secret("")

        assert result is None

    def test_is_encrypted_valid_encrypted_data(self):
        """Test is_encrypted with valid encrypted data."""
        encryption = EncryptionService(SecretStr("test_key"))

        encrypted = encryption.encrypt_secret("test_data")

        assert encryption.is_encrypted(encrypted) is True

    def test_is_encrypted_plain_text(self):
        """Test is_encrypted with plain text."""
        encryption = EncryptionService(SecretStr("test_key"))

        assert encryption.is_encrypted("plain_text_secret") is False
        assert encryption.is_encrypted("another_plain_string") is False

    def test_is_encrypted_short_data(self):
        """Test is_encrypted with short data."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Fernet encrypted data should be at least 32 bytes
        short_data = "dGVzdA=="  # "test" in base64 (only 4 bytes when decoded)

        assert encryption.is_encrypted(short_data) is False

    def test_is_encrypted_valid_base64_but_not_encrypted(self):
        """Test is_encrypted with valid base64 that's not encrypted data."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Create base64 data that's long enough but not encrypted
        # Standard
        import base64

        fake_data = b"a" * 40  # 40 bytes of 'a'
        base64_fake = base64.urlsafe_b64encode(fake_data).decode()

        # This should be considered "encrypted" based on length, but won't decrypt properly
        assert encryption.is_encrypted(base64_fake) is True

        # But decryption should fail
        assert encryption.decrypt_secret(base64_fake) is None

    def test_is_encrypted_invalid_base64(self):
        """Test is_encrypted with invalid base64."""
        encryption = EncryptionService(SecretStr("test_key"))

        assert encryption.is_encrypted("not_base64!@#$%") is False

    def test_is_encrypted_exception_handling(self):
        """Test exception handling in is_encrypted."""
        encryption = EncryptionService(SecretStr("test_key"))

        # Test with None (should handle gracefully)
        with patch("base64.urlsafe_b64decode", side_effect=Exception("Base64 error")):
            result = encryption.is_encrypted("any_string")
            assert result is False

    def test_get_encryption_service_function(self):
        """Test the get_encryption_service utility function."""
        # First-Party
        from mcpgateway.services.encryption_service import get_encryption_service

        encryption = get_encryption_service(SecretStr("test_secret"))

        assert isinstance(encryption, EncryptionService)
        assert encryption.encryption_secret == b"test_secret"

    def test_encryption_roundtrip_multiple_values(self):
        """Test encryption/decryption roundtrip with multiple values."""
        encryption = EncryptionService(SecretStr("test_key"))

        test_values = [
            "simple_token",
            "complex_token_with_special_chars_123!@#",
            "very_long_token_" * 100,  # Very long token
            "token_with_newlines\n\r\t",
            "token with spaces and symbols: !@#$%^&*()",
            "🔐🗝️🔑 tokens with emojis",
        ]

        for original in test_values:
            encrypted = encryption.encrypt_secret(original)
            decrypted = encryption.decrypt_secret(encrypted)

            assert decrypted == original, f"Failed for: {original}"
            assert encryption.is_encrypted(encrypted) is True

    def test_encryption_key_derivation_consistency(self):
        """Test that key derivation is consistent across instances."""
        # Create two instances with same key
        encryption1 = EncryptionService(SecretStr("same_key"))
        encryption2 = EncryptionService(SecretStr("same_key"))

        # Encrypt with first instance
        plaintext = "test_consistency"
        encrypted = encryption1.encrypt_secret(plaintext)

        # Decrypt with second instance
        decrypted = encryption2.decrypt_secret(encrypted)

        assert decrypted == plaintext

    def test_encryption_with_long_key(self):
        """Test encryption with very long key."""
        long_key = SecretStr("a" * 1000)  # Very long key
        encryption = EncryptionService(long_key)

        encrypted = encryption.encrypt_secret("test_data")
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == "test_data"

    def test_encryption_with_special_char_key(self):
        """Test encryption with key containing special characters."""
        special_key = SecretStr("key_with_special_chars!@#$%^&*()_+-={}[]|\\:;\"'<>?,./")
        encryption = EncryptionService(special_key)

        encrypted = encryption.encrypt_secret("test_data")
        decrypted = encryption.decrypt_secret(encrypted)

        assert decrypted == "test_data"
