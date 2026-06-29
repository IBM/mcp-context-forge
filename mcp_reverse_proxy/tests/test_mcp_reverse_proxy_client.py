# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/tests/test_mcp_reverse_proxy_client.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the reverse proxy multi-transport client module.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

# Third-Party
import pytest

# First-Party
from mcp_reverse_proxy.base import ConnectionState, MessageType
import mcp_reverse_proxy.client as client_mod
from mcp_reverse_proxy.client import ReverseProxyClient, SessionExpiredError, StdioSubprocessTerminated


class FakeMcpTransport:
    """Simple MCP transport fake for unit tests."""

    def __init__(self) -> None:
        self.handlers: list[Any] = []
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.send = AsyncMock()
        self.set_authentication = AsyncMock()
        self._connected = True
        self._message_endpoint = "/messages"
        self._session_id = "mcp-session"
        self.process = SimpleNamespace(returncode=None)

    def add_message_handler(self, handler) -> None:
        self.handlers.append(handler)


class FakeGatewayTransport:
    """Simple gateway transport fake for unit tests."""

    def __init__(self) -> None:
        self.handlers: list[Any] = []
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()
        self.send = AsyncMock()
        self.is_connected = AsyncMock(return_value=True)

    def add_message_handler(self, handler) -> None:
        self.handlers.append(handler)


@pytest.fixture
def transports():
    """Create paired fake transports."""
    return FakeMcpTransport(), FakeGatewayTransport()


@pytest.fixture
def proxy_client(transports) -> ReverseProxyClient:
    """Create a reverse proxy client with fake transports."""
    mcp_transport, gateway_transport = transports
    return ReverseProxyClient(
        mcp_transport=mcp_transport,
        gateway_transport=gateway_transport,
        session_id="session-12345678",
        server_name="Test Server",
        server_description="Test Description",
        reconnect_delay=0.01,
        keepalive_interval=0.01,
    )


def test_init_registers_message_handlers_and_defaults(transports) -> None:
    """Client initialization should wire handlers and defaults."""
    mcp_transport, gateway_transport = transports

    client = ReverseProxyClient(
        mcp_transport=mcp_transport,
        gateway_transport=gateway_transport,
        session_id="abcdef123456",
    )

    assert client.server_name == "reverse-proxy-abcdef12"
    assert client.description == "Reverse proxied MCP server"
    assert client.state == ConnectionState.DISCONNECTED
    assert len(mcp_transport.handlers) == 1
    assert len(gateway_transport.handlers) == 1


@pytest.mark.asyncio
async def test_connect_starts_transports_registers_and_creates_keepalive_task(proxy_client, monkeypatch) -> None:
    """Connect should start transports, register, and launch keepalive."""
    register_mock = AsyncMock()
    keepalive_mock = AsyncMock()
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=True))
    monkeypatch.setattr(proxy_client, "_register", register_mock)
    monkeypatch.setattr(proxy_client, "_keepalive_loop", keepalive_mock)

    await proxy_client.connect()

    assert proxy_client.state == ConnectionState.CONNECTED
    assert proxy_client.retry_count == 0
    proxy_client.mcp_transport.start.assert_awaited_once()
    proxy_client.gateway_transport.connect.assert_awaited_once()
    register_mock.assert_awaited_once()
    assert proxy_client._keepalive_task is not None

    proxy_client._keepalive_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await proxy_client._keepalive_task


