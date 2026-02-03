# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/grpc/client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

External plugin client which connects to a remote server through gRPC.
Module that contains plugin gRPC client code to serve external plugins.
"""

# Standard
import asyncio
import logging
from typing import Optional

# Third-Party
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct
import grpc

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.constants import IGNORE_CONFIG_EXTERNAL
from mcpgateway.plugins.framework.errors import convert_exception_to_error, PluginError
from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2, plugin_service_pb2_grpc
from mcpgateway.plugins.framework.external.grpc.tls_utils import create_insecure_channel, create_secure_channel
from mcpgateway.plugins.framework.external.proto_convert import pydantic_context_to_proto, update_pydantic_context_from_proto
from mcpgateway.plugins.framework.hooks.registry import get_hook_registry
from mcpgateway.plugins.framework.models import GRPCClientTLSConfig, PluginConfig, PluginContext, PluginErrorModel, PluginPayload, PluginResult

logger = logging.getLogger(__name__)


class GrpcExternalPlugin(Plugin):
    """External plugin object that connects to a remote gRPC server.

    This plugin implementation connects to a remote plugin server via gRPC,
    providing a faster binary protocol alternative to the MCP transport.

    Examples:
        >>> from mcpgateway.plugins.framework.models import PluginConfig, GRPCClientConfig
        >>> config = PluginConfig(
        ...     name="MyGrpcPlugin",
        ...     kind="external",
        ...     grpc=GRPCClientConfig(target="localhost:50051")
        ... )
        >>> plugin = GrpcExternalPlugin(config)
        >>> # await plugin.initialize()
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize a gRPC external plugin with a configuration.

        Args:
            config: The plugin configuration containing gRPC connection details.
        """
        super().__init__(config)
        self._channel: Optional[grpc.aio.Channel] = None
        self._stub: Optional[plugin_service_pb2_grpc.PluginServiceStub] = None

    async def initialize(self) -> None:
        """Initialize the plugin's connection to the gRPC server.

        This method:
        1. Creates a gRPC channel (secure or insecure based on config)
        2. Creates the service stub
        3. Fetches remote plugin configuration
        4. Merges remote config with local config

        Raises:
            PluginError: If unable to connect or retrieve plugin configuration.
        """
        if not self._config.grpc:
            raise PluginError(
                error=PluginErrorModel(
                    message="The grpc section must be defined for gRPC external plugin",
                    plugin_name=self.name,
                )
            )

        target = self._config.grpc.get_target()
        tls_config = self._config.grpc.tls or GRPCClientTLSConfig.from_env()
        is_uds = self._config.grpc.uds is not None

        try:
            # Create channel (TLS not supported for Unix domain sockets)
            if tls_config and not is_uds:
                self._channel = create_secure_channel(target, tls_config, self.name)
            else:
                self._channel = create_insecure_channel(target)

            # Create stub
            self._stub = plugin_service_pb2_grpc.PluginServiceStub(self._channel)

            # Verify connection and get remote config
            config = await self._get_plugin_config_with_retry()

            if not config:
                raise PluginError(
                    error=PluginErrorModel(
                        message="Unable to retrieve configuration for external plugin",
                        plugin_name=self.name,
                    )
                )

            # Merge remote config with local config (local takes precedence)
            current_config = self._config.model_dump(exclude_unset=True)
            remote_config = config.model_dump(exclude_unset=True)
            remote_config.update(current_config)

            context = {IGNORE_CONFIG_EXTERNAL: True}
            self._config = PluginConfig.model_validate(remote_config, context=context)

            logger.info("Successfully connected to gRPC plugin server at %s for plugin %s", target, self.name)

        except PluginError:
            raise
        except Exception as e:
            logger.exception("Error connecting to gRPC plugin server: %s", e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

    async def _get_plugin_config_with_retry(self, max_retries: int = 3, base_delay: float = 1.0) -> Optional[PluginConfig]:
        """Retrieve plugin configuration with retry logic.

        Args:
            max_retries: Maximum number of retry attempts.
            base_delay: Base delay between retries (exponential backoff).

        Returns:
            PluginConfig if successful, None otherwise.

        Raises:
            PluginError: If all retries fail.
        """
        for attempt in range(max_retries):
            try:
                return await self._get_plugin_config()
            except Exception as e:
                logger.warning("Connection attempt %d/%d failed: %s", attempt + 1, max_retries, e)
                if attempt == max_retries - 1:
                    error_msg = f"gRPC plugin '{self.name}' connection failed after {max_retries} attempts"
                    raise PluginError(error=PluginErrorModel(message=error_msg, plugin_name=self.name))
                delay = base_delay * (2**attempt)
                logger.info("Retrying in %ss...", delay)
                await asyncio.sleep(delay)

        return None

    async def _get_plugin_config(self) -> Optional[PluginConfig]:
        """Retrieve plugin configuration from the remote gRPC server.

        Returns:
            PluginConfig if found, None otherwise.

        Raises:
            PluginError: If there is a connection or validation error.
        """
        if not self._stub:
            raise PluginError(
                error=PluginErrorModel(
                    message="gRPC stub not initialized",
                    plugin_name=self.name,
                )
            )

        try:
            request = plugin_service_pb2.GetPluginConfigRequest(name=self.name)
            response = await self._stub.GetPluginConfig(request)

            if response.found:
                config_dict = json_format.MessageToDict(response.config)
                return PluginConfig.model_validate(config_dict)

            return None

        except grpc.RpcError as e:
            logger.error("gRPC error getting plugin config: %s", e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

    async def invoke_hook(self, hook_type: str, payload: PluginPayload, context: PluginContext) -> PluginResult:
        """Invoke an external plugin hook using gRPC.

        Args:
            hook_type: The type of hook invoked (e.g., "tool_pre_invoke").
            payload: The payload to be passed to the hook.
            context: The plugin context passed to the hook.

        Returns:
            The resulting payload from the plugin.

        Raises:
            PluginError: If there is an error invoking the hook.
        """
        # Get the result type from the global registry
        registry = get_hook_registry()
        result_type = registry.get_result_type(hook_type)
        if not result_type:
            raise PluginError(
                error=PluginErrorModel(
                    message=f"Hook type '{hook_type}' not registered in hook registry",
                    plugin_name=self.name,
                )
            )

        if not self._stub:
            raise PluginError(
                error=PluginErrorModel(
                    message="gRPC stub not initialized",
                    plugin_name=self.name,
                )
            )

        try:
            # Convert payload to Struct (still polymorphic)
            payload_struct = Struct()
            json_format.ParseDict(payload.model_dump(), payload_struct)

            # Convert context to explicit proto message (faster than Struct)
            context_proto = pydantic_context_to_proto(context)

            # Create and send request
            request = plugin_service_pb2.InvokeHookRequest(
                hook_type=hook_type,
                plugin_name=self.name,
                payload=payload_struct,
                context=context_proto,
            )

            response = await self._stub.InvokeHook(request)

            # Check for error
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
                    message="Received invalid response from gRPC plugin server",
                    plugin_name=self.name,
                )
            )

        except PluginError:
            raise
        except grpc.RpcError as e:
            logger.exception("gRPC error invoking hook: %s", e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))
        except Exception as e:
            logger.exception("Error invoking gRPC hook: %s", e)
            raise PluginError(error=convert_exception_to_error(e, plugin_name=self.name))

    async def shutdown(self) -> None:
        """Shutdown the gRPC connection and cleanup resources."""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
            logger.info("gRPC channel closed for plugin %s", self.name)
