# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/sso_provider_ids.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Helpers for SSO provider identifier canonicalization.
"""

MAX_SSO_PROVIDER_ID_LENGTH = 50

_PROVIDER_ALIASES = {
    "azure-ad": "entra",
}


class SSOProviderValidationError(Exception):
    """Raised when an SSO provider ID is invalid or unavailable.

    Examples:
        >>> canonicalize_sso_provider_id("azure-ad")
        'entra'
        >>> canonicalize_sso_provider_id(" Entra ")
        'entra'
        >>> canonicalize_sso_provider_id("custom-oidc")
        'custom-oidc'
        >>> canonicalize_sso_provider_id("")
        Traceback (most recent call last):
        ...
        mcpgateway.sso_provider_ids.SSOProviderValidationError: SSO provider ID is required
    """


def canonicalize_sso_provider_id(provider_id: str) -> str:
    """Return the canonical provider ID for an inbound SSO provider value.

    This helper is intentionally pure: it does not decide whether a provider
    is configured or enabled. Callers validate the returned ID against
    ``SSOProvider`` rows.

    Args:
        provider_id: Inbound provider ID.

    Returns:
        Canonical provider ID.

    Raises:
        SSOProviderValidationError: If the provider ID is empty or too long.

    Examples:
        >>> canonicalize_sso_provider_id("AZURE-AD")
        'entra'
        >>> canonicalize_sso_provider_id("okta")
        'okta'
        >>> canonicalize_sso_provider_id("custom-provider")
        'custom-provider'
        >>> canonicalize_sso_provider_id("x" * 51)
        Traceback (most recent call last):
        ...
        mcpgateway.sso_provider_ids.SSOProviderValidationError: SSO provider ID exceeds 50 characters
    """
    if not isinstance(provider_id, str):
        raise SSOProviderValidationError("SSO provider ID is required")

    normalized = provider_id.strip().lower()
    canonical = _PROVIDER_ALIASES.get(normalized, normalized)

    if not canonical:
        raise SSOProviderValidationError("SSO provider ID is required")
    if len(canonical) > MAX_SSO_PROVIDER_ID_LENGTH:
        raise SSOProviderValidationError(f"SSO provider ID exceeds {MAX_SSO_PROVIDER_ID_LENGTH} characters")

    return canonical
