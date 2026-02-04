# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/unix/test_client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for Unix socket external plugin client.
Tests for UnixSocketExternalPlugin initialization, hook invocation, and error handling.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# Check if grpc/protobuf is available
try:
    from google.protobuf import json_format
    from google.protobuf.struct_pb2 import Struct
    from mcpgateway.plugins.framework.external.unix.client import UnixSocketExternalPlugin

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False
    json_format = None  # type: ignore
    Struct = None  # type: ignore

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed (required for protobuf)")

# First-Party
from mcpgateway.plugins.framework import ToolPreInvokePayload
from mcpgateway.plugins.framework.errors import PluginError
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    UnixSocketClientConfig,
)


@pytest.fixture
def mock_plugin_config(tmp_path):
    """Create a mock plugin config for testing."""
    socket_path = str(tmp_path / "test.sock")
    return PluginConfig(
        name="TestUnixPlugin",
        kind="external",
        hooks=["tool_pre_invoke"],
        unix_socket=UnixSocketClientConfig(
            path=socket_path,
            timeout=5.0,
            reconnect_attempts=2,
            reconnect_delay=0.1,
        ),
    )


class TestUnixSocketExternalPluginInit:
    """Tests for UnixSocketExternalPlugin initialization."""

    def test_init_with_config(self, mock_plugin_config):
        """Test plugin initialization with valid config."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        assert plugin.name == "TestUnixPlugin"
        assert plugin._reader is None
        assert plugin._writer is None
        assert plugin._connected is False

    def test_init_stores_socket_config(self, mock_plugin_config):
        """Test plugin stores socket configuration."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        assert plugin._socket_path == mock_plugin_config.unix_socket.path
        assert plugin._timeout == 5.0
        assert plugin._reconnect_attempts == 2
        assert plugin._reconnect_delay == 0.1

    def test_init_missing_unix_socket_config(self):
        """Test init raises PluginError when unix_socket config is missing."""
        config = PluginConfig(
            name="TestPlugin",
            kind="external",
            hooks=["tool_pre_invoke"],
            unix_socket=UnixSocketClientConfig(path="/tmp/test.sock"),
        )
        plugin = UnixSocketExternalPlugin(config)
        plugin._config.unix_socket = None

        with pytest.raises(PluginError, match="unix_socket section must be defined"):
            # Re-initialize to trigger the check
            UnixSocketExternalPlugin.__init__(plugin, config)


class TestUnixSocketExternalPluginConnected:
    """Tests for UnixSocketExternalPlugin.connected property."""

    def test_connected_false_when_not_connected(self, mock_plugin_config):
        """Test connected returns False when not connected."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        assert plugin.connected is False

    def test_connected_false_when_writer_none(self, mock_plugin_config):
        """Test connected returns False when writer is None."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        plugin._connected = True
        plugin._writer = None
        assert plugin.connected is False

    def test_connected_false_when_writer_closing(self, mock_plugin_config):
        """Test connected returns False when writer is closing."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        plugin._connected = True
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = True
        plugin._writer = mock_writer
        assert plugin.connected is False

    def test_connected_true_when_active(self, mock_plugin_config):
        """Test connected returns True when properly connected."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        plugin._connected = True
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        plugin._writer = mock_writer
        assert plugin.connected is True


