# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sso_bootstrap.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test SSO bootstrap async functionality.
"""

# Standard
import logging
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
        sso_entra_graph_api_enabled=False,
        sso_entra_graph_api_timeout=42,
        sso_entra_graph_api_max_groups=777,
        sso_keycloak_enabled=True,
        sso_keycloak_base_url="https://keycloak.example.com",
        sso_keycloak_public_base_url="https://login.example.com",
        sso_keycloak_client_id="kc-client",
        sso_keycloak_client_secret=secret,
        sso_keycloak_realm="master",
        sso_keycloak_map_realm_roles=True,
        sso_keycloak_map_client_roles=False,
        sso_keycloak_username_claim="preferred_username",
        sso_keycloak_email_claim="email",
        sso_keycloak_groups_claim="groups",
        sso_keycloak_role_mappings={"gateway-admin": "platform_admin"},
        sso_keycloak_default_role="viewer",
        sso_keycloak_resolve_team_scope_to_personal_team=True,
        sso_generic_enabled=True,
        sso_generic_provider_id="authentik",
        sso_generic_display_name=None,
        sso_generic_client_id="generic-client",
        sso_generic_client_secret=secret,
        sso_generic_authorization_url="https://auth.example.com/authorize",
        sso_generic_token_url="https://auth.example.com/token",
        sso_generic_userinfo_url="https://auth.example.com/userinfo",
        sso_generic_issuer="https://auth.example.com",
        sso_generic_jwks_uri=None,
        sso_generic_scope="openid profile email",
        sso_trusted_domains=["example.com"],
        sso_auto_create_users=True,
    )

    monkeypatch.setattr("mcpgateway.utils.sso_bootstrap.settings", cfg)
    monkeypatch.setattr(
        "mcpgateway.utils.keycloak_discovery.discover_keycloak_endpoints_sync",
        lambda *args, **kwargs: {
            "authorization_url": f"{args[0]}/auth",
            "token_url": f"{args[0]}/token",
            "userinfo_url": f"{args[0]}/userinfo",
            "issuer": f"{args[0]}/realms/{args[1]}",
            "jwks_uri": f"{args[0]}/jwks",
        },
    )

    providers = get_predefined_sso_providers()
    provider_ids = {provider["id"] for provider in providers}

    assert {"github", "google", "ibm_verify", "okta", "entra", "keycloak", "authentik"} <= provider_ids

    entra_provider = next(provider for provider in providers if provider["id"] == "entra")
    entra_metadata = entra_provider["provider_metadata"]
    assert entra_provider["scope"] == "openid profile email User.Read"
    assert entra_metadata["graph_api_enabled"] is False
    assert entra_metadata["graph_api_timeout"] == 42
    assert entra_metadata["graph_api_max_groups"] == 777

    keycloak_provider = next(provider for provider in providers if provider["id"] == "keycloak")
    metadata = keycloak_provider["provider_metadata"]
    assert keycloak_provider["jwks_uri"] == "https://keycloak.example.com/jwks"
    assert metadata["jwks_uri"] == "https://keycloak.example.com/jwks"
    assert metadata["public_base_url"] == "https://login.example.com"
    assert metadata["role_mappings"] == {"gateway-admin": "platform_admin"}
    assert metadata["default_role"] == "viewer"
    assert metadata["resolve_team_scope_to_personal_team"] is True


def test_get_predefined_sso_providers_keycloak_discovery_none_logs_error(monkeypatch, caplog):
    """Keycloak bootstrap should log an error when discovery returns no endpoints."""
    # First-Party
    from mcpgateway.utils.sso_bootstrap import get_predefined_sso_providers

    cfg = SimpleNamespace(
        sso_github_enabled=False,
        sso_github_client_id=None,
        sso_github_client_secret=None,
        sso_google_enabled=False,
        sso_google_client_id=None,
        sso_google_client_secret=None,
        sso_ibm_verify_enabled=False,
        sso_ibm_verify_client_id=None,
        sso_ibm_verify_client_secret=None,
        sso_ibm_verify_issuer=None,
        sso_okta_enabled=False,
        sso_okta_client_id=None,
        sso_okta_client_secret=None,
        sso_okta_issuer=None,
        sso_entra_enabled=False,
        sso_entra_client_id=None,
        sso_entra_client_secret=None,
        sso_entra_tenant_id=None,
        sso_entra_groups_claim=None,
        sso_entra_role_mappings={},
        sso_keycloak_enabled=True,
        sso_keycloak_base_url="https://keycloak.example.com",
        sso_keycloak_client_id="kc-client",
        sso_keycloak_client_secret=None,
        sso_keycloak_realm="master",
        sso_keycloak_map_realm_roles=False,
        sso_keycloak_map_client_roles=False,
        sso_keycloak_username_claim="preferred_username",
        sso_keycloak_email_claim="email",
        sso_keycloak_groups_claim="groups",
        sso_generic_enabled=False,
        sso_generic_provider_id=None,
        sso_generic_display_name=None,
        sso_generic_client_id=None,
        sso_generic_client_secret=None,
        sso_generic_authorization_url=None,
        sso_generic_token_url=None,
        sso_generic_userinfo_url=None,
        sso_generic_issuer=None,
        sso_generic_scope=None,
        sso_trusted_domains=[],
        sso_auto_create_users=True,
    )

    monkeypatch.setattr("mcpgateway.utils.sso_bootstrap.settings", cfg)
    monkeypatch.setattr("mcpgateway.utils.keycloak_discovery.discover_keycloak_endpoints_sync", lambda *_args, **_kwargs: None)

    with caplog.at_level(logging.ERROR, logger="mcpgateway.utils.sso_bootstrap"):
        providers = get_predefined_sso_providers()

    assert providers == []
    assert any("Failed to discover Keycloak endpoints" in record.message for record in caplog.records)


def test_get_predefined_sso_providers_keycloak_discovery_exception_logs_error(monkeypatch, caplog):
    """Keycloak bootstrap should log errors when discovery raises."""
    # First-Party
    from mcpgateway.utils.sso_bootstrap import get_predefined_sso_providers

    cfg = SimpleNamespace(
        sso_github_enabled=False,
        sso_github_client_id=None,
        sso_github_client_secret=None,
        sso_google_enabled=False,
        sso_google_client_id=None,
        sso_google_client_secret=None,
        sso_ibm_verify_enabled=False,
        sso_ibm_verify_client_id=None,
        sso_ibm_verify_client_secret=None,
        sso_ibm_verify_issuer=None,
        sso_okta_enabled=False,
        sso_okta_client_id=None,
        sso_okta_client_secret=None,
        sso_okta_issuer=None,
        sso_entra_enabled=False,
        sso_entra_client_id=None,
        sso_entra_client_secret=None,
        sso_entra_tenant_id=None,
        sso_entra_groups_claim=None,
        sso_entra_role_mappings={},
        sso_keycloak_enabled=True,
        sso_keycloak_base_url="https://keycloak.example.com",
        sso_keycloak_client_id="kc-client",
        sso_keycloak_client_secret=None,
        sso_keycloak_realm="master",
        sso_keycloak_map_realm_roles=False,
        sso_keycloak_map_client_roles=False,
        sso_keycloak_username_claim="preferred_username",
        sso_keycloak_email_claim="email",
        sso_keycloak_groups_claim="groups",
        sso_generic_enabled=False,
        sso_generic_provider_id=None,
        sso_generic_display_name=None,
        sso_generic_client_id=None,
        sso_generic_client_secret=None,
        sso_generic_authorization_url=None,
        sso_generic_token_url=None,
        sso_generic_userinfo_url=None,
        sso_generic_issuer=None,
        sso_generic_scope=None,
        sso_trusted_domains=[],
        sso_auto_create_users=True,
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("discovery failed")

    monkeypatch.setattr("mcpgateway.utils.sso_bootstrap.settings", cfg)
    monkeypatch.setattr("mcpgateway.utils.keycloak_discovery.discover_keycloak_endpoints_sync", boom)

    with caplog.at_level(logging.ERROR, logger="mcpgateway.utils.sso_bootstrap"):
        providers = get_predefined_sso_providers()

    assert providers == []
    assert any("Error bootstrapping Keycloak provider" in record.message for record in caplog.records)


def test_get_predefined_sso_providers_skips_keycloak_when_disabled(monkeypatch):
    """Cover the branch where Keycloak auto-discovery is disabled and generic OIDC is used."""
    # First-Party
    from mcpgateway.utils.sso_bootstrap import get_predefined_sso_providers

    secret = DummySecret("secret-value")
    cfg = SimpleNamespace(
        sso_github_enabled=False,
        sso_github_client_id=None,
        sso_github_client_secret=None,
        sso_google_enabled=False,
        sso_google_client_id=None,
        sso_google_client_secret=None,
        sso_ibm_verify_enabled=False,
        sso_ibm_verify_client_id=None,
        sso_ibm_verify_client_secret=None,
        sso_ibm_verify_issuer=None,
        sso_okta_enabled=False,
        sso_okta_client_id=None,
        sso_okta_client_secret=None,
        sso_okta_issuer=None,
        sso_entra_enabled=False,
        sso_entra_client_id=None,
        sso_entra_client_secret=None,
        sso_entra_tenant_id=None,
        sso_entra_groups_claim=None,
        sso_entra_role_mappings={},
        sso_keycloak_enabled=False,
        sso_keycloak_base_url="https://keycloak.example.com",
        sso_keycloak_client_id="kc-client",
        sso_keycloak_client_secret=None,
        sso_keycloak_realm="master",
        sso_keycloak_map_realm_roles=False,
        sso_keycloak_map_client_roles=False,
        sso_keycloak_username_claim="preferred_username",
        sso_keycloak_email_claim="email",
        sso_keycloak_groups_claim="groups",
        sso_generic_enabled=True,
        sso_generic_provider_id="auth0",
        sso_generic_display_name="Auth0",
        sso_generic_client_id="generic-client",
        sso_generic_client_secret=secret,
        sso_generic_authorization_url="https://auth.example.com/authorize",
        sso_generic_token_url="https://auth.example.com/token",
        sso_generic_userinfo_url="https://auth.example.com/userinfo",
        sso_generic_issuer="https://auth.example.com",
        sso_generic_jwks_uri=None,
        sso_generic_scope="openid profile email",
        sso_trusted_domains=[],
        sso_auto_create_users=True,
    )

    monkeypatch.setattr("mcpgateway.utils.sso_bootstrap.settings", cfg)
    providers = get_predefined_sso_providers()
    provider_ids = {provider["id"] for provider in providers}

    assert "keycloak" not in provider_ids
    assert "auth0" in provider_ids


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
    async def test_bootstrap_merges_provider_metadata(self):
        """Env metadata should be merged with DB metadata (DB values win)."""
        # First-Party
        from mcpgateway.utils.sso_bootstrap import bootstrap_sso_providers

        mock_db = MagicMock()
        mock_existing_provider = MagicMock()
        mock_existing_provider.id = "existing-provider"
        mock_existing_provider.display_name = "Existing Provider"
        mock_existing_provider.provider_metadata = {"groups_claim": "custom", "sync_roles": False}

        mock_sso_service = MagicMock()
        mock_sso_service.get_provider.return_value = mock_existing_provider
        mock_sso_service.get_provider_by_name.return_value = None
        mock_sso_service.update_provider = AsyncMock(return_value=True)

        provider_config = {
            "id": "existing-provider",
            "name": "existing",
            "display_name": "Updated Provider",
            "provider_type": "oidc",
            "client_id": "updated-client",
            "client_secret": "updated-secret",
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "userinfo_url": "https://auth.example.com/userinfo",
            "scope": "openid email",
            "provider_metadata": {"groups_claim": "groups", "new_setting": "value"},
        }

        with patch("mcpgateway.utils.sso_bootstrap.settings") as mock_settings:
            mock_settings.sso_enabled = True

            with patch("mcpgateway.utils.sso_bootstrap.get_predefined_sso_providers", return_value=[provider_config]):
                with patch("mcpgateway.db.get_db", return_value=iter([mock_db])):
                    with patch("mcpgateway.services.sso_service.SSOService", return_value=mock_sso_service):
                        await bootstrap_sso_providers()

        _provider_id, merged_config = mock_sso_service.update_provider.call_args[0]
        assert merged_config["provider_metadata"] == {"groups_claim": "custom", "new_setting": "value", "sync_roles": False}

    @pytest.mark.asyncio
    async def test_bootstrap_prints_unchanged_provider(self, capsys):
        """When update_provider returns falsy, bootstrap should print 'unchanged'."""
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
        mock_sso_service.update_provider = AsyncMock(return_value=False)

        provider_config = {"id": "existing-provider", "name": "existing", "display_name": "Existing Provider"}

        with patch("mcpgateway.utils.sso_bootstrap.settings") as mock_settings:
            mock_settings.sso_enabled = True

            with patch("mcpgateway.utils.sso_bootstrap.get_predefined_sso_providers", return_value=[provider_config]):
                with patch("mcpgateway.db.get_db", return_value=iter([mock_db])):
                    with patch("mcpgateway.services.sso_service.SSOService", return_value=mock_sso_service):
                        await bootstrap_sso_providers()

        captured = capsys.readouterr().out
        assert "SSO provider unchanged" in captured

    @pytest.mark.asyncio
    async def test_bootstrap_rolls_back_and_prints_on_exception(self, capsys):
        """Exceptions should trigger rollback + failure message, then commit/close in finally."""
        # First-Party
        from mcpgateway.utils.sso_bootstrap import bootstrap_sso_providers

        mock_db = MagicMock()
        mock_sso_service = MagicMock()
        mock_sso_service.get_provider.return_value = None
        mock_sso_service.get_provider_by_name.return_value = None
        mock_sso_service.create_provider = AsyncMock(side_effect=RuntimeError("boom"))

        provider_config = {"id": "test-provider", "name": "test", "display_name": "Test Provider"}

        with patch("mcpgateway.utils.sso_bootstrap.settings") as mock_settings:
            mock_settings.sso_enabled = True

            with patch("mcpgateway.utils.sso_bootstrap.get_predefined_sso_providers", return_value=[provider_config]):
                with patch("mcpgateway.db.get_db", return_value=iter([mock_db])):
                    with patch("mcpgateway.services.sso_service.SSOService", return_value=mock_sso_service):
                        await bootstrap_sso_providers()

        assert mock_db.rollback.called
        captured = capsys.readouterr().out
        assert "Failed to bootstrap SSO providers" in captured

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


def test_generic_oidc_includes_jwks_uri_when_configured(monkeypatch):
    """Generic OIDC provider should include jwks_uri when configured."""
    # First-Party
    from mcpgateway.utils.sso_bootstrap import get_predefined_sso_providers

    secret = DummySecret("secret-value")
    cfg = SimpleNamespace(
        sso_github_enabled=False,
        sso_github_client_id=None,
        sso_github_client_secret=None,
        sso_google_enabled=False,
        sso_google_client_id=None,
        sso_google_client_secret=None,
        sso_ibm_verify_enabled=False,
        sso_ibm_verify_client_id=None,
        sso_ibm_verify_client_secret=None,
        sso_ibm_verify_issuer=None,
        sso_okta_enabled=False,
        sso_okta_client_id=None,
        sso_okta_client_secret=None,
        sso_okta_issuer=None,
        sso_entra_enabled=False,
        sso_entra_client_id=None,
        sso_entra_client_secret=None,
        sso_entra_tenant_id=None,
        sso_entra_groups_claim=None,
        sso_entra_role_mappings={},
        sso_keycloak_enabled=False,
        sso_keycloak_base_url=None,
        sso_keycloak_client_id=None,
        sso_generic_enabled=True,
        sso_generic_provider_id="keycloak",
        sso_generic_display_name="Keycloak",
        sso_generic_client_id="kc-client",
        sso_generic_client_secret=secret,
        sso_generic_authorization_url="https://keycloak.example.com/auth",
        sso_generic_token_url="https://keycloak.example.com/token",
        sso_generic_userinfo_url="https://keycloak.example.com/userinfo",
        sso_generic_issuer="https://keycloak.example.com",
        sso_generic_jwks_uri="https://keycloak.example.com/certs",
        sso_generic_scope="openid profile email",
        sso_trusted_domains=[],
        sso_auto_create_users=True,
    )

    monkeypatch.setattr("mcpgateway.utils.sso_bootstrap.settings", cfg)
    providers = get_predefined_sso_providers()

    assert len(providers) == 1
    assert providers[0]["id"] == "keycloak"
    assert providers[0]["jwks_uri"] == "https://keycloak.example.com/certs"


def test_generic_oidc_omits_jwks_uri_when_not_configured(monkeypatch):
    """Generic OIDC provider should not include jwks_uri when not configured."""
    # First-Party
    from mcpgateway.utils.sso_bootstrap import get_predefined_sso_providers

    secret = DummySecret("secret-value")
    cfg = SimpleNamespace(
        sso_github_enabled=False,
        sso_github_client_id=None,
        sso_github_client_secret=None,
        sso_google_enabled=False,
        sso_google_client_id=None,
        sso_google_client_secret=None,
        sso_ibm_verify_enabled=False,
        sso_ibm_verify_client_id=None,
        sso_ibm_verify_client_secret=None,
        sso_ibm_verify_issuer=None,
        sso_okta_enabled=False,
        sso_okta_client_id=None,
        sso_okta_client_secret=None,
        sso_okta_issuer=None,
        sso_entra_enabled=False,
        sso_entra_client_id=None,
        sso_entra_client_secret=None,
        sso_entra_tenant_id=None,
        sso_entra_groups_claim=None,
        sso_entra_role_mappings={},
        sso_keycloak_enabled=False,
        sso_keycloak_base_url=None,
        sso_keycloak_client_id=None,
        sso_generic_enabled=True,
        sso_generic_provider_id="auth0",
        sso_generic_display_name="Auth0",
        sso_generic_client_id="a0-client",
        sso_generic_client_secret=secret,
        sso_generic_authorization_url="https://auth0.example.com/authorize",
        sso_generic_token_url="https://auth0.example.com/token",
        sso_generic_userinfo_url="https://auth0.example.com/userinfo",
        sso_generic_issuer="https://auth0.example.com",
        sso_generic_jwks_uri=None,
        sso_generic_scope="openid profile email",
        sso_trusted_domains=[],
        sso_auto_create_users=True,
    )

    monkeypatch.setattr("mcpgateway.utils.sso_bootstrap.settings", cfg)
    providers = get_predefined_sso_providers()

    assert len(providers) == 1
    assert providers[0]["id"] == "auth0"
    assert "jwks_uri" not in providers[0]


class TestSSOProviderModel:
    """Tests for SSOProvider model accepting jwks_uri."""

    def test_sso_provider_accepts_jwks_uri(self):
        """SSOProvider constructor should accept jwks_uri as a valid column."""
        # First-Party
        from mcpgateway.db import SSOProvider

        provider = SSOProvider(
            id="test",
            name="test",
            display_name="Test",
            provider_type="oidc",
            client_id="cid",
            client_secret_encrypted="encrypted",
            authorization_url="https://example.com/auth",
            token_url="https://example.com/token",
            userinfo_url="https://example.com/userinfo",
            scope="openid",
            jwks_uri="https://example.com/certs",
        )
        assert provider.jwks_uri == "https://example.com/certs"

    def test_sso_provider_jwks_uri_defaults_to_none(self):
        """SSOProvider should have jwks_uri=None by default."""
        # First-Party
        from mcpgateway.db import SSOProvider

        provider = SSOProvider(
            id="test",
            name="test",
            display_name="Test",
            provider_type="oidc",
            client_id="cid",
            client_secret_encrypted="encrypted",
            authorization_url="https://example.com/auth",
            token_url="https://example.com/token",
            userinfo_url="https://example.com/userinfo",
            scope="openid",
        )
        assert provider.jwks_uri is None


class TestCreateProviderDefensive:
    """Tests for create_provider filtering unknown keys."""

    @pytest.mark.asyncio
    async def test_create_provider_ignores_unknown_keys(self):
        """create_provider should ignore unknown keys instead of raising TypeError."""
        # First-Party
        from mcpgateway.services.sso_service import SSOService

        mock_db = MagicMock()
        service = SSOService(mock_db)
        service._encrypt_secret = AsyncMock(side_effect=lambda s: "ENC(" + s + ")")

        data = {
            "id": "test",
            "name": "test",
            "display_name": "Test Provider",
            "provider_type": "oidc",
            "client_id": "cid",
            "client_secret": "secret",
            "authorization_url": "https://example.com/auth",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
            "scope": "openid",
            "completely_unknown_field": "should_be_ignored",
        }

        # Should NOT raise TypeError
        provider = await service.create_provider(data)
        assert provider.id == "test"
        assert not hasattr(provider, "completely_unknown_field") or provider.completely_unknown_field is None

    @pytest.mark.asyncio
    async def test_create_provider_accepts_jwks_uri(self):
        """create_provider should accept jwks_uri as a valid field."""
        # First-Party
        from mcpgateway.services.sso_service import SSOService

        mock_db = MagicMock()
        service = SSOService(mock_db)
        service._encrypt_secret = AsyncMock(side_effect=lambda s: "ENC(" + s + ")")

        data = {
            "id": "keycloak",
            "name": "keycloak",
            "display_name": "Keycloak",
            "provider_type": "oidc",
            "client_id": "cid",
            "client_secret": "secret",
            "authorization_url": "https://keycloak.example.com/auth",
            "token_url": "https://keycloak.example.com/token",
            "userinfo_url": "https://keycloak.example.com/userinfo",
            "issuer": "https://keycloak.example.com",
            "jwks_uri": "https://keycloak.example.com/certs",
            "scope": "openid profile email",
        }

        provider = await service.create_provider(data)
        assert provider.id == "keycloak"
        assert provider.jwks_uri == "https://keycloak.example.com/certs"


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
