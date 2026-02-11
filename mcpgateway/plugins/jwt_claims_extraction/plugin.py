# -*- coding: utf-8 -*-
"""JWT Claims Extraction Plugin.

Location: ./mcpgateway/plugins/jwt_claims_extraction/plugin.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

This plugin extracts JWT claims and metadata from access tokens and maps
them to a reserved context key for use by downstream authorization plugins
(Cedar, OPA, etc.).

Implements RFC 9396 (Rich Authorization Requests) for fine-grained permissions.

Related to Issue #1439: JWT claims and metadata extraction plugin
"""

# Standard
import logging
from typing import Optional

# Third-Party
import jwt

# First-Party
from mcpgateway.plugins.framework import (
    HttpAuthResolveUserPayload,
    Plugin,
    PluginContext,
    PluginResult,
)

logger = logging.getLogger(__name__)


class JwtClaimsExtractionPlugin(Plugin):
    """Plugin to extract JWT claims and add them to context.

    This plugin hooks into HTTP_AUTH_RESOLVE_USER to extract claims
    from JWT tokens and make them available in a reserved context key
    for downstream authorization plugins.

    Extracted claims include:
    - Standard claims (sub, iss, aud, exp, iat, nbf, jti)
    - Custom claims (roles, permissions, groups, attributes)
    - RFC 9396 rich authorization request data

    The claims are stored in global_context.metadata["jwt_claims"] for
    use by Cedar, OPA, and other policy enforcement plugins.
    """

    async def http_auth_resolve_user(
        self,
        payload: HttpAuthResolveUserPayload,
        context: PluginContext,
    ) -> PluginResult[dict]:
        """Extract JWT claims and add to context.

        This hook runs during JWT verification to extract claims
        and store them for downstream plugins.

        Args:
            payload: Auth payload with credentials and headers
            context: Plugin execution context with global_context

        Returns:
            PluginResult with continue_processing=True (passthrough)
        """
        try:
            # Extract JWT token from credentials
            token = self._extract_token(payload)

            if not token:
                # No JWT token present, skip extraction
                logger.debug("No JWT token found in request, skipping claims extraction")
                return PluginResult(continue_processing=True)

            # Decode JWT without verification (already verified by auth system)
            # We just want to extract the claims
            claims = jwt.decode(
                token,
                options={"verify_signature": False},  # Already verified
            )

            # Store claims in global context metadata
            # This makes them available to downstream plugins
            if not hasattr(context.global_context, "metadata"):
                context.global_context.metadata = {}

            # Store in reserved key for policy enforcement plugins
            context.global_context.metadata["jwt_claims"] = claims

            logger.info(f"Extracted JWT claims for user '{claims.get('sub', 'unknown')}': " f"{len(claims)} claims stored in context")

            # Log RFC 9396 rich authorization requests if present
            if "authorization_details" in claims:
                logger.debug(f"RFC 9396 authorization_details present: " f"{claims['authorization_details']}")

            # Return passthrough result (continue with standard auth)
            return PluginResult(continue_processing=True, metadata={"jwt_claims_extracted": True, "claims_count": len(claims)})

        except Exception as e:
            # Log error but don't block authentication
            logger.error(f"Error extracting JWT claims: {e}", exc_info=True)
            return PluginResult(continue_processing=True, metadata={"jwt_claims_extracted": False, "error": str(e)})

    def _extract_token(self, payload: HttpAuthResolveUserPayload) -> Optional[str]:
        """Extract JWT token from request.

        Args:
            payload: Auth payload with credentials and headers

        Returns:
            JWT token string or None if not found
        """
        # Try credentials first (Bearer token)
        if payload.credentials and isinstance(payload.credentials, dict):
            token = payload.credentials.get("credentials")
            if token:
                return token

        # Try Authorization header (access root dict)
        if payload.headers and hasattr(payload.headers, "root"):
            headers_dict = payload.headers.root
            auth_header = headers_dict.get("authorization") or headers_dict.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                return auth_header[7:]  # Remove "Bearer " prefix

        return None
