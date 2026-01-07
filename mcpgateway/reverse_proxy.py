# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/reverse_proxy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Reverse Proxy - Bridge local MCP servers to remote gateways.
This module implements a reverse proxy that connects local MCP servers
(running via stdio) to remote gateways, enabling servers behind firewalls
or NATs to be accessible without inbound network access.

The reverse proxy establishes an outbound WebSocket or SSE connection to
a remote gateway and registers the local server. All MCP protocol messages
are then tunneled through this persistent connection.

Environment variables:
- REVERSE_PROXY_GATEWAY: Remote gateway URL (required)
- REVERSE_PROXY_TOKEN: Bearer token for authentication (optional)
- REVERSE_PROXY_RECONNECT_DELAY: Initial reconnection delay in seconds (default 1)
- REVERSE_PROXY_MAX_RETRIES: Maximum reconnection attempts (default 0 = infinite)
- REVERSE_PROXY_LOG_LEVEL: Python log level (default INFO)

Example:
    $ export REVERSE_PROXY_GATEWAY=https://gateway.example.com
    $ export REVERSE_PROXY_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret key)
    $ python3 -m mcpgateway.reverse_proxy --local-stdio "uvx mcp-server-git"
"""

# Future
from __future__ import annotations

# Standard
import argparse
import asyncio
from contextlib import suppress
from enum import Enum
import logging
import os
import shlex
import signal
import sys
from typing import Any, cast, Dict, List, Optional
from urllib.parse import urljoin, urlparse
import uuid

# Third-Party
import orjson

try:
    # Third-Party
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    # Third-Party
    import websockets
except ImportError:
    websockets = None  # type: ignore[assignment]


try:
    # Third-Party
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Type alias for the websocket client protocol to avoid hard dependency at type-check time
WSClientProtocol = Any  # type: ignore[assignment]

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.reverse_proxy")

# Environment variable names
ENV_GATEWAY = "REVERSE_PROXY_GATEWAY"
ENV_TOKEN = "REVERSE_PROXY_TOKEN"  # nosec B105 - environment variable name, not a secret
ENV_RECONNECT_DELAY = "REVERSE_PROXY_RECONNECT_DELAY"
ENV_MAX_RETRIES = "REVERSE_PROXY_MAX_RETRIES"
ENV_LOG_LEVEL = "REVERSE_PROXY_LOG_LEVEL"

# Default configuration
DEFAULT_RECONNECT_DELAY = 1.0  # seconds
DEFAULT_MAX_RETRIES = 0  # 0 = infinite
DEFAULT_KEEPALIVE_INTERVAL = 30  # seconds
DEFAULT_REQUEST_TIMEOUT = 90  # seconds


class ConnectionState(Enum):
    """Connection state enumeration.

    Examples:
        >>> ConnectionState.DISCONNECTED.value
        'disconnected'
        >>> ConnectionState.CONNECTED.value
        'connected'
        >>> ConnectionState.CONNECTING.value
        'connecting'
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    SHUTTING_DOWN = "shutting_down"


class MessageType(Enum):
    """Control message types for the reverse proxy protocol.

    Examples:
        >>> MessageType.REGISTER.value
        'register'
        >>> MessageType.REQUEST.value
        'request'
        >>> MessageType.HEARTBEAT.value
        'heartbeat'
    """

    # Control messages
    REGISTER = "register"
    UNREGISTER = "unregister"
    HEARTBEAT = "heartbeat"
    ERROR = "error"

    # MCP messages
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