@pytest.mark.asyncio
async def test_connect_raises_when_mcp_health_check_fails(proxy_client, monkeypatch) -> None:
    """Connect should abort before gateway connection when MCP is unhealthy."""
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=False))

    with pytest.raises(RuntimeError, match="MCP server is not reachable"):
        await proxy_client.connect()

    assert proxy_client.state == ConnectionState.DISCONNECTED
    proxy_client.mcp_transport.start.assert_awaited_once()
    proxy_client.gateway_transport.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnect_sends_unregister_and_stops_transports(proxy_client) -> None:
    """Disconnect should cancel keepalive, unregister, and stop both transports."""
    proxy_client.state = ConnectionState.CONNECTED
    proxy_client._keepalive_task = asyncio.create_task(asyncio.sleep(10))
    proxy_client.gateway_transport.is_connected.return_value = True

    await proxy_client.disconnect()

    assert proxy_client.state == ConnectionState.DISCONNECTED
    proxy_client.gateway_transport.send.assert_awaited_once()
    unregister_payload = proxy_client.gateway_transport.send.await_args.args[0]
    assert MessageType.UNREGISTER.value in unregister_payload
    proxy_client.gateway_transport.disconnect.assert_awaited_once()
    proxy_client.mcp_transport.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_returns_immediately_when_already_shutting_down(proxy_client) -> None:
    """Disconnect should be a no-op when shutdown is already in progress."""
    proxy_client.state = ConnectionState.SHUTTING_DOWN

    await proxy_client.disconnect()

    proxy_client.gateway_transport.disconnect.assert_not_awaited()
    proxy_client.mcp_transport.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_sends_registration_envelope(proxy_client) -> None:
    """Register should send the correct gateway registration message."""
    await proxy_client._register()

    proxy_client.gateway_transport.send.assert_awaited_once()
    register_payload = proxy_client.gateway_transport.send.await_args.args[0]
    assert MessageType.REGISTER.value in register_payload
    assert proxy_client.session_id in register_payload
    assert proxy_client.server_name in register_payload


@pytest.mark.asyncio
async def test_handle_mcp_message_resolves_pending_health_check_future(proxy_client) -> None:
    """Health check responses should resolve pending future without gateway forwarding."""
    future: asyncio.Future[Any] = asyncio.Future()
    proxy_client._pending_requests["health_check_123"] = future

    await proxy_client._handle_mcp_message('{"jsonrpc":"2.0","id":"health_check_123","result":{"ok":true}}')

    assert future.done()
    assert future.result()["result"] == {"ok": True}
    proxy_client.gateway_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_mcp_message_resolves_pending_request_with_response_envelope(proxy_client) -> None:
    """Pending non-health responses should resolve with a gateway envelope."""
    future: asyncio.Future[Any] = asyncio.Future()
    proxy_client._pending_requests[7] = future

    await proxy_client._handle_mcp_message('{"jsonrpc":"2.0","id":7,"result":{"value":1}}')

    assert future.done()
    result = future.result()
    assert result["type"] == MessageType.RESPONSE.value
    assert result["sessionId"] == proxy_client.session_id
    assert result["payload"]["result"] == {"value": 1}


@pytest.mark.asyncio
async def test_handle_mcp_message_forwards_notification_to_gateway(proxy_client) -> None:
    """Non-pending notifications should be forwarded to the gateway."""
    await proxy_client._handle_mcp_message('{"jsonrpc":"2.0","method":"notifications/test","params":{"x":1}}')

    proxy_client.gateway_transport.send.assert_awaited_once()
    forwarded = proxy_client.gateway_transport.send.await_args.args[0]
    assert MessageType.NOTIFICATION.value in forwarded
    assert proxy_client.session_id in forwarded


@pytest.mark.asyncio
async def test_handle_gateway_request_sets_auth_and_forwards_to_mcp(proxy_client) -> None:
    """Gateway request should set auth and forward the payload to MCP."""
    message = """
    {
      "type": "request",
      "payload": {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
      "authentication": {"Authorization": "Bearer token"},
      "authType": "bearer"
    }
    """.strip()

    await proxy_client._handle_gateway_message(message)

    proxy_client.mcp_transport.set_authentication.assert_called_once_with({"Authorization": "Bearer token"}, "bearer")
    proxy_client.mcp_transport.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_gateway_request_sends_error_when_transport_unavailable_and_health_fails(proxy_client, monkeypatch) -> None:
    """Connection-related MCP errors should return an error when health check fails."""
    proxy_client.mcp_transport.send.side_effect = RuntimeError("Not connected")
    send_error_mock = AsyncMock()
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=False))
    monkeypatch.setattr(proxy_client, "_send_error_response", send_error_mock)

    await proxy_client._handle_gateway_message('{"type":"request","payload":{"jsonrpc":"2.0","id":5,"method":"x"}}')

    send_error_mock.assert_awaited_once()
    assert proxy_client._pending_reregistration_request is None