class TestUnixSocketExternalPluginInitialize:
    """Tests for UnixSocketExternalPlugin.initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_connects_to_socket(self, mock_plugin_config):
        """Test initialize establishes socket connection."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False

        # Mock the config response
        from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2

        config_response = plugin_service_pb2.GetPluginConfigResponse()
        config_response.found = True

        with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)) as mock_connect:
            with patch.object(plugin, "_writer", mock_writer):
                with patch(
                    "mcpgateway.plugins.framework.external.unix.client.write_message_async",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "mcpgateway.plugins.framework.external.unix.client.read_message",
                        new_callable=AsyncMock,
                        return_value=config_response.SerializeToString(),
                    ):
                        await plugin.initialize()

            mock_connect.assert_called_once_with(mock_plugin_config.unix_socket.path)

    @pytest.mark.asyncio
    async def test_initialize_connection_error(self, mock_plugin_config):
        """Test initialize handles connection errors."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)

        with patch("asyncio.open_unix_connection", side_effect=OSError("Connection refused")):
            with pytest.raises(PluginError, match="Failed to connect"):
                await plugin.initialize()


class TestUnixSocketExternalPluginInvokeHook:
    """Tests for UnixSocketExternalPlugin.invoke_hook()."""

    @pytest.fixture
    def initialized_plugin(self, mock_plugin_config):
        """Create an initialized plugin for testing."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        plugin._connected = True
        plugin._reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        plugin._writer = mock_writer
        return plugin

    @pytest.mark.asyncio
    async def test_invoke_hook_success(self, initialized_plugin):
        """Test successful hook invocation."""
        from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2

        # Create mock response
        response = plugin_service_pb2.InvokeHookResponse()
        result_struct = Struct()
        json_format.ParseDict({"continue_processing": True}, result_struct)
        response.result.CopyFrom(result_struct)

        with patch(
            "mcpgateway.plugins.framework.external.unix.client.write_message_async",
            new_callable=AsyncMock,
        ):
            with patch(
                "mcpgateway.plugins.framework.external.unix.client.read_message",
                new_callable=AsyncMock,
                return_value=response.SerializeToString(),
            ):
                context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
                payload = ToolPreInvokePayload(name="test_tool", args={"arg1": "value1"})

                result = await initialized_plugin.invoke_hook("tool_pre_invoke", payload, context)

                assert result is not None
                assert result.continue_processing is True

    @pytest.mark.asyncio
    async def test_invoke_hook_not_connected(self, mock_plugin_config):
        """Test invoke_hook reconnects when not connected."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        plugin._connected = False

        context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
        payload = ToolPreInvokePayload(name="test_tool", args={})

        with pytest.raises(PluginError):
            await plugin.invoke_hook("tool_pre_invoke", payload, context)

    @pytest.mark.asyncio
    async def test_invoke_hook_error_response(self, initialized_plugin):
        """Test invoke_hook handles error response from server."""
        from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2

        # Create error response
        response = plugin_service_pb2.InvokeHookResponse()
        response.error.message = "Plugin processing failed"
        response.error.plugin_name = "TestUnixPlugin"
        response.error.code = "PROCESSING_ERROR"

        with patch(
            "mcpgateway.plugins.framework.external.unix.client.write_message_async",
            new_callable=AsyncMock,
        ):
            with patch(
                "mcpgateway.plugins.framework.external.unix.client.read_message",
                new_callable=AsyncMock,
                return_value=response.SerializeToString(),
            ):
                context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
                payload = ToolPreInvokePayload(name="test_tool", args={})

                with pytest.raises(PluginError, match="Plugin processing failed"):
                    await initialized_plugin.invoke_hook("tool_pre_invoke", payload, context)

    @pytest.mark.asyncio
    async def test_invoke_hook_timeout(self, initialized_plugin):
        """Test invoke_hook handles timeout."""
        with patch(
            "mcpgateway.plugins.framework.external.unix.client.write_message_async",
            new_callable=AsyncMock,
        ):
            with patch(
                "mcpgateway.plugins.framework.external.unix.client.read_message",
                new_callable=AsyncMock,
                side_effect=asyncio.TimeoutError(),
            ):
                context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
                payload = ToolPreInvokePayload(name="test_tool", args={})

                with pytest.raises(PluginError, match="timed out"):
                    await initialized_plugin.invoke_hook("tool_pre_invoke", payload, context)

    @pytest.mark.asyncio
    async def test_invoke_hook_unregistered_hook_type(self, initialized_plugin):
        """Test invoke_hook raises error for unregistered hook type."""
        context = PluginContext(global_context=GlobalContext(request_id="test", server_id="test"))
        payload = ToolPreInvokePayload(name="test_tool", args={})

        with pytest.raises(PluginError, match="not registered"):
            await initialized_plugin.invoke_hook("invalid_hook_type", payload, context)


class TestUnixSocketExternalPluginShutdown:
    """Tests for UnixSocketExternalPlugin.shutdown()."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_connection(self, mock_plugin_config):
        """Test shutdown closes the socket connection."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        plugin._writer = mock_writer
        plugin._reader = AsyncMock()
        plugin._connected = True

        await plugin.shutdown()

        mock_writer.close.assert_called_once()
        assert plugin._writer is None
        assert plugin._reader is None
        assert plugin._connected is False

    @pytest.mark.asyncio
    async def test_shutdown_no_connection(self, mock_plugin_config):
        """Test shutdown handles case when not connected."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)

        # Should not raise
        await plugin.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self, mock_plugin_config):
        """Test shutdown can be called multiple times safely."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        plugin._writer = mock_writer
        plugin._reader = AsyncMock()
        plugin._connected = True

        await plugin.shutdown()
        await plugin.shutdown()  # Second call should not raise

        # close should only be called once
        mock_writer.close.assert_called_once()


class TestUnixSocketExternalPluginReconnect:
    """Tests for reconnection logic in UnixSocketExternalPlugin."""

    @pytest.mark.asyncio
    async def test_reconnect_success_after_failure(self, mock_plugin_config):
        """Test reconnection succeeds after initial failure."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        # First attempt fails, second succeeds
        with patch(
            "asyncio.open_unix_connection",
            side_effect=[OSError("Connection refused"), (mock_reader, mock_writer)],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await plugin._reconnect()

        assert plugin._connected is True

    @pytest.mark.asyncio
    async def test_reconnect_all_attempts_fail(self, mock_plugin_config):
        """Test reconnection raises after all attempts fail."""
        plugin = UnixSocketExternalPlugin(mock_plugin_config)

        with patch("asyncio.open_unix_connection", side_effect=OSError("Connection refused")):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(PluginError, match="Failed to reconnect"):
                    await plugin._reconnect()
