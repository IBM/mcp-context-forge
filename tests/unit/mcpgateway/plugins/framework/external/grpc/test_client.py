# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/grpc/test_client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for gRPC external plugin client.
Tests for GrpcExternalPlugin initialization, hook invocation, and error handling.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct
import grpc
import pytest

# First-Party
from mcpgateway.plugins.framework import ToolPreInvokePayload
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.external.grpc.client import GrpcExternalPlugin
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    GRPCClientConfig,
    PluginConfig,
    PluginContext,
)


@pytest.fixture
def mock_plugin_config():
    """Create a mock plugin config for testing."""
    return PluginConfig(
        name="TestGrpcPlugin",
        kind="external",
        hooks=["tool_pre_invoke"],
        grpc=GRPCClientConfig(target="localhost:50051"),
    )


@pytest.fixture
def mock_plugin_config_uds(tmp_path):
    """Create a mock plugin config with UDS for testing."""
    uds_path = str(tmp_path / "test.sock")
    return PluginConfig(
        name="TestGrpcUdsPlugin",
        kind="external",
        hooks=["tool_pre_invoke"],
        grpc=GRPCClientConfig(uds=uds_path),
    )


class TestGrpcExternalPluginInit:
    """Tests for GrpcExternalPlugin initialization."""

    def test_init_with_config(self, mock_plugin_config):
        """Test plugin initialization with valid config."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        assert plugin.name == "TestGrpcPlugin"
        assert plugin._channel is None
        assert plugin._stub is None

    def test_init_stores_config(self, mock_plugin_config):
        """Test plugin stores configuration."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        assert plugin._config.grpc is not None
        assert plugin._config.grpc.target == "localhost:50051"


