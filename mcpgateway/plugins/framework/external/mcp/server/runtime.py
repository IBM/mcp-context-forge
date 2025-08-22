# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/mcp/server/runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Runtime MCP server for external plugins.
"""

# Standard
import asyncio
import logging
from typing import Any, Dict

# Third-Party
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool
from chuk_mcp_runtime.entry import main_async

# First-Party
from mcpgateway.plugins.framework import (
    ExternalPluginServer,
    Plugin,
    PluginContext,
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

logger = logging.getLogger(__name__)

SERVER = None


@mcp_tool(name="get_plugin_configs", description="Get the plugin configurations installed on the server")
async def get_plugin_configs() -> list[dict]:
    """Return a list of plugin configurations for plugins currently installed on the MCP SERVER.

    Returns:
        A list of plugin configurations.
    """
    return await SERVER.get_plugin_configs()


@mcp_tool(name="get_plugin_config", description="Get the plugin configuration installed on the server given a plugin name")
async def get_plugin_config(name: str) -> dict:
    """Return a plugin configuration give a plugin name.

    Args:
        name: The name of the plugin of which to return the plugin configuration.

    Returns:
        A list of plugin configurations.
    """
    return await SERVER.get_plugin_config(name)


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
        """Wrapper function for hook.

        Args:
            plugin: The plugin instance.
            payload: The tool name and arguments to be analyzed.
            context: the contextual and state information required for the execution of the hook.

        Returns:
            The transformed or filtered response from the plugin hook.
        """
        return plugin.prompt_pre_fetch(payload, context)

    return await SERVER.invoke_hook(PromptPrehookPayload, prompt_pre_fetch_func, plugin_name, payload, context)


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
        """Wrapper function for hook.

        Args:
            plugin: The plugin instance.
            payload: The tool name and arguments to be analyzed.
            context: the contextual and state information required for the execution of the hook.

        Returns:
            The transformed or filtered response from the plugin hook.
        """
        return plugin.prompt_post_fetch(payload, context)

    return await SERVER.invoke_hook(PromptPosthookPayload, prompt_post_fetch_func, plugin_name, payload, context)


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
        """Wrapper function for hook.

        Args:
            plugin: The plugin instance.
            payload: The tool name and arguments to be analyzed.
            context: the contextual and state information required for the execution of the hook.

        Returns:
            The transformed or filtered response from the plugin hook.
        """
        return plugin.tool_pre_invoke(payload, context)

    return await SERVER.invoke_hook(ToolPreInvokePayload, tool_pre_invoke_func, plugin_name, payload, context)


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
        """Wrapper function for hook.

        Args:
            plugin: The plugin instance.
            payload: The tool name and arguments to be analyzed.
            context: the contextual and state information required for the execution of the hook.

        Returns:
            The transformed or filtered response from the plugin hook.
        """
        return plugin.tool_post_invoke(payload, context)

    return await SERVER.invoke_hook(ToolPostInvokePayload, tool_post_invoke_func, plugin_name, payload, context)


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

    def resource_pre_fetch_func(plugin: Plugin, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:  # pragma: no cover
        """Wrapper function for hook.

        Args:
            plugin: The plugin instance.
            payload: The tool name and arguments to be analyzed.
            context: the contextual and state information required for the execution of the hook.

        Returns:
            The transformed or filtered response from the plugin hook.
        """
        return plugin.resource_pre_fetch(payload, context)

    return await SERVER.invoke_hook(ResourcePreFetchPayload, resource_pre_fetch_func, plugin_name, payload, context)


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

    def resource_post_fetch_func(plugin: Plugin, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:  # pragma: no cover
        """Wrapper function for hook.

        Args:
            plugin: The plugin instance.
            payload: The tool name and arguments to be analyzed.
            context: the contextual and state information required for the execution of the hook.

        Returns:
            The transformed or filtered response from the plugin hook.
        """
        return plugin.resource_post_fetch(payload, context)

    return await SERVER.invoke_hook(ResourcePostFetchPayload, resource_post_fetch_func, plugin_name, payload, context)


async def run():  # pragma: no cover
    """Run the external plugin SERVER.

    Raises:
        Exception: if unnable to run the plugin SERVER.
    """
    global SERVER  # pylint: disable=global-statement
    SERVER = ExternalPluginServer()
    if await SERVER.initialize():
        try:
            await main_async()
        except Exception:
            logger.exception("Caught error while executing plugin server")
            raise
        finally:
            await SERVER.shutdown()


if __name__ == "__main__":  # pragma: no cover
    # launch
    asyncio.run(run())
