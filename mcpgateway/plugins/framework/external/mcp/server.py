# -*- coding: utf-8 -*-
"""Plugin MCP Server.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor
         Fred Araujo

Module that contains plugin MCP server code to serve external plugins.
"""

# Standard
import asyncio
import logging
import os
from typing import Any, Callable, Dict, Type, TypeVar

# Third-Party
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.entry import main_async
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import Plugin
from mcpgateway.plugins.framework.errors import convert_exception_to_error
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.manager import DEFAULT_PLUGIN_TIMEOUT, PluginManager
from mcpgateway.plugins.framework.models import (
    PluginContext,
    PluginErrorModel,
    PluginResult,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

P = TypeVar("P", bound=BaseModel)

logger = logging.getLogger(__name__)

config_file = os.environ.get("PLUGINS_CONFIG_PATH", os.path.join(".", "resources", "plugins", "config.yaml"))
global_plugin_manager = None


async def initialize() -> None:
    """Initialize the plugin manager with configured plugins."""
    try:
        global global_plugin_manager
        global_plugin_manager = PluginManager(config_file)
        await global_plugin_manager.initialize()
    except Exception:
        logger.exception("Could not initialize external plugin server.")
        raise


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
        name: The name of the plugin of which to return the plugin configuration.

    Returns:
        A list of plugin configurations.
    """
    config = ConfigLoader.load_config(config_file, use_jinja=False)
    for plug in config.plugins:
        if plug.name.lower() == name.lower():
            return plug.model_dump()
    return None


async def _invoke_hook(
    payload_model: Type[P], hook_function: Callable[[Plugin], Callable[[P, PluginContext], PluginResult]], plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]
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
    """
    plugin_timeout = global_plugin_manager.config.plugin_settings.plugin_timeout if global_plugin_manager.config else DEFAULT_PLUGIN_TIMEOUT
    plugin = global_plugin_manager.get_plugin(plugin_name)
    try:
        if plugin:
            _payload = payload_model.model_validate(payload)
            _context = PluginContext.model_validate(context)
            result = await asyncio.wait_for(hook_function(plugin, _payload, _context), plugin_timeout)
            return result.model_dump()
        raise ValueError(f"Unable to retrieve plugin {plugin_name} to execute.")
    except asyncio.TimeoutError:
        return PluginErrorModel(message=f"Plugin {plugin_name} timed out from execution after {plugin_timeout} seconds.", plugin_name=plugin_name).model_dump()
    except Exception as ex:
        logger.exception(ex)
        return convert_exception_to_error(ex, plugin_name=plugin_name).model_dump()


@mcp_tool(name="prompt_pre_fetch", description="Execute prompt prefetch hook for a plugin")
async def prompt_pre_fetch(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Invoke the prompt pre fetch hook for a particular plugin.

    Args:
        plugin_name: The name of the plugin to execute.
        payload: The prompt name and arguments to be analyzed.
        context: The contextual and state information required for the execution of the hook.

    Raises:
        ValueError: If unable to retrieve a plugin.

    Returns:
        The transformed or filtered response from the plugin hook.
    """

    def prompt_pre_fetch_func(plugin: Plugin, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        return plugin.prompt_pre_fetch(payload, context)

    return await _invoke_hook(PromptPrehookPayload, prompt_pre_fetch_func, plugin_name, payload, context)


@mcp_tool(name="prompt_post_fetch", description="Execute prompt postfetch hook for a plugin")
async def prompt_post_fetch(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
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

    def prompt_post_fetch_func(plugin: Plugin, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        return plugin.prompt_post_fetch(payload, context)

    return await _invoke_hook(PromptPosthookPayload, prompt_post_fetch_func, plugin_name, payload, context)


@mcp_tool(name="tool_pre_invoke", description="Execute tool pre-invoke hook for a plugin")
async def tool_pre_invoke(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Invoke the tool pre-invoke hook for a particular plugin.

    Args:
        plugin_name: The name of the plugin to execute.
        payload: The tool name and arguments to be analyzed.
        context: The contextual and state information required for the execution of the hook.

    Raises:
        ValueError: If unable to retrieve a plugin.

    Returns:
        The transformed or filtered response from the plugin hook.
    """

    def tool_pre_invoke_func(plugin: Plugin, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        return plugin.tool_pre_invoke(payload, context)

    return await _invoke_hook(ToolPreInvokePayload, tool_pre_invoke_func, plugin_name, payload, context)


@mcp_tool(name="tool_post_invoke", description="Execute tool post-invoke hook for a plugin")
async def tool_post_invoke(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Invoke the tool post-invoke hook for a particular plugin.

    Args:
        plugin_name: The name of the plugin to execute.
        payload: The tool name and arguments to be analyzed.
        context: the contextual and state information required for the execution of the hook.

    Raises:
        ValueError: If unable to retrieve a plugin.

    Returns:
        The transformed or filtered response from the plugin hook.
    """

    def tool_post_invoke_func(plugin: Plugin, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        return plugin.tool_post_invoke(payload, context)

    return await _invoke_hook(ToolPostInvokePayload, tool_post_invoke_func, plugin_name, payload, context)


@mcp_tool(name="resource_pre_fetch", description="Execute resource prefetch hook for a plugin")
async def resource_pre_fetch(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Invoke the resource pre fetch hook for a particular plugin.

    Args:
        plugin_name: The name of the plugin to execute.
        payload: The resource name and arguments to be analyzed.
        context: The contextual and state information required for the execution of the hook.

    Raises:
        ValueError: If unable to retrieve a plugin.

    Returns:
        The transformed or filtered response from the plugin hook.
    """

    def resource_pre_fetch_func(plugin: Plugin, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        return plugin.resource_pre_fetch(payload, context)

    return await _invoke_hook(ResourcePreFetchPayload, resource_pre_fetch_func, plugin_name, payload, context)


@mcp_tool(name="resource_post_fetch", description="Execute resource postfetch hook for a plugin")
async def resource_post_fetch(plugin_name: str, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
    """Call plugin's resource post-fetch hook.

    Args:
        plugin_name: The name of the plugin to execute.
        payload: The resource payload to be analyzed.
        context: Contextual information about the hook call.

    Raises:
        ValueError: if unable to retrieve a plugin.

    Returns:
        The result of the plugin execution.
    """

    def resource_post_fetch_func(plugin: Plugin, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        return plugin.resource_post_fetch(payload, context)

    return await _invoke_hook(ResourcePostFetchPayload, resource_post_fetch_func, plugin_name, payload, context)


async def run_plugin_mcp_server():
    """Initialize plugin manager and run mcp server."""
    await initialize()
    await main_async()


if __name__ == "__main__":  # pragma: no cover - executed only when run directly
    # launch
    asyncio.run(run_plugin_mcp_server())
