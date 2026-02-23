# -*- coding: utf-8 -*-
"""Location: ./plugins/iam_pre_tool/iam_pre_tool.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ioannis Ioannou

IAM Pre-Tool Plugin.

Handles IAM requirements for MCP servers including:
- OAuth2 client credentials token acquisition
- Token exchange flows
- Access token injection into HTTP requests

Related to Issue #1437: Create IAM pre-tool plugin

Hook: http_pre_request

This plugin intercepts HTTP requests to MCP servers and injects
authentication credentials (access tokens) into the Authorization header.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timedelta, timezone
import logging
from typing import Dict, Optional

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    HttpHeaderPayload,
    HttpPreRequestPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginResult,
)

logger = logging.getLogger(__name__)


class TokenCacheEntry(BaseModel):
    """Cached token entry with expiration.

    Attributes:
        access_token: The OAuth2 access token.
        expires_at: When the token expires (UTC).
        token_type: Token type (usually 'Bearer').
    """

    access_token: str
    expires_at: datetime
    token_type: str = "Bearer"

    def is_expired(self) -> bool:
        """Check if token is expired.

        Returns:
            True if token is expired or about to expire (60s buffer).
        """
        return datetime.now(timezone.utc) >= (self.expires_at - timedelta(seconds=60))


class IamPreToolConfig(BaseModel):
    """Configuration for IAM pre-tool plugin.

    Attributes:
        enabled: Whether the plugin is enabled.
        token_cache_ttl_seconds: Default TTL for cached tokens.
        oauth2_client_credentials_enabled: Enable OAuth2 client credentials flow.
        token_exchange_enabled: Enable OAuth2 token exchange (RFC 8693).
        inject_bearer_token: Whether to inject bearer tokens into requests.
        server_credentials: Map of server IDs to OAuth2 client credentials.
    """

    enabled: bool = True
    token_cache_ttl_seconds: int = 3600
    oauth2_client_credentials_enabled: bool = False
    token_exchange_enabled: bool = False
    inject_bearer_token: bool = True
    server_credentials: Dict[str, Dict[str, str]] = Field(default_factory=dict)


class IamPreToolPlugin(Plugin):
    """IAM pre-tool plugin for token acquisition and credential injection.

    This plugin handles authentication to MCP servers by:
    1. Acquiring access tokens via OAuth2 flows (client credentials)
    2. Caching tokens to avoid repeated auth requests
    3. Injecting tokens into HTTP Authorization headers

    Phase 1 Scope (Issue #1437):
    - Basic token acquisition (client credentials)
    - Token caching
    - Bearer token injection

    Future enhancements (Issue #1438):
    - Token exchange (RFC 8693)
    - Human-in-the-loop authorization flows
    - Enhanced OAuth2 flows (PKCE, device code)
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the IAM pre-tool plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = IamPreToolConfig(**(config.config or {}))
        self._token_cache: Dict[str, TokenCacheEntry] = {}
        logger.info(f"IamPreToolPlugin initialized: enabled={self._cfg.enabled}")

    async def http_pre_request(
        self,
        payload: HttpPreRequestPayload,
        context: PluginContext,
    ) -> PluginResult[HttpHeaderPayload]:
        """Inject authentication credentials before HTTP request.

        Args:
            payload: HTTP pre-request payload with headers and metadata.
            context: Plugin execution context.

        Returns:
            PluginResult with modified headers containing auth credentials.
        """
        if not self._cfg.enabled or not self._cfg.inject_bearer_token:
            return PluginResult(modified_payload=payload.headers)

        # Extract server/tool ID from context
        server_id = context.state.get("server_id") or context.state.get("tool_id")

        if not server_id:
            logger.debug("No server_id or tool_id in context, skipping auth injection")
            return PluginResult(modified_payload=payload.headers)

        # Check if we have credentials configured for this server
        if server_id not in self._cfg.server_credentials:
            logger.debug(f"No credentials configured for server: {server_id}")
            return PluginResult(modified_payload=payload.headers)

        # Get or acquire access token
        access_token = await self._get_access_token(server_id, context)

        if not access_token:
            logger.warning(f"Failed to acquire access token for server: {server_id}")
            return PluginResult(modified_payload=payload.headers)

        # Inject token into Authorization header
        modified_headers = HttpHeaderPayload(root=dict(payload.headers))
        modified_headers["authorization"] = f"Bearer {access_token}"

        logger.info(f"Injected bearer token for server: {server_id}")
        return PluginResult(modified_payload=modified_headers)

    async def _get_access_token(
        self,
        server_id: str,
        context: PluginContext
    ) -> Optional[str]:
        """Get access token for a server (from cache or acquire new).

        Args:
            server_id: Server/tool identifier.
            context: Plugin execution context.

        Returns:
            Access token string, or None if acquisition failed.
        """
        # Check cache first
        if server_id in self._token_cache:
            cached = self._token_cache[server_id]
            if not cached.is_expired():
                logger.debug(f"Using cached token for server: {server_id}")
                return cached.access_token

        # Acquire new token
        if self._cfg.oauth2_client_credentials_enabled:
            return await self._acquire_token_client_credentials(server_id, context)

        # No token acquisition method enabled
        logger.warning("No token acquisition method enabled")
        return None

    async def _acquire_token_client_credentials(
        self,
        server_id: str,
        context: PluginContext,
    ) -> Optional[str]:
        """Acquire access token using OAuth2 client credentials flow.

        Args:
            server_id: Server/tool identifier.
            context: Plugin execution context.

        Returns:
            Access token string, or None if acquisition failed.
        """
        # TODO: Implement OAuth2 client credentials flow
        # This is a placeholder for Phase 1
        # Will be implemented in conjunction with Issue #1434 (OAuth2 library)

        logger.info(f"OAuth2 client credentials flow not yet implemented for: {server_id}")
        return None
