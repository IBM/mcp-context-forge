# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_sessions.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for process-local reverse-proxy sessions and pending responses.
"""

from unittest.mock import patch

import anyio
from anyio.lowlevel import checkpoint
import pytest

from mcpgateway.services.reverse_proxy_protocol import JsonRpcNotification, JsonRpcRequest, JsonRpcSuccessResponse, ResponseMessage
from mcpgateway.services.reverse_proxy_sessions import (
    ConnectionClosedError,
    ConnectionId,
    ConnectionNotFoundError,
    DuplicateLocalSessionError,
    DuplicatePendingRequestError,
    LocalSessionId,
    ReverseProxySessionManager,
    StableGatewayId,
    get_reverse_proxy_session_manager,
)


class RecordingWebSocket:
    def __init__(self) -> None:
        self.frames: list[str] = []
        self.sent = anyio.Event()
        self.close_calls = 0

    async def send_text(self, data: str) -> None:
        self.frames.append(data)
        self.sent.set()

    async def close(self) -> None:
        self.close_calls += 1


class FailingWebSocket:
    async def send_text(self, data: str) -> None:
        raise WebSocketSendError(data)

    async def close(self) -> None:
        return None


class WebSocketSendError(Exception):
    pass


class ImmediateResponseWebSocket:
    def __init__(self, manager: ReverseProxySessionManager) -> None:
        self.manager = manager
        self.connection_id: ConnectionId | None = None
        self.pending_count_during_send = -1

    async def send_text(self, data: str) -> None:
        del data
        assert self.connection_id is not None
        self.pending_count_during_send = self.manager.pending_count(self.connection_id)
        response = ResponseMessage(type="response", payload=JsonRpcSuccessResponse.model_validate({"jsonrpc": "2.0", "id": 0, "result": "ok"}))
        assert self.manager.resolve_response(self.connection_id, response) is True

    async def close(self) -> None:
        return None


class CountingWebSocket:
    def __init__(self, expected_sends: int) -> None:
        self.expected_sends = expected_sends
        self.send_count = 0
        self.all_sent = anyio.Event()

    async def send_text(self, data: str) -> None:
        del data
        self.send_count += 1
        if self.send_count == self.expected_sends:
            self.all_sent.set()

    async def close(self) -> None:
        return None


class BlockingWebSocket:
    def __init__(self) -> None:
        self.entered = anyio.Event()
        self.cancelled = anyio.Event()

    async def send_text(self, data: str) -> None:
        del data
        self.entered.set()
        try:
            await anyio.sleep_forever()
        finally:
            self.cancelled.set()

    async def close(self) -> None:
        return None


class CloseFailingWebSocket:
    def __init__(self) -> None:
        self.close_calls = 0

    async def send_text(self, data: str) -> None:
        del data

    async def close(self) -> None:
        self.close_calls += 1
        raise ConnectionError("close on a lost socket")


class CloseStallingWebSocket:
    """Fake whose close suspends forever, as if stuck behind a stalled send."""

    def __init__(self) -> None:
        self.close_entered = anyio.Event()
        self.close_cancelled = anyio.Event()

    async def send_text(self, data: str) -> None:
        del data

    async def close(self) -> None:
        self.close_entered.set()
        try:
            await anyio.sleep_forever()
        finally:
            self.close_cancelled.set()


def _request_payload(request_id: str | int) -> JsonRpcRequest:
    return JsonRpcRequest.model_validate({"jsonrpc": "2.0", "id": request_id, "method": "tools/list"})


def _notification_payload() -> JsonRpcNotification:
    return JsonRpcNotification.model_validate({"jsonrpc": "2.0", "method": "notifications/initialized"})


def _response(request_id: str | int) -> ResponseMessage:
    return ResponseMessage(type="response", payload=JsonRpcSuccessResponse.model_validate({"jsonrpc": "2.0", "id": request_id, "result": {}}))


@pytest.mark.asyncio
async def test_connect_generates_server_owned_id_and_rejects_duplicate_local_id() -> None:
    manager = ReverseProxySessionManager()
    local_id = LocalSessionId("client-selected")

    first = await manager.connect(RecordingWebSocket(), local_id)

    assert first.connection_id != ConnectionId(local_id)
    with pytest.raises(DuplicateLocalSessionError):
        await manager.connect(RecordingWebSocket(), local_id)


@pytest.mark.asyncio
async def test_immediate_response_is_correlated_before_websocket_send() -> None:
    manager = ReverseProxySessionManager()
    websocket = ImmediateResponseWebSocket(manager)
    session = await manager.connect(websocket, LocalSessionId("local-1"))
    websocket.connection_id = session.connection_id

    response = await manager.send_request(session.connection_id, _request_payload(0), timeout_seconds=1)

    assert response.payload.id == 0
    assert websocket.pending_count_during_send == 1
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_response_cannot_resolve_another_connections_request() -> None:
    manager = ReverseProxySessionManager()
    websocket = RecordingWebSocket()
    first = await manager.connect(websocket, LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    received: list[ResponseMessage] = []

    async def send() -> None:
        received.append(await manager.send_request(first.connection_id, _request_payload("same-id"), timeout_seconds=1))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(send)
        await websocket.sent.wait()
        assert manager.resolve_response(second.connection_id, _response("same-id")) is False
        assert manager.pending_count(first.connection_id) == 1
        assert manager.resolve_response(first.connection_id, _response("same-id")) is True

    assert received[0].payload.id == "same-id"


@pytest.mark.asyncio
async def test_send_failure_removes_pending_response() -> None:
    manager = ReverseProxySessionManager()
    session = await manager.connect(FailingWebSocket(), LocalSessionId("local-1"))

    with pytest.raises(WebSocketSendError):
        await manager.send_request(session.connection_id, _request_payload("request-1"), timeout_seconds=1)

    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_timeout_removes_pending_response() -> None:
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))

    with pytest.raises(TimeoutError):
        await manager.send_request(session.connection_id, _request_payload("request-1"), timeout_seconds=0)

    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_send_notification_delivers_exact_envelope_without_pending_response() -> None:
    manager = ReverseProxySessionManager()
    websocket = RecordingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))

    await manager.send_notification(session.connection_id, _notification_payload(), timeout_seconds=1)

    assert websocket.frames == [f'{{"sessionId":"{session.connection_id}","type":"request","payload":{{"jsonrpc":"2.0","method":"notifications/initialized"}}}}']
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_send_notification_timeout_cancels_blocked_send_without_pending_response() -> None:
    manager = ReverseProxySessionManager()
    websocket = BlockingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))

    with pytest.raises(TimeoutError):
        await manager.send_notification(session.connection_id, _notification_payload(), timeout_seconds=0)

    assert websocket.cancelled.is_set()
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_send_notification_rejects_inactive_connection() -> None:
    manager = ReverseProxySessionManager()

    with pytest.raises(ConnectionNotFoundError):
        await manager.send_notification(ConnectionId("inactive"), _notification_payload(), timeout_seconds=1)


@pytest.mark.asyncio
async def test_timeout_covers_websocket_send_and_cancels_blocked_send() -> None:
    manager = ReverseProxySessionManager()
    websocket = BlockingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))

    with pytest.raises(TimeoutError):
        await manager.send_request(session.connection_id, _request_payload("request-1"), timeout_seconds=0)

    assert websocket.cancelled.is_set()
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_disconnect_cancels_blocked_send_and_surfaces_connection_closed() -> None:
    manager = ReverseProxySessionManager()
    websocket = BlockingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))
    disconnected = anyio.Event()

    async def send() -> None:
        with pytest.raises(ConnectionClosedError):
            await manager.send_request(session.connection_id, _request_payload("request-1"), timeout_seconds=10)
        disconnected.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(send)
        await websocket.entered.wait()
        await manager.disconnect(session.connection_id)
        await disconnected.wait()

    assert websocket.cancelled.is_set()
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_caller_cancellation_cancels_blocked_send_and_cleans_pending() -> None:
    manager = ReverseProxySessionManager()
    websocket = BlockingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(manager.send_request, session.connection_id, _request_payload("request-1"), 10)
        await websocket.entered.wait()
        task_group.cancel_scope.cancel()

    assert websocket.cancelled.is_set()
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_duplicate_pending_id_is_rejected_per_connection() -> None:
    manager = ReverseProxySessionManager()
    websocket = BlockingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))

    async def send_first() -> None:
        with pytest.raises(ConnectionClosedError):
            await manager.send_request(session.connection_id, _request_payload("same-id"), timeout_seconds=10)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(send_first)
        await websocket.entered.wait()
        with pytest.raises(DuplicatePendingRequestError):
            await manager.send_request(session.connection_id, _request_payload("same-id"), timeout_seconds=10)
        await manager.disconnect(session.connection_id)


@pytest.mark.asyncio
async def test_late_response_after_timeout_is_ignored() -> None:
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))

    with pytest.raises(TimeoutError):
        await manager.send_request(session.connection_id, _request_payload("request-1"), timeout_seconds=0)

    assert manager.resolve_response(session.connection_id, _response("request-1")) is False
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_same_request_id_resolves_independently_on_two_connections() -> None:
    manager = ReverseProxySessionManager()
    first_websocket = RecordingWebSocket()
    second_websocket = RecordingWebSocket()
    first = await manager.connect(first_websocket, LocalSessionId("local-1"))
    second = await manager.connect(second_websocket, LocalSessionId("local-2"))
    received: dict[ConnectionId, ResponseMessage] = {}

    async def send(connection_id: ConnectionId) -> None:
        received[connection_id] = await manager.send_request(connection_id, _request_payload("same-id"), timeout_seconds=1)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(send, first.connection_id)
        task_group.start_soon(send, second.connection_id)
        await first_websocket.sent.wait()
        await second_websocket.sent.wait()
        assert manager.resolve_response(first.connection_id, _response("same-id")) is True
        assert manager.resolve_response(second.connection_id, _response("same-id")) is True

    assert set(received) == {first.connection_id, second.connection_id}


@pytest.mark.asyncio
async def test_caller_cancellation_removes_pending_response() -> None:
    manager = ReverseProxySessionManager()
    websocket = RecordingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(manager.send_request, session.connection_id, _request_payload("request-1"), 10)
        await websocket.sent.wait()
        task_group.cancel_scope.cancel()

    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_disconnect_cancels_every_pending_connection_request() -> None:
    manager = ReverseProxySessionManager()
    websocket = CountingWebSocket(expected_sends=2)
    session = await manager.connect(websocket, LocalSessionId("local-1"))
    disconnected: list[str | int] = []

    async def send(request_id: str | int) -> None:
        with pytest.raises(ConnectionClosedError):
            await manager.send_request(session.connection_id, _request_payload(request_id), timeout_seconds=10)
        disconnected.append(request_id)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(send, "request-1")
        task_group.start_soon(send, "request-2")
        await websocket.all_sent.wait()
        await manager.disconnect(session.connection_id)

    assert set(disconnected) == {"request-1", "request-2"}
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_disconnect_allows_local_id_to_reconnect() -> None:
    manager = ReverseProxySessionManager()
    local_id = LocalSessionId("local-1")
    session = await manager.connect(RecordingWebSocket(), local_id)

    await manager.disconnect(session.connection_id)
    replacement = await manager.connect(RecordingWebSocket(), local_id)

    assert replacement.connection_id != session.connection_id


@pytest.mark.asyncio
async def test_promote_stable_id_then_resolve_returns_connection_id() -> None:
    """Given an active connection, when a stable ID is promoted to it, then resolve returns the connection ID and nothing is displaced."""
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")

    displaced = await manager.promote_stable_id(stable_id, session.connection_id)

    assert displaced is None
    assert manager.resolve_connection_id(stable_id) == session.connection_id


@pytest.mark.asyncio
async def test_resolve_unknown_stable_id_returns_none() -> None:
    """Given no attachment, when an unknown stable ID is resolved, then None is returned without raising."""
    manager = ReverseProxySessionManager()

    assert manager.resolve_connection_id(StableGatewayId("unknown")) is None


@pytest.mark.asyncio
async def test_disconnect_clears_stable_mapping() -> None:
    """Given a promoted stable ID, when the connection disconnects, then the stable ID resolves to None."""
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)

    await manager.disconnect(session.connection_id)

    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_promote_stable_id_replaces_mapping_and_returns_displaced_predecessor() -> None:
    """Given a stable ID promoted to A, when promoted to B, then resolve returns B and the promotion reports A as displaced."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, first.connection_id)

    displaced = await manager.promote_stable_id(stable_id, second.connection_id)

    assert displaced == first.connection_id
    assert manager.resolve_connection_id(stable_id) == second.connection_id
    assert first.connection_id != second.connection_id


