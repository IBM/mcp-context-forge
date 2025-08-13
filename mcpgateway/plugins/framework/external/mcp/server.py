# -*- coding: utf-8 -*-
"""Plugin MCP Server.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Module that contains plugin MCP server code to serve external plugins.
"""
# Standard
import asyncio
import logging
import os

# Third-Party
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.entry import main_async

# First-Party
from mcpgateway.plugins.framework.errors import convert_exception_to_error
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.manager import DEFAULT_PLUGIN_TIMEOUT, PluginManager
from mcpgateway.plugins.framework.models import (
    PluginContext,
    PluginErrorModel,
    PromptPosthookPayload,
    PromptPrehookPayload,
)

logger = logging.getLogger(__name__)

config_file = os.environ.get("CFMCP_PLUGIN_CONFIG", "resources/plugins/config.yaml")
global_plugin_manager = PluginManager(config_file)


async def initialize() -> None:
    """Initialize the plugin manager with configured plugins."""
    await global_plugin_manager.initialize()


@mcp_tool(name="get_plugin_configs", description="Get the plugin configurations installed on the server")
async def get_plugin_configs() -> list[dict]:
    """Return a list of plugin configurations for plugins currently installed on the MCP server.

    Returns:
        A list of plugin configurations.
    """
    config = ConfigLoader.load_config(config_file, use_jinja=False)
    plugins: list[dict] = []
    for plug in config.plugins:
        plugins.append(plug.model_dump())
    return plugins


@mcp_tool(name="get_plugin_config", description="Get the plugin configuration installed on the server given a plugin name")
async def get_plugin_config(name: str) -> dict:
    """Return a plugin configuration give a plugin name.

    Args:
        name: the name of the plugin of which to return the plugin configuration.

    Returns:
        A list of plugin configurations.
    """
    config = ConfigLoader.load_config(config_file, use_jinja=False)
    for plug in config.plugins:
        if plug.name.lower() == name.lower():
            return plug.model_dump()
    return None


@mcp_tool(name="prompt_pre_fetch", description="Execute prompt prefetch hook for a plugin")
async def prompt_pre_fetch(plugin_name: str, payload: dict, context: dict) -> dict:
    """Invoke the prompt pre fetch hook for a particular plugin.

    Args:
        plugin_name: the name of the plugin to execute.
        payload: the prompt name and arguments to be analyzed.
        context: the contextual and state information required for the execution of the hook.

    Raises:
        ValueError: if unable to retrieve a plugin.

    Returns:
        The transformed or filtered response from the plugin hook.
    """
    plugin_timeout = global_plugin_manager.config.plugin_settings.plugin_timeout if global_plugin_manager.config else DEFAULT_PLUGIN_TIMEOUT
    plugin = global_plugin_manager.get_plugin(plugin_name)
    try:
        if plugin:
            prepayload = PromptPrehookPayload.model_validate(payload)
            precontext = PluginContext.model_validate(context)
            result = await asyncio.wait_for(plugin.prompt_pre_fetch(prepayload, precontext), plugin_timeout)
            return result.model_dump()
        raise ValueError(f"Unable to retrieve plugin {plugin_name} to execute.")
    except asyncio.TimeoutError:
        return PluginErrorModel(message=f"Plugin {plugin_name} timed out from execution after {plugin_timeout} seconds.", plugin_name=plugin_name).model_dump()
    except Exception as ex:
        logger.exception(ex)
        return convert_exception_to_error(ex, plugin_name=plugin_name).model_dump()


@mcp_tool(name="prompt_post_fetch", description="Execute prompt postfetch hook for a plugin")
async def prompt_post_fetch(plugin_name: str, payload: dict, context: dict) -> dict:
    """Call plugin's prompt post-fetch hook.

    Args:
        plugin_name: The name of the plugin to execute.
        payload: The prompt payload to be analyzed.
        context: Contextual information about the hook call.

    Raises:
        ValueError: if unable to retrieve a plugin.

    Returns:
        The result of the plugin execution.
    """
    plugin_timeout = global_plugin_manager.config.plugin_settings.plugin_timeout if global_plugin_manager.config else DEFAULT_PLUGIN_TIMEOUT
    plugin = global_plugin_manager.get_plugin(plugin_name)
    try:
        if plugin:
            postpayload = PromptPosthookPayload.model_validate(payload)
            postcontext = PluginContext.model_validate(context)
            result = await asyncio.wait_for(plugin.prompt_post_fetch(postpayload, postcontext), plugin_timeout)
            return result.model_dump()
        raise ValueError(f"Unable to retrieve plugin {plugin_name} to execute.")
    except asyncio.TimeoutError:
        return PluginErrorModel(message=f"Plugin {plugin_name} timed out from execution after {plugin_timeout} seconds.", plugin_name=plugin_name).model_dump()
    except Exception as ex:
        logger.exception(ex)
        return convert_exception_to_error(ex, plugin_name=plugin_name).model_dump()


async def server_main():
    """Initialize plugin manager and run mcp server."""
    await initialize()
    await main_async()


if __name__ == "__main__":
    # launch
    asyncio.run(server_main())
