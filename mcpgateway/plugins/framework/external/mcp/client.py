# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/mcp/client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

External plugin client which connects to a remote server through MCP.
Module that contains plugin MCP client code to serve external plugins.
"""

# Standard
import asyncio
from contextlib import AsyncExitStack
import json
import logging
import os
from typing import Any, Optional, Type, TypeVar

# Third-Party
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.constants import CONTEXT, ERROR, GET_PLUGIN_CONFIG, IGNORE_CONFIG_EXTERNAL, NAME, PAYLOAD, PLUGIN_NAME, PYTHON, PYTHON_SUFFIX, RESULT
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError
from mcpgateway.plugins.framework.models import (
    HookType,
    PluginConfig,
    PluginContext,
    PluginErrorModel,
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

P = TypeVar("P", bound=BaseModel)

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
        self._current_task = asyncio.current_task()

    async def initialize(self) -> None:
        """Initialize the plugin's connection to the MCP server.

        Raises:
            PluginError: if unable to retrieve plugin configuration of external plugin.
        """

        if not self._config.mcp:
            raise PluginError(error=PluginErrorModel(message="The mcp section must be defined for external plugin", plugin_name=self.name))
        if self._config.mcp.proto == TransportType.STDIO:
            await self.__connect_to_stdio_server(self._config.mcp.script)
        elif self._config.mcp.proto == TransportType.STREAMABLEHTTP:
            await self.__connect_to_http_server(self._config.mcp.url)

        try:
            config = await self.__get_plugin_config()

            if not config:
                raise PluginError(error=PluginErrorModel(message="Unable to retrieve configuration for external plugin", plugin_name=self.name))

            current_config = self._config.model_dump(exclude_unset=True)
            remote_config = config.model_dump(exclude_unset=True)
            remote_config.update(current_config)

            context = {IGNORE_CONFIG_EXTERNAL: True}

            self._config = PluginConfig.model_validate(remote_config, context=context)
        except PluginError as pe:
            logger.exception(pe)
            raise
        except Exception as e:
            logger.exception(e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

    async def __connect_to_stdio_server(self, server_script_path: str) -> None:
        """Connect to an MCP plugin server via stdio.

        Args:
            server_script_path: Path to the server script (.py).

        Raises:
            PluginError: if stdio script is not a python script or if there is a connection error.
        """
        is_python = server_script_path.endswith(PYTHON_SUFFIX) if server_script_path else False
        if not is_python:
            raise PluginError(error=PluginErrorModel(message="Server script must be a .py file", plugin_name=self.name))

        current_env = os.environ.copy()

        try:
            server_params = StdioServerParameters(command=PYTHON, args=[server_script_path], env=current_env)

            stdio_transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
            self._stdio, self._write = stdio_transport
            self._session = await self._exit_stack.enter_async_context(ClientSession(self._stdio, self._write))

            await self._session.initialize()

            # List available tools
            response = await self._session.list_tools()
            tools = response.tools
            logger.info("\nConnected to plugin MCP server (stdio) with tools: %s", " ".join([tool.name for tool in tools]))
        except Exception as e:
            logger.exception(e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

    async def __connect_to_http_server(self, uri: str) -> None:
        """Connect to an MCP plugin server via streamable http.

        Args:
            uri: the URI of the mcp plugin server.

        Raises:
            PluginError: if there is an external connection error.
        """

        try:
            http_transport = await self._exit_stack.enter_async_context(streamablehttp_client(uri))
            self._http, self._write, _ = http_transport
            self._session = await self._exit_stack.enter_async_context(ClientSession(self._http, self._write))

            await self._session.initialize()

            # List available tools
            response = await self._session.list_tools()
            tools = response.tools
            logger.info("\nConnected to plugin MCP (http) server with tools: %s", " ".join([tool.name for tool in tools]))
        except Exception as e:
            logger.exception(e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

    async def __invoke_hook(self, payload_result_model: Type[P], hook_type: HookType, payload: BaseModel, context: PluginContext) -> P:
        """Invoke an external plugin hook using the MCP protocol.

        Args:
            payload_result_model: The type of result payload for the hook.
            hook_type:  The type of hook invoked (i.e., prompt_pre_hook)
            payload: The payload to be passed to the hook.
            context: The plugin context passed to the run.

        Raises:
            PluginError: error passed from external plugin server.

        Returns:
            The resulting payload from the plugin.
        """

        try:
            result = await self._session.call_tool(hook_type, {PLUGIN_NAME: self.name, PAYLOAD: payload, CONTEXT: context})
            for content in result.content:
                res = json.loads(content.text)
                if CONTEXT in res:
                    cxt = PluginContext.model_validate(res[CONTEXT])
                    context.state = cxt.state
                    context.metadata = cxt.metadata
                    context.global_context.state = cxt.global_context.state
                if RESULT in res:
                    return payload_result_model.model_validate(res[RESULT])
                if ERROR in res:
                    error = PluginErrorModel.model_validate(res[ERROR])
                    raise PluginError(error)
        except PluginError as pe:
            logger.exception(pe)
            raise
        except Exception as e:
            logger.exception(e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))
        raise PluginError(error=PluginErrorModel(message=f"Received invalid response. Result = {result}", plugin_name=self.name))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The prompt prehook with name and arguments as modified or blocked by the plugin.
        """

        return await self.__invoke_hook(payload_result_model=PromptPrehookResult, hook_type=HookType.PROMPT_PRE_FETCH, payload=payload, context=context)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            A set of prompt messages as modified or blocked by the plugin.
        """
        return await self.__invoke_hook(payload_result_model=PromptPosthookResult, hook_type=HookType.PROMPT_POST_FETCH, payload=payload, context=context)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The tool prehook with name and arguments as modified or blocked by the plugin.
        """

        return await self.__invoke_hook(payload_result_model=ToolPreInvokeResult, hook_type=HookType.TOOL_PRE_INVOKE, payload=payload, context=context)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The tool posthook with name and arguments as modified or blocked by the plugin.
        """

        return await self.__invoke_hook(payload_result_model=ToolPostInvokeResult, hook_type=HookType.TOOL_POST_INVOKE, payload=payload, context=context)

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Plugin hook run before a resource is fetched.

        Args:
            payload: The resource payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The resource prehook with name and arguments as modified or blocked by the plugin.
        """

        return await self.__invoke_hook(payload_result_model=ResourcePreFetchResult, hook_type=HookType.RESOURCE_PRE_FETCH, payload=payload, context=context)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Plugin hook run after a resource is fetched.

        Args:
            payload: The resource payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Returns:
            The resource posthook with name and arguments as modified or blocked by the plugin.
        """

        return await self.__invoke_hook(payload_result_model=ResourcePostFetchResult, hook_type=HookType.RESOURCE_POST_FETCH, payload=payload, context=context)

    async def __get_plugin_config(self) -> PluginConfig | None:
        """Retrieve plugin configuration for the current plugin on the remote MCP server.

        Raises:
            PluginError: if there is a connection issue or validation issue.

        Returns:
            A plugin configuration for the current plugin from a remote MCP server.
        """
        try:
            configs = await self._session.call_tool(GET_PLUGIN_CONFIG, {NAME: self.name})
            for content in configs.content:
                conf = json.loads(content.text)
                return PluginConfig.model_validate(conf)
        except Exception as e:
            logger.exception(e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

        return None

    async def shutdown(self) -> None:
        """Plugin cleanup code."""
        await self._exit_stack.aclose()