@pytest.mark.asyncio
async def test_handle_gateway_request_stores_pending_and_reregisters_when_health_recovers(proxy_client, monkeypatch) -> None:
    """Recoverable transport errors should save the request and trigger re-registration."""
    proxy_client.mcp_transport.send.side_effect = SessionExpiredError("expired")
    register_mock = AsyncMock()
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=True))
    monkeypatch.setattr(proxy_client, "_register", register_mock)

    await proxy_client._handle_gateway_message(
        '{"type":"request","payload":{"jsonrpc":"2.0","id":9,"method":"x"},"authentication":{"Authorization":"Bearer t"},"authType":"bearer"}'
    )

    assert proxy_client._pending_reregistration_request == {
        "payload": {"jsonrpc": "2.0", "id": 9, "method": "x"},
        "authentication": {"Authorization": "Bearer t"},
        "authType": "bearer",
    }
    assert proxy_client._registration_successful is False
    register_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_gateway_request_reraises_non_connection_runtime_error(proxy_client, monkeypatch) -> None:
    """Non-connection runtime errors should be re-raised then logged by the outer handler."""
    proxy_client.mcp_transport.send.side_effect = RuntimeError("different failure")
    check_health_mock = AsyncMock()
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", check_health_mock)

    await proxy_client._handle_gateway_message('{"type":"request","payload":{"jsonrpc":"2.0","id":11,"method":"x"}}')

    check_health_mock.assert_not_awaited()
    assert proxy_client._pending_reregistration_request is None


@pytest.mark.asyncio
async def test_handle_gateway_register_complete_retries_pending_request(proxy_client) -> None:
    """Successful register_complete should retry a stored request and restore auth."""
    proxy_client._pending_reregistration_request = {
        "payload": {"jsonrpc": "2.0", "id": 21, "method": "retry"},
        "authentication": {"Authorization": "Bearer token"},
        "authType": "bearer",
    }

    await proxy_client._handle_gateway_message('{"type":"register_complete","status":"success","sessionId":"session-12345678"}')

    assert proxy_client._registration_successful is True
    assert proxy_client._pending_reregistration_request is None
    proxy_client.mcp_transport.set_authentication.assert_called_once_with({"Authorization": "Bearer token"}, "bearer")
    proxy_client.mcp_transport.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_gateway_register_complete_sends_error_if_retry_fails(proxy_client, monkeypatch) -> None:
    """Retry failure after successful registration should send an error response."""
    proxy_client._pending_reregistration_request = {
        "payload": {"jsonrpc": "2.0", "id": 22, "method": "retry"},
        "authentication": None,
        "authType": None,
    }
    proxy_client.mcp_transport.send.side_effect = RuntimeError("retry failed")
    send_error_mock = AsyncMock()
    monkeypatch.setattr(proxy_client, "_send_error_response", send_error_mock)

    await proxy_client._handle_gateway_message('{"type":"register_complete","status":"success","sessionId":"session-12345678"}')

    send_error_mock.assert_awaited_once()
    assert proxy_client._pending_reregistration_request is None


