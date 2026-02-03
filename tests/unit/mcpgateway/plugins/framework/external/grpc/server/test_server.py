# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/grpc/server/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for gRPC plugin server.
Tests for GrpcPluginServicer and GrpcHealthServicer.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct
import pytest

# First-Party
from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2
from mcpgateway.plugins.framework.external.grpc.server.server import GrpcHealthServicer, GrpcPluginServicer
from mcpgateway.plugins.framework.models import GlobalContext, PluginConfig, PluginContext


@pytest.fixture
def mock_plugin_server():
    """Create a mock ExternalPluginServer for testing."""
    mock_server = AsyncMock()
    mock_server.get_plugin_configs = AsyncMock(return_value=[])
    mock_server.get_plugin_config = AsyncMock(return_value=None)
    mock_server.invoke_hook = AsyncMock(return_value={"continue_processing": True})
    return mock_server


@pytest.fixture
def servicer(mock_plugin_server):
    """Create a GrpcPluginServicer for testing."""
    return GrpcPluginServicer(mock_plugin_server)


@pytest.fixture
def health_servicer(mock_plugin_server):
    """Create a GrpcHealthServicer for testing."""
    return GrpcHealthServicer(mock_plugin_server)


class TestGrpcPluginServicerGetPluginConfig:
    """Tests for GrpcPluginServicer.GetPluginConfig."""

    @pytest.mark.asyncio
    async def test_get_plugin_config_found(self, servicer, mock_plugin_server):
        """Test GetPluginConfig returns config when found."""
        # Server expects dict from get_plugin_config
        mock_config_dict = {
            "name": "TestPlugin",
            "kind": "test.plugin.TestPlugin",
            "hooks": ["tool_pre_invoke"],
        }
        mock_plugin_server.get_plugin_config = AsyncMock(return_value=mock_config_dict)

        request = plugin_service_pb2.GetPluginConfigRequest(name="TestPlugin")
        context = MagicMock()

        response = await servicer.GetPluginConfig(request, context)

        assert response.found is True
        config_dict = json_format.MessageToDict(response.config)
        assert config_dict["name"] == "TestPlugin"

    @pytest.mark.asyncio
    async def test_get_plugin_config_not_found(self, servicer, mock_plugin_server):
        """Test GetPluginConfig returns not found when plugin doesn't exist."""
        mock_plugin_server.get_plugin_config = AsyncMock(return_value=None)

        request = plugin_service_pb2.GetPluginConfigRequest(name="NonExistent")
        context = MagicMock()

        response = await servicer.GetPluginConfig(request, context)

        assert response.found is False


class TestGrpcPluginServicerGetPluginConfigs:
    """Tests for GrpcPluginServicer.GetPluginConfigs."""

    @pytest.mark.asyncio
    async def test_get_plugin_configs_empty(self, servicer, mock_plugin_server):
        """Test GetPluginConfigs returns empty list when no plugins."""
        mock_plugin_server.get_plugin_configs = AsyncMock(return_value=[])

        request = plugin_service_pb2.GetPluginConfigsRequest()
        context = MagicMock()

        response = await servicer.GetPluginConfigs(request, context)

        assert len(response.configs) == 0

    @pytest.mark.asyncio
    async def test_get_plugin_configs_multiple(self, servicer, mock_plugin_server):
        """Test GetPluginConfigs returns multiple configs."""
        # Server expects list of dicts from get_plugin_configs
        mock_configs = [
            {"name": "Plugin1", "kind": "test.Plugin1", "hooks": ["tool_pre_invoke"]},
            {"name": "Plugin2", "kind": "test.Plugin2", "hooks": ["prompt_pre_fetch"]},
        ]
        mock_plugin_server.get_plugin_configs = AsyncMock(return_value=mock_configs)

        request = plugin_service_pb2.GetPluginConfigsRequest()
        context = MagicMock()

        response = await servicer.GetPluginConfigs(request, context)

        assert len(response.configs) == 2


