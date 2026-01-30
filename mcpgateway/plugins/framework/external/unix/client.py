# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/unix/client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unix socket client for external plugins.

This module provides a high-performance client for communicating with
external plugins over Unix domain sockets using length-prefixed protobuf
messages.

Examples:
    Create and use a Unix socket plugin client:

    >>> from mcpgateway.plugins.framework.external.unix.client import UnixSocketExternalPlugin
    >>> from mcpgateway.plugins.framework.models import PluginConfig, UnixSocketClientConfig

    >>> config = PluginConfig(
    ...     name="MyPlugin",
    ...     kind="external",
    ...     hooks=["tool_pre_invoke"],
    ...     unix_socket=UnixSocketClientConfig(path="/tmp/plugin.sock"),
    ... )
    >>> plugin = UnixSocketExternalPlugin(config)
    >>> # await plugin.initialize()
    >>> # result = await plugin.invoke_hook(hook_type, payload, context)
"""

import asyncio
import logging
from typing import Any, Optional

from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct

from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError
from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2
from mcpgateway.plugins.framework.external.proto_convert import pydantic_context_to_proto, update_pydantic_context_from_proto
from mcpgateway.plugins.framework.external.unix.protocol import read_message, write_message_async
from mcpgateway.plugins.framework.hooks.registry import get_hook_registry
from mcpgateway.plugins.framework.models import PluginConfig, PluginContext, PluginErrorModel, PluginResult

logger = logging.getLogger(__name__)


class UnixSocketExternalPlugin(Plugin):
    """External plugin client using raw Unix domain sockets.

    This client provides high-performance IPC for local plugins using
    length-prefixed protobuf messages. It includes automatic reconnection
    with configurable retry logic.

    Attributes:
        config: The plugin configuration.

    Examples:
        >>> from mcpgateway.plugins.framework.models import PluginConfig, UnixSocketClientConfig
        >>> config = PluginConfig(
        ...     name="TestPlugin",
        ...     kind="external",
        ...     hooks=["tool_pre_invoke"],
        ...     unix_socket=UnixSocketClientConfig(path="/tmp/test.sock"),
        ... )
        >>> plugin = UnixSocketExternalPlugin(config)
        >>> plugin.name
        'TestPlugin'
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the Unix socket plugin client.

        Args:
            config: The plugin configuration with unix_socket settings.

        Raises:
            PluginError: If unix_socket configuration is missing.
        """
        super().__init__(config)

        if not config.unix_socket:
            raise PluginError(error=PluginErrorModel(message="The unix_socket section must be defined for Unix socket plugin", plugin_name=config.name))

        self._socket_path = config.unix_socket.path
        self._reconnect_attempts = config.unix_socket.reconnect_attempts
        self._reconnect_delay = config.unix_socket.reconnect_delay
        self._timeout = config.unix_socket.timeout

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected and self._writer is not None and not self._writer.is_closing()

    async def _connect(self) -> None:
        """Establish connection to the Unix socket server.

        Raises:
            PluginError: If connection fails.
        """
        try:
            self._reader, self._writer = await asyncio.open_unix_connection(self._socket_path)
            self._connected = True
            logger.debug("Connected to Unix socket: %s", self._socket_path)
        except OSError as e:
            self._connected = False
            raise PluginError(error=PluginErrorModel(message=f"Failed to connect to {self._socket_path}: {e}", plugin_name=self.name)) from e

    async def _disconnect(self) -> None:
        """Close the connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        self._connected = False

    async def _reconnect(self) -> None:
        """Attempt to reconnect with retry logic.

        Raises:
            PluginError: If all reconnection attempts fail.
        """
        await self._disconnect()

        last_error: Optional[Exception] = None
        for attempt in range(1, self._reconnect_attempts + 1):
            try:
                logger.debug("Reconnection attempt %d/%d to %s", attempt, self._reconnect_attempts, self._socket_path)
                await self._connect()
                logger.info("Reconnected to %s on attempt %d", self._socket_path, attempt)
                return
            except PluginError as e:
                last_error = e
                if attempt < self._reconnect_attempts:
                    await asyncio.sleep(self._reconnect_delay * attempt)  # Exponential backoff

        raise PluginError(error=PluginErrorModel(message=f"Failed to reconnect after {self._reconnect_attempts} attempts: {last_error}", plugin_name=self.name))

    async def _send_request(self, request: plugin_service_pb2.InvokeHookRequest) -> plugin_service_pb2.InvokeHookResponse:
        """Send a request and receive response, with reconnection on failure.

        Args:
            request: The protobuf request to send.

        Returns:
            The protobuf response.

        Raises:
            PluginError: If sending fails after reconnection attempts.
        """
        request_bytes = request.SerializeToString()

        async with self._lock:
            for attempt in range(self._reconnect_attempts + 1):
                try:
                    if not self.connected:
                        await self._reconnect()

                    # Send request
                    await write_message_async(self._writer, request_bytes)

                    # Read response
                    response_bytes = await read_message(self._reader, timeout=self._timeout)

                    # Parse response
                    response = plugin_service_pb2.InvokeHookResponse()
                    response.ParseFromString(response_bytes)
                    return response

                except asyncio.TimeoutError as e:
                    logger.warning("Request timed out after %s seconds", self._timeout)
                    raise PluginError(error=PluginErrorModel(message=f"Request timed out after {self._timeout}s", plugin_name=self.name)) from e

                except PluginError:
                    raise

                except (OSError, asyncio.IncompleteReadError, BrokenPipeError) as e:
                    logger.warning("Connection error on attempt %d: %s", attempt + 1, e)
                    self._connected = False

                    if attempt < self._reconnect_attempts:
                        await asyncio.sleep(self._reconnect_delay * (attempt + 1))
                        continue
                    raise PluginError(error=PluginErrorModel(message=f"Request failed after {self._reconnect_attempts + 1} attempts: {e}", plugin_name=self.name)) from e

        # Should not reach here
        raise PluginError(error=PluginErrorModel(message="Unexpected state in _send_request", plugin_name=self.name))

    async def initialize(self) -> None:
        """Initialize the plugin client by connecting to the server.

        This establishes the Unix socket connection and optionally
        fetches the remote plugin configuration.

        Raises:
            PluginError: If initial connection fails.
        """
        logger.info("Initializing Unix socket plugin: %s -> %s", self.name, self._socket_path)

        try:
            await self._connect()
        except PluginError:
            raise
        except Exception as e:
            logger.exception(e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

        # Optionally fetch remote config to verify connection
        try:
            request = plugin_service_pb2.GetPluginConfigRequest(name=self.name)
            request_bytes = request.SerializeToString()

            await write_message_async(self._writer, request_bytes)
            response_bytes = await read_message(self._reader, timeout=self._timeout)

            response = plugin_service_pb2.GetPluginConfigResponse()
            response.ParseFromString(response_bytes)

            if response.found:
                logger.debug("Remote plugin config verified for %s", self.name)
            else:
                logger.warning("Plugin %s not found on remote server", self.name)

        except Exception as e:
            logger.warning("Could not verify remote plugin config: %s", e)
            # Continue anyway - the plugin might still work

        logger.info("Unix socket plugin initialized: %s", self.name)

    async def shutdown(self) -> None:
        """Shutdown the plugin client and close the connection."""
        logger.info("Shutting down Unix socket plugin: %s", self.name)
        await self._disconnect()

    async def invoke_hook(
        self,
        hook_type: str,
        payload: Any,
        context: PluginContext,
    ) -> PluginResult:
        """Invoke a plugin hook over the Unix socket connection.

        Args:
            hook_type: The type of hook to invoke (e.g., "tool_pre_invoke").
            payload: The hook payload (will be serialized to protobuf Struct).
            context: The plugin context.

        Returns:
            The plugin result.

        Raises:
            PluginError: If the request fails after retries or hook type is invalid.
        """
        # Get the result type from the global registry
        registry = get_hook_registry()
        result_type = registry.get_result_type(hook_type)
        if not result_type:
            raise PluginError(error=PluginErrorModel(message=f"Hook type '{hook_type}' not registered in hook registry", plugin_name=self.name))

        # Convert payload to Struct (still polymorphic)
        payload_struct = Struct()
        if hasattr(payload, "model_dump"):
            json_format.ParseDict(payload.model_dump(), payload_struct)
        else:
            json_format.ParseDict(payload, payload_struct)

        # Convert context to explicit proto message (faster than Struct)
        context_proto = pydantic_context_to_proto(context)

        # Build request
        request = plugin_service_pb2.InvokeHookRequest(
            hook_type=hook_type,
            plugin_name=self.name,
            payload=payload_struct,
            context=context_proto,
        )

        try:
            # Send request and get response
            response = await self._send_request(request)

            # Handle error response
            if response.HasField("error") and response.error.message:
                error = PluginErrorModel(
                    message=response.error.message,
                    plugin_name=response.error.plugin_name or self.name,
                    code=response.error.code,
                    mcp_error_code=response.error.mcp_error_code,
                )
                if response.error.HasField("details"):
                    error.details = json_format.MessageToDict(response.error.details)
                raise PluginError(error=error)

            # Update context if modified (using explicit proto message)
            if response.HasField("context"):
                update_pydantic_context_from_proto(context, response.context)

            # Parse and return result
            if response.HasField("result"):
                result_dict = json_format.MessageToDict(response.result)
                return result_type.model_validate(result_dict)

            raise PluginError(
                error=PluginErrorModel(
                    message="Received invalid response from Unix socket plugin server",
                    plugin_name=self.name,
                )
            )

        except PluginError:
            raise
        except Exception as e:
            logger.exception(e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))
