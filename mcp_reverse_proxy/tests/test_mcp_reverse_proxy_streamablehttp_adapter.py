# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/tests/test_mcp_reverse_proxy_streamablehttp_adapter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the streamable HTTP reverse proxy transport adapter.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import ssl
from unittest.mock import AsyncMock, Mock

# Third-Party
import httpx
import pytest

# First-Party
from mcp_reverse_proxy.transports.streamablehttp_adapter import SessionExpiredError, StreamableHttpAdapter


@pytest.mark.asyncio
async def test_start_creates_http_client_sets_endpoint_and_receive_task(monkeypatch) -> None:
    """Start should initialize the client, message endpoint, and receive task."""
    created_tasks: list[asyncio.Task[None]] = []

    class FakeClient:
        """Minimal async client fake."""

        async def aclose(self) -> None:
            """No-op close."""

    async_client_mock = Mock(return_value=FakeClient())
    original_create_task = asyncio.create_task

    def capture_task(coro):
        task = original_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("mcp_reverse_proxy.transports.streamablehttp_adapter.httpx.AsyncClient", async_client_mock)
    monkeypatch.setattr("mcp_reverse_proxy.transports.streamablehttp_adapter.asyncio.create_task", capture_task)

    adapter = StreamableHttpAdapter("http://server.example/mcp", timeout=12.5)

    await adapter.start()

    assert adapter._connected is True
    assert adapter._message_endpoint == "http://server.example/mcp"
    assert async_client_mock.call_args.kwargs["http2"] is True
    assert async_client_mock.call_args.kwargs["verify"] is False
    assert isinstance(async_client_mock.call_args.kwargs["timeout"], httpx.Timeout)
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
    receive_task = asyncio.create_task(asyncio.sleep(10))
    async_client_mock = Mock()

    # Mock load_cert_data to return test certificate data
    test_cert_data = "MOCK_CERT_DATA"
    monkeypatch.setattr("mcp_reverse_proxy.transports.streamablehttp_adapter.load_cert_data",
                        lambda cert: test_cert_data)

    # Mock SSLContext constructor to return our fake context
    monkeypatch.setattr("mcp_reverse_proxy.transports.streamablehttp_adapter.ssl.SSLContext",
                        lambda protocol: fake_ssl_context)
    monkeypatch.setattr("mcp_reverse_proxy.transports.streamablehttp_adapter.httpx.AsyncClient", async_client_mock)
    monkeypatch.setattr(
        "mcp_reverse_proxy.transports.streamablehttp_adapter.asyncio.create_task",
        Mock(return_value=receive_task),
    )

    adapter = StreamableHttpAdapter("https://secure.example/mcp", cert="test_cert_input")

    await adapter.start()

    # Verify load_verify_locations was called with the cert data
    fake_ssl_context.load_verify_locations.assert_called_once_with(cadata=test_cert_data)
    assert async_client_mock.call_args.kwargs["verify"] is fake_ssl_context
    assert fake_ssl_context.check_hostname is True
    assert fake_ssl_context.verify_mode == ssl.CERT_REQUIRED

    receive_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await receive_task


@pytest.mark.asyncio
async def test_stop_cancels_task_closes_client_and_clears_session_state() -> None:
    """Stop should cancel the receive task, close the client, and clear session state."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")
    adapter._connected = True
    adapter._session_id = "session-1"
    adapter._message_endpoint = "http://server.example/mcp"
    adapter._protocol_version = "2025-11-05"
    adapter._receive_task = asyncio.create_task(asyncio.sleep(10))
    adapter._client = AsyncMock()

    await adapter.stop()

    assert adapter._connected is False
    assert adapter._session_id is None
    assert adapter._message_endpoint is None
    assert adapter._protocol_version is None
    assert adapter._client is None


@pytest.mark.asyncio
async def test_send_initialize_stores_session_protocol_and_notifies_handlers() -> None:
    """Initialize response should set session state and forward inline JSON responses."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")
    adapter._connected = True
    adapter._client = AsyncMock()
    handler = AsyncMock()
    adapter.add_message_handler(handler)

    response = Mock()
    response.headers = {"mcp-session-id": "session-1"}
    response.status_code = 200
    response.content = b'{"jsonrpc":"2.0","result":{"protocolVersion":"2025-11-05"}}'
    response.text = '{"jsonrpc":"2.0","result":{"protocolVersion":"2025-11-05"}}'
    response.raise_for_status = Mock()
    adapter._client.post = AsyncMock(return_value=response)

    await adapter.send('{"jsonrpc":"2.0","id":1,"method":"initialize"}')

    assert adapter._session_id == "session-1"
    assert adapter._protocol_version == "2025-11-05"
    handler.assert_awaited_once_with('{"jsonrpc":"2.0","result":{"protocolVersion":"2025-11-05"}}')
    headers = adapter._client.post.await_args.kwargs["headers"]
    assert "mcp-session-id" not in headers
    assert "mcp-protocol-version" not in headers


