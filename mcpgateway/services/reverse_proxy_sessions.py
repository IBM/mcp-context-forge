# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_sessions.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Process-local reverse-proxy connections and pending responses.

``LocalSessionId`` is a non-authoritative admission nonce used only to reject
duplicate local connections. It does not convey ownership or access scope.
"""

from dataclasses import dataclass
from typing import NewType, Protocol, TypeAlias, assert_never
import uuid

import anyio

from mcpgateway.services.reverse_proxy_protocol import JsonRpcId, JsonRpcNotification, JsonRpcRequest, ResponseMessage, encode_server_message, request


ConnectionId = NewType("ConnectionId", str)
LocalSessionId = NewType("LocalSessionId", str)
StableGatewayId = NewType("StableGatewayId", str)  # persistent gateway identity used to locate a live reverse-proxy connection
PendingKey: TypeAlias = tuple[ConnectionId, JsonRpcId]


class TextWebSocket(Protocol):
    """Minimal WebSocket capability required by the session core."""

    async def send_text(self, data: str) -> None:
        """Send one serialized protocol frame."""


class DuplicateLocalSessionError(Exception):
    """Raised when a process already tracks a client's local identifier."""

    def __init__(self, local_id: LocalSessionId) -> None:
        """Initialize the duplicate local identifier error."""
        self.local_id = local_id
        super().__init__(local_id)

    def __str__(self) -> str:
        """Return the duplicate local session description."""
        return f"local reverse-proxy session {self.local_id} is already connected"


class ConnectionNotFoundError(Exception):
    """Raised when a server-owned connection identifier is inactive."""

    def __init__(self, connection_id: ConnectionId) -> None:
        """Initialize the inactive connection error."""
        self.connection_id = connection_id
        super().__init__(connection_id)

    def __str__(self) -> str:
        """Return the inactive connection description."""
        return f"reverse-proxy connection {self.connection_id} is not active"


class ConnectionClosedError(Exception):
    """Raised in pending callers when their connection disconnects."""

    def __init__(self, connection_id: ConnectionId) -> None:
        """Initialize the disconnected connection error."""
        self.connection_id = connection_id
        super().__init__(connection_id)

    def __str__(self) -> str:
        """Return the disconnected connection description."""
        return f"reverse-proxy connection {self.connection_id} disconnected"


class MissingRequestIdError(Exception):
    """Raised when response correlation is requested without a JSON-RPC ID."""

    def __init__(self, connection_id: ConnectionId) -> None:
        """Initialize the missing request identifier error."""
        self.connection_id = connection_id
        super().__init__(connection_id)

    def __str__(self) -> str:
        """Return the missing request identifier description."""
        return f"request for reverse-proxy connection {self.connection_id} has no JSON-RPC id"


class DuplicatePendingRequestError(Exception):
    """Raised for duplicate request IDs on one connection."""

    def __init__(self, connection_id: ConnectionId, request_id: JsonRpcId) -> None:
        """Initialize the duplicate pending request error."""
        self.connection_id = connection_id
        self.request_id = request_id
        super().__init__(connection_id, request_id)

    def __str__(self) -> str:
        """Return the duplicate pending request description."""
        return f"request {self.request_id} is already pending for reverse-proxy connection {self.connection_id}"


@dataclass(frozen=True, slots=True)
class ReverseProxySession:
    """One process-local WebSocket connection with server-owned identity."""

    connection_id: ConnectionId
    local_id: LocalSessionId
    websocket: TextWebSocket


PendingResult: TypeAlias = ResponseMessage | ConnectionClosedError


class _PendingResponse:
    """Mutable one-shot signal owned by a single pending request."""

    def __init__(self) -> None:
        self._event = anyio.Event()
        self._result: PendingResult | None = None
        self._operation_scope: anyio.CancelScope | None = None

    def attach_operation_scope(self, operation_scope: anyio.CancelScope) -> None:
        """Bind the caller's cancel scope so disconnect cancels the waiter."""
        self._operation_scope = operation_scope

    def finish(self, result: PendingResult) -> None:
        """Complete the wait with a result; only the first completion wins."""
        if self._result is None:
            self._result = result
            self._event.set()

    def disconnect(self, connection_id: ConnectionId) -> None:
        """Fail the pending request because the connection closed."""
        self.finish(ConnectionClosedError(connection_id=connection_id))
        if self._operation_scope is not None:
            self._operation_scope.cancel()

    async def wait(self) -> ResponseMessage:
        """Suspend until the response arrives or the connection closes."""
        await self._event.wait()
        return self.result()

    def result(self) -> ResponseMessage:
        """Return the response or raise the captured connection error."""
        result = self._result
        assert result is not None
        match result:
            case ResponseMessage():
                return result
            case ConnectionClosedError():
                raise result
            case unreachable:
                assert_never(unreachable)