@pytest.mark.asyncio
async def test_stable_mapping_is_isolated_per_connection() -> None:
    """Given two connections with distinct stable IDs, when resolving each, then the correct connection ID is returned."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    stable_a = StableGatewayId("stable-a")
    stable_b = StableGatewayId("stable-b")
    await manager.promote_stable_id(stable_a, first.connection_id)
    await manager.promote_stable_id(stable_b, second.connection_id)

    assert manager.resolve_connection_id(stable_a) == first.connection_id
    assert manager.resolve_connection_id(stable_b) == second.connection_id


@pytest.mark.asyncio
async def test_disconnect_still_raises_connection_closed_for_pending_calls() -> None:
    """Given a pending request and a promoted stable ID, when disconnect occurs, then callers get ConnectionClosedError and the mapping clears."""
    manager = ReverseProxySessionManager()
    websocket = BlockingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)
    disconnected = anyio.Event()

    async def send() -> None:
        with pytest.raises(ConnectionClosedError):
            await manager.send_request(session.connection_id, _request_payload("request-1"), timeout_seconds=10)
        disconnected.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(send)
        await websocket.entered.wait()
        await manager.disconnect(session.connection_id)
        await disconnected.wait()

    assert manager.resolve_connection_id(stable_id) is None
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_promote_stable_id_rejects_inactive_connection() -> None:
    """Given no active connection, when promoting a stable ID to it, then ConnectionNotFoundError is raised."""
    manager = ReverseProxySessionManager()

    with pytest.raises(ConnectionNotFoundError):
        await manager.promote_stable_id(StableGatewayId("stable-1"), ConnectionId("inactive"))


@pytest.mark.asyncio
async def test_get_reverse_proxy_session_manager_returns_singleton() -> None:
    """Given repeated calls, when the lazy accessor is invoked, then the same manager instance is returned."""
    first = await get_reverse_proxy_session_manager()
    second = await get_reverse_proxy_session_manager()

    assert first is second


@pytest.mark.asyncio
async def test_registration_lock_is_shared_per_stable_id_and_distinct_across_ids() -> None:
    """Given a stable ID, when registration guards are requested twice, then both share one lock entry; another ID gets its own entry."""
    manager = ReverseProxySessionManager()

    first = manager.registration_lock(StableGatewayId("stable-1"))
    second = manager.registration_lock(StableGatewayId("stable-1"))
    other = manager.registration_lock(StableGatewayId("stable-2"))

    assert first._entry is second._entry
    assert other._entry is not first._entry


@pytest.mark.asyncio
async def test_registration_lock_entry_is_discarded_after_last_release() -> None:
    """Given a completed registration-lock acquisition, when the guard exits, then the per-stable-ID entry is discarded rather than retained."""
    manager = ReverseProxySessionManager()
    stable_id = StableGatewayId("stable-1")

    async with manager.registration_lock(stable_id):
        assert manager._registration_locks.get(stable_id) is not None

    assert manager._registration_locks.get(stable_id) is None


@pytest.mark.asyncio
async def test_registration_lock_cancelled_acquisition_does_not_leak_entry() -> None:
    """Given a waiter cancelled while acquiring the registration lock, when the holder releases, then the entry is still discarded."""
    manager = ReverseProxySessionManager()
    stable_id = StableGatewayId("stable-1")

    async def waiter() -> None:
        async with manager.registration_lock(stable_id):
            pass  # never reached: the holder keeps the lock until the waiter is cancelled

    async with manager.registration_lock(stable_id):
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(waiter)
            await checkpoint()
            task_group.cancel_scope.cancel()
        assert manager._registration_locks.get(stable_id) is not None

    assert manager._registration_locks.get(stable_id) is None


@pytest.mark.asyncio
async def test_quiesce_stable_id_returns_evicted_predecessor_and_unmaps() -> None:
    """Given A promoted, when the stable ID is quiesced, then A's connection ID is returned and the stable ID resolves to None while A stays connected."""
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)

    evicted = await manager.quiesce_stable_id(stable_id)

    assert evicted == session.connection_id
    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_quiesce_stable_id_returns_none_when_unmapped() -> None:
    """Given no mapping, when an unknown stable ID is quiesced, then None is returned without raising."""
    manager = ReverseProxySessionManager()

    assert await manager.quiesce_stable_id(StableGatewayId("unknown")) is None


