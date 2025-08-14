# -*- coding: utf-8 -*-
"""Unit tests for the MCP reverse proxy module."""

# Standard
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.reverse_proxy import (
    ConnectionState,
    MessageType,
    ReverseProxyClient,
    StdioProcess,
    parse_args,
    ENV_GATEWAY,
    ENV_TOKEN,
)


class TestStdioProcess(unittest.TestCase):
    """Test cases for StdioProcess class."""

    def setUp(self):
        """Set up test fixtures."""
        self.command = "echo hello"
        self.stdio = StdioProcess(self.command)

    def test_init(self):
        """Test StdioProcess initialization."""
        assert self.stdio.command == self.command
        assert self.stdio.process is None
        assert self.stdio._stdout_reader_task is None
        assert self.stdio._message_handlers == []

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping stdio process."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            # Mock process
            mock_process = AsyncMock()
            mock_process.pid = 12345
            mock_process.stdin = AsyncMock()
            mock_process.stdout = AsyncMock()
            mock_process.stderr = None
            mock_process.returncode = None
            mock_create.return_value = mock_process

            # Start process
            await self.stdio.start()

            assert self.stdio.process is not None
            assert self.stdio._stdout_reader_task is not None
            mock_create.assert_called_once()

            # Stop process
            await self.stdio.stop()
            mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message(self):
        """Test sending message to subprocess."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            # Mock process
            mock_process = AsyncMock()
            mock_process.stdin = AsyncMock()
            mock_process.stdout = AsyncMock()
            mock_create.return_value = mock_process

            await self.stdio.start()

            # Send message
            message = '{"jsonrpc": "2.0", "id": 1, "method": "test"}'
            await self.stdio.send(message)

            mock_process.stdin.write.assert_called_once()
            mock_process.stdin.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_without_start(self):
        """Test sending message without starting process."""
        with pytest.raises(RuntimeError, match="Subprocess not running"):
            await self.stdio.send("test")

    def test_add_message_handler(self):
        """Test adding message handler."""
        handler = Mock()
        self.stdio.add_message_handler(handler)
        assert handler in self.stdio._message_handlers


class TestReverseProxyClient(unittest.TestCase):
    """Test cases for ReverseProxyClient class."""

    def setUp(self):
        """Set up test fixtures."""
        self.gateway_url = "wss://gateway.example.com"
        self.local_command = "uvx mcp-server-git"
        self.token = "test-token"
        self.client = ReverseProxyClient(
            gateway_url=self.gateway_url,
            local_command=self.local_command,
            token=self.token,
        )

    def test_init(self):
        """Test ReverseProxyClient initialization."""
        assert self.client.gateway_url == self.gateway_url
        assert self.client.local_command == self.local_command
        assert self.client.token == self.token
        assert self.client.state == ConnectionState.DISCONNECTED
        assert self.client.use_websocket is True
        assert self.client.connection is None

    def test_init_http_url(self):
        """Test initialization with HTTP URL."""
        client = ReverseProxyClient(
            gateway_url="https://gateway.example.com",
            local_command="echo test",
        )
        assert client.use_websocket is True

    @pytest.mark.asyncio
    async def test_connect_websocket(self):
        """Test WebSocket connection."""
        with patch("mcpgateway.reverse_proxy.websockets") as mock_ws:
            mock_ws.connect = AsyncMock()
            mock_connection = AsyncMock()
            mock_ws.connect.return_value = mock_connection

            with patch.object(self.client.stdio_process, "start", AsyncMock()):
                with patch.object(self.client, "_register", AsyncMock()):
                    await self.client.connect()

            assert self.client.state == ConnectionState.CONNECTED
            assert self.client.connection is not None
            mock_ws.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_when_already_connected(self):
        """Test connecting when already connected."""
        self.client.state = ConnectionState.CONNECTED
        with patch("mcpgateway.reverse_proxy.websockets"):
            await self.client.connect()
            # Should return early without attempting connection

    @pytest.mark.asyncio
    async def test_send_to_gateway(self):
        """Test sending message to gateway."""
        self.client.connection = AsyncMock()
        self.client.use_websocket = True

        message = '{"type": "heartbeat"}'
        await self.client._send_to_gateway(message)

        self.client.connection.send.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_to_gateway_not_connected(self):
        """Test sending when not connected."""
        with pytest.raises(RuntimeError, match="Not connected to gateway"):
            await self.client._send_to_gateway("test")

    @pytest.mark.asyncio
    async def test_handle_stdio_message(self):
        """Test handling message from stdio."""
        self.client.connection = AsyncMock()

        # Mock JSON-RPC response
        message = '{"jsonrpc": "2.0", "id": 1, "result": "test"}'
        await self.client._handle_stdio_message(message)

        # Should wrap and forward to gateway
        self.client.connection.send.assert_called_once()
        sent_data = json.loads(self.client.connection.send.call_args[0][0])
        assert sent_data["type"] == MessageType.RESPONSE.value
        assert sent_data["payload"]["id"] == 1

    @pytest.mark.asyncio
    async def test_handle_gateway_message_request(self):
        """Test handling request from gateway."""
        with patch.object(self.client.stdio_process, "send", AsyncMock()) as mock_send:
            message = json.dumps({
                "type": MessageType.REQUEST.value,
                "payload": {"jsonrpc": "2.0", "id": 1, "method": "test"}
            })

            await self.client._handle_gateway_message(message)

            mock_send.assert_called_once()
            sent_payload = json.loads(mock_send.call_args[0][0])
            assert sent_payload["method"] == "test"

    @pytest.mark.asyncio
    async def test_handle_gateway_message_heartbeat(self):
        """Test handling heartbeat from gateway."""
        self.client.connection = AsyncMock()

        message = json.dumps({
            "type": MessageType.HEARTBEAT.value
        })

        await self.client._handle_gateway_message(message)

        # Should respond with heartbeat
        self.client.connection.send.assert_called_once()
        sent_data = json.loads(self.client.connection.send.call_args[0][0])
        assert sent_data["type"] == MessageType.HEARTBEAT.value

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnection."""
        self.client.state = ConnectionState.CONNECTED
        self.client.connection = AsyncMock()
        self.client._keepalive_task = AsyncMock()
        self.client._receive_task = AsyncMock()

        with patch.object(self.client.stdio_process, "stop", AsyncMock()):
            await self.client.disconnect()

        assert self.client.state == ConnectionState.DISCONNECTED
        self.client.connection.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_with_reconnect(self):
        """Test run with reconnection logic."""
        self.client.max_retries = 1

        with patch.object(self.client, "connect", AsyncMock()) as mock_connect:
            # Simulate connection failure then shutdown
            mock_connect.side_effect = [Exception("Connection failed")]
            self.client.state = ConnectionState.SHUTTING_DOWN

            await self.client.run_with_reconnect()

            assert self.client.retry_count == 1


