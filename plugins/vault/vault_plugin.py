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
from mcpgateway.db import get_db
from mcpgateway.plugins.framework import (
    get_attr,
    HttpHeaderPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
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

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Generate bearer tokens from vault-saved tokens before tool invocation.

        Args:
            payload: The tool payload containing arguments.
            context: Plugin execution context.

        Returns:
            Result with potentially modified headers containing bearer token.
        """
        logger.debug(f"Processing tool pre-invoke for tool {payload}  with context {context}")
        logger.debug(f"Gateway metadata {context.global_context.metadata['gateway']}")

        gateway_metadata = context.global_context.metadata.get("gateway")

        system_key: str | None = None
        auth_header: str | None = None
        if self._sconfig.system_handling == SystemHandling.TAG:
            # Extract tags from dict format {"id": "...", "label": "..."}
            normalized_tags: list[str] = []
            gateway_tags = get_attr(gateway_metadata, "tags", [])
            for tag in gateway_tags if gateway_tags else []:
                if isinstance(tag, dict):
                    # Use 'label' field (the actual tag value)
                    tag_value = str(tag.get("label", ""))
                    if tag_value:
                        normalized_tags.append(tag_value)
                elif hasattr(tag, "label"):
                    normalized_tags.append(str(getattr(tag, "label")))
            # Find system tag with the configured prefix
            system_prefix = self._sconfig.system_tag_prefix + ":"
            system_tag = next((tag for tag in normalized_tags if tag.startswith(system_prefix)), None)
            if system_tag:
                system_key = system_tag.split(system_prefix)[1]
                logger.info(f"Using vault system from GW tags: {system_key}")
            # Find auth header tag with the configured prefix (e.g., "AUTH_HEADER:X-GitHub-Token")
            auth_header_prefix = self._sconfig.auth_header_tag_prefix + ":"
            auth_header_tag = next((tag for tag in normalized_tags if tag.startswith(auth_header_prefix)), None)
            if auth_header_tag:
                auth_header = auth_header_tag.split(auth_header_prefix)[1]
                logger.info(f"Found AUTH_HEADER tag: {auth_header}")

        elif self._sconfig.system_handling == SystemHandling.OAUTH2_CONFIG:
            gen = get_db()
            db = next(gen)
            try:
                gateway_service = GatewayService()
                gw_id = context.global_context.server_id
                if gw_id:
                    gateway = await gateway_service.get_gateway(db, gw_id)
                    logger.info(f"Gateway used {gateway.oauth_config}")
                    if gateway.oauth_config and "token_url" in gateway.oauth_config:
                        token_url = gateway.oauth_config["token_url"]
                        parsed_url = urlparse(token_url)
                        system_key = parsed_url.hostname
                        logger.info(f"Using vault system from oauth_config: {system_key}")
            finally:
                gen.close()

        if not system_key:
            logger.warning("System cannot be determined from gateway metadata.")
            return ToolPreInvokeResult()

        modified = False
        headers: dict[str, str] = payload.headers.model_dump() if payload.headers else {}

        # Check if vault header exists
        if self._sconfig.vault_header_name not in headers:
            logger.debug(f"Vault header '{self._sconfig.vault_header_name}' not found in headers")
            return ToolPreInvokeResult()

        try:
            vault_tokens: dict[str, str] = orjson.loads(headers[self._sconfig.vault_header_name])
        except (orjson.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse vault tokens from header: {e}")
            return ToolPreInvokeResult()

        vault_handling = self._sconfig.vault_handling

        # Try to find matching token in vault_tokens
        # First try exact match with system_key
        token_value: str | None = None
        token_key_used: str | None = None
        if system_key in vault_tokens:
            token_value = str(vault_tokens[system_key])
            token_key_used = str(system_key)
            logger.info(f"Found exact match for system key: {system_key}")
        else:
            # Try to find a key that starts with system_key (complex key format)
            for key in vault_tokens.keys():
                parsed_system, scope, token_type, token_name = self._parse_vault_token_key(key)
                if parsed_system == system_key:
                    token_value = vault_tokens[key]
                    token_key_used = key
                    logger.info(f"Found matching token with complex key: {key} (system: {parsed_system}, scope: {scope}, type: {token_type}, name: {token_name})")
                    break

        if token_value and token_key_used:
            # Parse the token key to determine handling
            parsed_system, scope, token_type, token_name = self._parse_vault_token_key(token_key_used)
            # Determine how to handle the token based on token_type and AUTH_HEADER tag
            if token_type == "PAT":
                # Handle Personal Access Token
                logger.info(f"Processing PAT token for system: {parsed_system}")
                # Check if AUTH_HEADER tag is defined
                if auth_header:
                    logger.info(f"Using AUTH_HEADER tag for {parsed_system}: header={auth_header}")
                    headers[auth_header] = str(token_value)
                    modified = True
                else:
                    # No AUTH_HEADER tag, use default Bearer token
                    logger.info(f"No AUTH_HEADER tag found for {parsed_system}, using Bearer token")
                    headers["Authorization"] = f"Bearer {token_value}"
                    modified = True
            elif token_type == "OAUTH2" or token_type is None:
                # Handle OAuth2 token or default behavior (when token_type is missing)
                if vault_handling == VaultHandling.RAW:
                    logger.info(f"Set Bearer token for system: {parsed_system}")
                    headers["Authorization"] = f"Bearer {token_value}"
                    modified = True
            else:
                # Unknown token type, use default behavior
                logger.warning(f"Unknown token type '{token_type}', using default Bearer token")
                if vault_handling == VaultHandling.RAW:
                    headers["Authorization"] = f"Bearer {token_value}"
                    modified = True

            # Remove vault header after processing
            if modified and self._sconfig.vault_header_name in headers:
                del headers[self._sconfig.vault_header_name]

            payload.headers = HttpHeaderPayload(root=headers)

        if modified:
            logger.info(f"Modified tool '{payload.name}' to add auth header")
            return ToolPreInvokeResult(modified_payload=payload)

        return ToolPreInvokeResult()

    async def shutdown(self) -> None:
        """Shutdown the plugin gracefully.

        Returns:
            None.
        """
        return None