@pytest.mark.asyncio
async def test_restore_stable_id_restores_predecessor_into_quiesced_mapping() -> None:
    """Given A quiesced (mapping absent), when a pre-commit failure restores, then the mapping points back at the still-active A."""
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)
    evicted = await manager.quiesce_stable_id(stable_id)

    await manager.restore_stable_id(stable_id, evicted, ConnectionId("candidate-never-promoted"))

    assert manager.resolve_connection_id(stable_id) == session.connection_id


@pytest.mark.asyncio
async def test_restore_stable_id_keeps_mapping_absent_when_predecessor_inactive() -> None:
    """Given A quiesced and then disconnected, when a pre-commit failure restores, then the mapping stays absent rather than routing to the dead predecessor."""
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)
    evicted = await manager.quiesce_stable_id(stable_id)
    await manager.disconnect(session.connection_id)

    await manager.restore_stable_id(stable_id, evicted, ConnectionId("candidate-never-promoted"))

    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_restore_stable_id_demotes_candidate_without_predecessor_restore() -> None:
    """Given the mapping points at the promoted candidate, when a post-commit failure restores with no predecessor, then the mapping is popped (fail-closed)."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, first.connection_id)
    await manager.quiesce_stable_id(stable_id)
    await manager.promote_stable_id(stable_id, second.connection_id)

    await manager.restore_stable_id(stable_id, None, second.connection_id)

    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_promote_stable_id_after_quiesce_displaces_nothing() -> None:
    """Given a quiesced stable ID, when the candidate promotes, then nothing is displaced because the mapping was already absent."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, first.connection_id)
    await manager.quiesce_stable_id(stable_id)

    displaced = await manager.promote_stable_id(stable_id, second.connection_id)

    assert displaced is None
    assert manager.resolve_connection_id(stable_id) == second.connection_id


