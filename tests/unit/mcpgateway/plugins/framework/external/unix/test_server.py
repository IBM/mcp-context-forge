# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/unix/test_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for Unix socket plugin server.
Tests for UnixSocketPluginServer message handling.
"""

# Standard
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# Check if grpc/protobuf is available
try:
    # Third-Party
    from google.protobuf import json_format
    from google.protobuf.struct_pb2 import Struct
    #First-Party
    from mcpgateway.plugins.framework.external.grpc.proto import plugin_service_pb2
    from mcpgateway.plugins.framework.external.unix.server.server import UnixSocketPluginServer

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False
    json_format = None  # type: ignore
    Struct = None  # type: ignore

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed (required for protobuf)")

# First-Party
from mcpgateway.plugins.framework.models import GlobalContext, PluginContext


@pytest.fixture
def mock_plugin_server():
    """Create a mock ExternalPluginServer for testing."""
    mock_server = AsyncMock()
    mock_server.get_plugin_configs = AsyncMock(return_value=[])
    mock_server.get_plugin_config = AsyncMock(return_value=None)
    mock_server.invoke_hook = AsyncMock(return_value={"result": {"continue_processing": True}})
    mock_server.shutdown = AsyncMock()
    return mock_server


@pytest.fixture
def server(tmp_path, mock_plugin_server):
    """Create a UnixSocketPluginServer for testing."""
    socket_path = str(tmp_path / "test.sock")
    srv = UnixSocketPluginServer(
        config_path="tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml",
        socket_path=socket_path,
    )
    srv._plugin_server = mock_plugin_server
    return srv


class TestUnixSocketPluginServerProperties:
    """Tests for UnixSocketPluginServer properties."""

    def test_socket_path(self, server):
        """Test socket_path property returns correct path."""
        assert server.socket_path.endswith("test.sock")

    def test_running_initially_false(self, server):
        """Test running property is False initially."""
        assert server.running is False


class TestUnixSocketPluginServerHandleMessage:
    """Tests for UnixSocketPluginServer._handle_message."""

    @pytest.mark.asyncio
    async def test_handle_invoke_hook_request(self, server, mock_plugin_server):
        """Test handling InvokeHookRequest message."""
        # Build request
        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)

        request.context.global_context.request_id = "test-request"
        request.context.global_context.server_id = "test-server"

        response_bytes = await server._handle_message(request.SerializeToString())

        # Parse response
        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("result")
        mock_plugin_server.invoke_hook.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_get_plugin_config_request_found(self, server, mock_plugin_server):
        """Test handling GetPluginConfigRequest when plugin is found."""
        mock_plugin_server.get_plugin_config = AsyncMock(
            return_value={
                "name": "TestPlugin",
                "kind": "test.plugin.TestPlugin",
                "hooks": ["tool_pre_invoke"],
            }
        )

        request = plugin_service_pb2.GetPluginConfigRequest(name="TestPlugin")
        response_bytes = await server._handle_message(request.SerializeToString())

        response = plugin_service_pb2.GetPluginConfigResponse()
        response.ParseFromString(response_bytes)

        assert response.found is True
        config_dict = json_format.MessageToDict(response.config)
        assert config_dict["name"] == "TestPlugin"

    @pytest.mark.asyncio
    async def test_handle_get_plugin_config_request_not_found(self, server, mock_plugin_server):
        """Test handling GetPluginConfigRequest when plugin is not found."""
        mock_plugin_server.get_plugin_config = AsyncMock(return_value=None)

        request = plugin_service_pb2.GetPluginConfigRequest(name="NonExistent")
        response_bytes = await server._handle_message(request.SerializeToString())

        response = plugin_service_pb2.GetPluginConfigResponse()
        response.ParseFromString(response_bytes)

        assert response.found is False

    @pytest.mark.asyncio
    async def test_handle_get_plugin_configs_request(self, server, mock_plugin_server):
        """Test handling GetPluginConfigsRequest."""
        mock_plugin_server.get_plugin_configs = AsyncMock(
            return_value=[
                {"name": "Plugin1", "kind": "test.Plugin1", "hooks": ["tool_pre_invoke"]},
                {"name": "Plugin2", "kind": "test.Plugin2", "hooks": ["prompt_pre_fetch"]},
            ]
        )

        request = plugin_service_pb2.GetPluginConfigsRequest()
        response_bytes = await server._handle_message(request.SerializeToString())

        response = plugin_service_pb2.GetPluginConfigsResponse()
        response.ParseFromString(response_bytes)

        assert len(response.configs) == 2


class TestUnixSocketPluginServerInvokeHook:
    """Tests for UnixSocketPluginServer._handle_invoke_hook."""

    @pytest.mark.asyncio
    async def test_invoke_hook_success(self, server, mock_plugin_server):
        """Test successful hook invocation returns result."""
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={
                "result": {
                    "continue_processing": True,
                    "modified_payload": None,
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

        response_bytes = await server._handle_invoke_hook(request)

        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("result")
        result_dict = json_format.MessageToDict(response.result)
        assert result_dict.get("continueProcessing") is True or result_dict.get("continue_processing") is True

    @pytest.mark.asyncio
    async def test_invoke_hook_with_error(self, server, mock_plugin_server):
        """Test hook invocation error is returned in response."""
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

        response_bytes = await server._handle_invoke_hook(request)

        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("error")
        # The error message contains the PluginError string representation
        assert "Processing failed" in response.error.message

    @pytest.mark.asyncio
    async def test_invoke_hook_with_context_update(self, server, mock_plugin_server):
        """Test hook invocation includes context updates."""
        result_context = PluginContext(
            global_context=GlobalContext(request_id="test", server_id="test"),
            state={"updated_key": "updated_value"},
        )
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={
                "result": {"continue_processing": True},
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

        response_bytes = await server._handle_invoke_hook(request)

        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("context")

    @pytest.mark.asyncio
    async def test_invoke_hook_unexpected_error(self, server, mock_plugin_server):
        """Test hook invocation handles unexpected exceptions."""
        mock_plugin_server.invoke_hook = AsyncMock(side_effect=RuntimeError("Unexpected error"))

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)

        request.context.global_context.request_id = "test-request"
        request.context.global_context.server_id = "test-server"

        response_bytes = await server._handle_invoke_hook(request)

        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("error")
        assert "Unexpected error" in response.error.message


class TestUnixSocketPluginServerLifecycle:
    """Tests for UnixSocketPluginServer start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_socket(self):
        """Test start creates the Unix socket."""
        import os
        import uuid

        # Use /tmp directly to avoid path length issues on macOS
        short_id = uuid.uuid4().hex[:8]
        socket_path = f"/tmp/unix-lifecycle-{short_id}.sock"

        try:
            server = UnixSocketPluginServer(
                config_path="tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml",
                socket_path=socket_path,
            )

            with patch.object(server, "_plugin_server", AsyncMock()):
                server._plugin_server.initialize = AsyncMock()
                await server.start()

                assert server.running is True
                assert os.path.exists(socket_path)

                await server.stop()
        finally:
            if os.path.exists(socket_path):
                os.unlink(socket_path)

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self):
        """Test stop cleans up resources."""
        import os
        import uuid

        # Use /tmp directly to avoid path length issues on macOS
        short_id = uuid.uuid4().hex[:8]
        socket_path = f"/tmp/unix-cleanup-{short_id}.sock"

        try:
            server = UnixSocketPluginServer(
                config_path="tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml",
                socket_path=socket_path,
            )

            with patch.object(server, "_plugin_server", AsyncMock()):
                server._plugin_server.initialize = AsyncMock()
                server._plugin_server.shutdown = AsyncMock()
                await server.start()
                await server.stop()

                assert server.running is False
                # Socket file should be cleaned up
                assert not os.path.exists(socket_path)
        finally:
            if os.path.exists(socket_path):
                os.unlink(socket_path)

    @pytest.mark.asyncio
    async def test_serve_forever_requires_start(self, server):
        """Test serve_forever raises if server not started."""
        with pytest.raises(RuntimeError, match="Server not started"):
            await server.serve_forever()

    @pytest.mark.asyncio
    async def test_start_removes_existing_socket(self, tmp_path):
        """Test start removes existing socket file before creating new one."""
        import uuid

        short_id = uuid.uuid4().hex[:8]
        socket_path = f"/tmp/unix-existing-{short_id}.sock"

        try:
            # Create an existing file at the socket path
            with open(socket_path, "w") as f:
                f.write("old socket")
            assert os.path.exists(socket_path)

            server = UnixSocketPluginServer(
                config_path="tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml",
                socket_path=socket_path,
            )

            with patch.object(server, "_plugin_server", AsyncMock()):
                server._plugin_server.initialize = AsyncMock()
                await server.start()

                # Old file should have been replaced
                assert server.running is True
                await server.stop()
        finally:
            if os.path.exists(socket_path):
                os.unlink(socket_path)

    @pytest.mark.asyncio
    async def test_stop_handles_socket_cleanup_error(self, tmp_path):
        """Test stop handles errors during socket file cleanup."""
        import uuid

        short_id = uuid.uuid4().hex[:8]
        socket_path = f"/tmp/unix-cleanup-err-{short_id}.sock"

        try:
            server = UnixSocketPluginServer(
                config_path="tests/unit/mcpgateway/plugins/fixtures/configs/valid_single_plugin.yaml",
                socket_path=socket_path,
            )

            with patch.object(server, "_plugin_server", AsyncMock()):
                server._plugin_server.initialize = AsyncMock()
                server._plugin_server.shutdown = AsyncMock()
                await server.start()

                # Remove the socket file before stop so unlink fails gracefully
                if os.path.exists(socket_path):
                    os.unlink(socket_path)

                # Re-create as a read-only dir to cause OSError on unlink
                os.makedirs(socket_path, exist_ok=True)

                # Should not raise
                await server.stop()
                assert server.running is False
        finally:
            if os.path.exists(socket_path):
                if os.path.isdir(socket_path):
                    os.rmdir(socket_path)
                else:
                    os.unlink(socket_path)

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """Test stop is safe when server was never started."""
        server = UnixSocketPluginServer(
            config_path="test.yaml",
            socket_path="/tmp/nonexistent.sock",
        )
        # Should not raise
        await server.stop()
        assert server.running is False


