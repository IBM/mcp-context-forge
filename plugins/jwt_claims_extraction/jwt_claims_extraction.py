# -*- coding: utf-8 -*-
"""Location: ./plugins/jwt_claims_extraction/jwt_claims_extraction.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

JWT Claims Extraction Plugin.

Extracts JWT claims and metadata from access tokens and stores them in
global_context.state for use by downstream authorization plugins
(Cedar, OPA, etc.).

Supports RFC 9396 (Rich Authorization Requests) for fine-grained permissions.

Related to Issue #1439: JWT claims and metadata extraction plugin.

Hook: http_auth_resolve_user

IMPORTANT: The http_auth_resolve_user hook fires BEFORE standard JWT
signature verification in the authentication flow. This plugin decodes
the token without verification because the standard auth system verifies
the signature immediately after this hook returns. Claims stored in
global_context.state are only used by downstream hooks
(e.g. http_auth_check_permission) which fire after authentication
is established. If the JWT is invalid, the request is rejected with
401 and no downstream hook ever reads the unverified claims.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Optional

# Third-Party
import jwt
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    HttpAuthResolveUserPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginResult,
)

logger = logging.getLogger(__name__)


class JwtClaimsExtractionConfig(BaseModel):
    """Configuration for JWT claims extraction.

    Attributes:
        context_key: Key in global_context.state where claims are stored.
    """

    context_key: str = Field(default="jwt_claims", description="Key in global_context.state where claims are stored")


class JwtClaimsExtractionPlugin(Plugin):
    """Plugin to extract JWT claims and add them to global context state.

    Hooks into HTTP_AUTH_RESOLVE_USER to extract claims from JWT tokens
    and make them available in global_context.state for downstream
    authorization plugins (Cedar, OPA, etc.).

    Extracted claims include:
    - Standard claims (sub, iss, aud, exp, iat, nbf, jti)
    - Custom claims (roles, permissions, groups, attributes)
    - RFC 9396 rich authorization request data
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the JWT claims extraction plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = JwtClaimsExtractionConfig(**(config.config or {}))

    async def http_auth_resolve_user(
        self,
        payload: HttpAuthResolveUserPayload,
        context: PluginContext,
    ) -> PluginResult[dict]:
        """Extract JWT claims and store in global context state.

        This hook runs during authentication to extract claims and store
        them for downstream authorization plugins. The standard auth
        system verifies the JWT signature after this hook returns.

        Args:
            payload: Auth payload with credentials and headers.
            context: Plugin execution context with global_context.

        Returns:
            PluginResult with continue_processing=True (passthrough).
        """
        try:
            token = self._extract_token(payload)

            if not token:
                logger.debug("No JWT token found in request, skipping claims extraction")
                return PluginResult(continue_processing=True)

            # Decode JWT without signature verification.
            # The standard auth flow verifies the signature immediately
            # after this hook returns. See module docstring for details.
            claims = jwt.decode(token, options={"verify_signature": False})

            context.global_context.state[self._cfg.context_key] = claims

            logger.debug("Extracted %d JWT claims for user '%s'", len(claims), claims.get("sub", "unknown"))

            if "authorization_details" in claims:
                logger.debug("RFC 9396 authorization_details present with %d entries", len(claims["authorization_details"]))

            return PluginResult(
                continue_processing=True,
                metadata={"jwt_claims_extracted": True, "claims_count": len(claims)},
            )

        except Exception as e:
            logger.error("Failed to extract JWT claims: %s", e, exc_info=True)
            return PluginResult(
                continue_processing=True,
                metadata={"jwt_claims_extracted": False},
            )

    def _extract_token(self, payload: HttpAuthResolveUserPayload) -> Optional[str]:
        """Extract JWT token from request credentials or Authorization header.

        Args:
            payload: Auth payload with credentials and headers.

        Returns:
            JWT token string or None if not found.
        """
        # Try credentials first (Bearer token from HTTPAuthorizationCredentials)
        if payload.credentials and isinstance(payload.credentials, dict):
            if payload.credentials.get("scheme") == "Bearer":
                token = payload.credentials.get("credentials")
                if token:
                    return token

        # Fallback to Authorization header
        headers_dict = getattr(payload.headers, "root", {})
        if headers_dict:
            auth_header = headers_dict.get("authorization") or headers_dict.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                return auth_header[7:]

        return None
