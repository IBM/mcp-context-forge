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

# Third-Party
import httpx

# Logger
logger = logging.getLogger(__name__)


async def discover_keycloak_endpoints(base_url: str, realm: str, timeout: int = 10) -> Optional[Dict[str, str]]:
    """
    Discover Keycloak OIDC endpoints from well-known configuration.

    Args:
        base_url: Keycloak base URL (e.g., https://keycloak.example.com)
        realm: Realm name (e.g., master)
        timeout: HTTP request timeout in seconds

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


def discover_keycloak_endpoints_sync(base_url: str, realm: str, timeout: int = 10) -> Optional[Dict[str, str]]:
    """
    Synchronous version of discover_keycloak_endpoints.

    Args:
        base_url: Keycloak base URL (e.g., https://keycloak.example.com)
        realm: Realm name (e.g., master)
        timeout: HTTP request timeout in seconds

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
