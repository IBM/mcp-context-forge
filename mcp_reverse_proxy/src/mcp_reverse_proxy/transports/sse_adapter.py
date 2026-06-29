# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/transports/sse_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

SSE transport adapter for MCP servers.
Implements Server-Sent Events (SSE) based communication with MCP servers.
This adapter connects to SSE endpoints and handles bidirectional communication
via SSE for server-to-client streaming and HTTP POST for client-to-server messages.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import os
import ssl
from typing import Awaitable, Callable, List, Optional

# Third-Party
import httpx
import orjson

# First-Party
from mcp_reverse_proxy.base import McpServerTransport
from mcp_reverse_proxy.cert_utils import load_cert_data
from mcp_reverse_proxy.logging_config import LoggingService

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcp_reverse_proxy.transports.sse_adapter")


class SseAdapter(McpServerTransport):
    """Transport adapter for SSE-based MCP servers.

    Communicates with MCP servers via Server-Sent Events (SSE) for server-to-client
    streaming and HTTP POST for client-to-server messages. The server can be local
    or remote - this adapter connects via HTTP/SSE.

    SSE Protocol Flow:
    1. Connect to SSE endpoint to receive server messages
    2. Extract message endpoint URL from initial SSE event
    3. Send client messages via HTTP POST to message endpoint
    4. Receive responses via SSE stream

    Authentication:
    - Supports Basic, Bearer, and custom header authentication
    - Auth headers are included in both SSE connection and POST requests
    - Session management via mcp-session-id header
    """

    def __init__(
        self,
        server_url: str,
        cert: Optional[str] = None,
        timeout: float = 90.0,
    ):
        """Initialize SSE adapter.

        Args:
            server_url: MCP server SSE endpoint URL (can be local or remote).
            cert: Optional CA certificate for SSL verification.
            timeout: Request timeout in seconds.
        """
        self.server_url = server_url.rstrip("/")
        self.cert = cert
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
        self._message_handlers: List[Callable[[str], Awaitable[None]]] = []
        self._receive_task: Optional[asyncio.Task[None]] = None
        self._message_endpoint: Optional[str] = None
        self._session_id: Optional[str] = None
        self._protocol_version: Optional[str] = None
        self._auth_headers: dict[str, str] = {}
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start SSE connection to MCP server.

        Establishes HTTP client, connects to SSE endpoint, and starts
        receiving messages from the server.

        Raises:
            RuntimeError: If connection fails or adapter is already connected.
        """
        if self._connected:
            return

        LOGGER.info(f"Connecting to MCP server via SSE: {self.server_url}")

        # Configure SSL context only for HTTPS
        is_https = self.server_url.startswith("https://")
        ssl_context = None

        if is_https:
            if self.cert is not None:
                # Load certificate data (from file or use as-is if already PEM content)
                try:
                    cert_data = load_cert_data(self.cert)
                    LOGGER.info("Certificate loaded successfully for HTTPS connection")
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
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE  # noqa: DUO122

        # Create HTTP client with HTTP/2 support for better SSE performance
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            http2=True,
            verify=ssl_context if is_https else False,
        )

        self._connected = True
        self._shutdown_event.clear()

        # Start receiving SSE messages
        self._receive_task = asyncio.create_task(self._receive_sse_stream())

        LOGGER.info("SSE connection to MCP server established")

    async def stop(self) -> None:
        """Stop SSE connection gracefully.

        Cancels receive task, closes HTTP client, and cleans up resources.
        Clears session state to ensure clean reconnection.
        """
        if not self._connected:
            return

        LOGGER.info("Disconnecting from MCP server via SSE")
        self._connected = False
        self._shutdown_event.set()

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.aclose()
            self._client = None

        # Clear session state to prevent using stale session ID on reconnection
        self._session_id = None
        self._message_endpoint = None
        self._protocol_version = None

        LOGGER.info("SSE connection closed and session state cleared")

    async def send(self, message: str) -> None:
        """Send a message to the MCP server via HTTP POST.

        Messages are sent to the message endpoint URL received from the
        initial SSE connection. Responses are received via the SSE stream.

        Args:
            message: JSON-RPC message to send.

        Raises:
            RuntimeError: If not connected or message endpoint not available.
            httpx.HTTPError: If HTTP request fails.
        """
        if not self._connected or not self._client:
            raise RuntimeError("Not connected to MCP server")

        if not self._message_endpoint:
            raise RuntimeError("Message endpoint not yet available from SSE stream")

        LOGGER.debug(f"→ SSE POST: {message[:200]}...")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Add authentication headers from gateway if available
        if self._auth_headers:
            LOGGER.info(f"Using authentication headers from gateway: {list(self._auth_headers.keys())}")
            headers.update(self._auth_headers)

        # Add session headers if available (required after initialization)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        if self._protocol_version:
            headers["mcp-protocol-version"] = self._protocol_version

        try:
            response = await self._client.post(
                self._message_endpoint,
                content=message,
                headers=headers,
            )
            response.raise_for_status()

            # Extract session ID from response headers (first request)
            session_id = response.headers.get("mcp-session-id")
            if session_id and not self._session_id:
                self._session_id = session_id
                LOGGER.info(f"Received session ID: {self._session_id}")

            LOGGER.debug(f"SSE POST successful: status={response.status_code}")

        except httpx.HTTPStatusError as e:
            # If we get a 404, the session is invalid (server restarted)
            # Clear session state to force reconnection
            if e.response.status_code == 404:
                LOGGER.warning("SSE POST returned 404 - session invalid, clearing state to force reconnection")
                self._session_id = None
                self._message_endpoint = None
                self._protocol_version = None
            LOGGER.error(f"SSE POST error: {e}")
            raise RuntimeError(f"Failed to send message: {e}") from e
        except httpx.HTTPError as e:
            LOGGER.error(f"SSE POST error: {e}")
            raise RuntimeError(f"Failed to send message: {e}") from e

    def add_message_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Add a handler for messages from the MCP server.

        Handlers are called when messages are received via the SSE stream.

        Args:
            handler: Async function to handle messages.
        """
        self._message_handlers.append(handler)

    def set_authentication(self, auth_headers: dict[str, str], auth_type: str | None = None) -> None:
        """Set authentication headers for subsequent requests to the MCP server.

        Converts various authentication types to standard HTTP headers.
        Headers are used for both SSE connection and POST requests.

        Args:
            auth_headers: Dictionary of HTTP headers to use for authentication.
            auth_type: Type of authentication (basic, bearer, authheaders, etc.)
        """
        # Convert basic auth credentials to standard Authorization header
        if auth_type == "basic" and "username" in auth_headers and "password" in auth_headers:
            # Standard
            import base64

            username = auth_headers["username"]
            password = auth_headers["password"]
            credentials = f"{username}:{password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._auth_headers = {"Authorization": f"Basic {encoded}"}
            LOGGER.info("Converted basic auth credentials to Authorization header")
        elif auth_type == "bearer" and "token" in auth_headers:
            # Convert bearer token to Authorization header
            self._auth_headers = {"Authorization": f"Bearer {auth_headers['token']}"}
            LOGGER.info("Converted bearer token to Authorization header")
        else:
            # For other auth types (authheaders, custom), use headers as-is
            self._auth_headers = auth_headers
            LOGGER.info(f"Authentication headers set ({auth_type or 'custom'}): {list(auth_headers.keys())}")

    async def _receive_sse_stream(self) -> None:
        """Receive and process SSE events from the MCP server.

        Connects to the SSE endpoint and processes incoming events:
        - endpoint: Extracts message endpoint URL for POST requests
        - message: Forwards JSON-RPC messages to handlers
        - keepalive: Maintains connection (no action needed)
        - error: Logs error events

        The stream runs until disconnection or cancellation.
        """
        if not self._client:
            LOGGER.error("Cannot start SSE stream: client not initialized")
            return

        LOGGER.info(f"Starting SSE stream from {self.server_url}")

        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }

        # Add authentication headers for SSE connection
        if self._auth_headers:
            LOGGER.info(f"Using authentication headers for SSE connection: {list(self._auth_headers.keys())}")
            headers.update(self._auth_headers)

        try:
            async with self._client.stream("GET", self.server_url, headers=headers) as response:
                response.raise_for_status()
                LOGGER.info(f"SSE stream connected: status={response.status_code}")

                # Process SSE events
                event_type = None
                data_lines = []

                async for line in response.aiter_lines():
                    # Check for shutdown
                    if self._shutdown_event.is_set():
                        LOGGER.info("Shutdown requested, closing SSE stream")
                        break

                    line = line.strip()

                    if not line:
                        # Empty line marks end of event
                        if event_type and data_lines:
                            await self._process_sse_event(event_type, "\n".join(data_lines))
                            event_type = None
                            data_lines = []
                        continue

                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif line.startswith("retry:"):
                        # Retry timeout - informational only
                        pass
                    elif line.startswith(":"):
                        # Comment - ignore
                        pass

        except httpx.HTTPError as e:
            if self._connected:
                LOGGER.error(f"SSE stream error: {e}")
                # Notify handlers of connection loss
                for handler in self._message_handlers:
                    try:
                        error_msg = orjson.dumps(
                            {
                                "jsonrpc": "2.0",
                                "error": {
                                    "code": -32000,
                                    "message": f"SSE connection lost: {e}",
                                },
                            }
                        ).decode()
                        await handler(error_msg)
                    except Exception as handler_error:
                        LOGGER.error(f"Error notifying handler of connection loss: {handler_error}")
        except asyncio.CancelledError:
            LOGGER.info("SSE stream cancelled")
            raise
        except Exception as e:
            LOGGER.error(f"Unexpected error in SSE stream: {e}", exc_info=True)
        finally:
            # Mark as disconnected when stream ends
            self._connected = False
            LOGGER.info("SSE stream ended, marked as disconnected")

    async def _process_sse_event(self, event_type: str, data: str) -> None:
        """Process a single SSE event.

        Args:
            event_type: Type of SSE event (endpoint, message, keepalive, error).
            data: Event data payload.
        """
        LOGGER.debug(f"← SSE event: type={event_type}, data={data[:200]}...")

        if event_type == "endpoint":
            # Extract message endpoint URL
            # If it's a relative URL, construct full URL from server_url
            if data.startswith("/"):
                # Parse base URL to get scheme and host
                # Standard
                from urllib.parse import urlparse

                parsed = urlparse(self.server_url)
                self._message_endpoint = f"{parsed.scheme}://{parsed.netloc}{data}"
            else:
                self._message_endpoint = data
            LOGGER.info(f"Received message endpoint: {self._message_endpoint}")

            # Extract session ID from endpoint URL query parameter if present
            # FastMCP SSE servers include session_id in the endpoint URL
            # Standard
            from urllib.parse import parse_qs, urlparse

            parsed_endpoint = urlparse(self._message_endpoint)
            query_params = parse_qs(parsed_endpoint.query)
            if "session_id" in query_params and query_params["session_id"]:
                self._session_id = query_params["session_id"][0]
                LOGGER.info(f"Extracted session ID from endpoint URL: {self._session_id}")

        elif event_type == "message":
            # Forward JSON-RPC message to handlers
            try:
                # Extract protocol version from initialize response
                if not self._protocol_version:
                    try:
                        msg_data = orjson.loads(data)
                        if msg_data.get("result", {}).get("protocolVersion"):
                            self._protocol_version = msg_data["result"]["protocolVersion"]
                            LOGGER.info(f"Negotiated protocol version: {self._protocol_version}")
                    except Exception:
                        pass  # Not an initialize response or parsing failed

                # Notify all message handlers
                for idx, handler in enumerate(self._message_handlers):
                    try:
                        LOGGER.debug(f"Calling handler {idx + 1}/{len(self._message_handlers)}")
                        await handler(data)
                    except Exception as handler_error:
                        LOGGER.error(f"Handler {idx + 1} failed: {handler_error}", exc_info=True)

            except Exception as e:
                LOGGER.error(f"Error processing SSE message: {e}", exc_info=True)

        elif event_type == "keepalive":
            # Keepalive event - no action needed
            LOGGER.debug("Received keepalive event")

        elif event_type == "error":
            # Error event from server
            LOGGER.error(f"SSE error event: {data}")
            # Forward error to handlers
            for handler in self._message_handlers:
                try:
                    await handler(data)
                except Exception as handler_error:
                    LOGGER.error(f"Error forwarding SSE error to handler: {handler_error}")

        else:
            LOGGER.warning(f"Unknown SSE event type: {event_type}")