class TestGrpcPluginServicerInvokeHook:
    """Tests for GrpcPluginServicer.InvokeHook."""

    @pytest.mark.asyncio
    async def test_invoke_hook_success(self, servicer, mock_plugin_server):
        """Test InvokeHook returns successful result."""
        # The server returns "result" key when the hook produces a result dict
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={
                "result": {
                    "continue_processing": True,
                    "modified_payload": None,
                }
            }
        )

        # Build request
        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)

        # Build context
        request.context.global_context.request_id = "test-request"
        request.context.global_context.server_id = "test-server"

        context = MagicMock()

        response = await servicer.InvokeHook(request, context)

        assert response.HasField("result")
        result_dict = json_format.MessageToDict(response.result)
        assert result_dict.get("continueProcessing") is True or result_dict.get("continue_processing") is True

    @pytest.mark.asyncio
    async def test_invoke_hook_with_error(self, servicer, mock_plugin_server):
        """Test InvokeHook handles plugin errors."""
        from mcpgateway.plugins.framework.errors import PluginError
        from mcpgateway.plugins.framework.models import PluginErrorModel

        mock_plugin_server.invoke_hook = AsyncMock(
            side_effect=PluginError(
                error=PluginErrorModel(
                    message="Processing failed",
                    plugin_name="TestPlugin",
                    code="PROCESSING_ERROR",
                )
            )
        )

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)

        request.context.global_context.request_id = "test-request"
        request.context.global_context.server_id = "test-server"

        context = MagicMock()

        response = await servicer.InvokeHook(request, context)

        assert response.HasField("error")
        assert response.error.message == "Processing failed"
        assert response.error.plugin_name == "TestPlugin"

    @pytest.mark.asyncio
    async def test_invoke_hook_with_context_update(self, servicer, mock_plugin_server):
        """Test InvokeHook includes context updates in response."""
        # Return result with context
        result_context = PluginContext(
            global_context=GlobalContext(request_id="test", server_id="test"),
            state={"updated_key": "updated_value"},
        )
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={
                "continue_processing": True,
                "context": result_context,
            }
        )

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)

        request.context.global_context.request_id = "test-request"
        request.context.global_context.server_id = "test-server"

        context = MagicMock()

        response = await servicer.InvokeHook(request, context)

        assert response.HasField("context")

    @pytest.mark.asyncio
    async def test_invoke_hook_unexpected_error(self, servicer, mock_plugin_server):
        """Test InvokeHook handles unexpected exceptions."""
        mock_plugin_server.invoke_hook = AsyncMock(side_effect=RuntimeError("Unexpected error"))

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)

        request.context.global_context.request_id = "test-request"
        request.context.global_context.server_id = "test-server"

        context = MagicMock()

        response = await servicer.InvokeHook(request, context)

        assert response.HasField("error")
        assert "Unexpected error" in response.error.message


class TestGrpcHealthServicer:
    """Tests for GrpcHealthServicer."""

    @pytest.mark.asyncio
    async def test_check_serving(self, health_servicer, mock_plugin_server):
        """Test health check returns SERVING when plugins are loaded."""
        mock_plugin_server.get_plugin_configs = AsyncMock(
            return_value=[
                PluginConfig(name="Plugin1", kind="test.Plugin1", hooks=[]),
            ]
        )

        request = plugin_service_pb2.HealthCheckRequest()
        context = MagicMock()

        response = await health_servicer.Check(request, context)

        assert response.status == plugin_service_pb2.HealthCheckResponse.SERVING

    @pytest.mark.asyncio
    async def test_check_always_serving(self, health_servicer, mock_plugin_server):
        """Test health check returns SERVING even when no plugins loaded.

        The current implementation always returns SERVING if the server is running.
        This may be enhanced in the future to check plugin server health.
        """
        mock_plugin_server.get_plugin_configs = AsyncMock(return_value=[])

        request = plugin_service_pb2.HealthCheckRequest()
        context = MagicMock()

        response = await health_servicer.Check(request, context)

        # Server always returns SERVING when running
        assert response.status == plugin_service_pb2.HealthCheckResponse.SERVING

    @pytest.mark.asyncio
    async def test_check_with_service_name(self, health_servicer, mock_plugin_server):
        """Test health check with specific service name."""
        request = plugin_service_pb2.HealthCheckRequest(service="plugin_service")
        context = MagicMock()

        response = await health_servicer.Check(request, context)

        # Server always returns SERVING when running
        assert response.status == plugin_service_pb2.HealthCheckResponse.SERVING


class TestGrpcPluginServicerEdgeCases:
    """Edge case tests for GrpcPluginServicer."""

    @pytest.mark.asyncio
    async def test_invoke_hook_with_violation(self, servicer, mock_plugin_server):
        """Test InvokeHook handles results with violations."""
        # Server expects "result" key in the invoke_hook return value
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={
                "result": {
                    "continue_processing": False,
                    "violation": {
                        "code": "BLOCKED",
                        "message": "Content blocked by policy",
                    },
                }
            }
        )

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)

        request.context.global_context.request_id = "test-request"
        request.context.global_context.server_id = "test-server"

        context = MagicMock()

        response = await servicer.InvokeHook(request, context)

        assert response.HasField("result")
        result_dict = json_format.MessageToDict(response.result)
        # Check continue_processing is False (camelCase in proto)
        assert result_dict.get("continueProcessing") is False or result_dict.get("continue_processing") is False

    @pytest.mark.asyncio
    async def test_invoke_hook_with_modified_payload(self, servicer, mock_plugin_server):
        """Test InvokeHook handles results with modified payload."""
        # Server expects "result" key in the invoke_hook return value
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={
                "result": {
                    "continue_processing": True,
                    "modified_payload": {"name": "modified_tool", "args": {"modified": True}},
                }
            }
        )

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)

        request.context.global_context.request_id = "test-request"
        request.context.global_context.server_id = "test-server"

        context = MagicMock()

        response = await servicer.InvokeHook(request, context)

        assert response.HasField("result")
        result_dict = json_format.MessageToDict(response.result)
        assert "modifiedPayload" in result_dict or "modified_payload" in result_dict
