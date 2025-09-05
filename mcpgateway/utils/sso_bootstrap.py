# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/sso_bootstrap.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Bootstrap SSO providers with predefined configurations.
"""

# Future
# Future
from __future__ import annotations

# Standard
from typing import Dict, List

# First-Party
from mcpgateway.config import settings


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
        ...     sso_ibm_verify_enabled=False, sso_okta_enabled=False
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
        ...     sso_ibm_verify_enabled=False
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
                "client_secret": settings.sso_github_client_secret or "",
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
                "client_secret": settings.sso_google_client_secret or "",
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
                "client_secret": settings.sso_ibm_verify_client_secret or "",
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
                "client_secret": settings.sso_okta_client_secret or "",
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
        print(f"❌ Failed to bootstrap SSO providers: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap_sso_providers()
