# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/mcp/server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo, Teryl Taylor

Module that contains plugin MCP server code to serve external plugins.
"""

# Standard
import logging
import os
from typing import Any, Dict, TypeVar

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.constants import CONTEXT, ERROR, PLUGIN_NAME, RESULT
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework.models import (
    MCPServerConfig,
    PluginContext,
)

P = TypeVar("P", bound=BaseModel)

logger = logging.getLogger(__name__)


class ExternalPluginServer:
    """External plugin server, providing methods for invoking plugin hooks."""

    def __init__(self, config_path: str | None = None) -> None:
        """Create an external plugin server.

        Args:
            config_path: The configuration file path for loading plugins.
                        If set, this attribute overrides the value in PLUGINS_CONFIG_PATH.

        Examples:
            >>> server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
            >>> server is not None
            True
        """
        self._config_path = config_path or os.environ.get("PLUGINS_CONFIG_PATH", os.path.join(".", "resources", "plugins", "config.yaml"))
        self._config = ConfigLoader.load_config(self._config_path, use_jinja=False)
        self._plugin_manager = PluginManager(self._config_path)

    async def get_plugin_configs(self) -> list[dict]:
        """Return a list of plugin configurations for plugins currently installed on the MCP server.

        Returns:
            A list of plugin configurations.

        Examples:
            >>> import asyncio
            >>> server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
            >>> plugins = asyncio.run(server.get_plugin_configs())
            >>> len(plugins) > 0
            True
        """
        plugins: list[dict] = []
        if self._config.plugins:
            for plug in self._config.plugins:
                plugins.append(plug.model_dump())
        return plugins

    async def get_plugin_config(self, name: str) -> dict | None:
        """Return a plugin configuration give a plugin name.

        Args:
            name: The name of the plugin of which to return the plugin configuration.

        Returns:
            A plugin configuration dict, or None if not found.

        Examples:
            >>> import asyncio
            >>> server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
            >>> c = asyncio.run(server.get_plugin_config(name = "DenyListPlugin"))
            >>> c is not None
            True
            >>> c["name"] == "DenyListPlugin"
            True
        """
        if self._config.plugins:
            for plug in self._config.plugins:
                if plug.name.lower() == name.lower():
                    return plug.model_dump()
        return None

    async def invoke_hook(self, hook_type: str, plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
        """Invoke a plugin hook.

        Args:
            hook_type: The type of hook function to be invoked.
            plugin_name: The name of the plugin to execute.
            payload: The prompt name and arguments to be analyzed.
            context: The contextual and state information required for the execution of the hook.

        Raises:
            ValueError: If unable to retrieve a plugin.

        Returns:
            The transformed or filtered response from the plugin hook.

        Examples:
            >>> import asyncio
            >>> import os
            >>> os.environ["PYTHONPATH"] = "."
            >>> from mcpgateway.plugins.framework import GlobalContext, Plugin, PromptHookType, PromptPrehookPayload, PluginContext, PromptPrehookResult
            >>> server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
            >>> payload = PromptPrehookPayload(prompt_id="123", name="test_prompt", args={"user": "This is so innovative"})
            >>> context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
            >>> initialized = asyncio.run(server.initialize())
            >>> initialized
            True
            >>> result = asyncio.run(server.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, "DenyListPlugin", payload.model_dump(), context.model_dump()))
            >>> result is not None
            True
            >>> result["result"]["continue_processing"]
            False
        """
        global_plugin_manager = PluginManager()
        result_payload: dict[str, Any] = {PLUGIN_NAME: plugin_name}
        try:
            _context = PluginContext.model_validate(context)

            result = await global_plugin_manager.invoke_hook_for_plugin(plugin_name, hook_type, payload, _context, payload_as_json=True)

            result_payload[RESULT] = result.model_dump()
            if not _context.is_empty():
                result_payload[CONTEXT] = _context.model_dump()
            return result_payload
        except PluginError as pe:
            result_payload[ERROR] = pe.error
            return result_payload
        except Exception as ex:
            logger.exception(ex)
            result_payload[ERROR] = convert_exception_to_error(ex, plugin_name=plugin_name).model_dump()
            return result_payload

    async def initialize(self) -> bool:
        """Initialize the plugin server.

        Returns:
            A boolean indicating the intialization status of the server.
        """
        await self._plugin_manager.initialize()
        return self._plugin_manager.initialized

    async def shutdown(self) -> None:
        """Shutdown the plugin server."""
        if self._plugin_manager.initialized:
            await self._plugin_manager.shutdown()

    def get_server_config(self) -> MCPServerConfig:
        """Return the configuration for the plugin server.

        Returns:
            A server configuration including host, port, and TLS information.
        """
        return self._config.server_settings or MCPServerConfig.from_env() or MCPServerConfig()