class ReverseProxySessionManager:
    """Mutable process-local registry for connections and request correlation."""

    def __init__(self) -> None:
        """Initialize empty connection and pending-response registries."""
        self._sessions: dict[ConnectionId, ReverseProxySession] = {}
        self._local_connections: dict[LocalSessionId, ConnectionId] = {}
        self._stable_connections: dict[StableGatewayId, ConnectionId] = {}
        self._pending: dict[PendingKey, _PendingResponse] = {}
        self._lock = anyio.Lock()

    async def connect(self, websocket: TextWebSocket, local_id: LocalSessionId) -> ReverseProxySession:
        """Register a connection using a fresh server-generated identity."""
        async with self._lock:
            if local_id in self._local_connections:
                raise DuplicateLocalSessionError(local_id=local_id)
            connection_id = ConnectionId(uuid.uuid4().hex)
            session = ReverseProxySession(connection_id=connection_id, local_id=local_id, websocket=websocket)
            self._sessions[connection_id] = session
            self._local_connections[local_id] = connection_id
            return session

    async def disconnect(self, connection_id: ConnectionId) -> None:
        """Remove a connection and fail all of its outstanding requests."""
        async with self._lock:
            session = self._sessions.pop(connection_id, None)
            if session is not None:
                self._local_connections.pop(session.local_id, None)
            keys = [key for key in self._pending if key[0] == connection_id]
            for key in keys:
                pending = self._pending.pop(key)
                pending.disconnect(connection_id)
            stable_ids = [sid for sid, cid in self._stable_connections.items() if cid == connection_id]
            for sid in stable_ids:
                self._stable_connections.pop(sid, None)

    async def send_request(self, connection_id: ConnectionId, payload: JsonRpcRequest, timeout_seconds: float) -> ResponseMessage:
        """Install correlation, send a request, and await its connection-scoped response."""
        session = self._sessions.get(connection_id)
        if session is None:
            raise ConnectionNotFoundError(connection_id=connection_id)
        request_id = payload.id
        if request_id is None:
            raise MissingRequestIdError(connection_id=connection_id)
        key = (connection_id, request_id)
        if key in self._pending:
            raise DuplicatePendingRequestError(connection_id=connection_id, request_id=request_id)
        pending = _PendingResponse()
        self._pending[key] = pending
        try:
            with anyio.fail_after(timeout_seconds):
                with anyio.CancelScope() as operation_scope:
                    pending.attach_operation_scope(operation_scope)
                    await session.websocket.send_text(encode_server_message(request(str(connection_id), payload)))
                    return await pending.wait()
                return pending.result()
        finally:
            if self._pending.get(key) is pending:
                self._pending.pop(key)

    async def send_notification(self, connection_id: ConnectionId, payload: JsonRpcNotification, timeout_seconds: float) -> None:
        """Send a notification without installing response correlation."""
        session = self._sessions.get(connection_id)
        if session is None:
            raise ConnectionNotFoundError(connection_id=connection_id)
        with anyio.fail_after(timeout_seconds):
            await session.websocket.send_text(encode_server_message(request(str(connection_id), payload)))

    def resolve_response(self, connection_id: ConnectionId, response: ResponseMessage) -> bool:
        """Resolve only the pending request owned by the responding connection."""
        request_id = response.payload.id
        pending = self._pending.pop((connection_id, request_id), None)
        if pending is None:
            return False
        pending.finish(response)
        return True

    def pending_count(self, connection_id: ConnectionId) -> int:
        """Return the outstanding request count for one connection."""
        return sum(key[0] == connection_id for key in self._pending)

    async def attach_stable_id(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> None:
        """Map a stable gateway identity to an active process-local connection.

        Replaces any existing mapping for ``stable_id`` (last-writer-wins).
        Raises ``ConnectionNotFoundError`` when ``connection_id`` is not active.
        """
        async with self._lock:
            if connection_id not in self._sessions:
                raise ConnectionNotFoundError(connection_id=connection_id)
            self._stable_connections[stable_id] = connection_id

    def resolve_connection_id(self, stable_id: StableGatewayId) -> ConnectionId | None:
        """Return the live connection identifier for ``stable_id`` or ``None`` when unknown."""
        return self._stable_connections.get(stable_id)


_default_manager: ReverseProxySessionManager | None = None
_manager_lock = anyio.Lock()


async def get_reverse_proxy_session_manager() -> ReverseProxySessionManager:
    """Return the process-default session manager, creating it lazily."""
    global _default_manager
    async with _manager_lock:
        if _default_manager is None:
            _default_manager = ReverseProxySessionManager()
        return _default_manager
