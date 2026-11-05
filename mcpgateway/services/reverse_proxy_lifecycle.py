# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_lifecycle.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Reverse-proxy WebSocket connection lifecycle.

This module owns everything that happens after an authenticated
reverse-proxy WebSocket has been accepted: session admission with the
typed session manager, registration metadata capture, the
continuously-running receive pump, heartbeat acknowledgement, and the
shielded teardown that disconnects the session.

The module is transport-agnostic: it never imports FastAPI's WebSocket.
It drives the narrow :class:`ConnectionIO` protocol, which the lock
serializer :class:`_LockedConnectionIO` satisfies over any text
WebSocket transport.
"""

# Standard
from dataclasses import dataclass
from typing import assert_never, Final, Literal, Protocol
import uuid

# Third-Party
import anyio
import orjson
from pydantic import ValidationError
from starlette import status
from starlette.websockets import WebSocketDisconnect

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.reverse_proxy_protocol import (
    encode_server_message,
    error,
    heartbeat,
    HeartbeatMessage,
    NotificationMessage,
    parse_client_message,
    register_ack,
    register_complete,
    RegisterMessage,
    RegistrationStatus,
    ResponseMessage,
    UnregisterMessage,
)
from mcpgateway.services.reverse_proxy_sessions import get_reverse_proxy_session_manager, LocalSessionId

# Initialize logging
logging_service = LoggingService()
LOGGER = logging_service.get_logger("mcpgateway.services.reverse_proxy_lifecycle")

_MAX_WEBSOCKET_FRAME_BYTES: Final = 1024 * 1024


class ConnectionIO(Protocol):
    """Narrow text-frame transport driven by the connection lifecycle.

    Any object able to send and receive text frames and close with a
    WebSocket close code satisfies this protocol; FastAPI's WebSocket and
    the lock serializer below both conform structurally.
    """

    async def send_text(self, data: str) -> None:
        """Send one serialized text frame."""

    async def receive_text(self) -> str:
        """Receive one text frame, raising WebSocketDisconnect when the transport is lost."""

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Close the transport with a WebSocket close code and reason."""


@dataclass(frozen=True, slots=True)
class ReverseProxyAuthenticatedContext:
    """Canonical authority retained for an admitted reverse-proxy connection."""

    owner_email: str
    team_id: str | None


class _LockedConnectionIO:
    """Serialize every send and close on one reverse-proxy connection.

    One per-connection lock funnels the endpoint's own frames (register acks,
    heartbeat acknowledgements, error frames), the typed session manager's
    request/notification frames and all server-initiated closes, so the
    WebSocket is never touched concurrently.
    """

    def __init__(self, websocket: ConnectionIO, io_lock: anyio.Lock) -> None:
        """Wrap the raw WebSocket with the connection's shared I/O lock."""
        self._websocket = websocket
        self._io_lock = io_lock

    async def send_text(self, data: str) -> None:
        """Send one text frame under the shared I/O lock."""
        async with self._io_lock:
            await self._websocket.send_text(data)

    async def receive_text(self) -> str:
        """Receive one text frame; reads stay unlocked because the receive pump is the sole reader."""
        return await self._websocket.receive_text()

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Close the connection under the shared I/O lock."""
        async with self._io_lock:
            await self._websocket.close(code=code, reason=reason)


async def run_proxied_connection(connection_io: ConnectionIO, context: ReverseProxyAuthenticatedContext) -> None:
    """Run the full lifecycle of one admitted reverse-proxy connection.

    The maintained client contract drives the lifecycle: ``register`` stores
    the client's non-authoritative server metadata on the typed session and is
    acknowledged as ``register_ack(processing)`` followed by
    ``register_complete(success)``. Heartbeats are acknowledgements, not
    pongs. One continuously-running receive pump owns every inbound frame, so
    the client's own JSON-RPC responses always resolve.

    Args:
        connection_io: Lock-serialized text-frame transport for this connection.
        context: Authenticated principal that owns the session.
    """
    session_manager = await get_reverse_proxy_session_manager()
    connection = await session_manager.connect(connection_io, LocalSessionId(uuid.uuid4().hex), owner_email=context.owner_email)
    connection_id = connection.connection_id

    async def send_frame(frame: str) -> None:
        """Send one endpoint frame serialized through the connection's I/O lock."""
        await connection_io.send_text(frame)
        session_manager.record_sent(connection_id, character_count=len(frame))

    try:
        LOGGER.info(f"Reverse proxy connected: {connection_id}")

        registration_state: Literal["unregistered", "registered"] = "unregistered"

        while True:
            try:
                frame = await connection_io.receive_text()
                if len(frame.encode("utf-8")) > _MAX_WEBSOCKET_FRAME_BYTES:
                    await connection_io.close(code=status.WS_1009_MESSAGE_TOO_BIG, reason="message too large")
                    break
                session_manager.record_received(connection_id, character_count=len(frame))
                message = parse_client_message(frame)
            except WebSocketDisconnect:
                LOGGER.info(f"WebSocket disconnected: {connection_id}")
                break
            except (ValidationError, orjson.JSONDecodeError) as exc:
                LOGGER.warning(f"Invalid message from connection {connection_id}: {exc}")
                await send_frame(encode_server_message(error(str(connection_id), "Invalid message format")))
                continue

            match message:
                case RegisterMessage():
                    if registration_state != "unregistered":
                        LOGGER.warning(f"Duplicate register on connection {connection_id}")
                        await send_frame(encode_server_message(error(str(connection_id), "connection already registered")))
                        await connection_io.close(code=status.WS_1008_POLICY_VIOLATION, reason="connection already registered")
                        break
                    await send_frame(encode_server_message(register_ack(str(connection_id))))
                    await session_manager.record_server_info(connection_id, message.server.model_dump(exclude_none=True))
                    registration_state = "registered"
                    LOGGER.info(f"Registered server for connection {connection_id}: {message.server.name}")
                    await send_frame(encode_server_message(register_complete(str(connection_id), RegistrationStatus.SUCCESS)))
                case UnregisterMessage():
                    LOGGER.info(f"Unregistering server for connection {connection_id}")
                    break
                case HeartbeatMessage():
                    heartbeat_at = await session_manager.record_heartbeat(connection_id)
                    await send_frame(encode_server_message(heartbeat(str(connection_id), heartbeat_at)))
                case ResponseMessage():
                    if not session_manager.resolve_response(connection_id, message):
                        LOGGER.debug(f"Unmatched response from connection {connection_id}: {message.payload.id}")
                case NotificationMessage():
                    LOGGER.debug(f"Received notification from connection {connection_id}: {message.payload.method}")
                case unreachable:
                    assert_never(unreachable)
    finally:
        # Shield typed disconnect so cancellation cannot skip authoritative cleanup.
        with anyio.CancelScope(shield=True):
            await session_manager.disconnect(connection_id)
        LOGGER.info(f"Reverse proxy session ended: {connection_id}")