class StdioProcess:
    """Manages a local MCP server subprocess via stdio."""

    def __init__(self, command: str):
        """Initialize stdio process manager.

        Args:
            command: The command to run as a subprocess.
        """
        self.command = command
        self.process: Optional[asyncio.subprocess.Process] = None
        self._stdout_reader_task: Optional[asyncio.Task] = None
        self._message_handlers: List[Any] = []

    async def start(self) -> None:
        """Start the stdio subprocess.

        Raises:
            RuntimeError: If subprocess creation fails with stdio.
        """
        LOGGER.info(f"Starting local MCP server: {self.command}")

        self.process = await asyncio.create_subprocess_exec(
            *shlex.split(self.command),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=sys.stderr,  # Pass through for debugging
        )

        if not self.process.stdin or not self.process.stdout:
            raise RuntimeError(f"Failed to create subprocess with stdio: {self.command}")

        # Start reading stdout
        self._stdout_reader_task = asyncio.create_task(self._read_stdout())
        LOGGER.info(f"Local MCP server started (PID: {self.process.pid})")

    async def stop(self) -> None:
        """Stop the stdio subprocess gracefully."""
        if not self.process:
            return

        LOGGER.info(f"Stopping local MCP server (PID: {self.process.pid})")

        # Cancel stdout reader
        if self._stdout_reader_task:
            self._stdout_reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stdout_reader_task

        # Terminate process
        self.process.terminate()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.process.wait(), timeout=5)

        # Force kill if needed
        if self.process.returncode is None:
            LOGGER.warning("Force killing subprocess")
            self.process.kill()
            await self.process.wait()

    async def send(self, message: str) -> None:
        """Send a message to the subprocess stdin.

        Args:
            message: JSON-RPC message to send.

        Raises:
            RuntimeError: If subprocess is not running.
        """
        if not self.process or not self.process.stdin:
            raise RuntimeError("Subprocess not running")

        LOGGER.debug(f"→ stdio: {message[:200]}...")
        self.process.stdin.write((message + "\n").encode())
        await self.process.stdin.drain()

    def add_message_handler(self, handler) -> None:
        """Add a handler for messages from stdout.

        Args:
            handler: Async function to handle messages.
        """
        self._message_handlers.append(handler)

    async def _read_stdout(self) -> None:
        """Read messages from subprocess stdout.

        Raises:
            asyncio.CancelledError: When the read task is cancelled.
        """
        if not self.process or not self.process.stdout:
            return

        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break

                message = line.decode().strip()
                if not message:
                    continue

                LOGGER.debug(f"← stdio: {message[:200]}...")

                # Notify handlers
                for handler in self._message_handlers:
                    try:
                        await handler(message)
                    except Exception as e:
                        LOGGER.error(f"Handler error: {e}")

        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as e:
            LOGGER.error(f"Error reading stdout: {e}")


