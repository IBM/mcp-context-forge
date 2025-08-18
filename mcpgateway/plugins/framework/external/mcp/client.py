# -*- coding: utf-8 -*-
"""External plugin client which connects to a remote server through MCP.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Module that contains plugin MCP client code to serve external plugins.
"""

# Standard
from contextlib import AsyncExitStack
import json
import logging
import os
from typing import Any, Optional

# Third-Party
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.constants import (
    CONTEXT,
    GET_PLUGIN_CONFIG,
    IGNORE_CONFIG_EXTERNAL,
    NAME,
    PAYLOAD,
    PLUGIN_NAME,
    PYTHON,
    PYTHON_SUFFIX,
)
from mcpgateway.plugins.framework.models import (
    HookType,
    PluginConfig,
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
from mcpgateway.schemas import TransportType

logger = logging.getLogger(__name__)


class ExternalPlugin(Plugin):
    """External plugin object for pre/post processing of inputs and outputs at various locations throughout the mcp gateway. The External Plugin connects to a remote MCP server that contains plugins."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize a plugin with a configuration and context.

        Args:
            config: The plugin configuration
        """
        super().__init__(config)
        self._session: Optional[ClientSession] = None
        self._exit_stack = AsyncExitStack()
        self._http: Optional[Any]
        self._stdio: Optional[Any]
        self._write: Optional[Any]

    async def initialize(self) -> None:
        """Initialize the plugin's connection to the MCP server.

        Raises:
            ValueError: if unable to retrieve plugin configuration of external plugin.
        """

        if not self._config.mcp:
            raise ValueError(f"The mcp section must be defined for external plugin {self.name}")
        if self._config.mcp.proto == TransportType.STDIO:
            await self.__connect_to_stdio_server(self._config.mcp.script)
        elif self._config.mcp.proto == TransportType.STREAMABLEHTTP:
            await self.__connect_to_http_server(self._config.mcp.url)

        config = await self.__get_plugin_config()

        if not config:
            raise ValueError(f"Unable to retrieve configuration for external plugin {self.name}")

        current_config = self._config.model_dump(exclude_unset=True)
        remote_config = config.model_dump(exclude_unset=True)
        remote_config.update(current_config)

        context = {IGNORE_CONFIG_EXTERNAL: True}

        self._config = PluginConfig.model_validate(remote_config, context=context)

    async def __connect_to_stdio_server(self, server_script_path: str) -> None:
        """Connect to an MCP plugin server via stdio.

        Args:
            server_script_path: Path to the server script (.py).

        Raises:
            ValueError: if stdio script is not a python script.
        """
        is_python = server_script_path.endswith(PYTHON_SUFFIX) if server_script_path else False
        if not is_python:
            raise ValueError("Server script must be a .py file")

        current_env = os.environ.copy()

        server_params = StdioServerParameters(command=PYTHON, args=[server_script_path], env=current_env)

        stdio_transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
        self._stdio, self._write = stdio_transport
        self._session = await self._exit_stack.enter_async_context(ClientSession(self._stdio, self._write))

        await self._session.initialize()

        # List available tools
        response = await self._session.list_tools()
        tools = response.tools
        logger.info("\nConnected to plugin MCP server (stdio) with tools: %s", " ".join([tool.name for tool in tools]))

    async def __connect_to_http_server(self, uri: str):
        """Connect to an MCP plugin server via streamable http.

        Args:
            uri: the URI of the mcp plugin server.
        """

        http_transport = await self._exit_stack.enter_async_context(streamablehttp_client(uri))
        self._http, self._write, _ = http_transport
        self._session = await self._exit_stack.enter_async_context(ClientSession(self._http, self._write))

        await self._session.initialize()

        # List available tools
        response = await self._session.list_tools()
        tools = response.tools
        logger.info("\nConnected to plugin MCP (http) server with tools: %s", " ".join([tool.name for tool in tools]))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The prompt prehook with name and arguments as modified or blocked by the plugin.
        """

        result = await self._session.call_tool(HookType.PROMPT_PRE_FETCH, {PLUGIN_NAME: self.name, PAYLOAD: payload, CONTEXT: context})
        for content in result.content:
            res = json.loads(content.text)
            return PromptPrehookResult.model_validate(res)
        return PromptPrehookResult(continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            A set of prompt messages as modified or blocked by the plugin.
        """

        result = await self._session.call_tool(HookType.PROMPT_POST_FETCH, {PLUGIN_NAME: self.name, PAYLOAD: payload, CONTEXT: context})
        print(result)
        for content in result.content:
            res = json.loads(content.text)
            return PromptPosthookResult.model_validate(res)
        return PromptPosthookResult(continue_processing=True)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The tool prehook with name and arguments as modified or blocked by the plugin.
        """

        result = await self._session.call_tool(HookType.TOOL_PRE_INVOKE, {PLUGIN_NAME: self.name, PAYLOAD: payload, CONTEXT: context})
        for content in result.content:
            res = json.loads(content.text)
            return ToolPreInvokeResult.model_validate(res)
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The tool posthook with name and arguments as modified or blocked by the plugin.
        """

        result = await self._session.call_tool(HookType.TOOL_POST_INVOKE, {PLUGIN_NAME: self.name, PAYLOAD: payload, CONTEXT: context})
        for content in result.content:
            res = json.loads(content.text)
            return ToolPostInvokeResult.model_validate(res)
        return ToolPostInvokeResult(continue_processing=True)

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Plugin hook run before a resource is fetched.

        Args:
            payload: The resource payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The resource prehook with name and arguments as modified or blocked by the plugin.
        """

        result = await self._session.call_tool(HookType.RESOURCE_PRE_FETCH, {PLUGIN_NAME: self.name, PAYLOAD: payload, CONTEXT: context})
        for content in result.content:
            res = json.loads(content.text)
            return ResourcePreFetchResult.model_validate(res)
        return ResourcePreFetchResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Plugin hook run after a resource is fetched.

        Args:
            payload: The resource payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The resource posthook with name and arguments as modified or blocked by the plugin.
        """

        result = await self._session.call_tool(HookType.RESOURCE_POST_FETCH, {PLUGIN_NAME: self.name, PAYLOAD: payload, CONTEXT: context})
        for content in result.content:
            res = json.loads(content.text)
            return ResourcePostFetchResult.model_validate(res)
        return ResourcePostFetchResult(continue_processing=True)

    async def __get_plugin_config(self) -> PluginConfig | None:
        """Retrieve plugin configuration for the current plugin on the remote MCP server.

        Returns:
            A plugin configuration for the current plugin from a remote MCP server.
        """
        configs = await self._session.call_tool(GET_PLUGIN_CONFIG, {NAME: self.name})
        for content in configs.content:
            conf = json.loads(content.text)
            return PluginConfig.model_validate(conf)
        return None

    async def shutdown(self) -> None:
        """Plugin cleanup code."""
        await self._exit_stack.aclose()
