# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sso_bootstrap.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test SSO bootstrap async functionality.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest


class DummySecret:
    def __init__(self, value: str):
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


def test_get_predefined_sso_providers_multiple(monkeypatch):
    """Ensure get_predefined_sso_providers builds provider configs across branches."""
    # First-Party
    from mcpgateway.utils.sso_bootstrap import get_predefined_sso_providers

    secret = DummySecret("secret-value")
    cfg = SimpleNamespace(
        sso_github_enabled=True,
        sso_github_client_id="gh-client",
        sso_github_client_secret=secret,
        sso_google_enabled=True,
        sso_google_client_id="g-client",
        sso_google_client_secret=secret,
        sso_ibm_verify_enabled=True,
        sso_ibm_verify_client_id="ibm-client",
        sso_ibm_verify_client_secret=secret,
        sso_ibm_verify_issuer="https://tenant.verify.ibm.com",
        sso_okta_enabled=True,
        sso_okta_client_id="okta-client",
        sso_okta_client_secret=secret,
        sso_okta_issuer="https://company.okta.com",
        sso_entra_enabled=True,
        sso_entra_client_id="entra-client",
        sso_entra_client_secret=secret,
        sso_entra_tenant_id="tenant-id",
        sso_entra_groups_claim="groups",
        sso_entra_role_mappings={"admin": "Admin"},
        sso_keycloak_enabled=True,
        sso_keycloak_base_url="https://keycloak.example.com",
        sso_keycloak_client_id="kc-client",
        sso_keycloak_client_secret=secret,
        sso_keycloak_realm="master",
        sso_keycloak_map_realm_roles=True,
        sso_keycloak_map_client_roles=False,
        sso_keycloak_username_claim="preferred_username",
        sso_keycloak_email_claim="email",
        sso_keycloak_groups_claim="groups",
        sso_generic_enabled=True,
        sso_generic_provider_id="authentik",
        sso_generic_display_name=None,
        sso_generic_client_id="generic-client",
        sso_generic_client_secret=secret,
        sso_generic_authorization_url="https://auth.example.com/authorize",
        sso_generic_token_url="https://auth.example.com/token",
        sso_generic_userinfo_url="https://auth.example.com/userinfo",
        sso_generic_issuer="https://auth.example.com",
        sso_generic_scope="openid profile email",
        sso_trusted_domains=["example.com"],
        sso_auto_create_users=True,
    )

    monkeypatch.setattr("mcpgateway.utils.sso_bootstrap.settings", cfg)
    monkeypatch.setattr(
        "mcpgateway.utils.keycloak_discovery.discover_keycloak_endpoints_sync",
        lambda base_url, realm: {
            "authorization_url": f"{base_url}/auth",
            "token_url": f"{base_url}/token",
            "userinfo_url": f"{base_url}/userinfo",
            "issuer": f"{base_url}/realms/{realm}",
            "jwks_uri": f"{base_url}/jwks",
        },
    )

    providers = get_predefined_sso_providers()
    provider_ids = {provider["id"] for provider in providers}

    assert {"github", "google", "ibm_verify", "okta", "entra", "keycloak", "authentik"} <= provider_ids