@pytest.mark.asyncio
async def test_retire_connection_bounds_a_stalled_close() -> None:
    """Given a close stuck behind the connection's I/O, when the connection is retired, then the close is cancelled by the retire timeout and cleanup still completes."""
    manager = ReverseProxySessionManager()
    websocket = CloseStallingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)

    with patch("mcpgateway.services.reverse_proxy_sessions._RETIRE_CLOSE_TIMEOUT_SECONDS", 0.05):
        with anyio.fail_after(5):
            await manager.retire_connection(session.connection_id)

    assert websocket.close_entered.is_set()
    assert websocket.close_cancelled.is_set()
    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_registration_lock_serializes_same_stable_id() -> None:
    """Given one stable ID, when a second task requests its registration lock while held, then the second task waits for the first to release."""
    manager = ReverseProxySessionManager()
    stable_id = StableGatewayId("stable-1")
    entered = anyio.Event()
    acquired = anyio.Event()

    async def second() -> None:
        entered.set()
        async with manager.registration_lock(stable_id):
            acquired.set()

    async with anyio.create_task_group() as task_group:
        async with manager.registration_lock(stable_id):
            task_group.start_soon(second)
            await entered.wait()
            await checkpoint()
            assert not acquired.is_set()
            async with manager.registration_lock(StableGatewayId("stable-2")):
                pass  # a distinct stable ID is never blocked by the held lock
        await acquired.wait()