class TestUnixSocketPluginServerHandleClient:
    """Tests for UnixSocketPluginServer._handle_client."""

    @pytest.mark.asyncio
    async def test_handle_client_timeout(self, server, mock_plugin_server):
        """Test _handle_client handles timeout gracefully."""
        from mcpgateway.plugins.framework.external.unix.protocol import ProtocolError

        server._running = True

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value="test-peer")
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.server.read_message",
            side_effect=asyncio.TimeoutError(),
        ):
            await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_client_incomplete_read(self, server, mock_plugin_server):
        """Test _handle_client handles client disconnect."""
        server._running = True

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value="test-peer")
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.server.read_message",
            side_effect=asyncio.IncompleteReadError(b"", 4),
        ):
            await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_client_protocol_error(self, server, mock_plugin_server):
        """Test _handle_client handles protocol errors."""
        from mcpgateway.plugins.framework.external.unix.protocol import ProtocolError

        server._running = True

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value="test-peer")
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.server.read_message",
            side_effect=ProtocolError("Bad message"),
        ):
            await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_client_write_error(self, server, mock_plugin_server):
        """Test _handle_client handles write errors during response."""
        server._running = True

        # First read succeeds, write fails
        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"
        request.context.global_context.request_id = "test"

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value="test-peer")
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        read_call_count = 0

        async def mock_read(*args, **kwargs):
            nonlocal read_call_count
            read_call_count += 1
            if read_call_count == 1:
                return request.SerializeToString()
            raise asyncio.IncompleteReadError(b"", 4)

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.server.read_message",
            side_effect=mock_read,
        ):
            with patch(
                "mcpgateway.plugins.framework.external.unix.server.server.write_message_async",
                side_effect=BrokenPipeError("Broken pipe"),
            ):
                await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_client_unexpected_exception(self, server, mock_plugin_server):
        """Test _handle_client handles unexpected exceptions."""
        server._running = True

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value="test-peer")
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.server.read_message",
            side_effect=RuntimeError("Unexpected"),
        ):
            await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called_once()


