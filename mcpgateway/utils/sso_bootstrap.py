# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/sso_bootstrap.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Bootstrap SSO providers with predefined configurations.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Dict, List

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


def get_predefined_sso_providers() -> List[Dict]:
    """Get list of predefined SSO providers based on environment configuration.

    Returns:
        List of SSO provider configurations ready for database storage.

    Examples:
        Default (no providers configured):
        >>> providers = get_predefined_sso_providers()
        >>> isinstance(providers, list)
        True

        Patch configuration to include GitHub provider:
        >>> from types import SimpleNamespace
        >>> from unittest.mock import patch
        >>> cfg = SimpleNamespace(
        ...     sso_github_enabled=True,
        ...     sso_github_client_id='id',
        ...     sso_github_client_secret='sec',
        ...     sso_trusted_domains=[],
        ...     sso_auto_create_users=True,
        ...     sso_google_enabled=False,
        ...     sso_ibm_verify_enabled=False,
        ...     sso_okta_enabled=False,
        ...     sso_entra_enabled=False,
        ... )
        >>> with patch('mcpgateway.utils.sso_bootstrap.settings', cfg):
        ...     result = get_predefined_sso_providers()
        >>> isinstance(result, list)
        True

        Patch configuration to include Google provider:
        >>> cfg = SimpleNamespace(
        ...     sso_github_enabled=False, sso_github_client_id=None, sso_github_client_secret=None,
        ...     sso_trusted_domains=[], sso_auto_create_users=True,
        ...     sso_google_enabled=True, sso_google_client_id='gid', sso_google_client_secret='gsec',
        ...     sso_ibm_verify_enabled=False, sso_okta_enabled=False, sso_entra_enabled=False
        ... )
        >>> with patch('mcpgateway.utils.sso_bootstrap.settings', cfg):
        ...     result = get_predefined_sso_providers()
        >>> isinstance(result, list)
        True

        Patch configuration to include Okta provider:
        >>> cfg = SimpleNamespace(
        ...     sso_github_enabled=False, sso_github_client_id=None, sso_github_client_secret=None,
        ...     sso_trusted_domains=[], sso_auto_create_users=True,
        ...     sso_google_enabled=False, sso_okta_enabled=True, sso_okta_client_id='ok', sso_okta_client_secret='os', sso_okta_issuer='https://company.okta.com',
        ...     sso_ibm_verify_enabled=False, sso_entra_enabled=False
        ... )
        >>> with patch('mcpgateway.utils.sso_bootstrap.settings', cfg):
        ...     result = get_predefined_sso_providers()
        >>> isinstance(result, list)
        True

        Patch configuration to include Microsoft Entra ID provider:
        >>> cfg = SimpleNamespace(
        ...     sso_github_enabled=False, sso_github_client_id=None, sso_github_client_secret=None,
        ...     sso_trusted_domains=[], sso_auto_create_users=True,
        ...     sso_google_enabled=False, sso_okta_enabled=False,
        ...     sso_ibm_verify_enabled=False, sso_entra_enabled=True, sso_entra_client_id='entra_client', sso_entra_client_secret='entra_secret', sso_entra_tenant_id='tenant-id-123',
        ...     sso_generic_enabled=False
        ... )
        >>> with patch('mcpgateway.utils.sso_bootstrap.settings', cfg):
        ...     result = get_predefined_sso_providers()
        >>> isinstance(result, list)
        True

        Patch configuration to include Generic OIDC provider:
        >>> cfg = SimpleNamespace(
        ...     sso_github_enabled=False, sso_github_client_id=None, sso_github_client_secret=None,
        ...     sso_trusted_domains=[], sso_auto_create_users=True,
        ...     sso_google_enabled=False, sso_okta_enabled=False, sso_ibm_verify_enabled=False, sso_entra_enabled=False,
        ...     sso_generic_enabled=True, sso_generic_provider_id='keycloak', sso_generic_display_name='Keycloak',
        ...     sso_generic_client_id='kc_client', sso_generic_client_secret='kc_secret',
        ...     sso_generic_authorization_url='https://keycloak.company.com/auth/realms/master/protocol/openid-connect/auth',
        ...     sso_generic_token_url='https://keycloak.company.com/auth/realms/master/protocol/openid-connect/token',
        ...     sso_generic_userinfo_url='https://keycloak.company.com/auth/realms/master/protocol/openid-connect/userinfo',
        ...     sso_generic_issuer='https://keycloak.company.com/auth/realms/master',
        ...     sso_generic_scope='openid profile email'
        ... )
        >>> with patch('mcpgateway.utils.sso_bootstrap.settings', cfg):
        ...     result = get_predefined_sso_providers()
        >>> isinstance(result, list)
        True
    """
    providers = []

    # GitHub OAuth Provider
    if settings.sso_github_enabled and settings.sso_github_client_id:
        providers.append(
            {
                "id": "github",
                "name": "github",
                "display_name": "GitHub",
                "provider_type": "oauth2",
                "client_id": settings.sso_github_client_id,
                "client_secret": settings.sso_github_client_secret.get_secret_value() if settings.sso_github_client_secret else "",
                "authorization_url": "https://github.com/login/oauth/authorize",
                "token_url": "https://github.com/login/oauth/access_token",
                "userinfo_url": "https://api.github.com/user",
                "scope": "user:email",
                "trusted_domains": settings.sso_trusted_domains,
                "auto_create_users": settings.sso_auto_create_users,
                "team_mapping": {},
            }
        )

    # Google OAuth Provider
    if settings.sso_google_enabled and settings.sso_google_client_id:
        providers.append(
            {
                "id": "google",
                "name": "google",
                "display_name": "Google",
                "provider_type": "oidc",
                "client_id": settings.sso_google_client_id,
                "client_secret": settings.sso_google_client_secret.get_secret_value() if settings.sso_google_client_secret else "",
                "authorization_url": "https://accounts.google.com/o/oauth2/auth",
                "token_url": "https://oauth2.googleapis.com/token",
                "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
                "issuer": "https://accounts.google.com",
                "scope": "openid profile email",
                "trusted_domains": settings.sso_trusted_domains,
                "auto_create_users": settings.sso_auto_create_users,
                "team_mapping": {},
            }
        )

    # IBM Security Verify Provider
    if settings.sso_ibm_verify_enabled and settings.sso_ibm_verify_client_id:
        base_url = settings.sso_ibm_verify_issuer or "https://tenant.verify.ibm.com"
        providers.append(
            {
                "id": "ibm_verify",
                "name": "ibm_verify",
                "display_name": "IBM Security Verify",
                "provider_type": "oidc",
                "client_id": settings.sso_ibm_verify_client_id,
                "client_secret": settings.sso_ibm_verify_client_secret.get_secret_value() if settings.sso_ibm_verify_client_secret else "",
                "authorization_url": f"{base_url}/oidc/endpoint/default/authorize",
                "token_url": f"{base_url}/oidc/endpoint/default/token",
                "userinfo_url": f"{base_url}/oidc/endpoint/default/userinfo",
                "issuer": f"{base_url}/oidc/endpoint/default",
                "scope": "openid profile email",
                "trusted_domains": settings.sso_trusted_domains,
                "auto_create_users": settings.sso_auto_create_users,
                "team_mapping": {},
            }
        )

    # Okta Provider
    if settings.sso_okta_enabled and settings.sso_okta_client_id:
        base_url = settings.sso_okta_issuer or "https://company.okta.com"
        providers.append(
            {
                "id": "okta",
                "name": "okta",
                "display_name": "Okta",
                "provider_type": "oidc",
                "client_id": settings.sso_okta_client_id,
                "client_secret": settings.sso_okta_client_secret.get_secret_value() if settings.sso_okta_client_secret else "",
                "authorization_url": f"{base_url}/oauth2/default/v1/authorize",
                "token_url": f"{base_url}/oauth2/default/v1/token",
                "userinfo_url": f"{base_url}/oauth2/default/v1/userinfo",
                "issuer": f"{base_url}/oauth2/default",
                "scope": "openid profile email",
                "trusted_domains": settings.sso_trusted_domains,
                "auto_create_users": settings.sso_auto_create_users,
                "team_mapping": {},
            }
        )

    # Microsoft Entra ID Provider
    if settings.sso_entra_enabled and settings.sso_entra_client_id and settings.sso_entra_tenant_id:
        tenant_id = settings.sso_entra_tenant_id
        base_url = f"https://login.microsoftonline.com/{tenant_id}"
        providers.append(
            {
                "id": "entra",
                "name": "entra",
                "display_name": "Microsoft Entra ID",
                "provider_type": "oidc",
                "client_id": settings.sso_entra_client_id,
                "client_secret": settings.sso_entra_client_secret.get_secret_value() if settings.sso_entra_client_secret else "",
                "authorization_url": f"{base_url}/oauth2/v2.0/authorize",
                "token_url": f"{base_url}/oauth2/v2.0/token",
                "userinfo_url": "https://graph.microsoft.com/oidc/userinfo",
                "issuer": f"{base_url}/v2.0",
                "scope": "openid profile email",
                "trusted_domains": settings.sso_trusted_domains,
                "auto_create_users": settings.sso_auto_create_users,
                "team_mapping": {},
            }
        )

    # Keycloak OIDC Provider with Auto-Discovery
    if settings.sso_keycloak_enabled and settings.sso_keycloak_base_url and settings.sso_keycloak_client_id:
        try:
            # First-Party
            from mcpgateway.utils.keycloak_discovery import discover_keycloak_endpoints_sync

            endpoints = discover_keycloak_endpoints_sync(settings.sso_keycloak_base_url, settings.sso_keycloak_realm)

            if endpoints:
                providers.append(
                    {
                        "id": "keycloak",
                        "name": "keycloak",
                        "display_name": f"Keycloak ({settings.sso_keycloak_realm})",
                        "provider_type": "oidc",
                        "client_id": settings.sso_keycloak_client_id,
                        "client_secret": settings.sso_keycloak_client_secret.get_secret_value() if settings.sso_keycloak_client_secret else "",
                        "authorization_url": endpoints["authorization_url"],
                        "token_url": endpoints["token_url"],
                        "userinfo_url": endpoints["userinfo_url"],
                        "issuer": endpoints["issuer"],
                        "jwks_uri": endpoints.get("jwks_uri"),
                        "scope": "openid profile email",
                        "trusted_domains": settings.sso_trusted_domains,
                        "auto_create_users": settings.sso_auto_create_users,
                        "team_mapping": {},
                        "metadata": {
                            "realm": settings.sso_keycloak_realm,
                            "base_url": settings.sso_keycloak_base_url,
                            "map_realm_roles": settings.sso_keycloak_map_realm_roles,
                            "map_client_roles": settings.sso_keycloak_map_client_roles,
                            "username_claim": settings.sso_keycloak_username_claim,
                            "email_claim": settings.sso_keycloak_email_claim,
                            "groups_claim": settings.sso_keycloak_groups_claim,
                        },
                    }
                )
            else:
                logger.error(f"Failed to discover Keycloak endpoints for realm '{settings.sso_keycloak_realm}' at {settings.sso_keycloak_base_url}")
        except Exception as e:
            logger.error(f"Error bootstrapping Keycloak provider: {e}")

    # Generic OIDC Provider (Keycloak, Auth0, Authentik, etc.)
    if settings.sso_generic_enabled and settings.sso_generic_client_id and settings.sso_generic_provider_id:
        provider_id = settings.sso_generic_provider_id
        display_name = settings.sso_generic_display_name or provider_id.title()

        providers.append(
            {
                "id": provider_id,
                "name": provider_id,
                "display_name": display_name,
                "provider_type": "oidc",
                "client_id": settings.sso_generic_client_id,
                "client_secret": settings.sso_generic_client_secret.get_secret_value() if settings.sso_generic_client_secret else "",
                "authorization_url": settings.sso_generic_authorization_url,
                "token_url": settings.sso_generic_token_url,
                "userinfo_url": settings.sso_generic_userinfo_url,
                "issuer": settings.sso_generic_issuer,
                "scope": settings.sso_generic_scope,
                "trusted_domains": settings.sso_trusted_domains,
                "auto_create_users": settings.sso_auto_create_users,
                "team_mapping": {},
            }
        )

    return providers


