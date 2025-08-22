# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_translate_echo.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for mcpgateway.translate stdio↔SSE echo loop.
This module contains integration tests for the translate module's
bidirectional stdio↔SSE communication, testing real echo scenarios
and message flow patterns.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import json
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.translate import _build_fastapi, _PubSub, _run_stdio_to_sse, StdIOEndpoint


# Test configuration
TEST_PORT = 19999  # Use high port to avoid conflicts
TEST_HOST = "127.0.0.1"


@pytest.fixture
async def echo_server():
    """Start a simple echo MCP server for testing."""
    # Create a simple Python echo script that speaks JSON-RPC
    echo_script = """
import sys
import json

while True:
    try:
        line = sys.stdin.readline()
        if not line:
            break

        # Parse JSON-RPC request
        request = json.loads(line)

        # Create echo response
        response = {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "echo": request,
                "timestamp": "2025-01-01T00:00:00Z"
            }
        }

        # Special handling for initialize
        if request.get("method") == "initialize":
            response["result"] = {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "serverInfo": {
                    "name": "echo-server",
                    "version": "1.0.0"
                }
            }

        # Write response
        print(json.dumps(response))
        sys.stdout.flush()

    except Exception as e:
        error_response = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32700,
                "message": str(e)
            }
        }
        print(json.dumps(error_response))
        sys.stdout.flush()
"""

    # Write script to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(echo_script)
        script_path = f.name

    yield f"{sys.executable} {script_path}"

    # Cleanup
    import os
    os.unlink(script_path)


@pytest.mark.asyncio
async def test_stdio_to_sse_echo_initialize(echo_server):
    """Test basic initialize handshake through stdio→SSE bridge."""
    # Start the bridge server in background
    server_task = asyncio.create_task(
        _run_stdio_to_sse(
            cmd=echo_server,
            port=TEST_PORT,
            host=TEST_HOST,
            log_level="error"  # Quiet for tests
        )
    )

    # Give server time to start
    await asyncio.sleep(1)

    try:
        async with httpx.AsyncClient() as client:
            # Connect to SSE endpoint
            message_endpoint = None
            received_messages = []

            async with client.stream('GET', f'http://{TEST_HOST}:{TEST_PORT}/sse') as response:
                line_count = 0
                async for line in response.aiter_lines():
                    line_count += 1

                    if line.startswith('data: '):
                        data = line[6:]

                        if message_endpoint is None and data.startswith('http'):
                            # First data is the endpoint URL
                            message_endpoint = data

                            # Send initialize request
                            init_request = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "initialize",
                                "params": {
                                    "protocolVersion": "2025-03-26",
                                    "capabilities": {},
                                    "clientInfo": {
                                        "name": "test-client",
                                        "version": "1.0.0"
                                    }
                                }
                            }

                            post_response = await client.post(
                                message_endpoint,
                                json=init_request
                            )
                            assert post_response.status_code == 202

                        elif data != '{}':  # Skip keepalive
                            try:
                                msg = json.loads(data)
                                received_messages.append(msg)

                                # Check if we got the initialize response
                                if msg.get('id') == 1:
                                    assert msg['result']['protocolVersion'] == '2025-03-26'
                                    break
                            except json.JSONDecodeError:
                                pass

                    # Safety limit
                    if line_count > 100:
                        break

            assert message_endpoint is not None
            assert len(received_messages) > 0
            assert received_messages[0]['id'] == 1

    finally:
        # Cancel server task
        server_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server_task


@pytest.mark.asyncio
async def test_stdio_to_sse_multiple_clients():
    """Test multiple SSE clients receiving the same messages."""
    # Use a simple cat command as echo server
    pubsub = _PubSub()
    stdio = StdIOEndpoint("cat", pubsub)

    # Build app with short keepalive
    app = _build_fastapi(pubsub, stdio, keep_alive=1)

    # Mock request for testing
    class MockRequest:
        def __init__(self):
            self.base_url = f"http://{TEST_HOST}:{TEST_PORT}/"
            self._disconnected = False

        async def is_disconnected(self):
            return self._disconnected

    # Get SSE handler
    sse_handler = None
    for route in app.routes:
        if getattr(route, 'path', None) == '/sse':
            sse_handler = route.endpoint
            break

    assert sse_handler is not None

    # Create multiple clients
    clients = []
    for i in range(3):
        req = MockRequest()
        response = await sse_handler(req)
        clients.append((req, response))

    # Verify all clients are subscribed
    assert len(pubsub._subscribers) == 3

    # Publish a message
    test_message = '{"test": "broadcast"}'
    await pubsub.publish(test_message)

    # All queues should have the message
    for subscriber in pubsub._subscribers:
        msg = await asyncio.wait_for(subscriber.get(), timeout=1)
        assert msg == test_message

    # Disconnect all clients
    for req, _ in clients:
        req._disconnected = True