@pytest.mark.asyncio
async def test_send_with_existing_session_adds_session_headers_and_parses_sse_response() -> None:
    """Established sessions should send MCP headers and parse SSE-formatted inline responses."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")
    adapter._connected = True
    adapter._client = AsyncMock()
    adapter._session_id = "session-1"
    adapter._protocol_version = "2025-11-05"
    adapter._auth_headers = {"Authorization": "Bearer token"}
    handler = AsyncMock()
    adapter.add_message_handler(handler)

    response = Mock()
    response.headers = {}
    response.status_code = 200
    response.content = b'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"ok":true}}\n\n'
    response.text = 'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"ok":true}}\n\n'
    response.raise_for_status = Mock()
    adapter._client.post = AsyncMock(return_value=response)

    await adapter.send('{"jsonrpc":"2.0","id":2,"method":"tools/call"}')

    handler.assert_awaited_once_with('{"jsonrpc":"2.0","id":2,"result":{"ok":true}}')
    headers = adapter._client.post.await_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer token"
    assert headers["mcp-session-id"] == "session-1"
    assert headers["mcp-protocol-version"] == "2025-11-05"


@pytest.mark.asyncio
async def test_send_raises_for_non_initialize_request_without_session() -> None:
    """Non-initialize messages without a session should fail fast."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")
    adapter._connected = True
    adapter._client = AsyncMock()

    with pytest.raises(RuntimeError, match="No valid session"):
        await adapter.send('{"jsonrpc":"2.0","id":2,"method":"tools/call"}')


@pytest.mark.asyncio
async def test_send_raises_runtime_error_when_not_connected() -> None:
    """Send should fail if the HTTP client connection has not been started."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")

    with pytest.raises(RuntimeError, match="Not connected to MCP server"):
        await adapter.send('{"jsonrpc":"2.0","id":1}')


@pytest.mark.asyncio
async def test_send_retries_initialize_after_404_and_updates_session_state() -> None:
    """Initialize requests should retry once without session headers after a 404."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")
    adapter._connected = True
    adapter._client = AsyncMock()
    adapter._session_id = "stale-session"
    adapter._protocol_version = "old-version"
    handler = AsyncMock()
    adapter.add_message_handler(handler)

    request = httpx.Request("POST", "http://server.example/mcp")
    first_response = httpx.Response(404, request=request)
    http_error = httpx.HTTPStatusError("missing", request=request, response=first_response)

    retry_response = Mock()
    retry_response.headers = {"mcp-session-id": "new-session"}
    retry_response.status_code = 200
    retry_response.content = b'{"jsonrpc":"2.0","result":{"protocolVersion":"2025-11-05"}}'
    retry_response.text = '{"jsonrpc":"2.0","result":{"protocolVersion":"2025-11-05"}}'
    retry_response.raise_for_status = Mock()

    adapter._client.post = AsyncMock(side_effect=[http_error, retry_response])

    await adapter.send('{"jsonrpc":"2.0","id":1,"method":"initialize"}')

    assert adapter._session_id == "new-session"
    assert adapter._protocol_version == "2025-11-05"
    assert adapter._client.post.await_count == 2
    handler.assert_awaited_once_with('{"jsonrpc":"2.0","result":{"protocolVersion":"2025-11-05"}}')


@pytest.mark.asyncio
async def test_send_raises_session_expired_for_non_initialize_404() -> None:
    """Non-initialize 404 responses should clear session state and raise SessionExpiredError."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")
    adapter._connected = True
    adapter._client = AsyncMock()
    adapter._session_id = "session-1"
    adapter._protocol_version = "2025-11-05"

    request = httpx.Request("POST", "http://server.example/mcp")
    response = httpx.Response(404, request=request)
    http_error = httpx.HTTPStatusError("missing", request=request, response=response)
    adapter._client.post = AsyncMock(side_effect=http_error)

    with pytest.raises(SessionExpiredError, match="session expired"):
        await adapter.send('{"jsonrpc":"2.0","id":2,"method":"tools/call"}')

    assert adapter._session_id is None
    assert adapter._protocol_version is None


@pytest.mark.asyncio
async def test_send_wraps_generic_http_error() -> None:
    """Non-status HTTP client failures should be wrapped in RuntimeError."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")
    adapter._connected = True
    adapter._client = AsyncMock()

    request = httpx.Request("POST", "http://server.example/mcp")
    adapter._client.post = AsyncMock(side_effect=httpx.ConnectError("boom", request=request))

    with pytest.raises(RuntimeError, match="Failed to send message"):
        await adapter.send('{"jsonrpc":"2.0","id":1,"method":"initialize"}')


def test_set_authentication_supports_basic_bearer_and_passthrough_headers() -> None:
    """Authentication helper should normalize supported auth styles."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")

    adapter.set_authentication({"username": "alice", "password": "secret"}, "basic")
    assert adapter._auth_headers == {"Authorization": "Basic YWxpY2U6c2VjcmV0"}

    adapter.set_authentication({"token": "abc123"}, "bearer")
    assert adapter._auth_headers == {"Authorization": "Bearer abc123"}

    adapter.set_authentication({"X-Api-Key": "key"}, "custom")
    assert adapter._auth_headers == {"X-Api-Key": "key"}


@pytest.mark.asyncio
async def test_receive_stream_sleeps_until_cancelled(monkeypatch) -> None:
    """Receive loop should keep sleeping while connected and propagate cancellation."""
    adapter = StreamableHttpAdapter("http://server.example/mcp")
    adapter._connected = True
    call_count = 0

    async def fake_sleep(_delay: float) -> None:
        nonlocal call_count
        call_count += 1
        raise asyncio.CancelledError()

    monkeypatch.setattr("mcp_reverse_proxy.transports.streamablehttp_adapter.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await adapter._receive_stream()

    assert call_count == 1
