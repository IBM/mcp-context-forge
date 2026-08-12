# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_sessions.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Process-local reverse-proxy connections and pending responses.

``LocalSessionId`` is a non-authoritative admission nonce used only to reject
duplicate local connections. It does not convey ownership or access scope.
"""

from dataclasses import dataclass
import logging
from types import TracebackType
from typing import Final, NewType, Protocol, TypeAlias, assert_never
import uuid

import anyio

from mcpgateway.services.reverse_proxy_protocol import JsonRpcId, JsonRpcNotification, JsonRpcRequest, ResponseMessage, encode_server_message, request

logger = logging.getLogger(__name__)


ConnectionId = NewType("ConnectionId", str)
LocalSessionId = NewType("LocalSessionId", str)
StableGatewayId = NewType("StableGatewayId", str)  # persistent gateway identity used to locate a live reverse-proxy connection
PendingKey: TypeAlias = tuple[ConnectionId, JsonRpcId]

# Bounded best-effort socket close when retiring a displaced connection: the
# close serializes on the connection's own I/O lock, so a close stuck behind a
# stalled send must never hang the retiring registration.
_RETIRE_CLOSE_TIMEOUT_SECONDS: Final = 5.0


class TextWebSocket(Protocol):
    """Minimal WebSocket capability required by the session core."""

    async def send_text(self, data: str) -> None:
        """Send one serialized protocol frame."""

    async def close(self) -> None:
        """Close the transport; used when retiring a displaced connection."""


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


class _RegistrationLockEntry:
    """One per-stable-ID registration lock with its live-reference count."""

    __slots__ = ("lock", "refcount")

    def __init__(self) -> None:
        """Initialize an unlocked entry with no live references."""
        self.lock = anyio.Lock()
        self.refcount = 0


class _RegistrationLockGuard:
    """Async context manager for one acquisition of a per-stable-ID registration lock."""

    def __init__(self, manager: "ReverseProxySessionManager", stable_id: StableGatewayId, entry: _RegistrationLockEntry) -> None:
        """Bind the guard to its manager, stable ID, and shared lock entry."""
        self._manager = manager
        self._stable_id = stable_id
        self._entry = entry

    async def __aenter__(self) -> None:
        """Take a live reference, then acquire the lock.

        The refcount increment runs before the first await, so the
        get-or-create in :meth:`ReverseProxySessionManager.registration_lock`
        plus this increment are atomic on the event loop: an entry can never be
        discarded while a caller is queued on it.
        """
        entry = self._entry
        entry.refcount += 1
        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
        finally:
            if not acquired:
                # Acquisition abandoned (for example by cancellation): drop the
                # live reference so the entry can still be discarded.
                entry.refcount -= 1
                self._manager._discard_registration_lock_entry(self._stable_id, entry)

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        """Release the lock and discard the entry once its last reference is gone.

        No awaits after the release: the decrement-and-discard check is atomic
        on the event loop, so a concurrent acquirer cannot race the pop.
        """
        entry = self._entry
        entry.lock.release()
        entry.refcount -= 1
        self._manager._discard_registration_lock_entry(self._stable_id, entry)


class ReverseProxySessionManager:
    """Mutable process-local registry for connections and request correlation."""

    def __init__(self) -> None:
        """Initialize empty connection and pending-response registries."""
        self._sessions: dict[ConnectionId, ReverseProxySession] = {}
        self._local_connections: dict[LocalSessionId, ConnectionId] = {}
        self._stable_connections: dict[StableGatewayId, ConnectionId] = {}
        self._pending: dict[PendingKey, _PendingResponse] = {}
        self._registration_locks: dict[StableGatewayId, _RegistrationLockEntry] = {}
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

    def registration_lock(self, stable_id: StableGatewayId) -> _RegistrationLockGuard:
        """Return a guard acquiring the per-stable-ID registration lifecycle lock.

        The router holds the guard across quiesce, discovery, catalog publish,
        and promotion so two concurrent registrations for one stable identity
        cannot interleave. The get-or-create below awaits nothing, so it is
        atomic on the event loop together with the refcount increment at the
        start of the guard's ``__aenter__``; the guard must be entered
        immediately after it is created.

        Entries are reference-counted and discarded once the last acquisition
        releases, so the dict cannot churn-grow over the process lifetime.
        """
        entry = self._registration_locks.get(stable_id)
        if entry is None:
            entry = _RegistrationLockEntry()
            self._registration_locks[stable_id] = entry
        return _RegistrationLockGuard(self, stable_id, entry)

    def _discard_registration_lock_entry(self, stable_id: StableGatewayId, entry: _RegistrationLockEntry) -> None:
        """Drop the lock entry once no live references remain and the lock is unowned.

        Callers hold no locks; this method awaits nothing, so the check-and-pop
        is atomic on the event loop.
        """
        if entry.refcount == 0 and not entry.lock.locked() and self._registration_locks.get(stable_id) is entry:
            self._registration_locks.pop(stable_id, None)

    async def quiesce_stable_id(self, stable_id: StableGatewayId) -> ConnectionId | None:
        """Pop the current stable mapping and return the evicted predecessor, if any.

        From the moment this returns, dispatch for ``stable_id`` fails closed
        until a later promotion; the evicted connection itself stays live.
        """
        async with self._lock:
            return self._stable_connections.pop(stable_id, None)

    async def promote_stable_id(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> ConnectionId | None:
        """Map ``stable_id`` to ``connection_id``, returning the displaced predecessor.

        Raises ``ConnectionNotFoundError`` when ``connection_id`` is not active.
        The caller owns the displaced predecessor's lifecycle: retire it after
        the replacement is acknowledged, or restore it on post-promotion failure.
        """
        async with self._lock:
            if connection_id not in self._sessions:
                raise ConnectionNotFoundError(connection_id=connection_id)
            displaced = self._stable_connections.get(stable_id)
            self._stable_connections[stable_id] = connection_id
            return displaced

    async def restore_stable_id(self, stable_id: StableGatewayId, predecessor: ConnectionId | None, candidate_connection_id: ConnectionId) -> None:
        """Compare-and-swap the stable mapping after a registration failure.

        A mapping pointing at a connection that is neither ``predecessor`` nor
        ``candidate_connection_id`` has moved on (for example to a newer
        registration) and is left untouched. Otherwise the mapping is set to
        ``predecessor`` when one is given and still active - the pre-commit
        failure case, where the catalog was never replaced and the predecessor
        stays compatible. Failing that, the mapping is removed whenever it
        points at the candidate - the post-commit demote case - leaving the
        stable ID fail-closed rather than routed to an incompatible connection.
        """
        async with self._lock:
            current = self._stable_connections.get(stable_id)
            if current is not None and current not in (predecessor, candidate_connection_id):
                return
            if predecessor is not None and predecessor in self._sessions:
                self._stable_connections[stable_id] = predecessor
            elif current == candidate_connection_id:
                self._stable_connections.pop(stable_id, None)

    async def retire_connection(self, connection_id: ConnectionId) -> None:
        """Disconnect ``connection_id`` and best-effort close its socket wrapper, bounded.

        Used to retire a displaced predecessor after a replacement registration
        is acknowledged. Disconnect semantics are unchanged (idempotent; fails
        pending calls; pops only this connection's stable mappings). The close
        runs through the stored wrapper, which serializes it on the
        connection's own I/O lock, and is bounded by
        ``_RETIRE_CLOSE_TIMEOUT_SECONDS`` so a close stuck behind a stalled
        send can never hang the retiring registration. Timeouts and ordinary
        close errors are debug-logged because a displaced socket may already be
        lost; cancellation is never swallowed.
        """
        session = self._sessions.get(connection_id)
        await self.disconnect(connection_id)
        if session is None:
            return
        try:
            with anyio.fail_after(_RETIRE_CLOSE_TIMEOUT_SECONDS):
                await session.websocket.close()
        except Exception as close_error:  # best-effort: timeout, or a displaced socket already lost
            logger.debug("Reverse proxy retired connection %s close failed: %s", connection_id, close_error)

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