@pytest.mark.asyncio
async def test_handle_gateway_register_complete_failure_schedules_disconnect(proxy_client, monkeypatch) -> None:
    """Failed registration completion should schedule disconnect."""
    created_tasks: list[asyncio.Task[Any]] = []

    original_create_task = asyncio.create_task

    def _capture_task(coro):
        task = original_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", _capture_task)
    disconnect_mock = AsyncMock()
    monkeypatch.setattr(proxy_client, "disconnect", disconnect_mock)

    await proxy_client._handle_gateway_message('{"type":"register_complete","status":"error","message":"bad","sessionId":"session-12345678"}')

    assert proxy_client._registration_successful is False
    assert len(created_tasks) == 1
    await created_tasks[0]
    disconnect_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_stdio_running_process(proxy_client) -> None:
    """Healthy stdio process should report healthy."""
    proxy_client.mcp_transport.process = SimpleNamespace(returncode=None)
    proxy_client.mcp_transport.__class__.__name__ = "StdioAdapter"

    assert await proxy_client._check_mcp_server_health() is True


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_stdio_terminated_process_raises(proxy_client) -> None:
    """Terminated stdio subprocess should raise shutdown exception."""
    proxy_client.mcp_transport.process = SimpleNamespace(returncode=17)
    proxy_client.mcp_transport.__class__.__name__ = "StdioAdapter"

    with pytest.raises(StdioSubprocessTerminated, match="returncode=17"):
        await proxy_client._check_mcp_server_health()


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_sse_requires_receive_task(proxy_client) -> None:
    """SSE transport without a running receive task should be unhealthy."""
    proxy_client.mcp_transport.__class__.__name__ = "SseAdapter"
    proxy_client.mcp_transport._receive_task = None

    assert await proxy_client._check_mcp_server_health() is False


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_http_transport_uses_head_request(proxy_client) -> None:
    """HTTP transport should use HEAD request reachability check."""
    proxy_client.mcp_transport.__class__.__name__ = "StreamableHttpAdapter"
    proxy_client.mcp_transport._client = SimpleNamespace(head=AsyncMock(return_value=SimpleNamespace(status_code=401)))
    proxy_client.mcp_transport.server_url = "https://server.example/mcp"

    assert await proxy_client._check_mcp_server_health() is True


@pytest.mark.asyncio
async def test_check_mcp_server_health_attempts_reconnect_when_transport_disconnected(proxy_client, monkeypatch) -> None:
    """Disconnected transport should attempt stop/start recovery before failing."""
    proxy_client.mcp_transport._connected = False
    proxy_client.mcp_transport._message_endpoint = "/messages"
    start_mock = AsyncMock(side_effect=lambda: setattr(proxy_client.mcp_transport, "_connected", False))
    stop_mock = AsyncMock()
    proxy_client.mcp_transport.start = start_mock
    proxy_client.mcp_transport.stop = stop_mock
    sleep_mock = AsyncMock()
    monkeypatch.setattr(client_mod.asyncio, "sleep", sleep_mock)

    assert await proxy_client._check_mcp_server_health() is False
    stop_mock.assert_awaited_once()
    start_mock.assert_awaited_once()
    sleep_mock.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_send_error_response_requires_request_id(proxy_client) -> None:
    """Missing request ID should skip sending an error envelope."""
    await proxy_client._send_error_response({"jsonrpc": "2.0"}, "broken")

    proxy_client.gateway_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_error_response_sends_gateway_envelope(proxy_client) -> None:
    """Error response should be wrapped and sent to the gateway."""
    await proxy_client._send_error_response({"jsonrpc": "2.0", "id": 33}, "broken")

    proxy_client.gateway_transport.send.assert_awaited_once()
    payload = proxy_client.gateway_transport.send.await_args.args[0]
    assert MessageType.RESPONSE.value in payload
    assert '"id":33' in payload or '"id": 33' in payload
    assert "broken" in payload

# Made with Bob


