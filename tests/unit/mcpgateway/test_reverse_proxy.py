# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_reverse_proxy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the MCP reverse proxy module.
"""

# Standard
import asyncio
import json
import os
import signal
import sys
from unittest.mock import AsyncMock, call, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.reverse_proxy import (
    ConnectionState,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RECONNECT_DELAY,
    DEFAULT_REQUEST_TIMEOUT,
    ENV_GATEWAY,
    ENV_LOG_LEVEL,
    ENV_MAX_RETRIES,
    ENV_RECONNECT_DELAY,
    ENV_TOKEN,
    main,
    MessageType,
    parse_args,
    ReverseProxyClient,
    run,
    StdioProcess,
)


class TestStdioProcess:
    """Test cases for StdioProcess class."""

    def setup_method(self):
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
    async def test_start_success(self):
        """Test successful process start."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = AsyncMock()
            mock_process.pid = 12345
            mock_process.stdin = AsyncMock()
            mock_process.stdout = AsyncMock()
            mock_create.return_value = mock_process

            await self.stdio.start()

            assert self.stdio.process is not None
            assert self.stdio._stdout_reader_task is not None
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_no_stdin(self):
        """Test start failure when no stdin."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = AsyncMock()
            mock_process.stdin = None
            mock_process.stdout = AsyncMock()
            mock_create.return_value = mock_process

            with pytest.raises(RuntimeError, match="Failed to create subprocess with stdio"):
                await self.stdio.start()

    @pytest.mark.asyncio
    async def test_start_no_stdout(self):
        """Test start failure when no stdout."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = AsyncMock()
            mock_process.stdin = AsyncMock()
            mock_process.stdout = None
            mock_create.return_value = mock_process

            with pytest.raises(RuntimeError, match="Failed to create subprocess with stdio"):
                await self.stdio.start()

    @pytest.mark.asyncio
    async def test_stop_graceful(self):
        """Test graceful process stop."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = AsyncMock()
            mock_process.pid = 12345
            mock_process.stdin = AsyncMock()
            mock_process.stdout = AsyncMock()
            mock_process.returncode = 0
            mock_create.return_value = mock_process

            await self.stdio.start()
            await self.stdio.stop()

            mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_force_kill(self):
        """Test force kill when process doesn't terminate."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                mock_process = AsyncMock()
                mock_process.pid = 12345
                mock_process.stdin = AsyncMock()
                mock_process.stdout = AsyncMock()
                mock_process.returncode = None
                mock_create.return_value = mock_process

                await self.stdio.start()
                await self.stdio.stop()

                mock_process.terminate.assert_called_once()
                mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_no_process(self):
        """Test stop when no process running."""
        await self.stdio.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_send_message(self):
        """Test sending message to subprocess."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = AsyncMock()
            mock_process.stdin = AsyncMock()
            mock_process.stdout = AsyncMock()
            mock_create.return_value = mock_process

            await self.stdio.start()

            message = '{"jsonrpc": "2.0", "id": 1, "method": "test"}'
            await self.stdio.send(message)

            mock_process.stdin.write.assert_called_once_with((message + "\n").encode())
            mock_process.stdin.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_without_start(self):
        """Test sending message without starting process."""
        with pytest.raises(RuntimeError, match="Subprocess not running"):
            await self.stdio.send("test")

    @pytest.mark.asyncio
    async def test_send_no_stdin(self):
        """Test sending when stdin is None."""
        self.stdio.process = AsyncMock()
        self.stdio.process.stdin = None

        with pytest.raises(RuntimeError, match="Subprocess not running"):
            await self.stdio.send("test")

    def test_add_message_handler(self):
        """Test adding message handler."""
        handler = Mock()
        self.stdio.add_message_handler(handler)
        assert handler in self.stdio._message_handlers

    @pytest.mark.asyncio
    async def test_read_stdout_messages(self):
        """Test reading messages from stdout."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = AsyncMock()
            mock_process.stdin = AsyncMock()
            mock_process.stdout = AsyncMock()
            mock_create.return_value = mock_process

            # Mock readline to return messages then EOF
            mock_process.stdout.readline.side_effect = [
                b'{"test": "message1"}\n',
                b'{"test": "message2"}\n',
                b'',  # EOF
            ]

            handler = AsyncMock()
            self.stdio.add_message_handler(handler)

            await self.stdio.start()
            # Wait a bit for the reader task to process messages
            await asyncio.sleep(0.1)
            await self.stdio.stop()

            # Verify handler was called with messages
            assert handler.call_count == 2
            handler.assert_has_calls([
                call('{"test": "message1"}'),
                call('{"test": "message2"}')
            ])

    @pytest.mark.asyncio
    async def test_read_stdout_handler_error(self):
        """Test error handling in message handlers."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = AsyncMock()
            mock_process.stdin = AsyncMock()
            mock_process.stdout = AsyncMock()
            mock_create.return_value = mock_process

            mock_process.stdout.readline.side_effect = [
                b'{"test": "message"}\n',
                b'',  # EOF
            ]

            # Handler that raises exception
            handler = AsyncMock(side_effect=Exception("Handler error"))
            self.stdio.add_message_handler(handler)

            await self.stdio.start()
            await asyncio.sleep(0.1)
            await self.stdio.stop()

            handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_stdout_cancelled(self):
        """Test cancellation of stdout reader."""
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = AsyncMock()
            mock_process.stdin = AsyncMock()
            mock_process.stdout = AsyncMock()
            mock_create.return_value = mock_process

            # Mock readline to block indefinitely
            mock_process.stdout.readline = AsyncMock(side_effect=asyncio.CancelledError())

            await self.stdio.start()
            # Stop should cancel the reader task
            await self.stdio.stop()


class TestReverseProxyClient:
    """Test cases for ReverseProxyClient class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.gateway_url = "wss://gateway.example.com"
        self.local_command = "uvx mcp-server-git"
        self.token = "test-token"
        self.client = ReverseProxyClient(
            gateway_url=self.gateway_url,
            local_command=self.local_command,
            token=self.token,
        )

    def test_init_websocket_urls(self):
        """Test initialization with various WebSocket URLs."""
        test_cases = [
            ("ws://example.com", True),
            ("wss://example.com", True),
            ("http://example.com", True),
            ("https://example.com", True),
            ("tcp://example.com", False),
        ]

        for url, expected in test_cases:
            client = ReverseProxyClient(gateway_url=url, local_command="echo test")
            assert client.use_websocket == expected

    def test_init_defaults(self):
        """Test initialization with default values."""
        client = ReverseProxyClient(
            gateway_url="wss://example.com",
            local_command="echo test"
        )
        assert client.token is None
        assert client.reconnect_delay == DEFAULT_RECONNECT_DELAY
        assert client.max_retries == DEFAULT_MAX_RETRIES
        assert client.keepalive_interval == DEFAULT_KEEPALIVE_INTERVAL
        assert client.state == ConnectionState.DISCONNECTED
        assert client.connection is None
        assert client.retry_count == 0

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        client = ReverseProxyClient(
            gateway_url="wss://example.com",
            local_command="echo test",
            token="custom-token",
            reconnect_delay=5.0,
            max_retries=10,
            keepalive_interval=60
        )
        assert client.token == "custom-token"
        assert client.reconnect_delay == 5.0
        assert client.max_retries == 10
        assert client.keepalive_interval == 60

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """Test connecting when already connected."""
        self.client.state = ConnectionState.CONNECTED
        await self.client.connect()
        # Should return early without changing state
        assert self.client.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_websocket_success(self):
        """Test successful WebSocket connection."""
        with patch("mcpgateway.reverse_proxy.websockets") as mock_ws:
            mock_connection = AsyncMock()
            mock_ws.connect = AsyncMock(return_value=mock_connection)

            with patch.object(self.client.stdio_process, "start", AsyncMock()):
                with patch.object(self.client, "_register", AsyncMock()):
                    with patch("asyncio.create_task") as mock_create_task:
                        await self.client.connect()

            assert self.client.state == ConnectionState.CONNECTED
            assert self.client.connection == mock_connection
            assert self.client.retry_count == 0
            mock_ws.connect.assert_called_once()
            mock_create_task.assert_called()  # keepalive task

    @pytest.mark.asyncio
    async def test_connect_websocket_failure(self):
        """Test WebSocket connection failure."""
        with patch("mcpgateway.reverse_proxy.websockets") as mock_ws:
            mock_ws.connect = AsyncMock(side_effect=Exception("Connection failed"))

            with patch.object(self.client.stdio_process, "start", AsyncMock()):
                with pytest.raises(Exception, match="Connection failed"):
                    await self.client.connect()

            assert self.client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_websocket_no_websockets_module(self):
        """Test WebSocket connection when websockets module not available."""
        with patch("mcpgateway.reverse_proxy.websockets", None):
            with patch.object(self.client.stdio_process, "start", AsyncMock()):
                with pytest.raises(ImportError, match="websockets package required"):
                    await self.client._connect_websocket()

    @pytest.mark.asyncio
    async def test_connect_sse_not_implemented(self):
        """Test SSE connection raises NotImplementedError."""
        with patch("mcpgateway.reverse_proxy.httpx", None):
            with pytest.raises(ImportError, match="httpx package required"):
                await self.client._connect_sse()

        with patch("mcpgateway.reverse_proxy.httpx", MagicMock()):
            with pytest.raises(NotImplementedError, match="SSE transport not yet implemented"):
                await self.client._connect_sse()

    @pytest.mark.asyncio
    async def test_send_to_gateway_websocket(self):
        """Test sending message via WebSocket."""
        self.client.connection = AsyncMock()
        self.client.use_websocket = True

        message = '{"type": "heartbeat"}'
        await self.client._send_to_gateway(message)

        self.client.connection.send.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_to_gateway_sse_not_implemented(self):
        """Test sending message via SSE raises NotImplementedError."""
        self.client.connection = AsyncMock()
        self.client.use_websocket = False

        with pytest.raises(NotImplementedError, match="SSE transport not yet implemented"):
            await self.client._send_to_gateway("test")

    @pytest.mark.asyncio
    async def test_send_to_gateway_not_connected(self):
        """Test sending when not connected."""
        with pytest.raises(RuntimeError, match="Not connected to gateway"):
            await self.client._send_to_gateway("test")

    @pytest.mark.asyncio
    async def test_register(self):
        """Test registration with gateway."""
        self.client.connection = AsyncMock()

        with patch.object(self.client.stdio_process, "send", AsyncMock()) as mock_send:
            with patch("asyncio.sleep", AsyncMock()):
                await self.client._register()

        # Should send initialize to local server
        mock_send.assert_called_once()
        init_msg = json.loads(mock_send.call_args[0][0])
        assert init_msg["method"] == "initialize"

        # Should send register to gateway
        self.client.connection.send.assert_called_once()
        register_msg = json.loads(self.client.connection.send.call_args[0][0])
        assert register_msg["type"] == MessageType.REGISTER.value
        assert register_msg["sessionId"] == self.client.session_id

    @pytest.mark.asyncio
    async def test_handle_stdio_message_response(self):
        """Test handling JSON-RPC response from stdio."""
        self.client.connection = AsyncMock()

        message = '{"jsonrpc": "2.0", "id": 1, "result": "test"}'
        await self.client._handle_stdio_message(message)

        self.client.connection.send.assert_called_once()
        sent_data = json.loads(self.client.connection.send.call_args[0][0])
        assert sent_data["type"] == MessageType.RESPONSE.value
        assert sent_data["payload"]["id"] == 1

    @pytest.mark.asyncio
    async def test_handle_stdio_message_notification(self):
        """Test handling JSON-RPC notification from stdio."""
        self.client.connection = AsyncMock()

        message = '{"jsonrpc": "2.0", "method": "notification"}'
        await self.client._handle_stdio_message(message)

        self.client.connection.send.assert_called_once()
        sent_data = json.loads(self.client.connection.send.call_args[0][0])
        assert sent_data["type"] == MessageType.NOTIFICATION.value
        assert "id" not in sent_data["payload"]

    @pytest.mark.asyncio
    async def test_handle_stdio_message_invalid_json(self):
        """Test handling invalid JSON from stdio."""
        self.client.connection = AsyncMock()

        message = 'invalid json'
        await self.client._handle_stdio_message(message)

        # Should not send anything to gateway
        self.client.connection.send.assert_not_called()

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

        message = json.dumps({"type": MessageType.HEARTBEAT.value})
        await self.client._handle_gateway_message(message)

        self.client.connection.send.assert_called_once()
        sent_data = json.loads(self.client.connection.send.call_args[0][0])
        assert sent_data["type"] == MessageType.HEARTBEAT.value
        assert sent_data["sessionId"] == self.client.session_id

    @pytest.mark.asyncio
    async def test_handle_gateway_message_error(self):
        """Test handling error message from gateway."""
        message = json.dumps({
            "type": MessageType.ERROR.value,
            "message": "Test error"
        })

        await self.client._handle_gateway_message(message)
        # Should log error but not crash

    @pytest.mark.asyncio
    async def test_handle_gateway_message_unknown_type(self):
        """Test handling unknown message type from gateway."""
        message = json.dumps({"type": "unknown"})
        await self.client._handle_gateway_message(message)
        # Should log warning but not crash

    @pytest.mark.asyncio
    async def test_handle_gateway_message_invalid_json(self):
        """Test handling invalid JSON from gateway."""
        message = "invalid json"
        await self.client._handle_gateway_message(message)
        # Should log error but not crash

    @pytest.mark.asyncio
    async def test_receive_websocket_messages(self):
        """Test receiving messages from WebSocket."""
        mock_connection = AsyncMock()
        mock_connection.__aiter__.return_value = [
            '{"type": "heartbeat"}',
            '{"type": "request", "payload": {"method": "test"}}'
        ]
        self.client.connection = mock_connection

        with patch.object(self.client, "_handle_gateway_message", AsyncMock()) as mock_handle:
            await self.client._receive_websocket()

        assert mock_handle.call_count == 2

    @pytest.mark.asyncio
    async def test_receive_websocket_connection_closed(self):
        """Test handling WebSocket connection closed."""
        mock_connection = AsyncMock()

        # Import the actual exception class
        try:
            # Third-Party
            from websockets.exceptions import ConnectionClosed
            mock_connection.__aiter__.side_effect = ConnectionClosed(None, None)
        except ImportError:
            # If websockets not available, use generic exception
            mock_connection.__aiter__.side_effect = Exception("Connection closed")

        self.client.connection = mock_connection
        self.client.state = ConnectionState.CONNECTED

        await self.client._receive_websocket()
        assert self.client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_receive_websocket_no_connection(self):
        """Test receive when no connection."""
        self.client.connection = None
        await self.client._receive_websocket()
        # Should return early

    @pytest.mark.asyncio
    async def test_keepalive_loop(self):
        """Test keepalive loop sends heartbeats."""
        self.client.state = ConnectionState.CONNECTED
        self.client.connection = AsyncMock()
        self.client.keepalive_interval = 0.1  # Fast for testing

        # Run keepalive for a short time
        keepalive_task = asyncio.create_task(self.client._keepalive_loop())
        await asyncio.sleep(0.25)  # Let it send a couple heartbeats
        keepalive_task.cancel()

        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass

        # Should have sent at least one heartbeat
        assert self.client.connection.send.call_count >= 1
        sent_data = json.loads(self.client.connection.send.call_args[0][0])
        assert sent_data["type"] == MessageType.HEARTBEAT.value

    @pytest.mark.asyncio
    async def test_keepalive_loop_send_failure(self):
        """Test keepalive loop handles send failures."""
        self.client.state = ConnectionState.CONNECTED
        self.client.connection = AsyncMock()
        self.client.connection.send.side_effect = Exception("Send failed")
        self.client.keepalive_interval = 0.1

        # Should exit loop on send failure
        await self.client._keepalive_loop()

    @pytest.mark.asyncio
    async def test_keepalive_loop_disconnected(self):
        """Test keepalive loop exits when disconnected."""
        self.client.state = ConnectionState.DISCONNECTED
        self.client.connection = AsyncMock()

        await self.client._keepalive_loop()
        # Should not send anything
        self.client.connection.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_full_cleanup(self):
        """Test full disconnect cleanup."""
        self.client.state = ConnectionState.CONNECTED
        self.client.connection = AsyncMock()
        self.client._keepalive_task = AsyncMock()
        self.client._receive_task = AsyncMock()

        with patch.object(self.client.stdio_process, "stop", AsyncMock()) as mock_stop:
            await self.client.disconnect()

        assert self.client.state == ConnectionState.DISCONNECTED
        self.client._keepalive_task.cancel.assert_called_once()
        self.client._receive_task.cancel.assert_called_once()
        self.client.connection.close.assert_called_once()
        mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_already_shutting_down(self):
        """Test disconnect when already shutting down."""
        self.client.state = ConnectionState.SHUTTING_DOWN
        await self.client.disconnect()
        # Should return early

    @pytest.mark.asyncio
    async def test_disconnect_send_unregister(self):
        """Test disconnect sends unregister message."""
        self.client.state = ConnectionState.CONNECTED
        self.client.connection = AsyncMock()

        with patch.object(self.client.stdio_process, "stop", AsyncMock()):
            await self.client.disconnect()

        # Should send unregister message
        self.client.connection.send.assert_called_once()
        sent_data = json.loads(self.client.connection.send.call_args[0][0])
        assert sent_data["type"] == MessageType.UNREGISTER.value

    @pytest.mark.asyncio
    async def test_disconnect_unregister_failure(self):
        """Test disconnect handles unregister send failure."""
        self.client.state = ConnectionState.CONNECTED
        self.client.connection = AsyncMock()
        self.client.connection.send.side_effect = Exception("Send failed")

        with patch.object(self.client.stdio_process, "stop", AsyncMock()):
            await self.client.disconnect()

        # Should still complete disconnect
        assert self.client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_run_with_reconnect_success(self):
        """Test successful run with reconnection."""
        self.client.max_retries = 2
        connect_count = 0

        async def mock_connect():
            nonlocal connect_count
            connect_count += 1
            if connect_count == 1:
                # First connection succeeds
                self.client.state = ConnectionState.CONNECTED
                # Simulate disconnection after a short time
                await asyncio.sleep(0.1)
                self.client.state = ConnectionState.DISCONNECTED
            else:
                # Second connection triggers shutdown
                self.client.state = ConnectionState.SHUTTING_DOWN

        with patch.object(self.client, "connect", side_effect=mock_connect):
            await self.client.run_with_reconnect()

        assert connect_count == 2

    @pytest.mark.asyncio
    async def test_run_with_reconnect_max_retries(self):
        """Test run with reconnection respects max retries."""
        self.client.max_retries = 2
        self.client.reconnect_delay = 0.01  # Fast for testing

        with patch.object(self.client, "connect", AsyncMock(side_effect=Exception("Connection failed"))):
            await self.client.run_with_reconnect()

        assert self.client.retry_count == 2

    @pytest.mark.asyncio
    async def test_run_with_reconnect_infinite_retries(self):
        """Test run with infinite retries."""
        self.client.max_retries = 0  # Infinite
        self.client.reconnect_delay = 0.01
        connect_count = 0

        async def mock_connect():
            nonlocal connect_count
            connect_count += 1
            if connect_count >= 3:
                self.client.state = ConnectionState.SHUTTING_DOWN
            else:
                raise Exception("Connection failed")

        with patch.object(self.client, "connect", side_effect=mock_connect):
            await self.client.run_with_reconnect()

        assert connect_count == 3
        assert self.client.retry_count >= 2

    @pytest.mark.asyncio
    async def test_run_with_reconnect_backoff(self):
        """Test reconnection backoff delay calculation."""
        self.client.max_retries = 3
        self.client.reconnect_delay = 1.0

        delays = []
        original_sleep = asyncio.sleep

        async def mock_sleep(delay):
            delays.append(delay)
            await original_sleep(0.01)  # Actually sleep briefly

        with patch.object(self.client, "connect", AsyncMock(side_effect=Exception("Connection failed"))):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                await self.client.run_with_reconnect()

        # Should have exponential backoff: 2, 4 (only 2 delays for 3 retries)
        assert len(delays) == 2
        assert delays[0] == 2.0  # 1 * 2^1
        assert delays[1] == 4.0  # 1 * 2^2