@pytest.mark.asyncio
async def test_restore_stable_id_restores_still_active_predecessor() -> None:
    """Given B displaced A, when B's post-promotion failure is restored, then the mapping returns to the still-active A."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, first.connection_id)
    displaced = await manager.promote_stable_id(stable_id, second.connection_id)

    await manager.restore_stable_id(stable_id, displaced, second.connection_id)

    assert manager.resolve_connection_id(stable_id) == first.connection_id


@pytest.mark.asyncio
async def test_restore_stable_id_pops_mapping_when_predecessor_inactive() -> None:
    """Given B displaced A and A disconnected, when B's failure is restored, then the mapping is removed rather than routed to the dead predecessor."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, first.connection_id)
    displaced = await manager.promote_stable_id(stable_id, second.connection_id)
    await manager.disconnect(first.connection_id)

    await manager.restore_stable_id(stable_id, displaced, second.connection_id)

    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_restore_stable_id_pops_mapping_when_no_predecessor() -> None:
    """Given a first-time promotion with no predecessor, when its failure is restored, then the mapping is removed."""
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)

    await manager.restore_stable_id(stable_id, None, session.connection_id)

    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_restore_stable_id_is_noop_when_mapping_moved_on() -> None:
    """Given C displaced B after B displaced A, when B's stale failure is restored, then the mapping still routes to C."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    third = await manager.connect(RecordingWebSocket(), LocalSessionId("local-3"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, first.connection_id)
    displaced = await manager.promote_stable_id(stable_id, second.connection_id)
    await manager.promote_stable_id(stable_id, third.connection_id)

    await manager.restore_stable_id(stable_id, displaced, second.connection_id)

    assert manager.resolve_connection_id(stable_id) == third.connection_id


@pytest.mark.asyncio
async def test_disconnect_pops_only_own_stable_mappings() -> None:
    """Given B displaced A, when A disconnects, then the stable mapping still routes to B."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, first.connection_id)
    await manager.promote_stable_id(stable_id, second.connection_id)

    await manager.disconnect(first.connection_id)

    assert manager.resolve_connection_id(stable_id) == second.connection_id


