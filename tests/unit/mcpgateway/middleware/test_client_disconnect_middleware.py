# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_client_disconnect_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the client disconnect middleware.
"""

# Standard
import asyncio

# Third-Party
import pytest

# First-Party
from mcpgateway.middleware.client_disconnect import ClientDisconnectMiddleware


async def _ok_app(scope, receive, send):  # type: ignore[no-untyped-def]
    """Simple ASGI app that responds OK."""
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _slow_app(scope, receive, send):  # type: ignore[no-untyped-def]
    """ASGI app that simulates slow processing."""
    await asyncio.sleep(3600)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _body_app(scope, receive, send):  # type: ignore[no-untyped-def]
    """ASGI app that reads request body."""
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


async def _receive_messages(messages):  # type: ignore[no-untyped-def]
    """Build an ASGI receive callable that yields messages then waits forever."""
    idx = 0

    async def receive():  # type: ignore[no-untyped-def]
        nonlocal idx
        if idx < len(messages):
            msg = messages[idx]
            idx += 1
            return msg
        # After all messages, wait forever (simulates open connection)
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}  # pragma: no cover

    return receive


@pytest.mark.asyncio
async def test_normal_request_completes():
    """Normal HTTP request completes without disconnect."""
    middleware = ClientDisconnectMiddleware(_ok_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])
    await middleware(scope, receive, send)

    assert len(messages) == 2
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 200
    assert messages[1]["type"] == "http.response.body"
    assert messages[1]["body"] == b"ok"


@pytest.mark.asyncio
async def test_handler_cancelled_on_disconnect():
    """Handler is cancelled when client disconnects before response."""
    middleware = ClientDisconnectMiddleware(_slow_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.disconnect"},
    ])

    await middleware(scope, receive, send)
    # No response should have been sent (handler was cancelled before send)
    assert len(messages) == 0


@pytest.mark.asyncio
async def test_websocket_passes_through():
    """WebSocket scope passes through unchanged."""
    middleware = ClientDisconnectMiddleware(_ok_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "websocket", "path": "/ws/chat"}
    receive = await _receive_messages([])
    await middleware(scope, receive, send)

    assert len(messages) == 2


@pytest.mark.asyncio
async def test_lifespan_passes_through():
    """Lifespan scope passes through unchanged."""
    middleware = ClientDisconnectMiddleware(_ok_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "lifespan", "path": "/"}
    receive = await _receive_messages([])
    await middleware(scope, receive, send)

    assert len(messages) == 2


@pytest.mark.parametrize(
    "path",
    [
        "/sse",
        "/sse/",
        "/mcp",
        "/mcp/",
        "/servers/abc/sse",
        "/servers/abc/mcp",
        "/_internal/mcp/transport",
        "/_internal/mcp/transport/",
    ],
)
@pytest.mark.asyncio
async def test_self_managed_paths_skipped(path):
    """SSE and MCP paths are skipped (receive/send passed through unwrapped)."""
    received_via: list[str] = []

    async def tracking_app(scope, receive, send):  # type: ignore[no-untyped-def]
        # Verify we got the original receive/send, not wrapped versions
        received_via.append("app")
        msg = await receive()
        assert msg["type"] == "http.request"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = ClientDisconnectMiddleware(tracking_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": path}
    receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])
    await middleware(scope, receive, send)

    assert len(messages) == 2
    assert received_via == ["app"]


@pytest.mark.asyncio
async def test_regular_server_paths_not_skipped():
    """Regular REST endpoints under /servers are NOT skipped."""
    middleware = ClientDisconnectMiddleware(_ok_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    # These are regular REST endpoints, not streaming paths
    for path in (
        "/servers",
        "/servers/abc",
        "/servers/abc/tools",
        "/servers/abc/state",
        "/_internal/mcp",
        "/_internal/mcp/authenticate",
        "/_internal/mcp/rpc",
    ):
        messages.clear()
        scope = {"type": "http", "path": path}
        receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])
        await middleware(scope, receive, send)
        assert len(messages) == 2, f"Expected middleware to process {path}, not skip it"


@pytest.mark.asyncio
async def test_cancelled_error_reraised_when_not_disconnect():
    """CancelledError from non-disconnect sources is re-raised."""
    async def app_that_gets_cancelled(scope, receive, send):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.01)
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = ClientDisconnectMiddleware(app_that_gets_cancelled)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])

    # Cancel the middleware itself to simulate external cancellation
    task = asyncio.create_task(middleware(scope, receive, send))
    await asyncio.sleep(0.005)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_task_cleanup_no_orphans():
    """All middleware-created tasks are cleaned up in finally block."""
    middleware = ClientDisconnectMiddleware(_slow_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.disconnect"},
    ])

    # Capture tasks created by the middleware by tracking before/after
    before_tasks = set(asyncio.all_tasks())
    await middleware(scope, receive, send)
    after_tasks = set(asyncio.all_tasks())

    # Only middleware-created tasks should be gone; ignore pytest/plugin tasks
    new_tasks = after_tasks - before_tasks
    pending_new = [t for t in new_tasks if not t.done()]
    assert len(pending_new) == 0


@pytest.mark.asyncio
async def test_send_wrapper_suppresses_after_disconnect():
    """Send wrapper suppresses sends after disconnect and before response start."""
    async def app_that_sends_after_delay(scope, receive, send):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.05)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = ClientDisconnectMiddleware(app_that_sends_after_delay)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.disconnect"},
    ])

    await middleware(scope, receive, send)
    # Response start should be suppressed because disconnect happened first
    assert len(messages) == 0


@pytest.mark.asyncio
async def test_send_wrapper_allows_response_after_disconnect():
    """Send wrapper allows response if response.start already sent."""
    async def app_that_starts_then_disconnects(scope, receive, send):  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await asyncio.sleep(0.05)
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = ClientDisconnectMiddleware(app_that_starts_then_disconnects)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.disconnect"},
    ])

    await middleware(scope, receive, send)
    # Response start was sent before disconnect, so it should be in messages
    assert len(messages) == 1
    assert messages[0]["type"] == "http.response.start"


@pytest.mark.asyncio
async def test_send_wrapper_oserror_sets_disconnected():
    """OSError from send sets disconnected flag."""
    call_count = 0

    async def flaky_send(msg):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionResetError("client gone")
        raise OSError("client gone")

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = ClientDisconnectMiddleware(app)
    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])
    await middleware(scope, receive, flaky_send)
    # Should not raise; the OSError is caught and disconnected is set


@pytest.mark.asyncio
async def test_request_body_reading():
    """Request body is correctly relayed through the queue."""
    middleware = ClientDisconnectMiddleware(_body_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([
        {"type": "http.request", "body": b"hello", "more_body": True},
        {"type": "http.request", "body": b" world", "more_body": False},
    ])
    await middleware(scope, receive, send)

    assert len(messages) == 2
    assert messages[1]["body"] == b"hello world"


@pytest.mark.asyncio
async def test_handler_cancelled_while_waiting_on_receive():
    """Handler is cancelled when waiting on receive() and client disconnects."""
    receive_call_count = 0

    async def app_that_reads_forever(scope, receive, send):  # type: ignore[no-untyped-def]
        nonlocal receive_call_count
        while True:
            await receive()
            receive_call_count += 1

    middleware = ClientDisconnectMiddleware(app_that_reads_forever)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.disconnect"},
    ])
    await middleware(scope, receive, send)

    # App received the first message, then was cancelled on the second receive()
    assert receive_call_count == 1


@pytest.mark.asyncio
async def test_non_managed_path_processed():
    """Non-managed paths go through the middleware."""
    middleware = ClientDisconnectMiddleware(_ok_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/tools"}
    receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])
    await middleware(scope, receive, send)

    assert len(messages) == 2


@pytest.mark.asyncio
async def test_empty_path_defaults_to_empty_string():
    """Scope with missing path defaults to empty string and is processed."""
    middleware = ClientDisconnectMiddleware(_ok_app)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http"}
    receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])
    await middleware(scope, receive, send)

    assert len(messages) == 2


@pytest.mark.asyncio
async def test_send_wrapper_suppresses_body_when_disconnected_before_start():
    """Non-start messages are suppressed when disconnected before response start."""
    async def app_that_sends_body_after_delay(scope, receive, send):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.05)
        await send({"type": "http.response.body", "body": b"should not send"})

    middleware = ClientDisconnectMiddleware(app_that_sends_body_after_delay)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.disconnect"},
    ])

    await middleware(scope, receive, send)
    assert len(messages) == 0


@pytest.mark.asyncio
async def test_send_wrapper_oserror_on_body_sets_disconnected():
    """OSError when sending body sets disconnected flag."""
    call_count = 0

    async def flaky_send(msg):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if msg["type"] == "http.response.body":
            raise ConnectionResetError("client gone")

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = ClientDisconnectMiddleware(app)
    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])
    await middleware(scope, receive, flaky_send)
    # Should not raise; the OSError is caught and disconnected is set


@pytest.mark.asyncio
async def test_handler_not_done_in_finally_gets_cancelled():
    """Handler task is cancelled in finally if not done when middleware returns."""
    handler_started = asyncio.Event()
    handler_continue = asyncio.Event()

    async def app_that_waits(scope, receive, send):  # type: ignore[no-untyped-def]
        handler_started.set()
        await handler_continue.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = ClientDisconnectMiddleware(app_that_waits)
    messages: list[dict] = []

    async def send(msg):  # type: ignore[no-untyped-def]
        messages.append(msg)

    scope = {"type": "http", "path": "/api/test"}
    receive = await _receive_messages([{"type": "http.request", "body": b"", "more_body": False}])

    # Run middleware in background so we can test the finally block
    middleware_task = asyncio.create_task(middleware(scope, receive, send))
    await handler_started.wait()
    # Cancel the middleware itself; this should trigger the finally block
    middleware_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await middleware_task
