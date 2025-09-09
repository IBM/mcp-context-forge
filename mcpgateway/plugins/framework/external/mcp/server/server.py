# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/mcp/server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Plugin MCP Server.
         Fred Araujo

Module that contains plugin MCP server code to serve external plugins.
"""

# Standard
import asyncio
import logging
import os
from typing import Any, Callable, Dict, Type, TypeVar

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.constants import CONTEXT, ERROR, PLUGIN_NAME, RESULT
from mcpgateway.plugins.framework.errors import convert_exception_to_error
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.manager import DEFAULT_PLUGIN_TIMEOUT, PluginManager
from mcpgateway.plugins.framework.models import (
    PluginContext,
    PluginErrorModel,
    PluginResult,
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
        for plug in self._config.plugins:
            plugins.append(plug.model_dump())
        return plugins

    async def get_plugin_config(self, name: str) -> dict:
        """Return a plugin configuration give a plugin name.

        Args:
            name: The name of the plugin of which to return the plugin configuration.

        Returns:
            A list of plugin configurations.

        Examples:
            >>> import asyncio
            >>> server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
            >>> c = asyncio.run(server.get_plugin_config(name = "DenyListPlugin"))
            >>> c is not None
            True
            >>> c["name"] == "DenyListPlugin"
            True
        """
        for plug in self._config.plugins:
            if plug.name.lower() == name.lower():
                return plug.model_dump()
        return None

    async def invoke_hook(
        self, payload_model: Type[P], hook_function: Callable[[Plugin], Callable[[P, PluginContext], PluginResult]], plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> dict:
        """Invoke a plugin hook.

        Args:
            payload_model: The type of the payload accepted for the hook.
            hook_function: The hook function to be invoked.
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
            >>> from mcpgateway.plugins.framework import GlobalContext, PromptPrehookPayload, PluginContext, PromptPrehookResult
            >>> server = ExternalPluginServer(config_path="./tests/unit/mcpgateway/plugins/fixtures/configs/valid_multiple_plugins_filter.yaml")
            >>> def prompt_pre_fetch_func(plugin: Plugin, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
            ...     return plugin.prompt_pre_fetch(payload, context)
            >>> payload = PromptPrehookPayload(name="test_prompt", args={"user": "This is so innovative"})
            >>> context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
            >>> initialized = asyncio.run(server.initialize())
            >>> initialized
            True
            >>> result = asyncio.run(server.invoke_hook(PromptPrehookPayload, prompt_pre_fetch_func, "DenyListPlugin", payload.model_dump(), context.model_dump()))
            >>> result is not None
            True
            >>> result["result"]["continue_processing"]
            False
        """
        global_plugin_manager = PluginManager()
        plugin_timeout = global_plugin_manager.config.plugin_settings.plugin_timeout if global_plugin_manager.config else DEFAULT_PLUGIN_TIMEOUT
        plugin = global_plugin_manager.get_plugin(plugin_name)
        result_payload: dict[str, Any] = {PLUGIN_NAME: plugin_name}
        try:
            if plugin:
                _payload = payload_model.model_validate(payload)
                _context = PluginContext.model_validate(context)
                result = await asyncio.wait_for(hook_function(plugin, _payload, _context), plugin_timeout)
                result_payload[RESULT] = result.model_dump()
                if not _context.is_empty():
                    result_payload[CONTEXT] = _context.model_dump()
                return result_payload
            raise ValueError(f"Unable to retrieve plugin {plugin_name} to execute.")
        except asyncio.TimeoutError:
            result_payload[ERROR] = PluginErrorModel(message=f"Plugin {plugin_name} timed out from execution after {plugin_timeout} seconds.", plugin_name=plugin_name).model_dump()
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
        """Shutdow the plugin server."""
        if self._plugin_manager.initialized:
            await self._plugin_manager.shutdown()
