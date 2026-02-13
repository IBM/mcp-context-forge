# -*- coding: utf-8 -*-
"""JWT Claims Extraction Plugin.

Location: ./mcpgateway/plugins/jwt_claims_extraction/plugin.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

This plugin extracts JWT claims and metadata from access tokens and maps
them to a reserved context key for use by downstream authorization plugins
(Cedar, OPA, etc.).

Implements RFC 9396 (Rich Authorization Requests) for fine-grained permissions.

Related to Issue #1439: JWT claims and metadata extraction plugin

SECURITY NOTE: This plugin assumes JWT tokens have already been verified by the
authentication system before reaching the http_auth_resolve_user hook. The plugin
uses verify_signature=False because signature validation is completed upstream.
If hook ordering changes or configuration allows this plugin to run before auth
verification, unverified tokens would be accepted. Always ensure this plugin runs
AFTER JWT verification in the authentication flow.
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

    SECURITY: Assumes tokens are pre-verified. See module docstring.
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
            # SECURITY: Token signature was validated upstream - see module docstring
            claims = jwt.decode(
                token,
                options={"verify_signature": False},
            )

            # Store claims in global context metadata
            # This makes them available to downstream plugins
            if not hasattr(context.global_context, "metadata"):
                context.global_context.metadata = {}

            # Store in reserved key for policy enforcement plugins
            context.global_context.metadata["jwt_claims"] = claims

            # Log at DEBUG level to avoid leaking PII/sensitive claims in production
            logger.debug(
                f"Extracted JWT claims for user '{claims.get('sub', 'unknown')}': "
                f"{len(claims)} claims stored in context"
            )

            # Log RFC 9396 rich authorization requests if present
            if "authorization_details" in claims:
                logger.debug(
                    f"RFC 9396 authorization_details present with "
                    f"{len(claims['authorization_details'])} entries"
                )

            # Return passthrough result (continue with standard auth)
            return PluginResult(
                continue_processing=True,
                metadata={"jwt_claims_extracted": True, "claims_count": len(claims)}
            )

        except Exception as e:
            # Log error but don't block authentication
            logger.error(f"Error extracting JWT claims: {e}", exc_info=True)
            return PluginResult(
                continue_processing=True,
                metadata={"jwt_claims_extracted": False, "error": str(e)}
            )

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

        # Try Authorization header using safe attribute access
        # Use getattr with default to handle potential model changes gracefully
        headers_dict = getattr(payload.headers, "root", {})
        if headers_dict:
            auth_header = headers_dict.get("authorization") or headers_dict.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                return auth_header[7:]  # Remove "Bearer " prefix

        return None