class ReverseProxyClient:
    """Reverse proxy client that bridges local stdio to remote gateway."""

    def __init__(
        self,
        gateway_url: str,
        local_command: str,
        token: Optional[str] = None,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL,
    ):
        """Initialize reverse proxy client.

        Args:
            gateway_url: Remote gateway URL.
            local_command: Local MCP server command.
            token: Optional bearer token for authentication.
            reconnect_delay: Initial reconnection delay in seconds.
            max_retries: Maximum reconnection attempts (0 = infinite).
            keepalive_interval: Heartbeat interval in seconds.
        """
        self.gateway_url = gateway_url
        self.local_command = local_command
        self.token = token
        self.reconnect_delay = reconnect_delay
        self.max_retries = max_retries
        self.keepalive_interval = keepalive_interval

        # Parse gateway URL
        parsed = urlparse(gateway_url)
        self.use_websocket = parsed.scheme in ("ws", "wss", "http", "https")

        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self.connection: Optional[WSClientProtocol] = None
        self.session_id = uuid.uuid4().hex
        self.retry_count = 0

        # Components
        self.stdio_process = StdioProcess(local_command)
        self.stdio_process.add_message_handler(self._handle_stdio_message)

        # Tasks
        self._keepalive_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None

        # Request tracking for correlation
        self._pending_requests: Dict[Any, asyncio.Future] = {}

    async def connect(self) -> None:
        """Establish connection to remote gateway.

        Raises:
            Exception: If connection fails.
        """
        if self.state != ConnectionState.DISCONNECTED:
            return

        self.state = ConnectionState.CONNECTING

        try:
            # Start local server first
            await self.stdio_process.start()

            # Connect to gateway
            if self.use_websocket:
                await self._connect_websocket()
            else:
                await self._connect_sse()

            self.state = ConnectionState.CONNECTED
            self.retry_count = 0

            # Register with gateway
            await self._register()

            # Start keepalive
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

            LOGGER.info(f"Connected to gateway: {self.gateway_url}")

        except Exception as e:
            LOGGER.error(f"Connection failed: {e}")
            self.state = ConnectionState.DISCONNECTED
            raise

    async def _connect_websocket(self) -> None:
        """Connect via WebSocket.

        Raises:
            ImportError: If websockets package is not installed.
        """
        if not websockets:
            raise ImportError("websockets package required for WebSocket support")

        # Build WebSocket URL
        ws_url = self.gateway_url.replace("http://", "ws://").replace("https://", "wss://")
        if not ws_url.startswith(("ws://", "wss://")):
            ws_url = f"wss://{ws_url}"

        # Add reverse proxy endpoint
        if "/reverse-proxy" not in ws_url:
            ws_url = urljoin(ws_url, "/reverse-proxy/ws")

        # Build headers
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers["X-Session-ID"] = self.session_id

        LOGGER.info(f"Connecting to WebSocket: {ws_url}")

        # Connect
        self.connection = await websockets.connect(
            ws_url,
            extra_headers=headers,
            ping_interval=20,
            ping_timeout=10,
        )

        # Start receiving messages
        self._receive_task = asyncio.create_task(self._receive_websocket())

    async def _connect_sse(self) -> None:
        """Connect via SSE (fallback).

        Raises:
            ImportError: If httpx package is not installed.
            NotImplementedError: SSE transport not yet implemented.
        """
        if not httpx:
            raise ImportError("httpx package required for SSE support")

        # SSE implementation would establish SSE connection
        # and use POST endpoint for sending messages
        raise NotImplementedError("SSE transport not yet implemented")

    async def _register(self) -> None:
        """Register local server with gateway."""
        # Get server info by sending initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": "init-" + uuid.uuid4().hex,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "reverse-proxy", "version": "1.0.0"}},
        }

        # Send to local server
        await self.stdio_process.send(orjson.dumps(init_request).decode())

        # Wait for response (simplified - should correlate properly)
        await asyncio.sleep(1)

        # Send registration to gateway
        register_msg = {
            "type": MessageType.REGISTER.value,
            "sessionId": self.session_id,
            "server": {
                "name": f"reverse-proxy-{self.session_id[:8]}",
                "description": f"Reverse proxied: {self.local_command}",
                "protocol": "stdio",
            },
        }

        await self._send_to_gateway(orjson.dumps(register_msg).decode())

    async def _send_to_gateway(self, message: str) -> None:
        """Send message to remote gateway.

        Args:
            message: Message to send.

        Raises:
            RuntimeError: If not connected to gateway.
            NotImplementedError: If SSE transport is used (not implemented).
        """
        conn = self.connection
        if not conn:
            raise RuntimeError("Not connected to gateway")

        if self.use_websocket:
            await cast(Any, conn).send(message)
        else:
            # SSE would POST to message endpoint
            raise NotImplementedError("SSE transport not yet implemented")

    async def _handle_stdio_message(self, message: str) -> None:
        """Handle message from local stdio server.

        Args:
            message: JSON-RPC message from stdio.
        """
        try:
            # Parse to check if it's a response or notification
            data = orjson.loads(message)

            # Wrap in reverse proxy envelope
            envelope = {"type": MessageType.RESPONSE.value if "id" in data else MessageType.NOTIFICATION.value, "sessionId": self.session_id, "payload": data}

            # Forward to gateway
            await self._send_to_gateway(orjson.dumps(envelope).decode())

        except Exception as e:
            LOGGER.error(f"Error forwarding stdio message: {e}")

    async def _receive_websocket(self) -> None:
        """Receive messages from WebSocket connection."""
        if not self.connection:
            return

        try:
            conn = cast(Any, self.connection)
            async for message in conn:
                await self._handle_gateway_message(message)
        except Exception as e:  # Catch broad exceptions to avoid dependency-specific attribute errors
            closed_exc = None
            if websockets is not None:
                ex_mod = getattr(websockets, "exceptions", None)
                if ex_mod is not None:
                    closed_exc = getattr(ex_mod, "ConnectionClosed", None)
            if closed_exc and isinstance(e, closed_exc):
                LOGGER.warning("WebSocket connection closed")
            else:
                LOGGER.error(f"WebSocket receive error: {e}")
        finally:
            self.state = ConnectionState.DISCONNECTED

    async def _handle_gateway_message(self, message: str) -> None:
        """Handle message from remote gateway.

        Args:
            message: Message from gateway.
        """
        try:
            data = orjson.loads(message)
            msg_type = data.get("type")

            if msg_type == MessageType.REQUEST.value:
                # Forward request to local server
                payload = data.get("payload", {})
                await self.stdio_process.send(orjson.dumps(payload).decode())

            elif msg_type == MessageType.HEARTBEAT.value:
                # Respond to heartbeat
                pong = {
                    "type": MessageType.HEARTBEAT.value,
                    "sessionId": self.session_id,
                }
                await self._send_to_gateway(orjson.dumps(pong).decode())

            elif msg_type == MessageType.ERROR.value:
                LOGGER.error(f"Gateway error: {data.get('message', 'Unknown error')}")

            else:
                LOGGER.warning(f"Unknown message type: {msg_type}")

        except Exception as e:
            LOGGER.error(f"Error handling gateway message: {e}")

    async def _keepalive_loop(self) -> None:
        """Send periodic keepalive messages."""
        try:
            while self.state == ConnectionState.CONNECTED:
                await asyncio.sleep(self.keepalive_interval)

                heartbeat = {
                    "type": MessageType.HEARTBEAT.value,
                    "sessionId": self.session_id,
                }

                try:
                    await self._send_to_gateway(orjson.dumps(heartbeat).decode())
                except Exception as e:
                    LOGGER.warning(f"Keepalive failed: {e}")
                    break

        except asyncio.CancelledError:
            pass

    async def disconnect(self) -> None:
        """Disconnect from gateway and stop local server."""
        if self.state == ConnectionState.SHUTTING_DOWN:
            return

        self.state = ConnectionState.SHUTTING_DOWN
        LOGGER.info("Disconnecting reverse proxy...")

        # Cancel tasks
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._receive_task:
            self._receive_task.cancel()

        # Send unregister message
        if self.connection:
            try:
                unregister = {
                    "type": MessageType.UNREGISTER.value,
                    "sessionId": self.session_id,
                }
                await self._send_to_gateway(orjson.dumps(unregister).decode())
            except Exception:
                pass  # nosec B110 - Intentionally swallow errors during cleanup

        # Close connection
        if self.connection:
            await cast(Any, self.connection).close()

        # Stop local server
        await self.stdio_process.stop()

        self.state = ConnectionState.DISCONNECTED
        LOGGER.info("Reverse proxy disconnected")

    async def run_with_reconnect(self) -> None:
        """Run the reverse proxy with automatic reconnection."""
        while True:
            try:
                if self.state == ConnectionState.SHUTTING_DOWN:
                    break

                await self.connect()

                # Wait for disconnection
                while self.state == ConnectionState.CONNECTED:
                    await asyncio.sleep(1)

                if self.state == ConnectionState.SHUTTING_DOWN:
                    break

            except Exception as e:
                LOGGER.error(f"Connection error: {e}")

            # Check retry limit
            self.retry_count += 1
            if self.max_retries > 0 and self.retry_count >= self.max_retries:
                LOGGER.error(f"Max retries ({self.max_retries}) exceeded")
                break

            # Calculate backoff delay
            delay = min(self.reconnect_delay * (2**self.retry_count), 60)
            LOGGER.info(f"Reconnecting in {delay}s (attempt {self.retry_count})")

            self.state = ConnectionState.RECONNECTING
            await asyncio.sleep(delay)
            self.state = ConnectionState.DISCONNECTED


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Command line arguments (default: sys.argv[1:]).

    Returns:
        Parsed arguments.

    Examples:
        >>> import os
        >>> os.environ['REVERSE_PROXY_GATEWAY'] = 'https://example.com'
        >>> args = parse_args(['--local-stdio', 'mcp-server'])
        >>> args.local_stdio
        'mcp-server'
        >>> args.gateway
        'https://example.com'
        >>> args.log_level
        'INFO'
        >>> args = parse_args(['--local-stdio', 'mcp-server', '--verbose'])
        >>> args.log_level
        'DEBUG'
        >>> args = parse_args(['--local-stdio', 'mcp-server', '--max-retries', '5'])
        >>> args.max_retries
        5
    """
    parser = argparse.ArgumentParser(
        prog="mcpgateway.reverse_proxy",
        description="Bridge local MCP servers to remote gateways",
    )

    # Required arguments
    parser.add_argument(
        "--local-stdio",
        required=True,
        help="Local MCP server command to run via stdio",
    )

    parser.add_argument(
        "--gateway",
        help="Remote gateway URL (can also use REVERSE_PROXY_GATEWAY env var)",
    )

    # Authentication
    parser.add_argument(
        "--token",
        help="Bearer token for authentication (can also use REVERSE_PROXY_TOKEN env var)",
    )

    # Connection options
    parser.add_argument(
        "--reconnect-delay",
        type=float,
        default=DEFAULT_RECONNECT_DELAY,
        help=f"Initial reconnection delay in seconds (default: {DEFAULT_RECONNECT_DELAY})",
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Maximum reconnection attempts, 0=infinite (default: {DEFAULT_MAX_RETRIES})",
    )

    parser.add_argument(
        "--keepalive",
        type=int,
        default=DEFAULT_KEEPALIVE_INTERVAL,
        help=f"Keepalive interval in seconds (default: {DEFAULT_KEEPALIVE_INTERVAL})",
    )

    # Configuration file
    parser.add_argument(
        "--config",
        help="Configuration file (YAML or JSON)",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Log level (default: INFO)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (same as --log-level DEBUG)",
    )

    args = parser.parse_args(argv)

    # Handle verbose flag
    if args.verbose:
        args.log_level = "DEBUG"

    # Get gateway from environment if not provided
    if not args.gateway:
        args.gateway = os.getenv(ENV_GATEWAY)
        if not args.gateway:
            parser.error("--gateway or REVERSE_PROXY_GATEWAY environment variable required")

    # Get token from environment if not provided
    if not args.token:
        args.token = os.getenv(ENV_TOKEN)

    # Load configuration file if provided
    if args.config:
        if not yaml:
            parser.error("PyYAML package required for configuration file support")
        yaml_module = cast(Any, yaml)

        with open(args.config, "r", encoding="utf-8") as f:
            if args.config.endswith((".yaml", ".yml")):
                config = yaml_module.safe_load(f)
            else:
                config = orjson.loads(f.read())

        # Merge configuration (command line takes precedence)
        if not isinstance(config, dict):
            parser.error("Configuration file must contain a JSON/YAML object at the top level")
        else:
            for key, value in config.items():
                if not hasattr(args, key) or getattr(args, key) is None:
                    setattr(args, key, value)

    return args


async def main(argv: Optional[List[str]] = None) -> None:
    """Main entry point for reverse proxy.

    Args:
        argv: Command line arguments.
    """
    args = parse_args(argv)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )

    # Create reverse proxy client
    client = ReverseProxyClient(
        gateway_url=args.gateway,
        local_command=args.local_stdio,
        token=args.token,
        reconnect_delay=args.reconnect_delay,
        max_retries=args.max_retries,
        keepalive_interval=args.keepalive,
    )

    # Handle shutdown signals
    shutdown_event = asyncio.Event()

    def signal_handler(*_args: object) -> None:
        """Handle shutdown signals gracefully.

        Args:
            *_args: Signal handler positional arguments (ignored).
        """
        LOGGER.info("Shutdown signal received")
        shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, signal_handler)

    # Run client with reconnection
    client_task = asyncio.create_task(client.run_with_reconnect())

    try:
        # Wait for shutdown
        await shutdown_event.wait()
    finally:
        # Clean shutdown
        await client.disconnect()
        client_task.cancel()
        with suppress(asyncio.CancelledError):
            await client_task


def run() -> None:
    """Console script entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
