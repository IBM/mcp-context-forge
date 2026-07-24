# -*- coding: utf-8 -*-
"""Location: ./plugins/vault/vault_plugin.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Vault Plugin.

Generates bearer tokens from vault-saved tokens based on OAUTH2 config protecting a tool.

Hook: tool_pre_invoke
"""

# Standard
from enum import Enum
from urllib.parse import urlparse

# Third-Party
import orjson
from pydantic import BaseModel

# First-Party
from cpex.framework import (
    AgentPreInvokePayload,
    AgentPreInvokeResult,
    HttpHeaderPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    get_attr,
)
from mcpgateway.db import get_db
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class VaultHandling(Enum):
    """Vault token handling modes.

    Attributes:
        RAW: Use raw token from vault.
    """

    RAW = "raw"


class SystemHandling(Enum):
    """System identification handling modes.

    Attributes:
        TAG: Identify system from gateway tags.
        OAUTH2_CONFIG: Identify system from OAuth2 config.
    """

    TAG = "tag"
    OAUTH2_CONFIG = "oauth2_config"


class VaultConfig(BaseModel):
    """Configuration for vault plugin.

    Attributes:
        system_tag_prefix: Prefix for system tags.
        vault_header_name: HTTP header name for vault tokens.
        vault_handling: Vault token handling mode.
        system_handling: System identification mode.
        auth_header_tag_prefix: Prefix for auth header tags (e.g., "AUTH_HEADER").
    """

    system_tag_prefix: str = "system"
    vault_header_name: str = "X-Vault-Tokens"
    vault_handling: VaultHandling = VaultHandling.RAW
    system_handling: SystemHandling = SystemHandling.TAG
    auth_header_tag_prefix: str = "AUTH_HEADER"


