# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/transports/streamablehttp_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Streamable HTTP transport adapter for MCP servers.
Implements HTTP-based communication with MCP servers using httpx.
This is an alternative to stdio for servers that expose HTTP endpoints.
The MCP server can be local or remote - the proxy connects via HTTP.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import ssl
from typing import Awaitable, Callable, List, Optional

# Third-Party
import httpx

# First-Party
from mcp_reverse_proxy.base import McpServerTransport
from mcp_reverse_proxy.cert_utils import load_cert_data
from mcp_reverse_proxy.logging_config import LoggingService


class SessionExpiredError(Exception):
    """Raised when MCP server session has expired and re-registration is needed."""


# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcp_reverse_proxy.transports.streamablehttp_adapter")


class StreamableHttpAdapter(McpServerTransport):
    """Transport adapter for Streamable HTTP MCP servers.

    Communicates with MCP servers via HTTP/2 streaming instead of stdio.
    The server can be local or remote - this adapter connects via HTTP.
    """

    def __init__(
        self,
        server_url: str,
        cert: Optional[str] = None,
        timeout: float = 90.0,
    ):
        """Initialize Streamable HTTP adapter.

        Args:
            server_url: MCP server HTTP URL (can be local or remote).
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
        # Streamable HTTP uses the main endpoint for communication
        self._endpoint_url = self.server_url
        # Message endpoint (for consistency with SSE adapter health checks)
        self._message_endpoint: Optional[str] = None
        # Session management (MCP protocol requirement)
        self._session_id: Optional[str] = None
        self._protocol_version: Optional[str] = None
        # Authentication headers from gateway
        self._auth_headers: dict[str, str] = {}

    async def start(self) -> None:
        """Start HTTP client connection to MCP server."""
        if self._connected:
            return

        LOGGER.info(f"Connecting to MCP server via HTTP: {self.server_url}")

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

        # Create HTTP client with HTTP/2 support
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            http2=True,
            verify=ssl_context if is_https else False,
        )

        self._connected = True

        # Set message endpoint (streamable HTTP knows endpoint immediately)
        self._message_endpoint = self._endpoint_url

        # Start receiving messages via SSE streaming
        self._receive_task = asyncio.create_task(self._receive_stream())

        LOGGER.info("HTTP connection to MCP server established")

    async def stop(self) -> None:
        """Stop HTTP client connection.

        Clears session state to ensure clean reconnection.
        """
        if not self._connected:
            return

        LOGGER.info("Disconnecting from MCP server")
        self._connected = False

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

        LOGGER.info("HTTP connection closed and session state cleared")

    async def send(self, message: str) -> None:
        """Send a message to the MCP server via HTTP POST and handle inline response.

        Args:
            message: JSON-RPC message to send to the MCP server.

        Raises:
            RuntimeError: If not connected to MCP server or HTTP request fails.
            SessionExpiredError: If MCP server session has expired (404) and re-registration is needed.
        """
        if not self._connected or not self._client:
            raise RuntimeError("Not connected to MCP server")

        LOGGER.debug(f"→ HTTP: {message[:200]}...")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        # Add authentication headers from gateway if available
        if self._auth_headers:
            LOGGER.info(f"Using authentication headers from gateway: {list(self._auth_headers.keys())}")
            headers.update(self._auth_headers)

        # IMPORTANT: Only add session headers AFTER we have received them from the server
        # The first request (initialize) should NOT include session headers - let the server create the session
        # Subsequent requests must include BOTH session ID and protocol version
        if self._session_id and self._protocol_version:
            headers["mcp-session-id"] = self._session_id
            headers["mcp-protocol-version"] = self._protocol_version
            LOGGER.debug(f"Including session headers: session_id={self._session_id}, protocol={self._protocol_version}")
        else:
            # No session - check if this is an initialize request
            # Standard
            import json

            try:
                msg_data = json.loads(message)
                is_initialize = msg_data.get("method") == "initialize"
            except Exception:
                is_initialize = False

            if not is_initialize:
                # Non-initialize request without a session - this should not happen
                # The gateway should have re-initialized before sending other requests
                LOGGER.error("Attempted to send non-initialize request without a valid session")
                raise RuntimeError("No valid session - gateway must send initialize request first")

            LOGGER.info("Initialize request - no session headers, server will create session and return headers")

        try:
            response = await self._client.post(
                self._endpoint_url,
                content=message,
                headers=headers,
            )
            response.raise_for_status()

            # Extract session ID from response headers (first request)
            session_id = response.headers.get("mcp-session-id")
            if session_id and not self._session_id:
                self._session_id = session_id
                LOGGER.info(f"Received session ID: {self._session_id}")
            LOGGER.info(
                f"HTTP POST successful: status={response.status_code}, content_length={len(response.content) if response.content else 0}")

            # Streamable HTTP returns responses inline - forward to handlers
            if response.content:
                response_text = response.text
                LOGGER.info(f"← HTTP response received: {response_text[:200]}... (total length: {len(response_text)})")
                LOGGER.info(f"Number of message handlers: {len(self._message_handlers)}")

                # Parse SSE format if present (streamable HTTP may return SSE-formatted responses)
                # SSE format: "event: message\ndata: {json}\n\n"
                json_message = response_text
                if response_text.startswith("event:") or response_text.startswith("data:"):
                    # Extract JSON from SSE format
                    lines = response_text.strip().split("\n")
                    for line in lines:
                        if line.startswith("data:"):
                            json_message = line[5:].strip()  # Remove "data:" prefix
                            LOGGER.info(f"Extracted JSON from SSE format: {json_message[:200]}...")
                            break

                # Extract protocol version from initialize response
                if not self._protocol_version:
                    try:
                        # Standard
                        import json

                        msg_data = json.loads(json_message)
                        if msg_data.get("result", {}).get("protocolVersion"):
                            self._protocol_version = msg_data["result"]["protocolVersion"]
                            LOGGER.info(f"Negotiated protocol version: {self._protocol_version}")
                    except Exception:
                        pass  # Not an initialize response or parsing failed

                # Notify all message handlers of the response
                for idx, handler in enumerate(self._message_handlers):
                    try:
                        LOGGER.info(f"Calling handler {idx + 1}/{len(self._message_handlers)}")
                        await handler(json_message)
                        LOGGER.info(f"Handler {idx + 1} completed successfully")
                    except Exception as handler_error:
                        LOGGER.error(f"Handler {idx + 1} failed: {handler_error}", exc_info=True)
            else:
                LOGGER.warning("HTTP response has no content - this may indicate a problem with the MCP server")

        except httpx.HTTPStatusError as e:
            # If we get a 404, the session is invalid (server restarted or session expired)
            # Only retry if this is an initialize request - other requests need gateway to re-initialize
            if e.response.status_code == 404 and (self._session_id or self._protocol_version):
                # Standard
                import json

                try:
                    msg_data = json.loads(message)
                    is_initialize = msg_data.get("method") == "initialize"
                except Exception:
                    is_initialize = False

                if is_initialize:
                    # Initialize requests can be retried without session headers
                    LOGGER.warning("Initialize request returned 404 - retrying without session headers")
                    self._session_id = None
                    self._protocol_version = None

                    try:
                        LOGGER.info("Retrying initialize request without session headers")
                        retry_headers = {
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream",
                        }
                        if self._auth_headers:
                            retry_headers.update(self._auth_headers)

                        response = await self._client.post(
                            self._endpoint_url,
                            content=message,
                            headers=retry_headers,
                        )
                        response.raise_for_status()

                        # Extract session ID from response headers
                        session_id = response.headers.get("mcp-session-id")
                        if session_id:
                            self._session_id = session_id
                            LOGGER.info(f"Received new session ID after retry: {self._session_id}")

                        LOGGER.info(f"Initialize retry successful: status={response.status_code}")

                        # Process the response
                        if response.content:
                            response_text = response.text
                            LOGGER.info(f"← HTTP response received: {response_text[:200]}...")

                            # Parse SSE format if present
                            json_message = response_text
                            if response_text.startswith("event:") or response_text.startswith("data:"):
                                lines = response_text.strip().split("\n")
                                for line in lines:
                                    if line.startswith("data:"):
                                        json_message = line[5:].strip()
                                        break

                            # Extract protocol version from initialize response
                            if not self._protocol_version:
                                try:
                                    msg_data = json.loads(json_message)
                                    if msg_data.get("result", {}).get("protocolVersion"):
                                        self._protocol_version = msg_data["result"]["protocolVersion"]
                                        LOGGER.info(f"Negotiated protocol version: {self._protocol_version}")
                                except Exception:
                                    pass

                            # Notify handlers
                            for handler in self._message_handlers:
                                try:
                                    await handler(json_message)
                                except Exception as handler_error:
                                    LOGGER.error(f"Handler failed: {handler_error}", exc_info=True)

                        return  # Success, exit the method

                    except Exception as retry_error:
                        LOGGER.error(f"Initialize retry after 404 failed: {retry_error}")
                        raise RuntimeError(f"Failed to send initialize after retry: {retry_error}") from retry_error
                else:
                    # For non-initialize requests, clear session state and raise special exception to trigger re-registration
                    LOGGER.warning(
                        "Non-initialize request returned 404 - clearing session state and triggering re-registration")
                    self._session_id = None
                    self._protocol_version = None
                    raise SessionExpiredError("MCP server session expired (404), re-registration required") from e

            LOGGER.error(f"HTTP send error: {e}")
            raise RuntimeError(f"Failed to send message: {e}") from e
        except httpx.HTTPError as e:
            LOGGER.error(f"HTTP send error: {e}")
            raise RuntimeError(f"Failed to send message: {e}") from e

    def add_message_handler(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Add a handler for messages from the MCP server."""
        self._message_handlers.append(handler)

    def set_authentication(self, auth_headers: dict[str, str], auth_type: str | None = None) -> None:
        """Set authentication headers for subsequent requests to the MCP server.

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

    async def _receive_stream(self) -> None:
        """Monitor connection for streamable HTTP.

        Streamable HTTP protocol handles bidirectional communication through
        the main endpoint with proper Accept headers. Responses come back
        inline with POST requests, not via a separate SSE stream.
        """
        LOGGER.debug("Streamable HTTP uses inline responses, monitoring connection")

        # Keep the task alive to maintain connection state
        try:
            while self._connected:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            LOGGER.debug("Connection monitoring cancelled")
            raise
