# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/unix/server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unix socket server for external plugins.

This module provides a high-performance server that handles plugin requests
over Unix domain sockets using length-prefixed protobuf messages.

Examples:
    Run the server:

    >>> import asyncio
    >>> from mcpgateway.plugins.framework.external.unix.server.server import UnixSocketPluginServer

    >>> async def main():
    ...     server = UnixSocketPluginServer(
    ...         config_path="plugins/config.yaml",
    ...         socket_path="/tmp/plugin.sock",
    ...     )
    ...     await server.start()
    ...     # Server runs until stopped
    ...     await server.stop()

    >>> # asyncio.run(main())
"""

# Standard
import asyncio
import logging
import os
import signal
from typing import Optional

# Third-Party
from google.protobuf import json_format

# First-Party
from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2
from mcpgateway.plugins.framework.external.mcp.server.server import ExternalPluginServer
from mcpgateway.plugins.framework.external.proto_convert import (
    proto_context_to_pydantic,
    pydantic_context_to_proto,
)
from mcpgateway.plugins.framework.external.unix.protocol import ProtocolError, read_message, write_message_async
from mcpgateway.plugins.framework.models import PluginContext

logger = logging.getLogger(__name__)


class UnixSocketPluginServer:
    """Unix socket server for handling external plugin requests.

    This server listens on a Unix domain socket and handles plugin
    requests using length-prefixed protobuf messages. It wraps the
    ExternalPluginServer for actual plugin execution.

    Attributes:
        socket_path: Path to the Unix socket file.

    Examples:
        >>> server = UnixSocketPluginServer(
        ...     config_path="plugins/config.yaml",
        ...     socket_path="/tmp/test.sock",
        ... )
        >>> server.socket_path
        '/tmp/test.sock'
    """

    def __init__(
        self,
        config_path: str,
        socket_path: str = "/tmp/mcpgateway-plugins.sock",
    ) -> None:
        """Initialize the Unix socket server.

        Args:
            config_path: Path to the plugin configuration file.
            socket_path: Path for the Unix socket file.
        """
        self._config_path = config_path
        self._socket_path = socket_path
        self._plugin_server: Optional[ExternalPluginServer] = None
        self._server: Optional[asyncio.Server] = None
        self._running = False

    @property
    def socket_path(self) -> str:
        """Get the socket path.

        Returns:
            str: The Unix socket file path.
        """
        return self._socket_path

    @property
    def running(self) -> bool:
        """Check if the server is running.

        Returns:
            bool: True if the server is running, False otherwise.
        """
        return self._running

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection.

        Args:
            reader: The stream reader for the client.
            writer: The stream writer for the client.
        """
        peer = writer.get_extra_info("peername") or "unknown"
        logger.debug("Client connected: %s", peer)

        try:
            while self._running:
                try:
                    # Read request with timeout
                    data = await read_message(reader, timeout=300.0)  # 5 min timeout
                except asyncio.TimeoutError:
                    logger.debug("Client %s timed out", peer)
                    break
                except asyncio.IncompleteReadError:
                    # Client disconnected
                    break
                except ProtocolError as e:
                    logger.warning("Protocol error from %s: %s", peer, e)
                    break

                # Determine message type and handle
                response_bytes = await self._handle_message(data)

                # Send response
                try:
                    await write_message_async(writer, response_bytes)
                except (OSError, BrokenPipeError):
                    logger.debug("Client %s disconnected during write", peer)
                    break

        except Exception as e:
            logger.exception("Error handling client %s: %s", peer, e)
        finally:
            logger.debug("Client disconnected: %s", peer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_message(self, data: bytes) -> bytes:
        """Handle a single message and return the response.

        Args:
            data: The raw message bytes.

        Returns:
            The serialized response bytes.
        """
        # Try to parse as InvokeHookRequest first (most common)
        try:
            request = plugin_service_pb2.InvokeHookRequest()
            request.ParseFromString(data)

            if request.hook_type and request.plugin_name:
                return await self._handle_invoke_hook(request)
        except Exception:
            pass

        # Try GetPluginConfigRequest
        try:
            request = plugin_service_pb2.GetPluginConfigRequest()
            request.ParseFromString(data)

            if request.name:
                return await self._handle_get_plugin_config(request)
        except Exception:
            pass

        # Try GetPluginConfigsRequest
        try:
            request = plugin_service_pb2.GetPluginConfigsRequest()
            request.ParseFromString(data)
            # This request has no required fields, so check if data is minimal
            if len(data) <= 2:  # Empty or near-empty message
                return await self._handle_get_plugin_configs(request)
        except Exception:
            pass

        # Unknown message type
        logger.warning("Unknown message type, length=%d", len(data))
        error_response = plugin_service_pb2.InvokeHookResponse()
        error_response.error.message = "Unknown message type"
        error_response.error.code = "UNKNOWN_MESSAGE"
        return error_response.SerializeToString()

    async def _handle_invoke_hook(
        self,
        request: plugin_service_pb2.InvokeHookRequest,
    ) -> bytes:
        """Handle an InvokeHook request.

        Args:
            request: The InvokeHookRequest.

        Returns:
            Serialized InvokeHookResponse.
        """
        response = plugin_service_pb2.InvokeHookResponse(plugin_name=request.plugin_name)

        try:
            # Convert payload to dict (still polymorphic)
            payload_dict = json_format.MessageToDict(request.payload)

            # Convert explicit PluginContext proto directly to Pydantic
            context_pydantic = proto_context_to_pydantic(request.context)

            # Invoke the hook (passing Pydantic context directly, no dict conversion)
            result = await self._plugin_server.invoke_hook(
                hook_type=request.hook_type,
                plugin_name=request.plugin_name,
                payload=payload_dict,
                context=context_pydantic,
            )

            # Build response
            if "error" in result:
                error_obj = result["error"]
                if hasattr(error_obj, "model_dump"):
                    error_dict = error_obj.model_dump()
                else:
                    error_dict = error_obj

                response.error.message = error_dict.get("message", "Unknown error")
                response.error.plugin_name = error_dict.get("plugin_name", "unknown")
                response.error.code = error_dict.get("code", "")
                response.error.mcp_error_code = error_dict.get("mcp_error_code", -32603)
            else:
                if "result" in result:
                    json_format.ParseDict(result["result"], response.result)
                if "context" in result:
                    ctx = result["context"]
                    # Handle both Pydantic (optimized path) and dict (MCP compat)
                    if isinstance(ctx, PluginContext):
                        response.context.CopyFrom(pydantic_context_to_proto(ctx))
                    else:
                        updated_context = PluginContext.model_validate(ctx)
                        response.context.CopyFrom(pydantic_context_to_proto(updated_context))

        except Exception as e:
            logger.exception("Error invoking hook: %s", e)
            response.error.message = str(e)
            response.error.code = "INTERNAL_ERROR"
            response.error.mcp_error_code = -32603

        return response.SerializeToString()

    async def _handle_get_plugin_config(
        self,
        request: plugin_service_pb2.GetPluginConfigRequest,
    ) -> bytes:
        """Handle a GetPluginConfig request.

        Args:
            request: The GetPluginConfigRequest.

        Returns:
            Serialized GetPluginConfigResponse.
        """
        response = plugin_service_pb2.GetPluginConfigResponse()

        try:
            config = await self._plugin_server.get_plugin_config(request.name)

            if config:
                response.found = True
                json_format.ParseDict(config, response.config)
            else:
                response.found = False

        except Exception as e:
            logger.exception("Error getting plugin config: %s", e)
            response.found = False

        return response.SerializeToString()

    async def _handle_get_plugin_configs(
        self,
        request: plugin_service_pb2.GetPluginConfigsRequest,
    ) -> bytes:
        """Handle a GetPluginConfigs request.

        Args:
            request: The GetPluginConfigsRequest.

        Returns:
            Serialized GetPluginConfigsResponse.
        """
        response = plugin_service_pb2.GetPluginConfigsResponse()

        try:
            configs = await self._plugin_server.get_plugin_configs()

            for config in configs:
                # Third-Party
                from google.protobuf.struct_pb2 import Struct

                config_struct = Struct()
                json_format.ParseDict(config, config_struct)
                response.configs.append(config_struct)

        except Exception as e:
            logger.exception("Error getting plugin configs: %s", e)

        return response.SerializeToString()

    async def start(self) -> None:
        """Start the Unix socket server.

        This initializes the plugin server and starts listening for
        connections on the Unix socket.
        """
        logger.info("Starting Unix socket plugin server on %s", self._socket_path)

        # Clean up old socket file
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

        # Initialize the plugin server
        self._plugin_server = ExternalPluginServer(config_path=self._config_path)
        await self._plugin_server.initialize()

        # Create the Unix socket server
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self._socket_path,
        )

        self._running = True
        logger.info("Unix socket plugin server started on %s", self._socket_path)

    async def serve_forever(self) -> None:
        """Serve requests until stopped.

        Raises:
            RuntimeError: If the server has not been started.
        """
        if not self._server:
            raise RuntimeError("Server not started. Call start() first.")

        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the Unix socket server."""
        logger.info("Stopping Unix socket plugin server")
        self._running = False

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if self._plugin_server:
            await self._plugin_server.shutdown()
            self._plugin_server = None

        # Clean up socket file
        if os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                pass

        logger.info("Unix socket plugin server stopped")


async def run_server(
    config_path: str,
    socket_path: str = "/tmp/mcpgateway-plugins.sock",
) -> None:
    """Run the Unix socket server until interrupted.

    Args:
        config_path: Path to the plugin configuration file.
        socket_path: Path for the Unix socket file.
    """
    server = UnixSocketPluginServer(config_path=config_path, socket_path=socket_path)

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    await server.start()

    # Signal ready (for parent process coordination)
    print("READY", flush=True)

    # Wait for shutdown signal
    await stop_event.wait()

    await server.stop()