class TestUnixSocketPluginServerMessageHandling:
    """Additional message handling tests for edge cases."""

    @pytest.mark.asyncio
    async def test_handle_message_unknown_type(self, server):
        """Test _handle_message returns error for unknown message type."""
        # Send some random bytes that don't match any known message type
        data = b"\x99\x99\x99\x99\x99\x99\x99\x99\x99\x99"

        response_bytes = await server._handle_message(data)
        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("error")
        assert "Unknown message type" in response.error.message

    @pytest.mark.asyncio
    async def test_handle_invoke_hook_with_error_dict(self, server, mock_plugin_server):
        """Test _handle_invoke_hook handles error as raw dict."""
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={
                "error": {
                    "message": "Raw error",
                    "plugin_name": "TestPlugin",
                    "code": "ERR",
                    "mcp_error_code": -32603,
                }
            }
        )

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)
        request.context.global_context.request_id = "test"

        response_bytes = await server._handle_invoke_hook(request)
        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("error")
        assert response.error.message == "Raw error"

    @pytest.mark.asyncio
    async def test_handle_invoke_hook_with_error_model(self, server, mock_plugin_server):
        """Test _handle_invoke_hook handles error as Pydantic model."""
        from mcpgateway.plugins.framework.models import PluginErrorModel

        error_model = PluginErrorModel(
            message="Model error",
            plugin_name="TestPlugin",
            code="MODEL_ERR",
        )
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={"error": error_model}
        )

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)
        request.context.global_context.request_id = "test"

        response_bytes = await server._handle_invoke_hook(request)
        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("error")
        assert response.error.message == "Model error"

    @pytest.mark.asyncio
    async def test_handle_invoke_hook_with_dict_context(self, server, mock_plugin_server):
        """Test _handle_invoke_hook handles context as plain dict."""
        mock_plugin_server.invoke_hook = AsyncMock(
            return_value={
                "result": {"continue_processing": True},
                "context": {
                    "global_context": {"request_id": "req-1", "server_id": "srv-1"},
                    "state": {"updated": True},
                },
            }
        )

        request = plugin_service_pb2.InvokeHookRequest()
        request.hook_type = "tool_pre_invoke"
        request.plugin_name = "TestPlugin"

        payload_struct = Struct()
        json_format.ParseDict({"name": "test_tool", "args": {}}, payload_struct)
        request.payload.CopyFrom(payload_struct)
        request.context.global_context.request_id = "test"

        response_bytes = await server._handle_invoke_hook(request)
        response = plugin_service_pb2.InvokeHookResponse()
        response.ParseFromString(response_bytes)

        assert response.HasField("context")

    @pytest.mark.asyncio
    async def test_handle_get_plugin_config_exception(self, server, mock_plugin_server):
        """Test _handle_get_plugin_config handles exceptions."""
        mock_plugin_server.get_plugin_config = AsyncMock(
            side_effect=RuntimeError("DB error")
        )

        request = plugin_service_pb2.GetPluginConfigRequest(name="TestPlugin")
        response_bytes = await server._handle_get_plugin_config(request)

        response = plugin_service_pb2.GetPluginConfigResponse()
        response.ParseFromString(response_bytes)

        assert response.found is False

    @pytest.mark.asyncio
    async def test_handle_get_plugin_configs_exception(self, server, mock_plugin_server):
        """Test _handle_get_plugin_configs handles exceptions."""
        mock_plugin_server.get_plugin_configs = AsyncMock(
            side_effect=RuntimeError("DB error")
        )

        request = plugin_service_pb2.GetPluginConfigsRequest()
        response_bytes = await server._handle_get_plugin_configs(request)

        response = plugin_service_pb2.GetPluginConfigsResponse()
        response.ParseFromString(response_bytes)

        assert len(response.configs) == 0


class TestUnixSocketRunServer:
    """Tests for the run_server function."""

    @pytest.mark.asyncio
    async def test_run_server_lifecycle(self, tmp_path):
        """Test run_server starts server and waits for signal."""
        from mcpgateway.plugins.framework.external.unix.server.server import run_server

        socket_path = str(tmp_path / "test.sock")

        mock_server = AsyncMock()
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()

        stop_event = asyncio.Event()
        stop_event.set()  # Immediately signal to stop

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.server.UnixSocketPluginServer",
            return_value=mock_server,
        ):
            with patch(
                "mcpgateway.plugins.framework.external.unix.server.server.asyncio.Event",
                return_value=stop_event,
            ):
                with patch("builtins.print"):
                    await run_server(
                        config_path="test.yaml",
                        socket_path=socket_path,
                    )

        mock_server.start.assert_called_once()
        mock_server.stop.assert_called_once()