@pytest.mark.asyncio
async def test_run_with_reconnect_breaks_immediately_when_shutting_down(proxy_client) -> None:
    """Reconnect loop should exit immediately during shutdown."""
    proxy_client.state = ConnectionState.SHUTTING_DOWN

    await proxy_client.run_with_reconnect()

    proxy_client.mcp_transport.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_with_reconnect_breaks_after_connect_if_shutdown_state_set(proxy_client, monkeypatch) -> None:
    """Reconnect loop should stop once connect transitions to shutting down."""
    connect_mock = AsyncMock(side_effect=lambda: setattr(proxy_client, "state", ConnectionState.SHUTTING_DOWN))
    monkeypatch.setattr(proxy_client, "connect", connect_mock)

    await proxy_client.run_with_reconnect()

    connect_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_with_reconnect_reraises_stdio_exception_from_connect(proxy_client, monkeypatch) -> None:
    """Stdio termination during connect should be re-raised."""
    monkeypatch.setattr(proxy_client, "connect", AsyncMock(side_effect=StdioSubprocessTerminated("dead")))

    with pytest.raises(StdioSubprocessTerminated):
        await proxy_client.run_with_reconnect()


@pytest.mark.asyncio
async def test_run_with_reconnect_disconnects_when_keepalive_task_fails(proxy_client, monkeypatch) -> None:
    """Reconnect loop should disconnect when keepalive task fails."""
    first_connect = True

    async def _fake_connect() -> None:
        nonlocal first_connect
        proxy_client.state = ConnectionState.CONNECTED
        if first_connect:
            # Create a failed task directly by creating a done task with an exception
            task = asyncio.create_task(asyncio.sleep(0))
            await task  # Let it complete
            # Now create a new task and set its exception
            proxy_client._keepalive_task = asyncio.Future()
            proxy_client._keepalive_task.set_exception(RuntimeError("keepalive failed"))
            first_connect = False
        else:
            proxy_client.state = ConnectionState.SHUTTING_DOWN

    monkeypatch.setattr(proxy_client, "connect", _fake_connect)
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=True))
    monkeypatch.setattr(client_mod.asyncio, "sleep", AsyncMock())

    await proxy_client.run_with_reconnect()

    assert proxy_client.retry_count == 1
    assert proxy_client.state == ConnectionState.SHUTTING_DOWN


@pytest.mark.asyncio
async def test_run_with_reconnect_breaks_when_gateway_disconnects(proxy_client, monkeypatch) -> None:
    """Gateway disconnect should trigger reconnect handling."""
    call_count = 0

    async def _fake_connect() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            proxy_client.state = ConnectionState.CONNECTED
            proxy_client._keepalive_task = None
            proxy_client.gateway_transport.is_connected.return_value = False
        else:
            proxy_client.state = ConnectionState.SHUTTING_DOWN

    monkeypatch.setattr(proxy_client, "connect", _fake_connect)
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=True))
    monkeypatch.setattr(client_mod.asyncio, "sleep", AsyncMock())

    await proxy_client.run_with_reconnect()

    assert proxy_client.retry_count == 1
    assert call_count == 2


@pytest.mark.asyncio
async def test_run_with_reconnect_marks_mcp_unhealthy_when_transport_disconnects(proxy_client, monkeypatch) -> None:
    """MCP transport disconnection should mark health false and continue loop."""
    call_count = 0

    async def _fake_connect() -> None:
        nonlocal call_count
        call_count += 1
        proxy_client._keepalive_task = None
        if call_count == 1:
            proxy_client.state = ConnectionState.CONNECTED
            proxy_client.gateway_transport.is_connected.return_value = True
            proxy_client.mcp_transport._connected = False
        else:
            proxy_client.state = ConnectionState.SHUTTING_DOWN

    async def _fake_sleep(_delay: float) -> None:
        if proxy_client.state == ConnectionState.CONNECTED:
            proxy_client.state = ConnectionState.DISCONNECTED

    monkeypatch.setattr(proxy_client, "connect", _fake_connect)
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=True))
    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    await proxy_client.run_with_reconnect()

    assert proxy_client._mcp_server_healthy is False
    assert proxy_client._consecutive_mcp_failures == 1