class TestParseArgs:
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

    def test_parse_config_file_yaml(self):
        """Test parsing with YAML config file."""
        config_content = """
gateway: https://config.example.com
token: config-token
reconnect_delay: 3.0
"""

        with patch("builtins.open", mock_open(read_data=config_content)):
            with patch("mcpgateway.reverse_proxy.yaml") as mock_yaml:
                mock_yaml.safe_load.return_value = {
                    "gateway": "https://config.example.com",
                    "token": "config-token",
                    "reconnect_delay": 3.0
                }

                # Need to provide gateway in environment since config loading happens after validation
                with patch.dict("os.environ", {"REVERSE_PROXY_GATEWAY": "https://config.example.com"}):
                    args = parse_args([
                        "--local-stdio", "echo test",
                        "--config", "config.yaml"
                    ])

                assert args.gateway == "https://config.example.com"
                assert args.token == "config-token"
                # reconnect_delay has a default value so config won't override it
                assert args.reconnect_delay == DEFAULT_RECONNECT_DELAY

    def test_parse_config_file_json(self):
        """Test parsing with JSON config file."""
        config_content = '{"gateway": "https://config.example.com", "token": "config-token"}'

        with patch("builtins.open", mock_open(read_data=config_content)):
            with patch("json.load") as mock_json:
                mock_json.return_value = {
                    "gateway": "https://config.example.com",
                    "token": "config-token"
                }

                # Need to provide gateway in environment since config loading happens after validation
                with patch.dict("os.environ", {"REVERSE_PROXY_GATEWAY": "https://config.example.com"}):
                    args = parse_args([
                        "--local-stdio", "echo test",
                        "--config", "config.json"
                    ])

                assert args.gateway == "https://config.example.com"
                assert args.token == "config-token"

    def test_parse_config_file_no_yaml(self):
        """Test config file parsing when PyYAML not available."""
        with patch("mcpgateway.reverse_proxy.yaml", None):
            with pytest.raises(SystemExit):
                parse_args([
                    "--local-stdio", "echo test",
                    "--config", "config.yaml"
                ])

    def test_parse_command_line_overrides_config(self):
        """Test command line arguments override config file."""
        with patch("builtins.open", mock_open()):
            with patch("mcpgateway.reverse_proxy.yaml") as mock_yaml:
                mock_yaml.safe_load.return_value = {
                    "gateway": "https://config.example.com",
                    "token": "config-token"
                }

                args = parse_args([
                    "--local-stdio", "echo test",
                    "--gateway", "https://cli.example.com",
                    "--config", "config.yaml"
                ])

                # CLI should override config
                assert args.gateway == "https://cli.example.com"
                assert args.token == "config-token"  # From config

    def test_missing_gateway(self):
        """Test error when gateway not provided."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit):
                parse_args(["--local-stdio", "echo test"])

    def test_token_from_env(self):
        """Test reading token from environment."""
        with patch.dict("os.environ", {
            ENV_GATEWAY: "https://gateway.example.com",
            ENV_TOKEN: "env-token"
        }):
            args = parse_args(["--local-stdio", "echo test"])
            assert args.token == "env-token"

    def test_env_variables(self):
        """Test reading various environment variables."""
        with patch.dict("os.environ", {
            ENV_GATEWAY: "https://gateway.example.com",
            ENV_TOKEN: "env-token",
            ENV_RECONNECT_DELAY: "5.0",
            ENV_MAX_RETRIES: "10",
            ENV_LOG_LEVEL: "WARNING"
        }):
            # Environment variables don't override command line args in current implementation
            # This test documents the current behavior
            args = parse_args(["--local-stdio", "echo test"])
            assert args.gateway == "https://gateway.example.com"
            assert args.token == "env-token"


class TestMainAndRun:
    """Test main function and run entry point."""

    @pytest.mark.asyncio
    async def test_main_success(self):
        """Test successful main execution."""
        mock_client = AsyncMock()

        with patch("mcpgateway.reverse_proxy.parse_args") as mock_parse:
            with patch("mcpgateway.reverse_proxy.ReverseProxyClient") as mock_client_class:
                with patch("logging.basicConfig"):
                    with patch("asyncio.Event") as mock_event_class:
                        mock_args = Mock()
                        mock_args.log_level = "INFO"
                        mock_args.gateway = "wss://example.com"
                        mock_args.local_stdio = "echo test"
                        mock_args.token = None
                        mock_args.reconnect_delay = 1.0
                        mock_args.max_retries = 0
                        mock_args.keepalive = 30
                        mock_parse.return_value = mock_args

                        mock_client_class.return_value = mock_client

                        mock_event = AsyncMock()
                        mock_event_class.return_value = mock_event

                        # Simulate immediate shutdown
                        mock_event.wait = AsyncMock()

                        await main(["--local-stdio", "echo test"])

                        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_signal_handling(self):
        """Test signal handler registration."""
        with patch("mcpgateway.reverse_proxy.parse_args") as mock_parse:
            with patch("mcpgateway.reverse_proxy.ReverseProxyClient") as mock_client_class:
                with patch("logging.basicConfig"):
                    with patch("asyncio.get_running_loop") as mock_get_loop:
                        with patch("asyncio.Event") as mock_event_class:
                            mock_args = Mock()
                            mock_args.log_level = "INFO"
                            mock_args.gateway = "wss://example.com"
                            mock_args.local_stdio = "echo test"
                            mock_args.token = None
                            mock_args.reconnect_delay = 1.0
                            mock_args.max_retries = 0
                            mock_args.keepalive = 30
                            mock_parse.return_value = mock_args

                            mock_client = AsyncMock()
                            mock_client_class.return_value = mock_client

                            mock_loop = Mock()
                            mock_get_loop.return_value = mock_loop

                            mock_event = AsyncMock()
                            mock_event_class.return_value = mock_event

                            await main()

                            # Should register signal handlers
                            assert mock_loop.add_signal_handler.call_count == 2
                            calls = mock_loop.add_signal_handler.call_args_list
                            signals = [call[0][0] for call in calls]
                            assert signal.SIGINT in signals
                            assert signal.SIGTERM in signals

    def test_run_success(self):
        """Test run function success."""
        with patch("asyncio.run") as mock_run:
            with patch("mcpgateway.reverse_proxy.main") as mock_main:
                run()
                mock_run.assert_called_once()
                mock_main.assert_called_once()

    def test_run_keyboard_interrupt(self):
        """Test run function handles KeyboardInterrupt."""
        with patch("asyncio.run", side_effect=KeyboardInterrupt):
            with patch("sys.exit") as mock_exit:
                run()
                mock_exit.assert_called_once_with(0)

    def test_run_exception(self):
        """Test run function handles general exceptions."""
        with patch("asyncio.run", side_effect=Exception("Test error")):
            with patch("sys.exit") as mock_exit:
                run()
                mock_exit.assert_called_once_with(1)


class TestConstants:
    """Test module constants and enums."""

    def test_connection_states(self):
        """Test all connection states are defined."""
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.RECONNECTING.value == "reconnecting"
        assert ConnectionState.SHUTTING_DOWN.value == "shutting_down"

    def test_message_types(self):
        """Test all message types are defined."""
        assert MessageType.REGISTER.value == "register"
        assert MessageType.UNREGISTER.value == "unregister"
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.ERROR.value == "error"
        assert MessageType.REQUEST.value == "request"
        assert MessageType.RESPONSE.value == "response"
        assert MessageType.NOTIFICATION.value == "notification"

    def test_environment_variables(self):
        """Test environment variable names."""
        assert ENV_GATEWAY == "REVERSE_PROXY_GATEWAY"
        assert ENV_TOKEN == "REVERSE_PROXY_TOKEN"
        assert ENV_RECONNECT_DELAY == "REVERSE_PROXY_RECONNECT_DELAY"
        assert ENV_MAX_RETRIES == "REVERSE_PROXY_MAX_RETRIES"
        assert ENV_LOG_LEVEL == "REVERSE_PROXY_LOG_LEVEL"

    def test_default_values(self):
        """Test default configuration values."""
        assert DEFAULT_RECONNECT_DELAY == 1.0
        assert DEFAULT_MAX_RETRIES == 0
        assert DEFAULT_KEEPALIVE_INTERVAL == 30
        assert DEFAULT_REQUEST_TIMEOUT == 90


# Helper function for mocking file operations
def mock_open(read_data=""):
    """Create a mock for open() that returns read_data."""
    # Standard
    from unittest.mock import mock_open as _mock_open
    return _mock_open(read_data=read_data)