class TestGrpcExternalPluginInitialize:
    """Tests for GrpcExternalPlugin.initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_missing_grpc_config(self):
        """Test initialize raises PluginError when grpc config is missing."""
        config = PluginConfig(
            name="TestPlugin",
            kind="external",
            hooks=["tool_pre_invoke"],
            grpc=GRPCClientConfig(target="localhost:50051"),
        )
        plugin = GrpcExternalPlugin(config)
        plugin._config.grpc = None  # Remove grpc config

        with pytest.raises(PluginError, match="grpc section must be defined"):
            await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_creates_channel(self, mock_plugin_config):
        """Test initialize creates gRPC channel."""
        plugin = GrpcExternalPlugin(mock_plugin_config)

        mock_channel = AsyncMock()
        mock_stub = MagicMock()

        # Mock the remote config response - must include grpc section for external plugins
        mock_response = MagicMock()
        mock_response.found = True
        config_struct = Struct()
        json_format.ParseDict(
            {
                "name": "TestGrpcPlugin",
                "kind": "test.plugin.TestPlugin",  # Non-external kind to avoid validation
                "hooks": ["tool_pre_invoke"],
            },
            config_struct,
        )
        mock_response.config = config_struct
        mock_stub.GetPluginConfig = AsyncMock(return_value=mock_response)

        with patch(
            "mcpgateway.plugins.framework.external.grpc.client.create_insecure_channel",
            return_value=mock_channel,
        ):
            with patch(
                "mcpgateway.plugins.framework.external.grpc.client.plugin_service_pb2_grpc.PluginServiceStub",
                return_value=mock_stub,
            ):
                await plugin.initialize()

                assert plugin._channel is mock_channel
                assert plugin._stub is mock_stub

    @pytest.mark.asyncio
    async def test_initialize_with_tls(self, mock_plugin_config):
        """Test initialize creates secure channel when TLS is configured."""
        from mcpgateway.plugins.framework.models import GRPCClientTLSConfig

        mock_plugin_config.grpc.tls = GRPCClientTLSConfig(verify=True)
        plugin = GrpcExternalPlugin(mock_plugin_config)

        mock_channel = AsyncMock()
        mock_stub = MagicMock()

        mock_response = MagicMock()
        mock_response.found = True
        config_struct = Struct()
        json_format.ParseDict({"name": "TestGrpcPlugin", "kind": "test.plugin.TestPlugin", "hooks": ["tool_pre_invoke"]}, config_struct)
        mock_response.config = config_struct
        mock_stub.GetPluginConfig = AsyncMock(return_value=mock_response)

        with patch(
            "mcpgateway.plugins.framework.external.grpc.client.create_secure_channel",
            return_value=mock_channel,
        ) as mock_create_secure:
            with patch(
                "mcpgateway.plugins.framework.external.grpc.client.plugin_service_pb2_grpc.PluginServiceStub",
                return_value=mock_stub,
            ):
                await plugin.initialize()

                mock_create_secure.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_with_uds(self, mock_plugin_config_uds):
        """Test initialize with Unix domain socket."""
        plugin = GrpcExternalPlugin(mock_plugin_config_uds)

        mock_channel = AsyncMock()
        mock_stub = MagicMock()

        mock_response = MagicMock()
        mock_response.found = True
        config_struct = Struct()
        json_format.ParseDict({"name": "TestGrpcUdsPlugin", "kind": "test.plugin.TestPlugin", "hooks": ["tool_pre_invoke"]}, config_struct)
        mock_response.config = config_struct
        mock_stub.GetPluginConfig = AsyncMock(return_value=mock_response)

        with patch(
            "mcpgateway.plugins.framework.external.grpc.client.create_insecure_channel",
            return_value=mock_channel,
        ) as mock_create_insecure:
            with patch(
                "mcpgateway.plugins.framework.external.grpc.client.plugin_service_pb2_grpc.PluginServiceStub",
                return_value=mock_stub,
            ):
                await plugin.initialize()

                # Should use insecure channel for UDS (TLS not supported)
                mock_create_insecure.assert_called_once()
                # Target should be in unix:// format
                call_args = mock_create_insecure.call_args[0][0]
                assert call_args.startswith("unix://")

    @pytest.mark.asyncio
    async def test_initialize_config_retrieval_failure(self, mock_plugin_config):
        """Test initialize raises PluginError when config retrieval fails."""
        plugin = GrpcExternalPlugin(mock_plugin_config)

        mock_channel = AsyncMock()
        mock_stub = MagicMock()

        # Mock config not found
        mock_response = MagicMock()
        mock_response.found = False
        mock_stub.GetPluginConfig = AsyncMock(return_value=mock_response)

        with patch(
            "mcpgateway.plugins.framework.external.grpc.client.create_insecure_channel",
            return_value=mock_channel,
        ):
            with patch(
                "mcpgateway.plugins.framework.external.grpc.client.plugin_service_pb2_grpc.PluginServiceStub",
                return_value=mock_stub,
            ):
                with pytest.raises(PluginError, match="Unable to retrieve configuration"):
                    await plugin.initialize()

    @pytest.mark.asyncio
    async def test_initialize_connection_error(self, mock_plugin_config):
        """Test initialize handles connection errors."""
        plugin = GrpcExternalPlugin(mock_plugin_config)

        mock_channel = AsyncMock()
        mock_stub = MagicMock()
        mock_stub.GetPluginConfig = AsyncMock(side_effect=grpc.RpcError())

        with patch(
            "mcpgateway.plugins.framework.external.grpc.client.create_insecure_channel",
            return_value=mock_channel,
        ):
            with patch(
                "mcpgateway.plugins.framework.external.grpc.client.plugin_service_pb2_grpc.PluginServiceStub",
                return_value=mock_stub,
            ):
                with pytest.raises(PluginError, match="connection failed"):
                    await plugin.initialize()


class TestGrpcExternalPluginInvokeHook:
    """Tests for GrpcExternalPlugin.invoke_hook()."""

    @pytest.fixture
    def initialized_plugin(self, mock_plugin_config):
        """Create an initialized plugin for testing."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        plugin._channel = AsyncMock()
        plugin._stub = MagicMock()
        return plugin

    @pytest.mark.asyncio
    async def test_invoke_hook_success(self, initialized_plugin):
        """Test successful hook invocation."""
        # Create mock response
        mock_response = MagicMock()
        mock_response.HasField = MagicMock(side_effect=lambda x: x == "result")
        result_struct = Struct()
        json_format.ParseDict({"continue_processing": True}, result_struct)
        mock_response.result = result_struct
        mock_response.error = MagicMock()
        mock_response.error.message = ""

        initialized_plugin._stub.InvokeHook = AsyncMock(return_value=mock_response)

        context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
        payload = ToolPreInvokePayload(name="test_tool", args={"arg1": "value1"})

        result = await initialized_plugin.invoke_hook("tool_pre_invoke", payload, context)

        assert result is not None
        assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_invoke_hook_stub_not_initialized(self, mock_plugin_config):
        """Test invoke_hook raises error when stub not initialized."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        # Don't initialize - stub should be None

        context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
        payload = ToolPreInvokePayload(name="test_tool", args={})

        with pytest.raises(PluginError, match="stub not initialized"):
            await plugin.invoke_hook("tool_pre_invoke", payload, context)

    @pytest.mark.asyncio
    async def test_invoke_hook_error_response(self, initialized_plugin):
        """Test invoke_hook handles error response from server."""
        mock_response = MagicMock()
        mock_response.HasField = MagicMock(side_effect=lambda x: x == "error")
        mock_response.error = MagicMock()
        mock_response.error.message = "Plugin processing failed"
        mock_response.error.plugin_name = "TestGrpcPlugin"
        mock_response.error.code = "PROCESSING_ERROR"
        mock_response.error.mcp_error_code = -32603  # Valid integer error code
        mock_response.error.HasField = MagicMock(return_value=False)

        initialized_plugin._stub.InvokeHook = AsyncMock(return_value=mock_response)

        context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
        payload = ToolPreInvokePayload(name="test_tool", args={})

        with pytest.raises(PluginError, match="Plugin processing failed"):
            await initialized_plugin.invoke_hook("tool_pre_invoke", payload, context)

    @pytest.mark.asyncio
    async def test_invoke_hook_grpc_error(self, initialized_plugin):
        """Test invoke_hook handles gRPC errors."""
        initialized_plugin._stub.InvokeHook = AsyncMock(side_effect=grpc.RpcError())

        context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
        payload = ToolPreInvokePayload(name="test_tool", args={})

        with pytest.raises(PluginError):
            await initialized_plugin.invoke_hook("tool_pre_invoke", payload, context)

    @pytest.mark.asyncio
    async def test_invoke_hook_unregistered_hook_type(self, initialized_plugin):
        """Test invoke_hook raises error for unregistered hook type."""
        context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
        payload = ToolPreInvokePayload(name="test_tool", args={})

        with pytest.raises(PluginError, match="not registered"):
            await initialized_plugin.invoke_hook("invalid_hook_type", payload, context)

    @pytest.mark.asyncio
    async def test_invoke_hook_updates_context(self, initialized_plugin):
        """Test invoke_hook updates context from response."""
        from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2

        mock_response = MagicMock()

        # Set up HasField to return True for both result and context
        def has_field(name):
            return name in ["result", "context"]

        mock_response.HasField = MagicMock(side_effect=has_field)

        # Set up result
        result_struct = Struct()
        json_format.ParseDict({"continue_processing": True}, result_struct)
        mock_response.result = result_struct

        # Set up context with updated state
        mock_context = plugin_service_pb2.PluginContext()
        state_struct = Struct()
        json_format.ParseDict({"key": "value"}, state_struct)
        mock_context.state.CopyFrom(state_struct)
        mock_response.context = mock_context

        # Error should not have message
        mock_response.error = MagicMock()
        mock_response.error.message = ""

        initialized_plugin._stub.InvokeHook = AsyncMock(return_value=mock_response)

        context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
        payload = ToolPreInvokePayload(name="test_tool", args={})

        await initialized_plugin.invoke_hook("tool_pre_invoke", payload, context)

        # Context should be updated with state from response
        assert context.state.get("key") == "value"


class TestGrpcExternalPluginShutdown:
    """Tests for GrpcExternalPlugin.shutdown()."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_channel(self, mock_plugin_config):
        """Test shutdown closes the gRPC channel."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        mock_channel = AsyncMock()
        plugin._channel = mock_channel
        plugin._stub = MagicMock()

        await plugin.shutdown()

        mock_channel.close.assert_called_once()
        assert plugin._channel is None
        assert plugin._stub is None

    @pytest.mark.asyncio
    async def test_shutdown_no_channel(self, mock_plugin_config):
        """Test shutdown handles case when channel is None."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        # Don't set channel - should be None

        # Should not raise
        await plugin.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self, mock_plugin_config):
        """Test shutdown can be called multiple times safely."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        mock_channel = AsyncMock()
        plugin._channel = mock_channel
        plugin._stub = MagicMock()

        await plugin.shutdown()
        await plugin.shutdown()  # Second call should not raise

        # close should only be called once
        mock_channel.close.assert_called_once()


class TestGrpcExternalPluginRetry:
    """Tests for retry logic in GrpcExternalPlugin."""

    @pytest.mark.asyncio
    async def test_get_plugin_config_with_retry_success(self, mock_plugin_config):
        """Test retry logic succeeds on first attempt."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        mock_stub = MagicMock()
        plugin._stub = mock_stub

        mock_response = MagicMock()
        mock_response.found = True
        config_struct = Struct()
        # Use non-external kind to avoid validation requiring grpc/mcp/unix_socket section
        json_format.ParseDict({"name": "TestPlugin", "kind": "test.plugin.TestPlugin", "hooks": []}, config_struct)
        mock_response.config = config_struct

        mock_stub.GetPluginConfig = AsyncMock(return_value=mock_response)

        result = await plugin._get_plugin_config_with_retry(max_retries=3)

        assert result is not None
        assert mock_stub.GetPluginConfig.call_count == 1

    @pytest.mark.asyncio
    async def test_get_plugin_config_with_retry_eventual_success(self, mock_plugin_config):
        """Test retry logic succeeds after failures."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        mock_stub = MagicMock()
        plugin._stub = mock_stub

        mock_response = MagicMock()
        mock_response.found = True
        config_struct = Struct()
        # Use non-external kind to avoid validation requiring grpc/mcp/unix_socket section
        json_format.ParseDict({"name": "TestPlugin", "kind": "test.plugin.TestPlugin", "hooks": []}, config_struct)
        mock_response.config = config_struct

        # Fail twice, then succeed
        mock_stub.GetPluginConfig = AsyncMock(side_effect=[grpc.RpcError(), grpc.RpcError(), mock_response])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await plugin._get_plugin_config_with_retry(max_retries=3, base_delay=0.01)

        assert result is not None
        assert mock_stub.GetPluginConfig.call_count == 3

    @pytest.mark.asyncio
    async def test_get_plugin_config_with_retry_all_failures(self, mock_plugin_config):
        """Test retry logic raises after all attempts fail."""
        plugin = GrpcExternalPlugin(mock_plugin_config)
        mock_stub = MagicMock()
        plugin._stub = mock_stub

        mock_stub.GetPluginConfig = AsyncMock(side_effect=grpc.RpcError())

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(PluginError, match="connection failed after 3 attempts"):
                await plugin._get_plugin_config_with_retry(max_retries=3, base_delay=0.01)

        assert mock_stub.GetPluginConfig.call_count == 3