@pytest.mark.asyncio
async def test_run_with_reconnect_honors_max_retries(proxy_client, monkeypatch) -> None:
    """Reconnect loop should stop when max retries is exceeded."""
    proxy_client.max_retries = 1
    monkeypatch.setattr(proxy_client, "connect", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(client_mod.asyncio, "sleep", AsyncMock())

    await proxy_client.run_with_reconnect()

    assert proxy_client.retry_count == 1


@pytest.mark.asyncio
async def test_run_with_reconnect_decrements_retry_when_mcp_still_unhealthy(proxy_client, monkeypatch) -> None:
    """Health-check failures during reconnect should not consume a retry."""
    call_count = 0

    async def _fake_connect() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        proxy_client.state = ConnectionState.SHUTTING_DOWN

    health_mock = AsyncMock(side_effect=[False, True])
    sleep_mock = AsyncMock()
    monkeypatch.setattr(proxy_client, "connect", _fake_connect)
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", health_mock)
    monkeypatch.setattr(client_mod.asyncio, "sleep", sleep_mock)

    await proxy_client.run_with_reconnect()

    assert proxy_client.retry_count == 0


@pytest.mark.asyncio
async def test_handle_mcp_message_invalid_json_is_swallowed(proxy_client) -> None:
    """Malformed MCP messages should be logged and swallowed."""
    await proxy_client._handle_mcp_message("{invalid-json")

    proxy_client.gateway_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_gateway_heartbeat_ack_does_nothing(proxy_client) -> None:
    """Heartbeat acknowledgments should be ignored."""
    await proxy_client._handle_gateway_message('{"type":"heartbeat"}')

    proxy_client.mcp_transport.send.assert_not_awaited()
    proxy_client.gateway_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_gateway_register_ack_does_nothing(proxy_client) -> None:
    """Register acknowledgments should not trigger side effects."""
    await proxy_client._handle_gateway_message('{"type":"register_ack","status":"ok"}')

    proxy_client.mcp_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_gateway_error_message_does_nothing(proxy_client) -> None:
    """Gateway error messages should be logged without raising."""
    await proxy_client._handle_gateway_message('{"type":"error","message":"bad"}')

    proxy_client.mcp_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_gateway_unknown_message_type_is_ignored(proxy_client) -> None:
    """Unknown gateway messages should be ignored safely."""
    await proxy_client._handle_gateway_message('{"type":"mystery"}')

    proxy_client.mcp_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_gateway_invalid_json_is_swallowed(proxy_client) -> None:
    """Malformed gateway messages should be logged and swallowed."""
    await proxy_client._handle_gateway_message("{broken")

    proxy_client.mcp_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_mcp_server_health_returns_false_when_endpoint_not_ready(proxy_client) -> None:
    """Missing message endpoint should make connected HTTP/SSE transport unhealthy."""
    proxy_client.mcp_transport.__class__.__name__ = "StreamableHttpAdapter"
    proxy_client.mcp_transport._message_endpoint = None

    assert await proxy_client._check_mcp_server_health() is False


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_sse_running_receive_task_without_endpoint_returns_false(proxy_client) -> None:
    """SSE receive task without endpoint should not yet be healthy."""
    proxy_client.mcp_transport.__class__.__name__ = "SseAdapter"
    proxy_client.mcp_transport._message_endpoint = None
    proxy_client.mcp_transport._receive_task = asyncio.create_task(asyncio.sleep(10))

    try:
        assert await proxy_client._check_mcp_server_health() is False
    finally:
        proxy_client.mcp_transport._receive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await proxy_client.mcp_transport._receive_task


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_sse_running_receive_task_with_endpoint_is_true(proxy_client) -> None:
    """SSE receive task with endpoint should be healthy."""
    proxy_client.mcp_transport.__class__.__name__ = "SseAdapter"
    proxy_client.mcp_transport._message_endpoint = "/messages"
    proxy_client.mcp_transport._session_id = None
    proxy_client.mcp_transport._receive_task = asyncio.create_task(asyncio.sleep(10))

    try:
        assert await proxy_client._check_mcp_server_health() is True
    finally:
        proxy_client.mcp_transport._receive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await proxy_client.mcp_transport._receive_task


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_http_uninitialized_transport_returns_false(proxy_client) -> None:
    """HTTP transport without client or URL should be unhealthy."""
    proxy_client.mcp_transport.__class__.__name__ = "StreamableHttpAdapter"
    proxy_client.mcp_transport._client = None
    proxy_client.mcp_transport.server_url = None

    assert await proxy_client._check_mcp_server_health() is False


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_http_5xx_returns_false(proxy_client) -> None:
    """HTTP 5xx responses should be considered unhealthy."""
    proxy_client.mcp_transport.__class__.__name__ = "StreamableHttpAdapter"
    proxy_client.mcp_transport._client = SimpleNamespace(head=AsyncMock(return_value=SimpleNamespace(status_code=503)))
    proxy_client.mcp_transport.server_url = "https://server.example/mcp"

    assert await proxy_client._check_mcp_server_health() is False


@pytest.mark.asyncio
async def test_check_mcp_server_health_for_http_exception_returns_false(proxy_client) -> None:
    """HTTP HEAD exceptions should be considered unhealthy."""
    proxy_client.mcp_transport.__class__.__name__ = "StreamableHttpAdapter"
    proxy_client.mcp_transport._client = SimpleNamespace(head=AsyncMock(side_effect=RuntimeError("bad")))
    proxy_client.mcp_transport.server_url = "https://server.example/mcp"

    assert await proxy_client._check_mcp_server_health() is False


@pytest.mark.asyncio
async def test_check_mcp_server_health_unknown_transport_returns_connected_state(proxy_client) -> None:
    """Unknown transport types should fall back to connected state."""
    proxy_client.mcp_transport.__class__.__name__ = "MysteryAdapter"
    proxy_client.mcp_transport._connected = True

    assert await proxy_client._check_mcp_server_health() is True


@pytest.mark.asyncio
async def test_check_mcp_server_health_returns_false_on_unexpected_exception(proxy_client, monkeypatch) -> None:
    """Unexpected health-check exceptions should return false."""
    monkeypatch.delattr(proxy_client, "mcp_transport", raising=False)

    assert await proxy_client._check_mcp_server_health() is False


@pytest.mark.asyncio
async def test_keepalive_loop_sends_heartbeat_when_mcp_is_healthy(proxy_client, monkeypatch) -> None:
    """Healthy MCP server should produce a heartbeat."""
    proxy_client.state = ConnectionState.CONNECTED
    proxy_client.keepalive_interval = 0
    check_health_mock = AsyncMock(return_value=True)

    async def _fake_sleep(_delay: float) -> None:
        proxy_client.state = ConnectionState.SHUTTING_DOWN

    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", check_health_mock)
    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    await proxy_client._keepalive_loop()

    proxy_client.gateway_transport.send.assert_awaited_once()
    payload = proxy_client.gateway_transport.send.await_args.args[0]
    assert MessageType.HEARTBEAT.value in payload


@pytest.mark.asyncio
async def test_keepalive_loop_recovers_and_reregisters_when_mcp_returns(proxy_client, monkeypatch) -> None:
    """Recovered MCP server should reconnect gateway if needed and re-register."""
    proxy_client.state = ConnectionState.CONNECTED
    proxy_client.keepalive_interval = 0
    proxy_client._mcp_server_healthy = False
    proxy_client._consecutive_mcp_failures = 2
    proxy_client.gateway_transport.is_connected.return_value = False
    check_health_mock = AsyncMock(return_value=True)
    register_mock = AsyncMock()

    async def _fake_sleep(_delay: float) -> None:
        proxy_client.state = ConnectionState.SHUTTING_DOWN

    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", check_health_mock)
    monkeypatch.setattr(proxy_client, "_register", register_mock)
    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    await proxy_client._keepalive_loop()

    proxy_client.gateway_transport.connect.assert_awaited_once()
    register_mock.assert_awaited_once()
    assert proxy_client._mcp_server_healthy is True
    assert proxy_client._consecutive_mcp_failures == 0
    proxy_client.gateway_transport.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_keepalive_loop_continues_when_gateway_reconnect_fails(proxy_client, monkeypatch) -> None:
    """Gateway reconnect failure during recovery should skip heartbeat send."""
    proxy_client.state = ConnectionState.CONNECTED
    proxy_client.keepalive_interval = 0
    proxy_client._mcp_server_healthy = False
    proxy_client.gateway_transport.is_connected.return_value = False
    proxy_client.gateway_transport.connect.side_effect = RuntimeError("cannot reconnect")
    check_health_mock = AsyncMock(return_value=True)

    async def _fake_sleep(_delay: float) -> None:
        proxy_client.state = ConnectionState.SHUTTING_DOWN

    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", check_health_mock)
    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    await proxy_client._keepalive_loop()

    proxy_client.gateway_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_keepalive_loop_continues_when_reregister_fails(proxy_client, monkeypatch) -> None:
    """Re-registration failure during recovery should skip heartbeat send."""
    proxy_client.state = ConnectionState.CONNECTED
    proxy_client.keepalive_interval = 0
    proxy_client._mcp_server_healthy = False
    proxy_client.gateway_transport.is_connected.return_value = True
    check_health_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", check_health_mock)
    monkeypatch.setattr(proxy_client, "_register", AsyncMock(side_effect=RuntimeError("register fail")))

    async def _fake_sleep(_delay: float) -> None:
        proxy_client.state = ConnectionState.SHUTTING_DOWN

    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    await proxy_client._keepalive_loop()

    proxy_client.gateway_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_keepalive_loop_breaks_when_heartbeat_send_fails(proxy_client, monkeypatch) -> None:
    """Heartbeat send failures should break the loop."""
    proxy_client.state = ConnectionState.CONNECTED
    proxy_client.keepalive_interval = 0
    proxy_client.gateway_transport.send.side_effect = RuntimeError("send fail")
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=True))

    async def _fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    await proxy_client._keepalive_loop()