@pytest.mark.asyncio
async def test_stdio_to_sse_error_handling():
    """Test error handling in stdio→SSE bridge."""
    pubsub = _PubSub()

    # Create endpoint with non-existent command
    stdio = StdIOEndpoint("nonexistent_command_xyz", pubsub)

    # Starting should fail
    with pytest.raises(FileNotFoundError):
        await stdio.start()


@pytest.mark.asyncio
async def test_message_endpoint_validation():
    """Test message endpoint JSON validation."""
    pubsub = _PubSub()
    stdio = StdIOEndpoint("cat", pubsub)

    app = _build_fastapi(pubsub, stdio)

    # Get message handler
    message_handler = None
    for route in app.routes:
        if getattr(route, 'path', None) == '/message':
            message_handler = route.endpoint
            break

    assert message_handler is not None

    # Test with invalid JSON
    class MockRequest:
        def __init__(self, body: bytes):
            self._body = body

        async def body(self):
            return self._body

    # Invalid JSON should return 400
    invalid_req = MockRequest(b'not json')
    response = await message_handler(invalid_req, session_id="test")
    assert response.status_code == 400
    assert "Invalid JSON" in response.body.decode()

    # Valid JSON should be accepted
    valid_req = MockRequest(b'{"jsonrpc": "2.0", "id": 1}')

    # Create proper async mock for send
    async def mock_send(x):
        pass

    stdio.send = mock_send
    response = await message_handler(valid_req, session_id="test")
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_keepalive_events():
    """Test that keepalive events are sent periodically."""
    pubsub = _PubSub()
    stdio = StdIOEndpoint("cat", pubsub)

    # Build app with very short keepalive
    app = _build_fastapi(pubsub, stdio, keep_alive=0.1)  # 100ms

    class MockRequest:
        def __init__(self):
            self.base_url = "http://test/"
            self._checks = 0

        async def is_disconnected(self):
            self._checks += 1
            return self._checks > 10  # Disconnect after 10 checks

    # Get SSE handler
    sse_handler = None
    for route in app.routes:
        if getattr(route, 'path', None) == '/sse':
            sse_handler = route.endpoint
            break

    response = await sse_handler(MockRequest())

    # Collect events
    events = []
    async for event in response.body_iterator:
        events.append(event)
        if len(events) > 5:  # Collect a few events
            break

    # Should have endpoint and keepalive events
    event_types = [e.get('event') for e in events if isinstance(e, dict)]
    assert 'endpoint' in event_types
    assert 'keepalive' in event_types


@pytest.mark.asyncio
async def test_cors_headers():
    """Test CORS headers are properly set."""
    pubsub = _PubSub()
    stdio = StdIOEndpoint("cat", pubsub)

    cors_origins = ["https://example.com", "http://localhost:3000"]
    app = _build_fastapi(pubsub, stdio, cors_origins=cors_origins)

    # Verify CORS middleware is configured
    middlewares = [str(m) for m in app.user_middleware]
    assert any("CORSMiddleware" in m for m in middlewares)


@pytest.mark.asyncio
async def test_custom_paths():
    """Test custom SSE and message paths."""
    pubsub = _PubSub()
    stdio = StdIOEndpoint("cat", pubsub)

    app = _build_fastapi(
        pubsub,
        stdio,
        sse_path="/custom/events",
        message_path="/custom/send"
    )

    # Check custom routes exist
    routes = [r.path for r in app.routes if hasattr(r, 'path')]
    assert "/custom/events" in routes
    assert "/custom/send" in routes
    assert "/healthz" in routes  # Health check should still be at default