@pytest.mark.asyncio
async def test_retire_connection_fails_pending_clears_mapping_and_closes_socket() -> None:
    """Given a promoted connection with a pending call, when retired, then the caller fails, the mapping clears, and the socket close is attempted."""
    manager = ReverseProxySessionManager()
    websocket = RecordingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)
    disconnected = anyio.Event()

    async def send() -> None:
        with pytest.raises(ConnectionClosedError):
            await manager.send_request(session.connection_id, _request_payload("request-1"), timeout_seconds=10)
        disconnected.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(send)
        await websocket.sent.wait()
        await manager.retire_connection(session.connection_id)
        await disconnected.wait()

    assert manager.resolve_connection_id(stable_id) is None
    assert websocket.close_calls == 1
    assert manager.pending_count(session.connection_id) == 0


@pytest.mark.asyncio
async def test_retire_connection_keeps_replacement_mapping() -> None:
    """Given B displaced A, when A is retired, then the mapping still routes to B and only A's socket is closed."""
    manager = ReverseProxySessionManager()
    first_websocket = RecordingWebSocket()
    second_websocket = RecordingWebSocket()
    first = await manager.connect(first_websocket, LocalSessionId("local-1"))
    second = await manager.connect(second_websocket, LocalSessionId("local-2"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, first.connection_id)
    await manager.promote_stable_id(stable_id, second.connection_id)

    await manager.retire_connection(first.connection_id)

    assert manager.resolve_connection_id(stable_id) == second.connection_id
    assert first_websocket.close_calls == 1
    assert second_websocket.close_calls == 0


@pytest.mark.asyncio
async def test_retire_connection_swallows_close_errors() -> None:
    """Given a socket whose close raises, when its connection is retired, then cleanup completes and the close error does not propagate."""
    manager = ReverseProxySessionManager()
    websocket = CloseFailingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.promote_stable_id(stable_id, session.connection_id)

    await manager.retire_connection(session.connection_id)

    assert websocket.close_calls == 1
    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_retire_connection_is_idempotent_for_unknown_connection() -> None:
    """Given an inactive connection, when retired, then nothing happens and no error is raised."""
    manager = ReverseProxySessionManager()

    await manager.retire_connection(ConnectionId("inactive"))
