# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/transports/websocket_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

WebSocket transport adapter for gateway connections.
Implements WebSocket-based communication with the remote gateway.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import os
import ssl
from typing import Any, Awaitable, Callable, cast, List, Optional
from urllib.parse import urljoin

try:
    # Third-Party
    import websockets
except ImportError:
    websockets = None  # type: ignore[assignment]

# First-Party
from mcp_reverse_proxy.base import GatewayTransport
from mcp_reverse_proxy.cert_utils import load_cert_data
from mcp_reverse_proxy.logging_config import LoggingService

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcp_reverse_proxy.transports.websocket_adapter")

# Type alias for websocket client protocol
WSClientProtocol = Any


class WebSocketAdapter(GatewayTransport):
    """Transport adapter for WebSocket gateway connections.

    Handles WebSocket communication with the remote gateway.
    """

    def __init__(
        self,
        gateway_url: str,
        session_id: str,
        token: Optional[str] = None,
        cert: Optional[str] = None,
    ):
        """Initialize WebSocket adapter.

        Args:
            gateway_url: Remote gateway base URL.
            session_id: Session identifier for this connection.
            token: Optional bearer token for authentication.
            cert: Optional CA certificate for SSL verification.
        """
        self.gateway_url = gateway_url
        self.session_id = session_id
        self.token = token
        self.cert = cert

        self._connection: Optional[WSClientProtocol] = None
        self._connected = False
        self._message_handlers: List[Callable[[str], Awaitable[None]]] = []
        self._receive_task: Optional[asyncio.Task[None]] = None

    async def connect(self) -> None:
        """Establish WebSocket connection to gateway."""
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

        # Configure SSL context only for wss:// URLs
        is_secure = ws_url.startswith("wss://")
        ssl_context = None

        if is_secure:
            if self.cert is not None:
                # Load certificate data (from file or use as-is if already PEM content)
                try:
                    cert_data = load_cert_data(self.cert)
                    LOGGER.info("Certificate loaded successfully for WebSocket connection")
                except (FileNotFoundError, ValueError) as e:
                    LOGGER.error(f"Failed to load certificate: {e}")
                    raise RuntimeError(f"Certificate error: {e}") from e

                # Create SSL context with ONLY the custom CA (not system CAs)
                # This is critical for self-signed certificates to work properly
                # Using create_default_context() would load system CAs which reject self-signed certs
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED
                # Load ONLY our custom CA, not system CAs
                ssl_context.load_verify_locations(cadata=cert_data)
                LOGGER.info("SSL context configured with custom CA bundle (self-signed CA support enabled)")
            else:
                # No cert provided - disable verification (insecure, for development only)
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE  # noqa: DUO122

        # Connect
        self._connection = await websockets.connect(
            ws_url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
            ssl=ssl_context if is_secure else None,
        )

        # Mark as connected
        self._connected = True

        # Start receiving messages
        self._receive_task = asyncio.create_task(self._receive_messages())

        LOGGER.info("WebSocket connection established")

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        if not self._connected:
            return

        LOGGER.info("Disconnecting WebSocket")
        self._connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._connection:
            await cast(Any, self._connection).close()
        self._connection = None

    async def send(self, message: str | bytes) -> None:
        """Send a message to the gateway via WebSocket."""
        if not self._connected or not self._connection:
            raise RuntimeError("Not connected to gateway")

        # Ensure message is string for WebSocket text frames
        if isinstance(message, bytes):
            message = message.decode("utf-8")

        await cast(Any, self._connection).send(message)
        LOGGER.debug(f"→ WS: {message[:200]}...")

    def add_message_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Add a handler for messages from the gateway."""
        self._message_handlers.append(handler)

    async def is_connected(self) -> bool:
        """Check if WebSocket is connected.

        Uses _connected flag for consistency with SSE/StreamableHTTP adapters.
        This prevents race conditions where the receive loop has ended but
        the connection object hasn't been cleared yet.
        """
        return self._connected

    async def _receive_messages(self) -> None:
        """Receive messages from WebSocket connection."""
        if not self._connection:
            return

        try:
            conn = cast(Any, self._connection)
            async for message in conn:
                # Ensure message is string
                if isinstance(message, bytes):
                    message = message.decode("utf-8")

                LOGGER.debug(f"← WS: {message[:200]}...")

                for handler in self._message_handlers:
                    try:
                        await handler(message)
                    except Exception as e:
                        LOGGER.error(f"Handler error: {e}")

        except Exception as e:
            # Check for ConnectionClosed exception
            closed_exc = None
            if websockets is not None:
                ex_mod = getattr(websockets, "exceptions", None)
                if ex_mod is not None:
                    closed_exc = getattr(ex_mod, "ConnectionClosed", None)

            if closed_exc and isinstance(e, closed_exc):
                LOGGER.warning("WebSocket connection closed by remote")
            else:
                LOGGER.error(f"WebSocket receive error: {e}")
        except asyncio.CancelledError:
            LOGGER.debug("WebSocket receive cancelled")
            raise
        finally:
            # Mark connection as closed when receive loop exits
            LOGGER.info("WebSocket receive loop ended, marking connection as closed")
            self._connected = False
            self._connection = None