def bootstrap_sso_providers() -> None:
    """Bootstrap SSO providers from environment configuration.

    This function should be called during application startup to
    automatically configure SSO providers based on environment variables.

    Examples:
        >>> # This would typically be called during app startup
        >>> bootstrap_sso_providers()  # doctest: +SKIP
    """
    if not settings.sso_enabled:
        return

    # First-Party
    from mcpgateway.db import get_db
    from mcpgateway.services.sso_service import SSOService

    providers = get_predefined_sso_providers()
    if not providers:
        return

    db = next(get_db())
    try:
        sso_service = SSOService(db)

        for provider_config in providers:
            # Check if provider already exists by ID or name (both have unique constraints)
            existing_by_id = sso_service.get_provider(provider_config["id"])
            existing_by_name = sso_service.get_provider_by_name(provider_config["name"])

            if not existing_by_id and not existing_by_name:
                sso_service.create_provider(provider_config)
                print(f"✅ Created SSO provider: {provider_config['display_name']}")
            else:
                # Update existing provider with current configuration
                existing_provider = existing_by_id or existing_by_name
                updated = sso_service.update_provider(existing_provider.id, provider_config)
                if updated:
                    print(f"🔄 Updated SSO provider: {provider_config['display_name']} (ID: {existing_provider.id})")
                else:
                    print(f"ℹ️  SSO provider unchanged: {existing_provider.display_name} (ID: {existing_provider.id})")

    except Exception as e:
        db.rollback()  # Rollback on error
        print(f"❌ Failed to bootstrap SSO providers: {e}")
    finally:
        db.commit()  # Commit transaction to avoid implicit rollback
        db.close()


if __name__ == "__main__":
    bootstrap_sso_providers()
