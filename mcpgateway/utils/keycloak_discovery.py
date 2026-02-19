# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/keycloak_discovery.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Keycloak OIDC endpoint discovery utility.
"""

# Standard
import logging
from typing import Dict, Optional
from urllib.parse import urlsplit, urlunsplit

# Third-Party
import httpx

# Logger
logger = logging.getLogger(__name__)


def _rewrite_endpoint_base(endpoint_url: Optional[str], target_base_url: Optional[str], endpoint_type: str) -> Optional[str]:
    """Rewrite a discovered endpoint URL to use a target base URL.

    Keeps the discovered path/query/fragment and swaps scheme+host+port only.

    Args:
        endpoint_url: Endpoint URL discovered from OIDC metadata.
        target_base_url: Replacement base URL to apply (scheme/host/port).
        endpoint_type: Endpoint identifier used for logging.

    Returns:
        Rewritten URL when target base is valid and differs, otherwise the original URL.
    """
    if not endpoint_url or not target_base_url:
        return endpoint_url

    parsed_endpoint = urlsplit(endpoint_url)
    parsed_base = urlsplit(target_base_url)

    if not parsed_base.scheme or not parsed_base.netloc:
        return endpoint_url

    if parsed_endpoint.scheme == parsed_base.scheme and parsed_endpoint.netloc == parsed_base.netloc:
        return endpoint_url

    rewritten = urlunsplit(
        (
            parsed_base.scheme,
            parsed_base.netloc,
            parsed_endpoint.path,
            parsed_endpoint.query,
            parsed_endpoint.fragment,
        )
    )
    logger.info("Rewrote Keycloak %s URL from %s to %s", endpoint_type, endpoint_url, rewritten)
    return rewritten


async def discover_keycloak_endpoints(base_url: str, realm: str, timeout: int = 10, public_base_url: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Discover Keycloak OIDC endpoints from well-known configuration.

    Args:
        base_url: Keycloak base URL (e.g., https://keycloak.example.com)
        realm: Realm name (e.g., master)
        timeout: HTTP request timeout in seconds
        public_base_url: Optional browser-facing Keycloak base URL for authorization URL rewrite

    Returns:
        Dict containing authorization_url, token_url, userinfo_url, issuer, jwks_uri
        Returns None if discovery fails

    Examples:
        >>> import asyncio
        >>> # Mock successful discovery
        >>> async def test():
        ...     # This would require a real Keycloak instance
        ...     result = await discover_keycloak_endpoints('https://keycloak.example.com', 'master')
        ...     return result is None or isinstance(result, dict)
        >>> asyncio.run(test())
        True
    """
    well_known_url = f"{base_url}/realms/{realm}/.well-known/openid-configuration"

    try:
        # First-Party
        from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

        client = await get_http_client()
        logger.info(f"Discovering Keycloak endpoints from {well_known_url}")
        response = await client.get(well_known_url, timeout=timeout)
        response.raise_for_status()
        config = response.json()

        endpoints = {
            "authorization_url": config.get("authorization_endpoint"),
            "token_url": config.get("token_endpoint"),
            "userinfo_url": config.get("userinfo_endpoint"),
            "issuer": config.get("issuer"),
            "jwks_uri": config.get("jwks_uri"),
        }

        # Use optional browser-facing base for authorization endpoint while keeping
        # token/userinfo/jwks endpoints reachable from the gateway runtime.
        endpoints["authorization_url"] = _rewrite_endpoint_base(endpoints.get("authorization_url"), public_base_url, "authorization")
        endpoints["token_url"] = _rewrite_endpoint_base(endpoints.get("token_url"), base_url, "token")
        endpoints["userinfo_url"] = _rewrite_endpoint_base(endpoints.get("userinfo_url"), base_url, "userinfo")
        endpoints["jwks_uri"] = _rewrite_endpoint_base(endpoints.get("jwks_uri"), base_url, "jwks")

        # Validate that all required endpoints are present
        if not all(endpoints.values()):
            logger.error(f"Incomplete OIDC configuration from {well_known_url}")
            return None

        logger.info(f"Successfully discovered Keycloak endpoints for realm '{realm}'")
        return endpoints

    except httpx.HTTPError as e:
        logger.error(f"Failed to discover Keycloak endpoints from {well_known_url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error discovering Keycloak endpoints: {e}")
        return None


def discover_keycloak_endpoints_sync(base_url: str, realm: str, timeout: int = 10, public_base_url: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Synchronous version of discover_keycloak_endpoints.

    Args:
        base_url: Keycloak base URL (e.g., https://keycloak.example.com)
        realm: Realm name (e.g., master)
        timeout: HTTP request timeout in seconds
        public_base_url: Optional browser-facing Keycloak base URL for authorization URL rewrite

    Returns:
        Dict containing authorization_url, token_url, userinfo_url, issuer, jwks_uri
        Returns None if discovery fails
    """
    well_known_url = f"{base_url}/realms/{realm}/.well-known/openid-configuration"

    try:
        # First-Party
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        with httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=settings.httpx_max_connections,
                max_keepalive_connections=settings.httpx_max_keepalive_connections,
                keepalive_expiry=settings.httpx_keepalive_expiry,
            ),
            verify=not settings.skip_ssl_verify,
        ) as client:
            logger.info(f"Discovering Keycloak endpoints from {well_known_url}")
            response = client.get(well_known_url)
            response.raise_for_status()
            config = response.json()

            endpoints = {
                "authorization_url": config.get("authorization_endpoint"),
                "token_url": config.get("token_endpoint"),
                "userinfo_url": config.get("userinfo_endpoint"),
                "issuer": config.get("issuer"),
                "jwks_uri": config.get("jwks_uri"),
            }

            # Use optional browser-facing base for authorization endpoint while keeping
            # token/userinfo/jwks endpoints reachable from the gateway runtime.
            endpoints["authorization_url"] = _rewrite_endpoint_base(endpoints.get("authorization_url"), public_base_url, "authorization")
            endpoints["token_url"] = _rewrite_endpoint_base(endpoints.get("token_url"), base_url, "token")
            endpoints["userinfo_url"] = _rewrite_endpoint_base(endpoints.get("userinfo_url"), base_url, "userinfo")
            endpoints["jwks_uri"] = _rewrite_endpoint_base(endpoints.get("jwks_uri"), base_url, "jwks")

            # Validate that all required endpoints are present
            if not all(endpoints.values()):
                logger.error(f"Incomplete OIDC configuration from {well_known_url}")
                return None

            logger.info(f"Successfully discovered Keycloak endpoints for realm '{realm}'")
            return endpoints

    except httpx.HTTPError as e:
        logger.error(f"Failed to discover Keycloak endpoints from {well_known_url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error discovering Keycloak endpoints: {e}")
        return None
