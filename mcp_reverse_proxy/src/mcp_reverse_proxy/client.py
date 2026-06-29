# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Refactored reverse proxy client using transport abstractions.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from typing import Any, Dict, Optional

# Third-Party
import orjson

# First-Party
from mcp_reverse_proxy.base import (
    ConnectionState,
    GatewayTransport,
    McpServerTransport,
    MessageType,
)
from mcp_reverse_proxy.transports.streamablehttp_adapter import SessionExpiredError
from mcp_reverse_proxy.logging_config import LoggingService

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcp_reverse_proxy.client")

# Default configuration
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_MAX_RETRIES = 0
# Client sends heartbeats at this interval (MUST be less than gateway's HEARTBEAT_TIMEOUT)
# CRITICAL: Gateway with MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT=5 requires client < 5s
# Default 2s provides safety margin for network latency and processing delays
# For production with default gateway settings (90s timeout), this can be increased to 30s
DEFAULT_KEEPALIVE_INTERVAL = 2
DEFAULT_MCP_HEALTH_CHECK_TIMEOUT = 5.0
DEFAULT_MCP_HEALTH_CHECK_RETRY_INTERVAL = 10.0


class StdioSubprocessTerminated(Exception):
    """Exception raised when stdio subprocess terminates and cannot be recovered."""