class TestParseArgs(unittest.TestCase):
    """Test argument parsing."""

    def test_parse_minimal_args(self):
        """Test parsing minimal required arguments."""
        with patch.dict("os.environ", {ENV_GATEWAY: "https://gateway.example.com"}):
            args = parse_args(["--local-stdio", "echo test"])
            assert args.local_stdio == "echo test"
            assert args.gateway == "https://gateway.example.com"
            assert args.log_level == "INFO"

    def test_parse_all_args(self):
        """Test parsing all arguments."""
        args = parse_args([
            "--local-stdio", "uvx mcp-server-git",
            "--gateway", "wss://gateway.example.com",
            "--token", "secret-token",
            "--reconnect-delay", "2.0",
            "--max-retries", "5",
            "--keepalive", "60",
            "--log-level", "DEBUG",
        ])

        assert args.local_stdio == "uvx mcp-server-git"
        assert args.gateway == "wss://gateway.example.com"
        assert args.token == "secret-token"
        assert args.reconnect_delay == 2.0
        assert args.max_retries == 5
        assert args.keepalive == 60
        assert args.log_level == "DEBUG"

    def test_parse_verbose_flag(self):
        """Test verbose flag sets debug logging."""
        with patch.dict("os.environ", {ENV_GATEWAY: "https://gateway.example.com"}):
            args = parse_args(["--local-stdio", "echo test", "--verbose"])
            assert args.log_level == "DEBUG"

    def test_missing_gateway(self):
        """Test error when gateway not provided."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.exit") as mock_exit:
                with patch("sys.stderr"):
                    parse_args(["--local-stdio", "echo test"])
                    mock_exit.assert_called()

    def test_token_from_env(self):
        """Test reading token from environment."""
        with patch.dict("os.environ", {
            ENV_GATEWAY: "https://gateway.example.com",
            ENV_TOKEN: "env-token"
        }):
            args = parse_args(["--local-stdio", "echo test"])
            assert args.token == "env-token"


class TestConnectionState(unittest.TestCase):
    """Test ConnectionState enum."""

    def test_connection_states(self):
        """Test all connection states are defined."""
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.RECONNECTING.value == "reconnecting"
        assert ConnectionState.SHUTTING_DOWN.value == "shutting_down"


class TestMessageType(unittest.TestCase):
    """Test MessageType enum."""

    def test_message_types(self):
        """Test all message types are defined."""
        assert MessageType.REGISTER.value == "register"
        assert MessageType.UNREGISTER.value == "unregister"
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.ERROR.value == "error"
        assert MessageType.REQUEST.value == "request"
        assert MessageType.RESPONSE.value == "response"
        assert MessageType.NOTIFICATION.value == "notification"


if __name__ == "__main__":
    unittest.main()
