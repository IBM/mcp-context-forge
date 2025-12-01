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
from functools import partial
import json
import logging
import os
from typing import Any, Awaitable, Callable, Optional

# Third-Party
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import TextContent

# First-Party
from mcpgateway.common.models import TransportType
from mcpgateway.plugins.framework.base import HookRef, Plugin, PluginRef
from mcpgateway.plugins.framework.constants import CONTEXT, ERROR, GET_PLUGIN_CONFIG, HOOK_TYPE, IGNORE_CONFIG_EXTERNAL, INVOKE_HOOK, NAME, PAYLOAD, PLUGIN_NAME, PYTHON, PYTHON_SUFFIX, RESULT
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError
from mcpgateway.plugins.framework.external.mcp.tls_utils import create_ssl_context
from mcpgateway.plugins.framework.hooks.registry import get_hook_registry
from mcpgateway.plugins.framework.models import MCPClientTLSConfig, PluginConfig, PluginContext, PluginErrorModel, PluginPayload, PluginResult

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
            if not self._config.mcp.script:
                raise PluginError(error=PluginErrorModel(message="STDIO transport requires script", plugin_name=self.name))
            await self.__connect_to_stdio_server(self._config.mcp.script)
        elif self._config.mcp.proto == TransportType.STREAMABLEHTTP:
            if not self._config.mcp.url:
                raise PluginError(error=PluginErrorModel(message="STREAMABLEHTTP transport requires url", plugin_name=self.name))
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
        """Connect to an MCP plugin server via streamable http with retry logic.

        Args:
            uri: the URI of the mcp plugin server.

        Raises:
            PluginError: if there is an external connection error after all retries.
        """
        plugin_tls = self._config.mcp.tls if self._config and self._config.mcp else None
        tls_config = plugin_tls or MCPClientTLSConfig.from_env()

        def _tls_httpx_client_factory(
            headers: Optional[dict[str, str]] = None,
            timeout: Optional[httpx.Timeout] = None,
            auth: Optional[httpx.Auth] = None,
        ) -> httpx.AsyncClient:
            """Build an httpx client with TLS configuration for external MCP servers.

            Args:
                headers: Optional HTTP headers to include in requests.
                timeout: Optional timeout configuration for HTTP requests.
                auth: Optional authentication handler for HTTP requests.

            Returns:
                Configured httpx AsyncClient with TLS settings applied.

            Raises:
                PluginError: If TLS configuration fails.
            """

            kwargs: dict[str, Any] = {"follow_redirects": True}
            if headers:
                kwargs["headers"] = headers
            kwargs["timeout"] = timeout or httpx.Timeout(30.0)
            if auth is not None:
                kwargs["auth"] = auth

            if not tls_config:
                return httpx.AsyncClient(**kwargs)

            # Create SSL context using the utility function
            # This implements certificate validation per test_client_certificate_validation.py
            ssl_context = create_ssl_context(tls_config, self.name)
            kwargs["verify"] = ssl_context

            return httpx.AsyncClient(**kwargs)

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):

            try:
                client_factory = _tls_httpx_client_factory if tls_config else None
                async with AsyncExitStack() as temp_stack:
                    streamable_client = streamablehttp_client(uri, httpx_client_factory=client_factory) if client_factory else streamablehttp_client(uri)
                    http_transport = await temp_stack.enter_async_context(streamable_client)
                    http_client, write_func, _ = http_transport
                    session = await temp_stack.enter_async_context(ClientSession(http_client, write_func))
                    await session.initialize()
                    # List available tools
                    response = await session.list_tools()
                    tools = response.tools
                    logger.info(
                        "Successfully connected to plugin MCP server with tools: %s",
                        " ".join([tool.name for tool in tools]),
                    )

                client_factory = _tls_httpx_client_factory if tls_config else None
                streamable_client = streamablehttp_client(uri, httpx_client_factory=client_factory) if client_factory else streamablehttp_client(uri)
                http_transport = await self._exit_stack.enter_async_context(streamable_client)
                self._http, self._write, _ = http_transport
                self._session = await self._exit_stack.enter_async_context(ClientSession(self._http, self._write))

                await self._session.initialize()
                return
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt == max_retries - 1:
                    # Final attempt failed
                    error_msg = f"External plugin '{self.name}' connection failed after {max_retries} attempts: {uri} is not reachable. Please ensure the MCP server is running."
                    logger.error(error_msg)
                    raise PluginError(error=PluginErrorModel(message=error_msg, plugin_name=self.name))
                await self.shutdown()
                # Wait before retry
                delay = base_delay * (2**attempt)
                logger.info(f"Retrying in {delay}s...")
                await asyncio.sleep(delay)

    async def invoke_hook(self, hook_type: str, payload: PluginPayload, context: PluginContext) -> PluginResult:
        """Invoke an external plugin hook using the MCP protocol.

        Args:
            hook_type:  The type of hook invoked (i.e., prompt_pre_fetch)
            payload: The payload to be passed to the hook.
            context: The plugin context passed to the run.

        Raises:
            PluginError: error passed from external plugin server.

        Returns:
            The resulting payload from the plugin.
        """
        # Get the result type from the global registry
        registry = get_hook_registry()
        result_type = registry.get_result_type(hook_type)
        if not result_type:
            raise PluginError(error=PluginErrorModel(message=f"Hook type '{hook_type}' not registered in hook registry", plugin_name=self.name))

        if not self._session:
            raise PluginError(error=PluginErrorModel(message="Plugin session not initialized", plugin_name=self.name))

        try:
            result = await self._session.call_tool(INVOKE_HOOK, {HOOK_TYPE: hook_type, PLUGIN_NAME: self.name, PAYLOAD: payload, CONTEXT: context})
            for content in result.content:
                if not isinstance(content, TextContent):
                    continue
                try:
                    res = json.loads(content.text)
                except json.decoder.JSONDecodeError:
                    raise PluginError(error=PluginErrorModel(message=f"Error trying to decode json: {content.text}", code="JSON_DECODE_ERROR", plugin_name=self.name))
                if CONTEXT in res:
                    cxt = PluginContext.model_validate(res[CONTEXT])
                    context.state = cxt.state
                    context.metadata = cxt.metadata
                    context.global_context.state = cxt.global_context.state
                if RESULT in res:
                    return result_type.model_validate(res[RESULT])
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

    async def __get_plugin_config(self) -> PluginConfig | None:
        """Retrieve plugin configuration for the current plugin on the remote MCP server.

        Raises:
            PluginError: if there is a connection issue or validation issue.

        Returns:
            A plugin configuration for the current plugin from a remote MCP server.
        """
        if not self._session:
            raise PluginError(error=PluginErrorModel(message="Plugin session not initialized", plugin_name=self.name))
        try:
            configs = await self._session.call_tool(GET_PLUGIN_CONFIG, {NAME: self.name})
            for content in configs.content:
                if not isinstance(content, TextContent):
                    continue
                conf = json.loads(content.text)
                return PluginConfig.model_validate(conf)
        except Exception as e:
            logger.exception(e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

        return None

    async def shutdown(self) -> None:
        """Plugin cleanup code."""
        if self._exit_stack:
            await self._exit_stack.aclose()


class ExternalHookRef(HookRef):
    """A Hook reference point for external plugins."""

    def __init__(self, hook: str, plugin_ref: PluginRef):  # pylint: disable=super-init-not-called
        """Initialize a hook reference point for an external plugin.

        Note: We intentionally don't call super().__init__() because external plugins
        use invoke_hook() rather than direct method attributes.

        Args:
            hook: name of the hook point.
            plugin_ref: The reference to the plugin to hook.

        Raises:
            PluginError: If the plugin is not an external plugin.
        """
        self._plugin_ref = plugin_ref
        self._hook = hook
        if hasattr(plugin_ref.plugin, INVOKE_HOOK):
            self._func: Callable[[PluginPayload, PluginContext], Awaitable[PluginResult]] = partial(plugin_ref.plugin.invoke_hook, hook)  # type: ignore[attr-defined]
        else:
            raise PluginError(error=PluginErrorModel(message=f"Plugin: {plugin_ref.plugin.name} is not an external plugin", plugin_name=plugin_ref.plugin.name))