@pytest.mark.asyncio
async def test_keepalive_loop_marks_first_unhealthy_failure(proxy_client, monkeypatch) -> None:
    """First unhealthy check should flip the health flag and increment failures."""
    proxy_client.state = ConnectionState.CONNECTED
    proxy_client.keepalive_interval = 0
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=False))

    async def _fake_sleep(_delay: float) -> None:
        proxy_client.state = ConnectionState.SHUTTING_DOWN

    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    await proxy_client._keepalive_loop()

    assert proxy_client._mcp_server_healthy is False
    assert proxy_client._consecutive_mcp_failures == 1
    proxy_client.gateway_transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_keepalive_loop_tracks_ongoing_unhealthy_failures(proxy_client, monkeypatch) -> None:
    """Repeated unhealthy checks should continue incrementing failure count."""
    proxy_client.state = ConnectionState.CONNECTED
    proxy_client.keepalive_interval = 0
    proxy_client._mcp_server_healthy = False
    proxy_client._consecutive_mcp_failures = 1
    monkeypatch.setattr(proxy_client, "_check_mcp_server_health", AsyncMock(return_value=False))

    async def _fake_sleep(_delay: float) -> None:
        proxy_client.state = ConnectionState.SHUTTING_DOWN

    monkeypatch.setattr(client_mod.asyncio, "sleep", _fake_sleep)

    await proxy_client._keepalive_loop()

    assert proxy_client._consecutive_mcp_failures == 2


@pytest.mark.asyncio
async def test_send_error_response_swallow_send_failures(proxy_client) -> None:
    """Gateway send failures while returning an error should be swallowed."""
    proxy_client.gateway_transport.send.side_effect = RuntimeError("cannot send")

    await proxy_client._send_error_response({"jsonrpc": "2.0", "id": 34}, "broken")