class Vault(Plugin):
    """Vault plugin that based on OAUTH2 config that protects a tool will generate bearer token based on a vault saved token"""

    def __init__(self, config: PluginConfig):
        """Initialize the vault plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        # load config with pydantic model for convenience
        try:
            self._sconfig = VaultConfig.model_validate(self._config.config or {})
        except Exception:
            self._sconfig = VaultConfig()
        # Normalize vault header name to lowercase for case-insensitive lookup (ASGI headers are lowercase)
        self._vault_header_key = self._sconfig.vault_header_name.lower()

    def _parse_vault_token_key(self, key: str) -> tuple[str, str | None, str | None, str | None]:
        """Parse vault token key in format: system[:scope][:token_type][:token_name].

        Args:
            key: Token key to parse (e.g., "github.com:USER:OAUTH2:TOKEN" or "github.com").

        Returns:
            Tuple of (system, scope, token_type, token_name). Missing parts are None.
        """
        parts = key.split(":")
        system = parts[0] if len(parts) > 0 else key
        scope = parts[1] if len(parts) > 1 else None
        token_type = parts[2] if len(parts) > 2 else None
        token_name = parts[3] if len(parts) > 3 else None
        return system, scope, token_type, token_name

    def _resolve_system_and_auth_from_tags(self, metadata: object) -> tuple[str | None, str | None]:
        """Resolve the vault system key and optional auth header from a target's tags.

        Handles both tag shapes:
        - MCP gateway tags: ``List[Dict{"id", "label"}]`` (or objects exposing ``.label``)
        - A2A agent tags: ``List[str]`` (plain string labels)

        Args:
            metadata: Gateway or A2A agent metadata carrying a ``tags`` attribute.

        Returns:
            Tuple of ``(system_key, auth_header)``; either element may be ``None``.
        """
        # Normalize the varied tag shapes into a uniform list of string labels.
        normalized_tags: list[str] = []
        tags = get_attr(metadata, "tags", [])
        for tag in tags if tags else []:
            if isinstance(tag, dict):
                # Gateway dict tag — use the 'label' field (the actual tag value)
                tag_value = str(tag.get("label", ""))
                if tag_value:
                    normalized_tags.append(tag_value)
            elif isinstance(tag, str):
                # A2A agent tag — plain string label
                if tag:
                    normalized_tags.append(tag)
            elif hasattr(tag, "label"):
                # ORM/object tag exposing a `.label` attribute
                normalized_tags.append(str(getattr(tag, "label")))

        system_key: str | None = None
        auth_header: str | None = None

        # Find system tag with the configured prefix
        system_prefix = self._sconfig.system_tag_prefix + ":"
        system_tag = next((tag for tag in normalized_tags if tag.startswith(system_prefix)), None)
        if system_tag:
            system_key = system_tag.split(system_prefix)[1]
            logger.debug("Using vault system from tags: %s", system_key)

        # Find auth header tag with the configured prefix (e.g., "AUTH_HEADER:X-GitHub-Token")
        auth_header_prefix = self._sconfig.auth_header_tag_prefix + ":"
        auth_header_tag = next((tag for tag in normalized_tags if tag.startswith(auth_header_prefix)), None)
        if auth_header_tag:
            auth_header = auth_header_tag.split(auth_header_prefix)[1]
            logger.debug("Found AUTH_HEADER tag: %s", auth_header)

        return system_key, auth_header

    async def _resolve_system_from_oauth2_config(self, server_id: str | None) -> str | None:
        """Resolve the vault system key from a gateway's OAuth2 config (gateway-only).

        Args:
            server_id: Gateway identifier to load OAuth2 config for.

        Returns:
            The system key (token_url hostname) or ``None`` when unavailable.
        """
        if not server_id:
            return None
        gen = get_db()
        db = next(gen)
        try:
            gateway_service = GatewayService()
            gateway = await gateway_service.get_gateway(db, server_id)
            logger.debug("Gateway oauth_config resolved")
            if gateway.oauth_config and "token_url" in gateway.oauth_config:
                token_url = gateway.oauth_config["token_url"]
                parsed_url = urlparse(token_url)
                logger.debug("Using vault system from oauth_config: %s", parsed_url.hostname)
                return parsed_url.hostname
        finally:
            gen.close()
        return None

    def _apply_vault_token(
        self,
        payload: ToolPreInvokePayload | AgentPreInvokePayload,
        system_key: str | None,
        auth_header: str | None,
    ) -> HttpHeaderPayload | None:
        """Match a vault token for *system_key* and inject the appropriate auth header.

        This helper is shared by ``tool_pre_invoke`` and ``agent_pre_invoke``. It owns all
        header handling, including the SECURITY-critical stripping of the vault header on every
        path (match, no match, parse error, undeterminable system).

        Args:
            payload: The pre-invoke payload carrying request headers.
            system_key: Resolved system identifier, or ``None`` if undeterminable.
            auth_header: Optional custom header name for PAT tokens.

        Returns:
            A new ``HttpHeaderPayload`` when the payload's headers must be replaced, or ``None``
            when there is nothing to change (no headers present, or vault header absent).
        """
        if not system_key:
            logger.warning("System cannot be determined from target metadata.")
            # SECURITY: Strip vault header even when system cannot be determined
            if payload.headers:
                safe_headers = {k.lower(): v for k, v in payload.headers.root.items()}
                if self._vault_header_key in safe_headers:
                    del safe_headers[self._vault_header_key]
                    return HttpHeaderPayload(root=safe_headers)
            return None

        modified = False
        headers: dict[str, str] = {k.lower(): v for k, v in payload.headers.root.items()} if payload.headers else {}

        # Check if vault header exists
        if self._vault_header_key not in headers:
            logger.debug("Vault header '%s' not found in headers", self._vault_header_key)
            return None

        try:
            vault_tokens = orjson.loads(headers[self._vault_header_key])
        except (orjson.JSONDecodeError, TypeError) as e:
            logger.error("Failed to parse vault tokens from header: %s", e)
            # SECURITY: Always remove vault header even on parse error
            del headers[self._vault_header_key]
            return HttpHeaderPayload(root=headers)

        # SECURITY: Always remove vault header immediately after successful parsing
        # This header should NEVER be sent to the upstream server
        del headers[self._vault_header_key]

        if not isinstance(vault_tokens, dict):
            logger.error("Vault tokens header is not a JSON object: %s", type(vault_tokens).__name__)
            return HttpHeaderPayload(root=headers)
        logger.debug("Removed vault header '%s' from headers", self._vault_header_key)

        vault_handling = self._sconfig.vault_handling

        # Try to find matching token in vault_tokens
        # First try exact match with system_key
        token_value: str | None = None
        token_key_used: str | None = None
        if system_key in vault_tokens:
            token_value = str(vault_tokens[system_key])
            token_key_used = str(system_key)
            logger.debug("Found exact match for system key: %s", system_key)
        else:
            # Try to find a key that starts with system_key (complex key format)
            for key in vault_tokens.keys():
                parsed_system, scope, token_type, token_name = self._parse_vault_token_key(key)
                if parsed_system == system_key:
                    token_value = vault_tokens[key]
                    token_key_used = key
                    logger.debug("Found matching token with complex key for system: %s", parsed_system)
                    break

        if token_value and token_key_used:
            # Parse the token key to determine handling
            parsed_system, scope, token_type, token_name = self._parse_vault_token_key(token_key_used)
            # Determine how to handle the token based on token_type and AUTH_HEADER tag
            if token_type == "PAT":
                # Handle Personal Access Token
                logger.debug("Processing PAT token for system: %s", parsed_system)
                # Check if AUTH_HEADER tag is defined
                if auth_header:
                    logger.debug("Using AUTH_HEADER tag for %s: header=%s", parsed_system, auth_header)
                    headers[auth_header.lower()] = str(token_value)
                    modified = True
                else:
                    # No AUTH_HEADER tag, use default Bearer token
                    logger.debug("No AUTH_HEADER tag found for %s, using Bearer token", parsed_system)
                    headers["authorization"] = f"Bearer {token_value}"
                    modified = True
            elif token_type == "OAUTH2" or token_type is None:
                # Handle OAuth2 token or default behavior (when token_type is missing)
                if vault_handling == VaultHandling.RAW:
                    logger.debug("Set Bearer token for system: %s", parsed_system)
                    headers["authorization"] = f"Bearer {token_value}"
                    modified = True
            else:
                # Unknown token type, use default behavior
                logger.warning("Unknown token type '%s', using default Bearer token", token_type)
                if vault_handling == VaultHandling.RAW:
                    headers["authorization"] = f"Bearer {token_value}"
                    modified = True

        if modified:
            logger.debug("Injected auth header for system: %s", system_key)
        elif not token_value:
            # Even if we didn't modify headers (no token match), we still removed the vault header
            logger.warning("Vault tokens provided but no match found for system '%s' - possible misconfiguration", system_key)

        # Always return replacement headers since the vault header was stripped
        return HttpHeaderPayload(root=headers)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Generate bearer tokens from vault-saved tokens before tool invocation.

        Args:
            payload: The tool payload containing arguments.
            context: Plugin execution context.

        Returns:
            Result with potentially modified headers containing bearer token.
        """
        logger.debug("Processing tool pre-invoke for tool %s", payload.name)
        logger.debug("Gateway metadata for server %s", context.global_context.server_id)

        gateway_metadata = context.global_context.metadata.get("gateway")

        system_key: str | None = None
        auth_header: str | None = None
        if self._sconfig.system_handling == SystemHandling.TAG:
            system_key, auth_header = self._resolve_system_and_auth_from_tags(gateway_metadata)
        elif self._sconfig.system_handling == SystemHandling.OAUTH2_CONFIG:
            system_key = await self._resolve_system_from_oauth2_config(context.global_context.server_id)

        new_headers = self._apply_vault_token(payload, system_key, auth_header)
        if new_headers is None:
            return ToolPreInvokeResult()
        payload = payload.model_copy(update={"headers": new_headers})
        return ToolPreInvokeResult(modified_payload=payload)

    async def agent_pre_invoke(self, payload: AgentPreInvokePayload, context: PluginContext) -> AgentPreInvokeResult:
        """Generate bearer tokens from vault-saved tokens before A2A agent invocation.

        Uses the ``a2a_agent`` metadata published by the A2A service. Only ``system_handling:
        "tag"`` is supported for agents; ``oauth2_config`` resolution is gateway-only (it loads
        a Gateway row, which does not exist for A2A agents).

        Args:
            payload: The agent payload containing request headers.
            context: Plugin execution context.

        Returns:
            Result with potentially modified headers containing bearer token.
        """
        logger.debug("Processing agent pre-invoke for agent %s", payload.agent_id)
        logger.debug("A2A agent metadata for server %s", context.global_context.server_id)

        agent_metadata = context.global_context.metadata.get("a2a_agent")

        system_key: str | None = None
        auth_header: str | None = None
        if self._sconfig.system_handling == SystemHandling.TAG:
            system_key, auth_header = self._resolve_system_and_auth_from_tags(agent_metadata)
        else:
            logger.warning("system_handling='%s' is not supported for A2A agents; only 'tag' mode is available. Vault header will be stripped.", self._sconfig.system_handling.value)

        new_headers = self._apply_vault_token(payload, system_key, auth_header)
        if new_headers is None:
            return AgentPreInvokeResult()
        payload = payload.model_copy(update={"headers": new_headers})
        return AgentPreInvokeResult(modified_payload=payload)

    async def shutdown(self) -> None:
        """Shutdown the plugin gracefully.

        Returns:
            None.
        """
        return None
