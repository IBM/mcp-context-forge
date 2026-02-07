# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/grpc/server/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

gRPC servicer implementations for external plugin server.

This module provides gRPC servicer classes that adapt gRPC calls to the
ExternalPluginServer, which handles the actual plugin loading and execution.
"""
# pylint: disable=no-member,no-name-in-module

# Standard
import logging
from typing import Any

# Third-Party
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct
import grpc

# First-Party
from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2, plugin_service_pb2_grpc
from mcpgateway.plugins.framework.external.mcp.server.server import ExternalPluginServer
from mcpgateway.plugins.framework.external.proto_convert import (
    proto_context_to_pydantic,
    pydantic_context_to_proto,
)
from mcpgateway.plugins.framework.models import PluginContext

logger = logging.getLogger(__name__)


class GrpcPluginServicer(plugin_service_pb2_grpc.PluginServiceServicer):
    """gRPC servicer that adapts gRPC calls to ExternalPluginServer.

    This servicer wraps an ExternalPluginServer instance and translates
    between gRPC protocol buffer messages and the Pydantic models used
    by the plugin framework.

    Examples:
        >>> from mcpgateway.plugins.framework.external.mcp.server.server import ExternalPluginServer
        >>> plugin_server = ExternalPluginServer(config_path="plugins/config.yaml")
        >>> servicer = GrpcPluginServicer(plugin_server)
    """

    def __init__(self, plugin_server: ExternalPluginServer) -> None:
        """Initialize the gRPC servicer with a plugin server.

        Args:
            plugin_server: The ExternalPluginServer instance that handles
                          plugin loading and execution.
        """
        self._plugin_server = plugin_server

    async def GetPluginConfig(  # pylint: disable=invalid-overridden-method
        self,
        request: plugin_service_pb2.GetPluginConfigRequest,
        context: grpc.aio.ServicerContext,
    ) -> plugin_service_pb2.GetPluginConfigResponse:
        """Get configuration for a single plugin by name.

        Args:
            request: gRPC request containing the plugin name.
            context: gRPC servicer context.

        Returns:
            Response containing the plugin configuration or empty if not found.
        """
        logger.debug("GetPluginConfig called for plugin: %s", request.name)

        try:
            config = await self._plugin_server.get_plugin_config(request.name)

            response = plugin_service_pb2.GetPluginConfigResponse()
            if config:
                response.found = True
                json_format.ParseDict(config, response.config)
            else:
                response.found = False

            return response

        except Exception as e:
            logger.exception("Error in GetPluginConfig: %s", e)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return plugin_service_pb2.GetPluginConfigResponse(found=False)

    async def GetPluginConfigs(  # pylint: disable=invalid-overridden-method
        self,
        request: plugin_service_pb2.GetPluginConfigsRequest,
        context: grpc.aio.ServicerContext,
    ) -> plugin_service_pb2.GetPluginConfigsResponse:
        """Get configurations for all plugins on the server.

        Args:
            request: gRPC request (empty).
            context: gRPC servicer context.

        Returns:
            Response containing list of all plugin configurations.
        """
        logger.debug("GetPluginConfigs called")

        try:
            configs = await self._plugin_server.get_plugin_configs()

            response = plugin_service_pb2.GetPluginConfigsResponse()
            for config in configs:
                config_struct = Struct()
                json_format.ParseDict(config, config_struct)
                response.configs.append(config_struct)

            return response

        except Exception as e:
            logger.exception("Error in GetPluginConfigs: %s", e)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return plugin_service_pb2.GetPluginConfigsResponse()

    async def InvokeHook(  # pylint: disable=invalid-overridden-method
        self,
        request: plugin_service_pb2.InvokeHookRequest,
        context: grpc.aio.ServicerContext,
    ) -> plugin_service_pb2.InvokeHookResponse:
        """Invoke a plugin hook.

        Args:
            request: gRPC request containing hook_type, plugin_name, payload, and context.
            context: gRPC servicer context.

        Returns:
            Response containing the plugin result or error.
        """
        logger.debug(
            "InvokeHook called: hook_type=%s, plugin_name=%s",
            request.hook_type,
            request.plugin_name,
        )

        try:
            # Convert payload Struct to Python dict (still polymorphic)
            payload_dict = json_format.MessageToDict(request.payload)

            # Convert explicit PluginContext proto directly to Pydantic
            context_pydantic = proto_context_to_pydantic(request.context)

            # Invoke the hook using the plugin server (passing Pydantic context directly)
            result = await self._plugin_server.invoke_hook(
                hook_type=request.hook_type,
                plugin_name=request.plugin_name,
                payload=payload_dict,
                context=context_pydantic,
            )

            # Build the response
            response = plugin_service_pb2.InvokeHookResponse(plugin_name=request.plugin_name)

            # Check for error in result
            if "error" in result:
                error_obj = result["error"]
                # Handle both Pydantic models and dicts
                if hasattr(error_obj, "model_dump"):
                    error_dict = error_obj.model_dump()
                else:
                    error_dict = error_obj
                response.error.CopyFrom(self._dict_to_plugin_error(error_dict))
            else:
                # Convert result to Struct (still polymorphic)
                if "result" in result:
                    json_format.ParseDict(result["result"], response.result)
                # Convert context to explicit proto message
                if "context" in result:
                    ctx = result["context"]
                    # Handle both Pydantic (optimized path) and dict (MCP compat)
                    if isinstance(ctx, PluginContext):
                        response.context.CopyFrom(pydantic_context_to_proto(ctx))
                    else:
                        updated_context = PluginContext.model_validate(ctx)
                        response.context.CopyFrom(pydantic_context_to_proto(updated_context))

            return response

        except Exception as e:
            logger.exception("Error in InvokeHook: %s", e)
            response = plugin_service_pb2.InvokeHookResponse(plugin_name=request.plugin_name)
            response.error.message = str(e)
            response.error.plugin_name = request.plugin_name
            response.error.code = "INTERNAL_ERROR"
            response.error.mcp_error_code = -32603
            return response

    def _dict_to_plugin_error(self, error_dict: dict[str, Any]) -> plugin_service_pb2.PluginError:
        """Convert an error dictionary to a PluginError protobuf message.

        Args:
            error_dict: Dictionary containing error information.

        Returns:
            PluginError protobuf message.
        """
        error = plugin_service_pb2.PluginError()
        error.message = error_dict.get("message", "Unknown error")
        error.plugin_name = error_dict.get("plugin_name", "unknown")
        error.code = error_dict.get("code", "")
        error.mcp_error_code = error_dict.get("mcp_error_code", -32603)

        if "details" in error_dict and error_dict["details"]:
            json_format.ParseDict(error_dict["details"], error.details)

        return error


class GrpcHealthServicer(plugin_service_pb2_grpc.HealthServicer):
    """gRPC health check servicer following the standard gRPC health protocol.

    This servicer provides health check endpoints that can be used by
    load balancers and orchestration systems to verify the server is
    operational.

    Examples:
        >>> servicer = GrpcHealthServicer()
        >>> # Register with gRPC server
    """

    def __init__(self, plugin_server: ExternalPluginServer | None = None) -> None:
        """Initialize the health servicer.

        Args:
            plugin_server: Optional ExternalPluginServer for checking plugin health.
        """
        self._plugin_server = plugin_server

    async def Check(  # pylint: disable=invalid-overridden-method
        self,
        request: plugin_service_pb2.HealthCheckRequest,
        context: grpc.aio.ServicerContext,
    ) -> plugin_service_pb2.HealthCheckResponse:
        """Check the health status of the server.

        Args:
            request: Health check request with optional service name.
            context: gRPC servicer context.

        Returns:
            Health check response with serving status.
        """
        logger.debug("Health check called for service: %s", request.service or "(overall)")

        # For now, always return SERVING if the server is running
        # In the future, could check plugin_server health
        return plugin_service_pb2.HealthCheckResponse(status=plugin_service_pb2.HealthCheckResponse.SERVING)
