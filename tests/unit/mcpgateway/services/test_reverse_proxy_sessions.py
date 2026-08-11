# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_sessions.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for process-local reverse-proxy sessions and pending responses.
"""

import anyio
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

    async def send_text(self, data: str) -> None:
        self.frames.append(data)
        self.sent.set()


class FailingWebSocket:
    async def send_text(self, data: str) -> None:
        raise WebSocketSendError(data)


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
async def test_attach_stable_id_then_resolve_returns_connection_id() -> None:
    """Given an active connection, when a stable ID is attached, then resolve returns the connection ID."""
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")

    await manager.attach_stable_id(stable_id, session.connection_id)

    assert manager.resolve_connection_id(stable_id) == session.connection_id


@pytest.mark.asyncio
async def test_resolve_unknown_stable_id_returns_none() -> None:
    """Given no attachment, when an unknown stable ID is resolved, then None is returned without raising."""
    manager = ReverseProxySessionManager()

    assert manager.resolve_connection_id(StableGatewayId("unknown")) is None


@pytest.mark.asyncio
async def test_disconnect_clears_stable_mapping() -> None:
    """Given an attached stable ID, when the connection disconnects, then the stable ID resolves to None."""
    manager = ReverseProxySessionManager()
    session = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.attach_stable_id(stable_id, session.connection_id)

    await manager.disconnect(session.connection_id)

    assert manager.resolve_connection_id(stable_id) is None


@pytest.mark.asyncio
async def test_reattach_stable_id_replaces_mapping() -> None:
    """Given a stable ID attached to connection A, when re-attached to connection B, then resolve returns B."""
    manager = ReverseProxySessionManager()
    first = await manager.connect(RecordingWebSocket(), LocalSessionId("local-1"))
    second = await manager.connect(RecordingWebSocket(), LocalSessionId("local-2"))
    stable_id = StableGatewayId("stable-1")
    await manager.attach_stable_id(stable_id, first.connection_id)

    await manager.attach_stable_id(stable_id, second.connection_id)

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
    await manager.attach_stable_id(stable_a, first.connection_id)
    await manager.attach_stable_id(stable_b, second.connection_id)

    assert manager.resolve_connection_id(stable_a) == first.connection_id
    assert manager.resolve_connection_id(stable_b) == second.connection_id


@pytest.mark.asyncio
async def test_disconnect_still_raises_connection_closed_for_pending_calls() -> None:
    """Given a pending request and an attached stable ID, when disconnect occurs, then callers get ConnectionClosedError and the mapping clears."""
    manager = ReverseProxySessionManager()
    websocket = BlockingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("local-1"))
    stable_id = StableGatewayId("stable-1")
    await manager.attach_stable_id(stable_id, session.connection_id)
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
async def test_attach_stable_id_rejects_inactive_connection() -> None:
    """Given no active connection, when attaching a stable ID to it, then ConnectionNotFoundError is raised."""
    manager = ReverseProxySessionManager()

    with pytest.raises(ConnectionNotFoundError):
        await manager.attach_stable_id(StableGatewayId("stable-1"), ConnectionId("inactive"))


@pytest.mark.asyncio
async def test_get_reverse_proxy_session_manager_returns_singleton() -> None:
    """Given repeated calls, when the lazy accessor is invoked, then the same manager instance is returned."""
    first = await get_reverse_proxy_session_manager()
    second = await get_reverse_proxy_session_manager()

    assert first is second