class ReverseProxyClient:
    """Reverse proxy client using transport abstractions.

    Bridges MCP servers to remote gateways using pluggable transports.
    """

    def __init__(
        self,
        mcp_transport: McpServerTransport,
        gateway_transport: GatewayTransport,
        session_id: str,
        server_name: Optional[str] = None,
        server_description: Optional[str] = None,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL,
        mcp_health_check_timeout: float = DEFAULT_MCP_HEALTH_CHECK_TIMEOUT,
        mcp_health_check_retry_interval: float = DEFAULT_MCP_HEALTH_CHECK_RETRY_INTERVAL,
    ):
        """Initialize reverse proxy client.

        Args:
            mcp_transport: Transport for MCP server communication.
            gateway_transport: Transport for gateway communication.
            session_id: Session identifier.
            server_name: Optional server name.
            server_description: Optional server description.
            reconnect_delay: Initial reconnection delay in seconds.
            max_retries: Maximum reconnection attempts (0 = infinite).
            keepalive_interval: Heartbeat interval in seconds.
            mcp_health_check_timeout: Timeout for MCP health check calls in seconds.
            mcp_health_check_retry_interval: Interval between MCP health check retries when server is down.
        """
        self.mcp_transport = mcp_transport
        self.gateway_transport = gateway_transport
        self.session_id = session_id
        self.reconnect_delay = reconnect_delay
        self.max_retries = max_retries
        self.keepalive_interval = keepalive_interval
        self.mcp_health_check_timeout = mcp_health_check_timeout
        self.mcp_health_check_retry_interval = mcp_health_check_retry_interval

        self.server_name = server_name or f"reverse-proxy-{session_id[:8]}"
        self.description = server_description or "Reverse proxied MCP server"

        self.state = ConnectionState.DISCONNECTED
        self.retry_count = 0
        self._mcp_server_healthy = True
        self._consecutive_mcp_failures = 0
        self._registration_successful = False

        # Session expiration recovery: When an MCP server restarts, its session IDs become invalid.
        # If a request (e.g., tool call) fails with 404, we need to:
        # 1. Re-register with the gateway to trigger a new initialize sequence
        # 2. Save the failed request so we can retry it after the new session is established
        # Without this, the original request would be lost and the gateway would timeout waiting for a response.
        self._pending_reregistration_request: Optional[Dict[str, Any]] = None

        self._keepalive_task: Optional[asyncio.Task[None]] = None
        self._pending_requests: Dict[Any, asyncio.Future[Any]] = {}

        # Register message handlers
        self.mcp_transport.add_message_handler(self._handle_mcp_message)
        self.gateway_transport.add_message_handler(self._handle_gateway_message)

    async def connect(self) -> None:
        """Establish connection to gateway and MCP server."""
        if self.state != ConnectionState.DISCONNECTED:
            return

        self.state = ConnectionState.CONNECTING
        LOGGER.info("Establishing reverse proxy connection...")

        try:
            # Start MCP server transport
            LOGGER.info("Starting MCP server transport...")
            await self.mcp_transport.start()

            # Check MCP server health before connecting to gateway
            LOGGER.info("[CONNECT] Checking MCP server health before connecting to gateway...")
            mcp_healthy = await self._check_mcp_server_health()

            if not mcp_healthy:
                LOGGER.warning("[CONNECT] MCP server is not reachable, aborting gateway connection | " "Will retry connection later")
                self.state = ConnectionState.DISCONNECTED
                raise RuntimeError("MCP server is not reachable")

            LOGGER.info("[CONNECT] MCP server is healthy, proceeding with gateway connection")

            # Connect to gateway
            LOGGER.info("Connecting to gateway...")
            await self.gateway_transport.connect()

            self.state = ConnectionState.CONNECTED
            self.retry_count = 0

            # Register with gateway
            LOGGER.info("Registering with gateway...")
            await self._register()

            # Start keepalive (only if not already running)
            if self._keepalive_task is None or self._keepalive_task.done():
                LOGGER.info("Starting new keepalive task")
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            else:
                LOGGER.warning("Keepalive task already running, not starting a new one")

            LOGGER.info("Reverse proxy connected successfully")

        except Exception as e:
            LOGGER.error(f"Connection failed: {e}")
            self.state = ConnectionState.DISCONNECTED
            raise

    async def disconnect(self) -> None:
        """Disconnect from gateway and stop MCP server."""
        if self.state == ConnectionState.SHUTTING_DOWN:
            return

        self.state = ConnectionState.SHUTTING_DOWN
        LOGGER.info("Disconnecting reverse proxy...")

        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

        # Send unregister message
        if await self.gateway_transport.is_connected():
            try:
                unregister = {
                    "type": MessageType.UNREGISTER.value,
                    "sessionId": self.session_id,
                }
                await self.gateway_transport.send(orjson.dumps(unregister).decode())
            except Exception:
                pass  # nosec B110

        await self.gateway_transport.disconnect()
        await self.mcp_transport.stop()

        self.state = ConnectionState.DISCONNECTED
        LOGGER.info("Reverse proxy disconnected")

    async def run_with_reconnect(self) -> None:
        """Run the reverse proxy with automatic reconnection."""
        while True:
            try:
                if self.state == ConnectionState.SHUTTING_DOWN:
                    break

                await self.connect()

                # Wait for disconnection by monitoring both gateway and MCP connections
                while self.state == ConnectionState.CONNECTED:
                    # Check if keepalive task has failed with an exception
                    if self._keepalive_task and self._keepalive_task.done():
                        try:
                            # This will re-raise any exception from the task
                            self._keepalive_task.result()
                        except StdioSubprocessTerminated:
                            LOGGER.error("[RUN_WITH_RECONNECT] Keepalive task failed with StdioSubprocessTerminated, re-raising")
                            raise
                        except Exception as e:
                            LOGGER.error(f"[RUN_WITH_RECONNECT] Keepalive task failed: {e}")
                            self.state = ConnectionState.DISCONNECTED
                            break

                    # Check if gateway is still connected
                    if not await self.gateway_transport.is_connected():
                        LOGGER.warning("Gateway connection lost, triggering reconnection")
                        self.state = ConnectionState.DISCONNECTED
                        break

                    # Check if MCP transport is still connected (for SSE/HTTP transports)
                    # This detects when the MCP server restarts and the SSE stream disconnects
                    # The keepalive loop will handle stopping heartbeats when MCP is unhealthy
                    # which causes the gateway to mark this gateway as unreachable
                    mcp_connected = getattr(self.mcp_transport, "_connected", True)
                    if not mcp_connected:
                        LOGGER.info("[RUN_WITH_RECONNECT] MCP transport disconnected (server likely restarted)")
                        LOGGER.info("[RUN_WITH_RECONNECT] Keepalive loop will stop sending heartbeats, gateway will mark as unreachable")
                        LOGGER.info("[RUN_WITH_RECONNECT] Monitoring for MCP server recovery...")
                        # Mark MCP server as unhealthy so recovery logic triggers re-registration
                        if self._mcp_server_healthy:
                            LOGGER.info("[RUN_WITH_RECONNECT] Marking MCP server as unhealthy to trigger re-registration on recovery")
                            self._mcp_server_healthy = False
                            self._consecutive_mcp_failures += 1
                        # Don't break or disconnect - let the keepalive loop handle health checks
                        # It will stop sending heartbeats when MCP is unhealthy

                    await asyncio.sleep(1)

                if self.state == ConnectionState.SHUTTING_DOWN:
                    break

            except StdioSubprocessTerminated as e:
                # Re-raise to trigger proxy shutdown
                LOGGER.error(f"[RUN_WITH_RECONNECT] Caught StdioSubprocessTerminated, re-raising: {e}")
                LOGGER.error("[RUN_WITH_RECONNECT] About to raise - this should exit the function")
                raise
            except Exception as e:
                LOGGER.error(f"Connection error: {e}")
                LOGGER.error("[RUN_WITH_RECONNECT] After logging connection error, continuing to retry logic")

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

            # Before reconnecting to gateway, verify MCP server is reachable
            LOGGER.info("[RECONNECT] Checking MCP server health before reconnecting to gateway...")
            mcp_healthy = await self._check_mcp_server_health()

            if not mcp_healthy:
                LOGGER.warning(f"[RECONNECT] MCP server still unreachable, delaying gateway reconnection | " f"Will retry in {self.mcp_health_check_retry_interval}s")
                # Wait before checking again
                await asyncio.sleep(self.mcp_health_check_retry_interval)
                # Don't increment retry count for MCP health check failures
                self.retry_count -= 1
                continue

            LOGGER.info("[RECONNECT] MCP server is healthy, proceeding with gateway reconnection")
            self.state = ConnectionState.DISCONNECTED

    async def _register(self) -> None:
        """Register MCP server with gateway."""
        register_msg = {
            "type": MessageType.REGISTER.value,
            "sessionId": self.session_id,
            "server": {
                "name": self.server_name,
                "description": self.description,
                "protocol": "mcp",
            },
        }
        LOGGER.info(f"Sending registration: session={self.session_id}, name={self.server_name}")
        await self.gateway_transport.send(orjson.dumps(register_msg).decode())
        LOGGER.debug(f"Registration message sent: {register_msg}")

    async def _handle_mcp_message(self, message: str) -> None:
        """Handle message from MCP server."""
        try:
            LOGGER.debug(f"Handling MCP message: {message[:200]}...")
            data = orjson.loads(message)

            result = data.get("result")
            LOGGER.info(f"MCP response result: {result}, type: {type(result)}")
            request_id = data.get("id")

            # Check if this is a health check response (don't forward to gateway)
            is_health_check = request_id and str(request_id).startswith("health_check_")

            if request_id and request_id in self._pending_requests:
                LOGGER.info(f"Request ID {request_id} found in pending requests")
                future = self._pending_requests.pop(request_id)
                LOGGER.info(f"Future retrieved: {future}")
                if not future.done():
                    LOGGER.info("Setting result on future")
                    # For health checks, just resolve the future (don't forward to gateway)
                    # For normal requests, create envelope and resolve future
                    if is_health_check:
                        future.set_result(data)
                    else:
                        envelope = {
                            "type": MessageType.RESPONSE.value,
                            "sessionId": self.session_id,
                            "payload": data,
                        }
                        future.set_result(envelope)
            elif not is_health_check:
                # Forward to gateway (but not health check responses)
                envelope = {
                    "type": (MessageType.RESPONSE.value if "id" in data else MessageType.NOTIFICATION.value),
                    "sessionId": self.session_id,
                    "payload": data,
                }
                LOGGER.debug(f"Forwarding MCP message to gateway: {envelope}")
                await self.gateway_transport.send(orjson.dumps(envelope).decode())

        except Exception as e:
            LOGGER.error(f"Error handling MCP message: {e}")

    async def _handle_gateway_message(self, message: str) -> None:
        """Handle message from gateway."""
        try:
            LOGGER.debug(f"Handling gateway message: {message[:200]}...")
            data = orjson.loads(message)
            msg_type = data.get("type")

            if msg_type == MessageType.REQUEST.value:
                LOGGER.info("=" * 80)
                LOGGER.info("[REVERSE_PROXY_CLIENT] Received REQUEST from gateway")
                payload = data.get("payload", {})
                authentication = data.get("authentication")
                auth_type = data.get("authType")

                LOGGER.info(f"[REVERSE_PROXY_CLIENT] Message keys: {list(data.keys())}")
                LOGGER.info(f"[REVERSE_PROXY_CLIENT] Authentication present: {authentication is not None}")

                if authentication:
                    LOGGER.info(f"[REVERSE_PROXY_CLIENT] ✓ Gateway provided authentication (type: {auth_type})")
                    LOGGER.info(f"[REVERSE_PROXY_CLIENT] ✓ Auth headers: {list(authentication.keys())}")
                    # Store authentication for this request, passing auth_type for proper formatting
                    self.mcp_transport.set_authentication(authentication, auth_type)
                else:
                    LOGGER.warning("[REVERSE_PROXY_CLIENT] ✗ NO authentication in gateway message")

                LOGGER.info(f"[REVERSE_PROXY_CLIENT] Gateway request payload: {payload}")
                LOGGER.info("=" * 80)

                try:
                    await self.mcp_transport.send(orjson.dumps(payload).decode())
                except (SessionExpiredError, RuntimeError) as e:
                    # Session Expiration / Disconnection Recovery Flow:
                    # When an MCP server restarts, it loses all session state. This can manifest as:
                    # - SessionExpiredError: Streamable-HTTP gets 404 with stale session ID
                    # - RuntimeError("Not connected"): SSE transport is disconnected
                    # - RuntimeError("Failed to send message"): All connection attempts failed
                    # - RuntimeError("Subprocess not running"): Stdio process terminated
                    # - RuntimeError("Subprocess terminated..."): Stdio process crashed
                    # - RuntimeError("Subprocess stdin closed..."): Broken pipe to stdio process
                    #
                    # Recovery steps:
                    # 1. Save the failed request (tool call, etc.) so we don't lose it
                    # 2. Trigger re-registration with the gateway
                    # 3. Gateway will send a new initialize request to establish a fresh session
                    # 4. After successful re-registration, retry the saved request with the new session
                    #
                    # If the MCP server is completely stopped (not restarting), we'll send an error
                    # response after a timeout to prevent the gateway from hanging indefinitely.

                    # Check if this is a connection-related RuntimeError
                    is_connection_error = isinstance(e, RuntimeError) and (
                        "Not connected" in str(e)
                        or "Failed to send message" in str(e)
                        or "All connection attempts failed" in str(e)
                        or "Subprocess not running" in str(e)
                        or "Subprocess terminated" in str(e)
                        or "Subprocess stdin closed" in str(e)
                    )

                    if isinstance(e, RuntimeError) and not is_connection_error:
                        LOGGER.warning(f"[REVERSE_PROXY_CLIENT] Re-raising non-connection RuntimeError: {e}")
                        raise

                    LOGGER.warning(f"[REVERSE_PROXY_CLIENT] MCP transport unavailable: {e}")

                    # Check if MCP server is healthy - if not, send immediate error response
                    mcp_healthy = await self._check_mcp_server_health()
                    if not mcp_healthy:
                        LOGGER.warning("[REVERSE_PROXY_CLIENT] MCP server is down, sending error response to gateway")
                        await self._send_error_response(payload, f"MCP server is unavailable: {e}")
                        return

                    LOGGER.info("[REVERSE_PROXY_CLIENT] MCP server appears healthy, storing request for retry after re-registration...")

                    # Store the full message data for retry after re-registration completes
                    self._pending_reregistration_request = {
                        "payload": payload,
                        "authentication": authentication,
                        "authType": auth_type,
                    }

                    LOGGER.info("[REVERSE_PROXY_CLIENT] Triggering re-registration with gateway...")
                    self._registration_successful = False
                    await self._register()
                    LOGGER.info("[REVERSE_PROXY_CLIENT] Re-registration triggered, returning from handler")
                    return

            elif msg_type == MessageType.HEARTBEAT.value:
                # Gateway heartbeat is just an acknowledgment, no pong needed
                LOGGER.debug("Received HEARTBEAT acknowledgment from gateway")

            elif msg_type == "register_ack":
                # Gateway acknowledged receipt of registration request
                LOGGER.info(f"Gateway registration acknowledged: {data.get('status', 'unknown')}")

            elif msg_type == "register_complete":
                # Gateway completed registration (success or error)
                status = data.get("status", "unknown")
                if status == "success":
                    self._registration_successful = True
                    LOGGER.info(f"Gateway registration completed successfully for session {data.get('sessionId')}")

                    # Session Expiration Recovery - Part 2: Retry the saved request
                    # After successful re-registration, the gateway has sent an initialize request and
                    # a new session has been established with the MCP server. Now we can safely retry
                    # the request (e.g., tool call) that originally failed with 404.
                    #
                    # This ensures the gateway receives a response and doesn't timeout waiting for one.
                    if self._pending_reregistration_request:
                        LOGGER.info("[REVERSE_PROXY_CLIENT] Retrying stored request after re-registration...")
                        pending = self._pending_reregistration_request
                        self._pending_reregistration_request = None

                        # Restore authentication headers for the retry
                        if pending.get("authentication"):
                            self.mcp_transport.set_authentication(pending["authentication"], pending.get("authType"))

                        # Retry the original request with the new session
                        try:
                            await self.mcp_transport.send(orjson.dumps(pending["payload"]).decode())
                            LOGGER.info("[REVERSE_PROXY_CLIENT] Successfully retried request after re-registration")
                        except Exception as retry_error:
                            LOGGER.error(f"[REVERSE_PROXY_CLIENT] Failed to retry request after re-registration: {retry_error}")
                            # Send error response back to gateway so it doesn't hang waiting
                            await self._send_error_response(pending["payload"], f"MCP server unavailable after re-registration: {retry_error}")
                else:
                    self._registration_successful = False
                    error_msg = data.get("message", "Unknown error")
                    LOGGER.error(f"Gateway registration failed for session {data.get('sessionId')}: {error_msg}")
                    LOGGER.error("Disconnecting due to registration failure...")
                    # Schedule disconnect to avoid blocking message handler
                    asyncio.create_task(self.disconnect())

            elif msg_type == MessageType.ERROR.value:
                LOGGER.error(f"Gateway error: {data.get('message', 'Unknown')}")

            else:
                LOGGER.warning(f"Unknown message type from gateway: {msg_type}")

        except Exception as e:
            LOGGER.error(f"Error handling gateway message: {e}")

    async def _check_mcp_server_health(self) -> bool:
        """Check MCP server health using transport-specific connectivity checks.

        For HTTP-based transports: performs a simple HTTP connectivity check without authentication.
        For stdio transports: checks if the process is still running.

        This avoids authentication failures when the reverse proxy doesn't have credentials
        (credentials are stored in ContextForge and forwarded per-request).

        Returns:
            True if MCP server is reachable, False otherwise.
        """
        try:
            # Check if MCP transport is connected
            is_connected = getattr(self.mcp_transport, "_connected", True)
            LOGGER.info(f"[MCP_HEALTH] Starting health check | is_connected={is_connected}")

            # If not connected, try to connect to see if server is back online
            if not is_connected:
                LOGGER.info("[MCP_HEALTH] MCP transport not connected, attempting to connect to check if server is available")
                try:
                    await self.mcp_transport.stop()
                    await self.mcp_transport.start()
                    # Give SSE stream a moment to establish
                    await asyncio.sleep(0.5)
                    # Re-check connection status after start attempt
                    is_connected = getattr(self.mcp_transport, "_connected", False)
                    LOGGER.info(f"[MCP_HEALTH] After connection attempt: is_connected={is_connected}")
                    if not is_connected:
                        LOGGER.info("[MCP_HEALTH] Failed to connect - server is down")
                        return False
                except Exception as e:
                    LOGGER.warning(f"[MCP_HEALTH] Failed to connect to MCP server: {e}")
                    return False

            # Get transport type for health check logic
            transport_type = type(self.mcp_transport).__name__

            # Check if MCP transport is ready (has message endpoint for SSE/HTTP transports)
            has_endpoint_attr = hasattr(self.mcp_transport, "_message_endpoint")
            endpoint_value = getattr(self.mcp_transport, "_message_endpoint", None) if has_endpoint_attr else None
            LOGGER.info(f"[MCP_HEALTH] Endpoint check | has_attr={has_endpoint_attr}, value={endpoint_value}")

            if has_endpoint_attr and not endpoint_value:
                LOGGER.info("[MCP_HEALTH] MCP transport not ready yet (waiting for endpoint)")
                return False

            # For HTTP-based transports, check if session is initialized
            has_session_id = hasattr(self.mcp_transport, "_session_id")
            session_id_value = getattr(self.mcp_transport, "_session_id", None) if has_session_id else None

            # Perform transport-specific health check

            if transport_type == "StdioAdapter":
                # For stdio: check if process is still running
                process = getattr(self.mcp_transport, "process", None)
                if process and process.returncode is None:
                    LOGGER.info("[MCP_HEALTH] Stdio process is running ✓")
                    return True
                else:
                    # Stdio subprocess has terminated - no recovery possible
                    returncode = process.returncode if process else "N/A"
                    LOGGER.error(f"[MCP_HEALTH] Stdio subprocess terminated (returncode={returncode}) | " f"Session {self.session_id[:8]}... | " f"No automatic recovery possible for stdio transport")
                    LOGGER.error("[MCP_HEALTH] Raising exception to trigger proxy shutdown | " "Process supervisor will restart with fresh subprocess")

                    # Raise exception to trigger clean shutdown
                    LOGGER.error("[MCP_HEALTH] About to raise StdioSubprocessTerminated exception")
                    raise StdioSubprocessTerminated(f"Stdio subprocess terminated with returncode={returncode}")

            elif transport_type in ("SseAdapter", "StreamableHttpAdapter"):
                # For SSE transports: verify the SSE stream is actually established and stable
                # The _connected flag is set immediately in start(), but the SSE stream connects
                # asynchronously. We need to check if the receive task is running and healthy.
                if transport_type == "SseAdapter":
                    receive_task = getattr(self.mcp_transport, "_receive_task", None)

                    # Check if receive task exists and is running (not done/failed)
                    if receive_task and not receive_task.done():
                        # SSE stream is actively running and connected
                        # Healthy once endpoint is available, even without session ID
                        # The gateway will send initialize to establish the session
                        if is_connected and endpoint_value:
                            if session_id_value:
                                LOGGER.info("[MCP_HEALTH] SSE stream active with session ID - healthy ✓")
                            else:
                                LOGGER.info("[MCP_HEALTH] SSE stream active with endpoint (no session yet - gateway will initialize) ✓")
                            return True
                        else:
                            LOGGER.info("[MCP_HEALTH] SSE stream active but no endpoint yet - waiting for endpoint event")
                            return False
                    else:
                        # No receive task or it's done (failed/cancelled)
                        LOGGER.warning("[MCP_HEALTH] SSE receive task not running - server unreachable")
                        return False

                # For HTTP-based transports (including StreamableHttpAdapter): perform HTTP connectivity check
                # to verify the server is actually reachable, not just configured
                client = getattr(self.mcp_transport, "_client", None)
                server_url = getattr(self.mcp_transport, "server_url", None)

                if not client or not server_url:
                    LOGGER.warning("[MCP_HEALTH] HTTP transport not properly initialized")
                    return False

                try:
                    # Simple HEAD or GET request to check if server is reachable
                    # Use a short timeout for health checks
                    LOGGER.info(f"[MCP_HEALTH] Checking HTTP connectivity to {server_url}")
                    response = await client.head(server_url, timeout=self.mcp_health_check_timeout)

                    # Accept any response (including 401/403 auth errors) as "healthy"
                    # because it means the server is reachable
                    if response.status_code < 500:
                        LOGGER.info(f"[MCP_HEALTH] HTTP server is reachable (status: {response.status_code}) ✓")
                        return True
                    else:
                        LOGGER.warning(f"[MCP_HEALTH] HTTP server returned error: {response.status_code}")
                        return False

                except Exception as e:
                    LOGGER.warning(f"[MCP_HEALTH] HTTP connectivity check failed: {e}")
                    return False
            else:
                # Unknown transport type - assume healthy if connected
                LOGGER.info(f"[MCP_HEALTH] Unknown transport type {transport_type}, assuming healthy if connected")
                return is_connected

        except StdioSubprocessTerminated as e:
            # Re-raise this exception to trigger proxy shutdown
            LOGGER.error(f"[MCP_HEALTH] Caught StdioSubprocessTerminated in health check, re-raising: {e}")
            raise
        except Exception as e:
            LOGGER.warning(f"[MCP_HEALTH] MCP server health check failed: {e}")
            return False

    async def _keepalive_loop(self) -> None:
        """Send periodic heartbeat messages, conditional on MCP server health.

        This implements the transport-aware heartbeat strategy:
        1. Check MCP server health using transport-specific checks:
           - HTTP transports: HTTP HEAD request to verify server connectivity
           - Stdio transports: verify subprocess is still running (process.returncode is None)
        2. Only send heartbeat to gateway if MCP server is healthy
        3. If MCP server is unhealthy, skip heartbeat (gateway will detect timeout)
        4. Continue checking MCP server health and reconnect when it recovers
        """
        LOGGER.info(
            f"[HEARTBEAT_LOOP] Session {self.session_id[:8]}... | "
            f"Starting keepalive loop | Interval: {self.keepalive_interval}s | "
            f"MCP health check timeout: {self.mcp_health_check_timeout}s | "
            f"MCP retry interval: {self.mcp_health_check_retry_interval}s"
        )

        heartbeat_count = 0

        while self.state == ConnectionState.CONNECTED:
            await asyncio.sleep(self.keepalive_interval)

            # Check MCP server health before sending heartbeat
            LOGGER.debug(f"[HEARTBEAT_LOOP] Session {self.session_id[:8]}... | " f"Checking MCP server health (heartbeat #{heartbeat_count + 1})")
            mcp_healthy = await self._check_mcp_server_health()

            if mcp_healthy:
                # MCP server is healthy - send heartbeat to gateway
                if not self._mcp_server_healthy:
                    # MCP server recovered - always trigger re-registration to establish new session
                    LOGGER.info(
                        f"[HEARTBEAT_RECOVERY] Session {self.session_id[:8]}... | "
                        f"MCP server recovered after {self._consecutive_mcp_failures} failures | "
                        f"Triggering re-registration to establish new session"
                    )
                    self._mcp_server_healthy = True
                    self._consecutive_mcp_failures = 0

                    # Always re-register when MCP recovers to trigger new initialization
                    if not await self.gateway_transport.is_connected():
                        LOGGER.info(f"[HEARTBEAT_RECOVERY] Session {self.session_id[:8]}... | " f"Gateway disconnected, reconnecting before re-registration")
                        try:
                            await self.gateway_transport.connect()
                        except Exception as e:
                            LOGGER.error(f"[HEARTBEAT_RECOVERY] Session {self.session_id[:8]}... | " f"Failed to reconnect to gateway: {e}")
                            continue

                    # Re-register to trigger new MCP initialization sequence
                    try:
                        LOGGER.info(f"[HEARTBEAT_RECOVERY] Session {self.session_id[:8]}... | " f"Sending re-registration to gateway")
                        self._registration_successful = False
                        await self._register()
                        LOGGER.info(f"[HEARTBEAT_RECOVERY] Session {self.session_id[:8]}... | " f"Re-registration sent, gateway will initialize MCP server")
                    except Exception as e:
                        LOGGER.error(f"[HEARTBEAT_RECOVERY] Session {self.session_id[:8]}... | " f"Failed to re-register with gateway: {e}")
                        continue

                # Send heartbeat
                heartbeat = {
                    "type": MessageType.HEARTBEAT.value,
                    "sessionId": self.session_id,
                }

                try:
                    heartbeat_count += 1
                    LOGGER.info(f"[HEARTBEAT_SENT] Session {self.session_id[:8]}... | " f"Sending heartbeat #{heartbeat_count} to gateway | " f"MCP server: healthy | Consecutive failures: 0")
                    await self.gateway_transport.send(orjson.dumps(heartbeat).decode())
                except Exception as e:
                    LOGGER.warning(f"[HEARTBEAT_ERROR] Session {self.session_id[:8]}... | " f"Failed to send heartbeat to gateway: {e}")
                    break

            else:
                # MCP server is unhealthy - skip heartbeat
                self._consecutive_mcp_failures += 1

                if self._mcp_server_healthy:
                    # First failure detected
                    LOGGER.warning(
                        f"[HEARTBEAT_SKIPPED] Session {self.session_id[:8]}... | "
                        f"MCP server unhealthy - skipping heartbeat #{heartbeat_count + 1} | "
                        f"Gateway will detect timeout and mark unreachable | "
                        f"Consecutive failures: {self._consecutive_mcp_failures}"
                    )
                    self._mcp_server_healthy = False
                else:
                    # Ongoing failure
                    LOGGER.info(
                        f"[HEARTBEAT_SKIPPED] Session {self.session_id[:8]}... | "
                        f"MCP server still unhealthy - skipping heartbeat #{heartbeat_count + 1} | "
                        f"Consecutive failures: {self._consecutive_mcp_failures}"
                    )

                # Continue checking MCP server with shorter interval during outage
                # This allows faster recovery detection
                # Note: We already slept for keepalive_interval at the start of the loop,
                # so we don't need to sleep again here. The next iteration will sleep
                # for keepalive_interval before checking health again.
                LOGGER.debug(f"[HEARTBEAT_RETRY] Session {self.session_id[:8]}... | " f"Will retry MCP health check in {self.keepalive_interval}s (next loop iteration)")

        LOGGER.info(f"[HEARTBEAT_LOOP] Session {self.session_id[:8]}... | " f"Keepalive loop ended | Total heartbeats sent: {heartbeat_count} | " f"Final state: {self.state.value}")

    async def _send_error_response(self, request_payload: Dict[str, Any], error_message: str) -> None:
        """Send an error response back to the gateway for a failed request.

        Args:
            request_payload: The original request payload that failed
            error_message: Description of the error
        """
        try:
            request_id = request_payload.get("id")
            if not request_id:
                LOGGER.warning("[SEND_ERROR] Cannot send error response - no request ID in payload")
                return

            # Create JSON-RPC error response
            error_response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,  # Internal error
                    "message": error_message,
                },
            }

            # Wrap in gateway envelope
            envelope = {
                "type": MessageType.RESPONSE.value,
                "sessionId": self.session_id,
                "payload": error_response,
            }

            LOGGER.info(f"[SEND_ERROR] Sending error response to gateway for request {request_id}")
            await self.gateway_transport.send(orjson.dumps(envelope).decode())

        except Exception as e:
            LOGGER.error(f"[SEND_ERROR] Failed to send error response to gateway: {e}")
