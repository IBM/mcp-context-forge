# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/translate_grpc.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: MCP Gateway Contributors

gRPC to MCP Translation Module

This module provides gRPC to MCP protocol translation capabilities.
It enables exposing gRPC services as MCP tools via HTTP/SSE endpoints
using automatic service discovery through gRPC server reflection.
"""

# Standard
import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

try:
    # Third-Party
    from google.protobuf import descriptor_pool, json_format, message_factory
    from google.protobuf.descriptor_pb2 import FileDescriptorProto  # pylint: disable=no-name-in-module
    import grpc
    from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc  # pylint: disable=no-member

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    # Placeholder values for when grpc is not available
    descriptor_pool = None  # type: ignore
    json_format = None  # type: ignore
    message_factory = None  # type: ignore
    FileDescriptorProto = None  # type: ignore
    grpc = None  # type: ignore
    reflection_pb2 = None  # type: ignore
    reflection_pb2_grpc = None  # type: ignore

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


PROTO_TO_JSON_TYPE_MAP = {
    1: "number",  # TYPE_DOUBLE
    2: "number",  # TYPE_FLOAT
    3: "integer",  # TYPE_INT64
    4: "integer",  # TYPE_UINT64
    5: "integer",  # TYPE_INT32
    8: "boolean",  # TYPE_BOOL
    9: "string",  # TYPE_STRING
    12: "string",  # TYPE_BYTES (base64)
    13: "integer",  # TYPE_UINT32
    14: "string",  # TYPE_ENUM
}


class GrpcEndpoint:
    """Wrapper around a gRPC channel with reflection-based introspection."""

    def __init__(
        self,
        target: str,
        reflection_enabled: bool = True,
        tls_enabled: bool = False,
        tls_cert_path: Optional[str] = None,
        tls_key_path: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ):
        """Initialize gRPC endpoint.

        Args:
            target: gRPC server address (host:port)
            reflection_enabled: Enable server reflection for discovery
            tls_enabled: Use TLS for connection
            tls_cert_path: Path to TLS certificate
            tls_key_path: Path to TLS key
            metadata: gRPC metadata headers
        """
        self._target = target
        self._reflection_enabled = reflection_enabled
        self._tls_enabled = tls_enabled
        self._tls_cert_path = tls_cert_path
        self._tls_key_path = tls_key_path
        self._metadata = metadata or {}
        self._channel: Optional[grpc.Channel] = None
        self._services: Dict[str, Any] = {}
        self._descriptors: Dict[str, Any] = {}
        self._pool = descriptor_pool.Default()
        self._factory = message_factory.MessageFactory()

    async def start(self) -> None:
        """Initialize gRPC channel and perform reflection if enabled."""
        logger.info(f"Starting gRPC endpoint connection to {self._target}")

        # Create channel
        if self._tls_enabled:
            if self._tls_cert_path and self._tls_key_path:
                with open(self._tls_cert_path, "rb") as f:
                    cert = f.read()
                with open(self._tls_key_path, "rb") as f:
                    key = f.read()
                credentials = grpc.ssl_channel_credentials(root_certificates=cert, private_key=key)
                self._channel = grpc.secure_channel(self._target, credentials)
            else:
                credentials = grpc.ssl_channel_credentials()
                self._channel = grpc.secure_channel(self._target, credentials)
        else:
            self._channel = grpc.insecure_channel(self._target)

        # Perform reflection if enabled
        if self._reflection_enabled:
            await self._discover_services()

    async def _discover_services(self) -> None:
        """Use gRPC reflection to discover services and methods.

        Raises:
            Exception: If service discovery fails
        """
        logger.info(f"Discovering services on {self._target} via reflection")

        try:
            stub = reflection_pb2_grpc.ServerReflectionStub(self._channel)

            # List all services
            request = reflection_pb2.ServerReflectionRequest(list_services="")  # pylint: disable=no-member

            response = stub.ServerReflectionInfo(iter([request]))

            service_names = []
            for resp in response:
                if resp.HasField("list_services_response"):
                    for svc in resp.list_services_response.service:
                        service_name = svc.name
                        # Skip reflection service itself
                        if "ServerReflection" in service_name:
                            continue
                        service_names.append(service_name)
                        logger.debug(f"Discovered service: {service_name}")

            # Get file descriptors for each service
            for service_name in service_names:
                await self._discover_service_details(stub, service_name)

            logger.info(f"Discovered {len(self._services)} gRPC services")

        except Exception as e:
            logger.error(f"Service discovery failed: {e}")
            raise

    async def _discover_service_details(self, stub, service_name: str) -> None:
        """Discover detailed information about a service including methods and message types.

        Args:
            stub: gRPC reflection stub
            service_name: Name of the service to discover
        """
        try:  # pylint: disable=too-many-nested-blocks
            # Request file descriptor containing this service
            request = reflection_pb2.ServerReflectionRequest(file_containing_symbol=service_name)  # pylint: disable=no-member

            response = stub.ServerReflectionInfo(iter([request]))

            for resp in response:
                if resp.HasField("file_descriptor_response"):
                    # Process all file descriptors
                    for file_desc_proto_bytes in resp.file_descriptor_response.file_descriptor_proto:
                        file_desc_proto = FileDescriptorProto()
                        file_desc_proto.ParseFromString(file_desc_proto_bytes)

                        # Add to pool (ignore if already exists)
                        try:
                            self._pool.Add(file_desc_proto)
                        except Exception as e:  # pylint: disable=broad-except
                            # Descriptor already in pool, safe to skip
                            logger.debug(f"Descriptor already in pool: {e}")

                        # Extract service and method information
                        for service_desc in file_desc_proto.service:
                            if service_desc.name in service_name or service_name.endswith(service_desc.name):
                                full_service_name = f"{file_desc_proto.package}.{service_desc.name}" if file_desc_proto.package else service_desc.name

                                methods = []
                                for method_desc in service_desc.method:
                                    methods.append(
                                        {
                                            "name": method_desc.name,
                                            "input_type": method_desc.input_type,
                                            "output_type": method_desc.output_type,
                                            "client_streaming": method_desc.client_streaming,
                                            "server_streaming": method_desc.server_streaming,
                                        }
                                    )

                                self._services[full_service_name] = {
                                    "name": full_service_name,
                                    "methods": methods,
                                    "package": file_desc_proto.package,
                                }

                                # Store descriptors for this service
                                self._descriptors[full_service_name] = file_desc_proto

                                logger.debug(f"Service {full_service_name} has {len(methods)} methods")

        except Exception as e:
            logger.warning(f"Failed to get details for {service_name}: {e}")
            # Still add basic service info even if details fail
            self._services[service_name] = {
                "name": service_name,
                "methods": [],
            }

    async def invoke(
        self,
        service: str,
        method: str,
        request_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Invoke a gRPC method with JSON request data.

        Args:
            service: Service name
            method: Method name
            request_data: JSON request data

        Returns:
            JSON response data

        Raises:
            ValueError: If service or method not found
            Exception: If invocation fails
        """
        logger.debug(f"Invoking {service}.{method}")

        # Get method info
        if service not in self._services:
            raise ValueError(f"Service {service} not found")

        method_info = None
        for m in self._services[service]["methods"]:
            if m["name"] == method:
                method_info = m
                break

        if not method_info:
            raise ValueError(f"Method {method} not found in service {service}")

        if method_info["client_streaming"] or method_info["server_streaming"]:
            raise ValueError(f"Method {method} is streaming, use invoke_streaming instead")

        # Get message descriptors from pool
        input_type = method_info["input_type"].lstrip(".")
        output_type = method_info["output_type"].lstrip(".")

        try:
            input_desc = self._pool.FindMessageTypeByName(input_type)
            output_desc = self._pool.FindMessageTypeByName(output_type)
        except KeyError as e:
            raise ValueError(f"Message type not found in descriptor pool: {e}")

        # Create message classes
        # pylint: disable=no-member
        request_class = self._factory.GetPrototype(input_desc)
        response_class = self._factory.GetPrototype(output_desc)

        # Convert JSON to protobuf message
        request_msg = json_format.ParseDict(request_data, request_class())

        # Create generic stub and invoke
        channel = self._channel
        method_path = f"/{service}/{method}"

        # Use generic_stub for dynamic invocation
        response_msg = await asyncio.get_event_loop().run_in_executor(
            None, channel.unary_unary(method_path, request_serializer=request_msg.SerializeToString, response_deserializer=response_class.FromString), request_msg
        )

        # Convert protobuf response to JSON
        # pylint: disable=unexpected-keyword-arg
        response_dict = json_format.MessageToDict(response_msg, preserving_proto_field_name=True, including_default_value_fields=True)

        logger.debug(f"Successfully invoked {service}.{method}")
        return response_dict

    async def invoke_streaming(
        self,
        service: str,
        method: str,
        request_data: Dict[str, Any],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Invoke a server-streaming gRPC method.

        Args:
            service: Service name
            method: Method name
            request_data: JSON request data

        Yields:
            JSON response chunks

        Raises:
            ValueError: If service or method not found or not streaming
            grpc.RpcError: If streaming RPC fails
        """
        logger.debug(f"Invoking streaming {service}.{method}")

        # Get method info
        if service not in self._services:
            raise ValueError(f"Service {service} not found")

        method_info = None
        for m in self._services[service]["methods"]:
            if m["name"] == method:
                method_info = m
                break

        if not method_info:
            raise ValueError(f"Method {method} not found in service {service}")

        if not method_info["server_streaming"]:
            raise ValueError(f"Method {method} is not server-streaming")

        if method_info["client_streaming"]:
            raise ValueError("Client streaming not yet supported")

        # Get message descriptors from pool
        input_type = method_info["input_type"].lstrip(".")
        output_type = method_info["output_type"].lstrip(".")

        try:
            input_desc = self._pool.FindMessageTypeByName(input_type)
            output_desc = self._pool.FindMessageTypeByName(output_type)
        except KeyError as e:
            raise ValueError(f"Message type not found in descriptor pool: {e}")

        # Create message classes
        # pylint: disable=no-member
        request_class = self._factory.GetPrototype(input_desc)
        response_class = self._factory.GetPrototype(output_desc)

        # Convert JSON to protobuf message
        request_msg = json_format.ParseDict(request_data, request_class())

        # Create streaming call
        channel = self._channel
        method_path = f"/{service}/{method}"

        stream_call = channel.unary_stream(method_path, request_serializer=request_msg.SerializeToString, response_deserializer=response_class.FromString)(request_msg)

        # Yield responses as they arrive
        try:
            for response_msg in stream_call:
                # pylint: disable=unexpected-keyword-arg
                response_dict = json_format.MessageToDict(response_msg, preserving_proto_field_name=True, including_default_value_fields=True)
                yield response_dict
        except grpc.RpcError as e:
            logger.error(f"Streaming RPC error: {e}")
            raise

        logger.debug(f"Streaming complete for {service}.{method}")

    async def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            self._channel.close()
            logger.info(f"Closed gRPC connection to {self._target}")

    def get_services(self) -> List[str]:
        """Get list of discovered service names.

        Returns:
            List of service names
        """
        return list(self._services.keys())

    def get_methods(self, service: str) -> List[str]:
        """Get list of methods for a service.

        Args:
            service: Service name

        Returns:
            List of method names
        """
        if service in self._services:
            return [m["name"] for m in self._services[service].get("methods", [])]
        return []


class GrpcToMcpTranslator:
    """Translates between gRPC and MCP protocols."""

    def __init__(self, endpoint: GrpcEndpoint):
        """Initialize translator.

        Args:
            endpoint: gRPC endpoint to translate
        """
        self._endpoint = endpoint

    def grpc_service_to_mcp_server(self, service_name: str) -> Dict[str, Any]:
        """Convert a gRPC service to an MCP virtual server definition.

        Args:
            service_name: gRPC service name

        Returns:
            MCP server definition
        """
        return {
            "name": service_name,
            "description": f"gRPC service: {service_name}",
            "transport": ["sse", "http"],
            "tools": self.grpc_methods_to_mcp_tools(service_name),
        }

    def grpc_methods_to_mcp_tools(self, service_name: str) -> List[Dict[str, Any]]:
        """Convert gRPC methods to MCP tool definitions.

        Args:
            service_name: gRPC service name

        Returns:
            List of MCP tool definitions
        """
        # pylint: disable=protected-access
        if service_name not in self._endpoint._services:
            return []

        service_info = self._endpoint._services[service_name]
        tools = []

        for method_info in service_info.get("methods", []):
            method_name = method_info["name"]
            input_type = method_info["input_type"].lstrip(".")

            # Try to get input schema from descriptor
            try:
                input_desc = self._endpoint._pool.FindMessageTypeByName(input_type)
                input_schema = self.protobuf_to_json_schema(input_desc)
            except KeyError:
                # Fallback to generic schema if descriptor not found
                input_schema = {"type": "object", "properties": {}}

            tools.append({"name": f"{service_name}.{method_name}", "description": f"gRPC method {service_name}.{method_name}", "inputSchema": input_schema})

        return tools

    def protobuf_to_json_schema(self, message_descriptor: Any) -> Dict[str, Any]:
        """Convert protobuf message descriptor to JSON schema.

        Args:
            message_descriptor: Protobuf message descriptor

        Returns:
            JSON schema
        """
        schema = {"type": "object", "properties": {}, "required": []}

        # Iterate over fields in the message
        for field in message_descriptor.fields:
            field_name = field.name
            field_schema = self._protobuf_field_to_json_schema(field)
            schema["properties"][field_name] = field_schema

            # Add to required if field is required (proto2/proto3 handling)
            if hasattr(field, "label") and field.label == 2:  # LABEL_REQUIRED
                schema["required"].append(field_name)

        return schema

    def _protobuf_field_to_json_schema(self, field: Any) -> Dict[str, Any]:
        """Convert a protobuf field to JSON schema type.

        Args:
            field: Protobuf field descriptor

        Returns:
            JSON schema for the field
        """
        # Map protobuf types to JSON schema types
        type_map = {
            1: "number",  # TYPE_DOUBLE
            2: "number",  # TYPE_FLOAT
            3: "integer",  # TYPE_INT64
            4: "integer",  # TYPE_UINT64
            5: "integer",  # TYPE_INT32
            6: "integer",  # TYPE_FIXED64
            7: "integer",  # TYPE_FIXED32
            8: "boolean",  # TYPE_BOOL
            9: "string",  # TYPE_STRING
            11: "object",  # TYPE_MESSAGE
            12: "string",  # TYPE_BYTES (base64)
            13: "integer",  # TYPE_UINT32
            14: "string",  # TYPE_ENUM
            15: "integer",  # TYPE_SFIXED32
            16: "integer",  # TYPE_SFIXED64
            17: "integer",  # TYPE_SINT32
            18: "integer",  # TYPE_SINT64
        }

        field_type = type_map.get(field.type, "string")

        # Handle repeated fields
        if hasattr(field, "label") and field.label == 3:  # LABEL_REPEATED
            return {"type": "array", "items": {"type": field_type}}

        # Handle message types (nested objects)
        if field.type == 11:  # TYPE_MESSAGE
            try:
                nested_desc = field.message_type
                return self.protobuf_to_json_schema(nested_desc)
            except Exception:
                return {"type": "object"}

        return {"type": field_type}


# Utility functions for CLI usage


async def expose_grpc_via_sse(
    target: str,
    port: int = 9000,
    tls_enabled: bool = False,
    tls_cert: Optional[str] = None,
    tls_key: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
) -> None:
    """Expose a gRPC service via SSE/HTTP endpoints.

    Args:
        target: gRPC server address (host:port)
        port: HTTP port to listen on
        tls_enabled: Use TLS for gRPC connection
        tls_cert: TLS certificate path
        tls_key: TLS key path
        metadata: gRPC metadata headers
    """
    logger.info(f"Exposing gRPC service {target} via SSE on port {port}")

    endpoint = GrpcEndpoint(
        target=target,
        reflection_enabled=True,
        tls_enabled=tls_enabled,
        tls_cert_path=tls_cert,
        tls_key_path=tls_key,
        metadata=metadata,
    )

    try:
        await endpoint.start()

        logger.info(f"gRPC service exposed. Discovered services: {endpoint.get_services()}")
        logger.info("To expose via HTTP/SSE, register this service in the gateway admin UI")
        logger.info(f"  Target: {target}")
        logger.info(f"  Discovered: {len(endpoint.get_services())} services")

        # Keep endpoint connection alive
        # Note: For full HTTP/SSE exposure, register the service via the gateway admin API
        # which will make it accessible through the existing multi-protocol server infrastructure
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await endpoint.close()
