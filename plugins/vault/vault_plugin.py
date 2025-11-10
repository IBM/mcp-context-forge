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
import json
from urllib.parse import urlparse

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.db import get_db
from mcpgateway.plugins.framework import (
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
    """

    system_tag_prefix: str = "system"
    vault_header_name: str = "X-Vault-Tokens"
    vault_handling: VaultHandling = VaultHandling.RAW
    system_handling: SystemHandling = SystemHandling.TAG


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

        gateway_metadata = context.global_context.metadata["gateway"]

        system_key: str | None = None
        if self._sconfig.system_handling == SystemHandling.TAG:
            system_tag = next((tag for tag in gateway_metadata.tags if tag.startswith(self._sconfig.system_tag_prefix)), None)
            match_exp = self._sconfig.system_tag_prefix + ":"
            if system_tag and system_tag.startswith(match_exp):
                system_key = system_tag.split(match_exp)[1]
                logger.info(f"Using vault system from GW tags: {system_key}")

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
            vault_tokens: dict[str, str] = json.loads(headers[self._sconfig.vault_header_name])
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse vault tokens from header: {e}")
            return ToolPreInvokeResult()

        vault_handling = self._sconfig.vault_handling

        if system_key in vault_tokens:
            if vault_handling == VaultHandling.RAW:
                logger.info(f"Set Bearer token for system tag: {system_key}")
                bearer_token: str = str(vault_tokens[system_key])
                headers["Authorization"] = f"Bearer {bearer_token}"
                del headers[self._sconfig.vault_header_name]
                modified = True

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