class TestSSOBootstrapAsync:
    """Test async SSO bootstrap functionality."""

    @pytest.mark.asyncio
    async def test_bootstrap_creates_provider_with_await(self):
        """Test that bootstrap_sso_providers awaits create_provider."""
        # First-Party
        from mcpgateway.utils.sso_bootstrap import bootstrap_sso_providers

        mock_db = MagicMock()
        mock_sso_service = MagicMock()
        mock_sso_service.get_provider.return_value = None
        mock_sso_service.get_provider_by_name.return_value = None
        mock_sso_service.create_provider = AsyncMock()

        provider_config = {
            "id": "test-provider",
            "name": "test",
            "display_name": "Test Provider",
            "provider_type": "oauth2",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "userinfo_url": "https://auth.example.com/userinfo",
            "scope": "openid email",
        }

        with patch("mcpgateway.utils.sso_bootstrap.settings") as mock_settings:
            mock_settings.sso_enabled = True

            with patch("mcpgateway.utils.sso_bootstrap.get_predefined_sso_providers", return_value=[provider_config]):
                # Patch at the source module since it's imported inside the function
                with patch("mcpgateway.db.get_db", return_value=iter([mock_db])):
                    with patch("mcpgateway.services.sso_service.SSOService", return_value=mock_sso_service):
                        await bootstrap_sso_providers()

                        # Verify create_provider was awaited
                        mock_sso_service.create_provider.assert_called_once_with(provider_config)

    @pytest.mark.asyncio
    async def test_bootstrap_updates_provider_with_await(self):
        """Test that bootstrap_sso_providers awaits update_provider."""
        # First-Party
        from mcpgateway.utils.sso_bootstrap import bootstrap_sso_providers

        mock_db = MagicMock()
        mock_existing_provider = MagicMock()
        mock_existing_provider.id = "existing-provider"
        mock_existing_provider.display_name = "Existing Provider"
        mock_existing_provider.provider_metadata = None

        mock_sso_service = MagicMock()
        mock_sso_service.get_provider.return_value = mock_existing_provider
        mock_sso_service.get_provider_by_name.return_value = None
        mock_sso_service.update_provider = AsyncMock(return_value=mock_existing_provider)

        provider_config = {
            "id": "existing-provider",
            "name": "existing",
            "display_name": "Updated Provider",
            "provider_type": "oauth2",
            "client_id": "updated-client",
            "client_secret": "updated-secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "userinfo_url": "https://auth.example.com/userinfo",
            "scope": "openid email",
        }

        with patch("mcpgateway.utils.sso_bootstrap.settings") as mock_settings:
            mock_settings.sso_enabled = True

            with patch("mcpgateway.utils.sso_bootstrap.get_predefined_sso_providers", return_value=[provider_config]):
                # Patch at the source module since it's imported inside the function
                with patch("mcpgateway.db.get_db", return_value=iter([mock_db])):
                    with patch("mcpgateway.services.sso_service.SSOService", return_value=mock_sso_service):
                        await bootstrap_sso_providers()

                        # Verify update_provider was awaited
                        mock_sso_service.update_provider.assert_called_once()

    @pytest.mark.asyncio
    async def test_bootstrap_skips_when_sso_disabled(self):
        """Test that bootstrap_sso_providers returns early when SSO is disabled."""
        # First-Party
        from mcpgateway.utils.sso_bootstrap import bootstrap_sso_providers

        with patch("mcpgateway.utils.sso_bootstrap.settings") as mock_settings:
            mock_settings.sso_enabled = False

            with patch("mcpgateway.utils.sso_bootstrap.get_predefined_sso_providers") as mock_get_providers:
                await bootstrap_sso_providers()

                # Should not call get_predefined_sso_providers when SSO is disabled
                mock_get_providers.assert_not_called()

    @pytest.mark.asyncio
    async def test_bootstrap_skips_when_no_providers(self):
        """Test that bootstrap_sso_providers returns early when no providers configured."""
        # First-Party
        from mcpgateway.utils.sso_bootstrap import bootstrap_sso_providers

        with patch("mcpgateway.utils.sso_bootstrap.settings") as mock_settings:
            mock_settings.sso_enabled = True

            with patch("mcpgateway.utils.sso_bootstrap.get_predefined_sso_providers", return_value=[]):
                # Patch at the source module since it's imported inside the function
                with patch("mcpgateway.db.get_db") as mock_get_db:
                    await bootstrap_sso_providers()

                    # Should not try to get a DB session when no providers
                    mock_get_db.assert_not_called()


class TestAttemptToBootstrapSSOProviders:
    """Test the main.py wrapper for SSO bootstrap."""

    @pytest.mark.asyncio
    async def test_attempt_bootstrap_awaits_bootstrap_sso_providers(self):
        """Test that attempt_to_bootstrap_sso_providers awaits bootstrap_sso_providers."""
        # First-Party
        from mcpgateway.main import attempt_to_bootstrap_sso_providers

        # Patch where it's imported inside the function
        with patch("mcpgateway.utils.sso_bootstrap.bootstrap_sso_providers", new_callable=AsyncMock) as mock_bootstrap:
            await attempt_to_bootstrap_sso_providers()

            mock_bootstrap.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_attempt_bootstrap_handles_exceptions(self):
        """Test that attempt_to_bootstrap_sso_providers handles exceptions gracefully."""
        # First-Party
        from mcpgateway.main import attempt_to_bootstrap_sso_providers

        # Patch where it's imported inside the function
        with patch("mcpgateway.utils.sso_bootstrap.bootstrap_sso_providers", new_callable=AsyncMock) as mock_bootstrap:
            mock_bootstrap.side_effect = Exception("Bootstrap failed")

            # Should not raise, just log warning
            await attempt_to_bootstrap_sso_providers()

            mock_bootstrap.assert_awaited_once()