@pytest.mark.asyncio
async def test_session_id_tracking():
    """Test that session IDs are properly generated and tracked."""
    pubsub = _PubSub()
    stdio = StdIOEndpoint("cat", pubsub)

    app = _build_fastapi(pubsub, stdio)

    class MockRequest:
        def __init__(self):
            self.base_url = "http://test/"
            self._disconnected = False

        async def is_disconnected(self):
            if not self._disconnected:
                self._disconnected = True
                return False
            return True

    # Get SSE handler
    sse_handler = None
    for route in app.routes:
        if getattr(route, 'path', None) == '/sse':
            sse_handler = route.endpoint
            break

    # Connect and get endpoint URL
    response = await sse_handler(MockRequest())

    # Get first event (should be endpoint)
    events = []
    async for event in response.body_iterator:
        events.append(event)
        if len(events) >= 1:
            break

    # Verify endpoint event contains session_id
    assert events[0]['event'] == 'endpoint'
    endpoint_url = events[0]['data']
    assert 'session_id=' in endpoint_url

    # Extract session ID
    session_id = endpoint_url.split('session_id=')[1]
    assert len(session_id) == 32  # UUID hex is 32 chars


@pytest.mark.asyncio
async def test_concurrent_requests():
    """Test handling of concurrent message requests."""
    pubsub = _PubSub()

    # Track sent messages
    sent_messages = []

    class MockStdio:
        async def send(self, msg):
            sent_messages.append(msg)

    stdio = MockStdio()
    app = _build_fastapi(pubsub, stdio)

    # Get message handler
    message_handler = None
    for route in app.routes:
        if getattr(route, 'path', None) == '/message':
            message_handler = route.endpoint
            break

    # Send multiple concurrent requests
    requests = []
    for i in range(10):
        # Create a closure to capture the current index
        def create_body_func(idx):
            async def body(self):
                return json.dumps({"id": idx}).encode()
            return body

        req = type('Request', (), {
            'body': create_body_func(i)
        })()
        requests.append(message_handler(req, session_id=f"session_{i}"))

    # Execute all requests concurrently
    responses = await asyncio.gather(*requests)

    # All should succeed
    assert all(r.status_code == 202 for r in responses)
    assert len(sent_messages) == 10

    # Verify all messages were sent
    sent_ids = [json.loads(msg.strip())['id'] for msg in sent_messages]
    assert set(sent_ids) == set(range(10))


@pytest.mark.asyncio
async def test_subprocess_termination():
    """Test graceful subprocess termination."""
    pubsub = _PubSub()

    # Use a long-running command
    stdio = StdIOEndpoint("sleep 100", pubsub)

    await stdio.start()
    assert stdio._proc is not None
    assert stdio._proc.pid > 0

    # Stop should terminate the process
    await stdio.stop()

    # Process should be terminated
    assert stdio._proc.returncode is not None or stdio._proc.terminated


@pytest.mark.asyncio
async def test_large_message_handling():
    """Test handling of large JSON-RPC messages."""
    pubsub = _PubSub()

    # Create a large message
    large_data = "x" * 10000  # 10KB of data
    large_message = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"data": large_data}
    })

    # Publish to subscribers
    q1 = pubsub.subscribe()
    q2 = pubsub.subscribe()

    await pubsub.publish(large_message)

    # Both should receive the full message
    msg1 = await q1.get()
    msg2 = await q2.get()

    assert msg1 == large_message
    assert msg2 == large_message
    assert len(msg1) > 10000


@pytest.mark.asyncio
async def test_queue_overflow_handling():
    """Test handling when subscriber queues are full."""
    pubsub = _PubSub()

    # Subscribe but don't consume
    slow_subscriber = pubsub.subscribe()

    # Fill the queue (max size is 1024)
    for i in range(1025):
        await pubsub.publish(f"message_{i}")

    # Slow subscriber should be removed
    assert slow_subscriber not in pubsub._subscribers

    # New subscriber should work fine
    new_subscriber = pubsub.subscribe()
    await pubsub.publish("new_message")

    msg = await new_subscriber.get()
    assert msg == "new_message"


# Mark slow tests
@pytest.mark.slow
@pytest.mark.asyncio
async def test_long_running_session():
    """Test a long-running SSE session with multiple messages."""
    pubsub = _PubSub()

    # Subscribe first before publishing
    subscriber = pubsub.subscribe()

    # Publish messages
    message_count = 100
    for i in range(message_count):
        await pubsub.publish(f'{{"message": {i}}}')

    # Consume all messages
    received = []
    for _ in range(message_count):
        msg = await asyncio.wait_for(subscriber.get(), timeout=1)
        received.append(msg)

    assert len(received) == message_count
    # Check that all messages are present
    for i in range(message_count):
        expected_msg = f'{{"message": {i}}}'
        assert expected_msg in received
