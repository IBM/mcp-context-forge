# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_oauth_authorization_code_health.py
Copyright contributors to the MCP-CONTEXT-FORGE project
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


class TestAuthorizationCodeStreamableHTTP:
    """Test that 401/403 from a streamablehttp-transport authorization_code gateway
    is treated as 'reachable, unauthorized' (Issue #5237, streamablehttp path).

    The MCP SDK's streamablehttp_client spawns its HTTP POST inside an anyio
    TaskGroup. Exceptions from the task surface at the ``async with`` boundary
    wrapped in a BaseExceptionGroup. The fix unwraps one level so the inner
    httpx.HTTPStatusError is inspected for 401/403.
    """

    @pytest.mark.asyncio
    async def test_streamablehttp_401_treated_as_reachable(self):
        """401 wrapped in BaseExceptionGroup (streamablehttp) should not mark gateway unhealthy."""
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()
        service.set_gateway_state = AsyncMock()

        gateway = MagicMock(spec=DbGateway)
        gateway.id = "gw-streamable"
        gateway.name = "Streamable Gateway"
        gateway.url = "https://mcp.example.com/v1/mcp"
        gateway.transport = "streamablehttp"
        gateway.auth_type = "oauth"
        gateway.oauth_config = {"grant_type": "authorization_code"}
        gateway.enabled = True
        gateway.reachable = False
        gateway.auth_value = None
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None

        # Build the 401 HTTPStatusError as it would come from the MCP SDK task group:
        # wrapped one level deep in a BaseExceptionGroup.
        mock_response = MagicMock()
        mock_response.status_code = 401
        inner_exc = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=mock_response)
        wrapped_exc = BaseExceptionGroup("task group error", [inner_exc])

        update_db = MagicMock()
        mock_db_gateway = MagicMock()
        update_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_db_gateway)))

        class _TokenDBCM:
            def __enter__(self):
                return MagicMock()
            def __exit__(self, *exc):
                return False

        class _UpdateDBCM:
            def __enter__(self):
                return update_db
            def __exit__(self, *exc):
                return False

        class _StatusDBCM:
            def __enter__(self):
                return MagicMock()
            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                return MagicMock()
            async def __aexit__(self, *exc):
                return False

        with (
            patch("mcpgateway.services.gateway_service.settings", MagicMock(enable_ed25519_signing=False, health_check_timeout=5)),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            # streamablehttp_client is called directly (not via the httpx client),
            # so we patch it to raise the BaseExceptionGroup-wrapped 401 error.
            patch("mcpgateway.services.gateway_service.streamablehttp_client", side_effect=wrapped_exc),
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh_db,
            patch("mcpgateway.services.gateway_service.SessionLocal", return_value=_StatusDBCM()),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_tss,
        ):
            mock_fresh_db.side_effect = [_TokenDBCM(), _UpdateDBCM()]
            mock_tss.return_value.get_user_token = AsyncMock(return_value=None)

            await service._check_single_gateway_health(gateway, user_email="admin@example.com")

        # Gateway MUST NOT be marked unhealthy — 401 means it's reachable
        service._handle_gateway_failure.assert_not_called()
        # last_seen should have been updated
        assert mock_db_gateway.last_seen is not None
        update_db.commit.assert_called_once()


class TestTokenRefreshClientSecret:
    """Test client_secret decryption during token refresh (Issue #5237.2a)."""

    @pytest.mark.asyncio
    async def test_decryption_failure_raises_oauth_error_and_preserves_token(self):
        """Decryption failure must raise OAuthError (fail closed) and preserve the token.

        Sending the ciphertext envelope as a literal client_secret to an Authorization
        Server causes repeated invalid_client attempts that can trigger IdP
        rate-limiting/lockout.  The fix raises OAuthError so the caller's
        ``except OAuthError`` branch preserves the token for a later retry.
        """
        mock_db = MagicMock()

        # Mock gateway with encrypted client_secret
        gateway = MagicMock(spec=DbGateway)
        gateway.id = "gw-test"
        gateway.owner_email = "user@example.com"
        gateway.visibility = "public"
        gateway.oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test-client",
            "client_secret": "v2:{\"ciphertext\":\"encrypted_data\",\"nonce\":\"abc123\"}",  # pragma: allowlist secret
            "token_url": "https://oauth.example.com/token",
        }
        gateway.url = "https://example.com"
        gateway.ca_certificate = None
        gateway.client_cert = None
        gateway.client_key = None

        mock_db.query.return_value.filter.return_value.first.return_value = gateway

        with patch("mcpgateway.services.token_storage_service.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.AUTH_ENCRYPTION_SECRET = "test-secret"  # pragma: allowlist secret
            mock_get_settings.return_value = mock_settings

            service = TokenStorageService(mock_db)

            # refresh_token decryption succeeds; client_secret decryption fails
            decrypt_calls = [
                "decrypted_refresh_token",
                ValueError("Decryption failed — wrong AUTH_ENCRYPTION_SECRET"),
            ]

            async def mock_decrypt(value):
                result = decrypt_calls.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

            mock_encryption = MagicMock()
            mock_encryption.decrypt_secret_async = AsyncMock(side_effect=mock_decrypt)
            service.encryption = mock_encryption

            token_record = MagicMock(spec=OAuthToken)
            token_record.gateway_id = "gw-test"
            token_record.app_user_email = "user@example.com"
            token_record.refresh_token = "encrypted_refresh_token"
            token_record.expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)

            # _refresh_access_token catches OAuthError internally and returns None;
            # the outer caller never sees the exception — but the token must NOT be deleted.
            result = await service._refresh_access_token(token_record)

            assert result is None, "Must return None on decryption failure"
            mock_db.delete.assert_not_called(), "Token must be preserved on decryption failure"


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
            "client_secret": "plaintext_secret",  # pragma: allowlist secret
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
            "client_secret": "plaintext_secret",  # pragma: allowlist secret
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
            "client_secret": "secret",  # pragma: allowlist secret
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
                mock_oauth.refresh_token = AsyncMock(side_effect=OAuthInvalidGrantError("Refresh token permanently invalid (invalid_grant): {'error': 'invalid_grant'}"))  # pragma: allowlist secret
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
            "client_secret": "wrong_secret",  # pragma: allowlist secret
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
            "client_secret": "secret",  # pragma: allowlist secret
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
