# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/tests/test_mcp_reverse_proxy_sse_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the SSE reverse proxy transport adapter.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import ssl
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

# Third-Party
import httpx
import pytest

# First-Party
from mcp_reverse_proxy.transports.sse_adapter import SseAdapter


class FakeSseResponse:
    """Minimal async SSE response fake."""

    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        """Mimic successful HTTP responses."""

    async def aiter_lines(self) -> AsyncIterator[str]:
        """Yield configured SSE lines."""
        for line in self._lines:
            yield line


class FakeStreamContext:
    """Async context manager wrapper for SSE response fakes."""

    def __init__(self, response: FakeSseResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeSseResponse:
        """Return the fake response."""
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        """Do not suppress exceptions."""
        return False


@pytest.mark.asyncio
async def test_start_creates_http_client_and_receive_task_for_http(monkeypatch) -> None:
    """Start should initialize the client and spawn the receive loop task."""
    created_clients: list[dict[str, object]] = []
    created_tasks: list[asyncio.Task[None]] = []

    class FakeClient:
        """Async client fake capturing constructor parameters."""

        def __init__(self, **kwargs) -> None:
            created_clients.append(kwargs)

        async def aclose(self) -> None:
            """No-op close."""

    original_create_task = asyncio.create_task

    def capture_task(coro):
        task = original_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("mcp_reverse_proxy.transports.sse_adapter.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("mcp_reverse_proxy.transports.sse_adapter.asyncio.create_task", capture_task)

    adapter = SseAdapter("http://server.example/sse", timeout=12.5)

    await adapter.start()

    assert adapter._connected is True
    assert len(created_clients) == 1
    assert created_clients[0]["http2"] is True
    assert created_clients[0]["verify"] is False
    assert isinstance(created_clients[0]["timeout"], httpx.Timeout)
    assert adapter._receive_task is created_tasks[0]

    adapter._receive_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await adapter._receive_task


@pytest.mark.asyncio
async def test_start_configures_https_ssl_context_with_custom_cert(monkeypatch) -> None:
    """HTTPS start should use an SSL context created from the provided CA data."""
    fake_ssl_context = Mock(spec=ssl.SSLContext)
    fake_ssl_context.check_hostname = True
    fake_ssl_context.verify_mode = ssl.CERT_REQUIRED
    fake_ssl_context.load_verify_locations = Mock()  # Mock the load_verify_locations method
    async_client_mock = Mock()
    receive_task = asyncio.create_task(asyncio.sleep(10))
    create_task_mock = Mock(return_value=receive_task)

    # Mock load_cert_data to return test certificate data
    test_cert_data = "MOCK_CERT_DATA"
    monkeypatch.setattr("mcp_reverse_proxy.transports.sse_adapter.load_cert_data", lambda cert: test_cert_data)

    # Mock SSLContext constructor to return our fake context
    monkeypatch.setattr("mcp_reverse_proxy.transports.sse_adapter.ssl.SSLContext", lambda protocol: fake_ssl_context)
    monkeypatch.setattr("mcp_reverse_proxy.transports.sse_adapter.httpx.AsyncClient", async_client_mock)
    monkeypatch.setattr("mcp_reverse_proxy.transports.sse_adapter.asyncio.create_task", create_task_mock)

    adapter = SseAdapter("https://secure.example/sse", cert="test_cert_input")

    await adapter.start()

    # Verify load_verify_locations was called with the cert data
    fake_ssl_context.load_verify_locations.assert_called_once_with(cadata=test_cert_data)
    async_client_mock.assert_called_once()
    assert async_client_mock.call_args.kwargs["verify"] is fake_ssl_context
    assert fake_ssl_context.check_hostname is True
    assert fake_ssl_context.verify_mode == ssl.CERT_REQUIRED

    receive_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await receive_task


@pytest.mark.asyncio
async def test_stop_cancels_task_closes_client_and_clears_session_state() -> None:
    """Stop should cancel the receive task, close the client, and clear session state."""
    adapter = SseAdapter("http://server.example/sse")
    adapter._connected = True
    adapter._session_id = "session-1"
    adapter._message_endpoint = "http://server.example/messages"
    adapter._protocol_version = "2025-11-05"

    adapter._receive_task = asyncio.create_task(asyncio.sleep(10))
    adapter._client = AsyncMock()
    adapter._shutdown_event.clear()

    await adapter.stop()

    assert adapter._connected is False
    assert adapter._shutdown_event.is_set()
    adapter._client = None
    assert adapter._session_id is None
    assert adapter._message_endpoint is None
    assert adapter._protocol_version is None


@pytest.mark.asyncio
async def test_send_posts_payload_with_auth_session_and_protocol_headers() -> None:
    """Send should POST JSON using auth, session, and protocol headers."""
    adapter = SseAdapter("http://server.example/sse")
    adapter._connected = True
    adapter._message_endpoint = "http://server.example/messages"
    adapter._session_id = "session-1"
    adapter._protocol_version = "2025-11-05"
    adapter._auth_headers = {"Authorization": "Bearer token"}

    response = Mock()
    response.headers = {"mcp-session-id": "session-2"}
    response.status_code = 200
    response.raise_for_status = Mock()

    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    adapter._client = client

    await adapter.send('{"jsonrpc":"2.0","id":1}')

    client.post.assert_awaited_once()
    assert client.post.await_args.args[0] == "http://server.example/messages"
    assert client.post.await_args.kwargs["content"] == '{"jsonrpc":"2.0","id":1}'
    assert client.post.await_args.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer token",
        "mcp-session-id": "session-1",
        "mcp-protocol-version": "2025-11-05",
    }
    assert adapter._session_id == "session-1"


@pytest.mark.asyncio
async def test_send_stores_session_id_from_first_successful_response() -> None:
    """First successful POST should capture the session ID from response headers."""
    adapter = SseAdapter("http://server.example/sse")
    adapter._connected = True
    adapter._message_endpoint = "http://server.example/messages"

    response = Mock()
    response.headers = {"mcp-session-id": "new-session"}
    response.status_code = 200
    response.raise_for_status = Mock()

    adapter._client = AsyncMock()
    adapter._client.post = AsyncMock(return_value=response)

    await adapter.send('{"jsonrpc":"2.0","id":1}')

    assert adapter._session_id == "new-session"


@pytest.mark.asyncio
async def test_send_clears_session_state_on_http_404() -> None:
    """A 404 from POST should clear session-related state before raising."""
    adapter = SseAdapter("http://server.example/sse")
    adapter._connected = True
    adapter._client = AsyncMock()
    adapter._message_endpoint = "http://server.example/messages"
    adapter._session_id = "session-1"
    adapter._protocol_version = "2025-11-05"

    request = httpx.Request("POST", adapter._message_endpoint)
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("missing", request=request, response=response)
    adapter._client.post = AsyncMock(side_effect=error)

    with pytest.raises(RuntimeError, match="Failed to send message"):
        await adapter.send('{"jsonrpc":"2.0","id":1}')

    assert adapter._session_id is None
    assert adapter._message_endpoint is None
    assert adapter._protocol_version is None


def test_set_authentication_supports_basic_bearer_and_passthrough_headers() -> None:
    """Authentication helper should normalize supported auth styles."""
    adapter = SseAdapter("http://server.example/sse")

    adapter.set_authentication({"username": "alice", "password": "secret"}, "basic")
    assert adapter._auth_headers == {"Authorization": "Basic YWxpY2U6c2VjcmV0"}

    adapter.set_authentication({"token": "abc123"}, "bearer")
    assert adapter._auth_headers == {"Authorization": "Bearer abc123"}

    adapter.set_authentication({"X-Api-Key": "key"}, "custom")
    assert adapter._auth_headers == {"X-Api-Key": "key"}


@pytest.mark.asyncio
async def test_receive_sse_stream_processes_events_and_forwards_auth_headers(monkeypatch) -> None:
    """SSE receive loop should parse streamed events and pass connection headers."""
    adapter = SseAdapter("http://server.example/sse")
    adapter._connected = True
    adapter._auth_headers = {"Authorization": "Bearer token"}

    processed_events: list[tuple[str, str]] = []

    async def fake_process(event_type: str, data: str) -> None:
        processed_events.append((event_type, data))

    stream_mock = Mock(
        return_value=FakeStreamContext(
            FakeSseResponse(
                [
                    "event: endpoint",
                    "data: /messages?session_id=abc",
                    "",
                    "retry: 5000",
                    ": comment",
                    "event: message",
                    'data: {"jsonrpc":"2.0"}',
                    "",
                ]
            )
        )
    )

    adapter._client = Mock()
    adapter._client.stream = stream_mock
    monkeypatch.setattr(adapter, "_process_sse_event", fake_process)

    await adapter._receive_sse_stream()

    stream_mock.assert_called_once_with(
        "GET",
        "http://server.example/sse",
        headers={
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "Authorization": "Bearer token",
        },
    )
    assert processed_events == [
        ("endpoint", "/messages?session_id=abc"),
        ("message", '{"jsonrpc":"2.0"}'),
    ]
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_receive_sse_stream_notifies_handlers_on_http_error() -> None:
    """HTTP stream failures while connected should notify registered handlers."""
    adapter = SseAdapter("http://server.example/sse")
    adapter._connected = True

    request = httpx.Request("GET", adapter.server_url)
    stream_error = httpx.ConnectError("boom", request=request)

    handler = AsyncMock()
    adapter.add_message_handler(handler)

    class RaisingStreamContext:
        """Context manager that raises the configured HTTP error."""

        async def __aenter__(self):
            raise stream_error

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    adapter._client = Mock()
    adapter._client.stream = Mock(return_value=RaisingStreamContext())

    await adapter._receive_sse_stream()

    handler.assert_awaited_once()
    payload = handler.await_args.args[0]
    assert "SSE connection lost: boom" in payload
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_process_sse_event_endpoint_builds_absolute_url_and_extracts_session() -> None:
    """Endpoint events should resolve relative URLs and extract session query parameters."""
    adapter = SseAdapter("https://server.example/sse")

    await adapter._process_sse_event("endpoint", "/messages?session_id=session-123")

    assert adapter._message_endpoint == "https://server.example/messages?session_id=session-123"
    assert adapter._session_id == "session-123"


@pytest.mark.asyncio
async def test_process_sse_event_message_sets_protocol_and_calls_all_handlers() -> None:
    """Message events should negotiate protocol version and notify handlers."""
    adapter = SseAdapter("http://server.example/sse")
    handler_one = AsyncMock()
    handler_two = AsyncMock()
    adapter.add_message_handler(handler_one)
    adapter.add_message_handler(handler_two)

    payload = '{"jsonrpc":"2.0","result":{"protocolVersion":"2025-11-05"}}'

    await adapter._process_sse_event("message", payload)

    assert adapter._protocol_version == "2025-11-05"
    handler_one.assert_awaited_once_with(payload)
    handler_two.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_process_sse_event_error_forwards_to_handlers_even_if_one_fails() -> None:
    """Error events should continue forwarding after an individual handler failure."""
    adapter = SseAdapter("http://server.example/sse")
    failing_handler = AsyncMock(side_effect=RuntimeError("handler failed"))
    successful_handler = AsyncMock()
    adapter.add_message_handler(failing_handler)
    adapter.add_message_handler(successful_handler)

    await adapter._process_sse_event("error", '{"error":"bad"}')

    failing_handler.assert_awaited_once_with('{"error":"bad"}')
    successful_handler.assert_awaited_once_with('{"error":"bad"}')
