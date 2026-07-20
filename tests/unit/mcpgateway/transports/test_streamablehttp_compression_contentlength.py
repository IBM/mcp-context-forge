# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_streamablehttp_compression_contentlength.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for issue #5457: Content-Length mismatch when compression enabled.

This test suite verifies that the streamable HTTP transport does NOT manually
set Content-Length headers, allowing the compression middleware (or ASGI server)
to set them correctly after compression.

Bug Background
--------------
When compression is enabled (COMPRESSION_ENABLED=true, the default), manually
setting Content-Length in the transport layer based on uncompressed body size
causes "Too much data for declared Content-Length" errors because the compression
middleware compresses the body AFTER the headers are sent.

The fix: Remove all manual Content-Length header additions from the transport
layer at these locations:
1. Line 1312 - _send_streamable_http_json_response()
2. Line 4182 - Loopback /rpc routing
3. Line 4246 - Redis-forwarded responses
4. Line 4348 - Local session owner /rpc routing

These tests ensure the fix remains in place and prevent regression.
"""

# Future
from __future__ import annotations

# Standard
import gzip
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from starlette.types import ASGIApp, Receive, Scope, Send

# First-Party
from mcpgateway.middleware.compression import SSEAwareCompressMiddleware
from mcpgateway.transports.streamablehttp_transport import _send_streamable_http_json_response


class ContentLengthCapturingApp:
    """Test app that captures the Content-Length header sent via ASGI send()."""

    def __init__(self):
        self.response_headers: list[tuple[bytes, bytes]] = []
        self.response_body: bytes = b""
        self.response_status: int = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Capture headers and body from send() calls."""

        async def capturing_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.response_status = message["status"]
                self.response_headers = message.get("headers", [])
            elif message["type"] == "http.response.body":
                self.response_body += message.get("body", b"")

        # Call the upstream handler (if any) with our capturing send
        await send(message := {"type": "http.response.start", "status": 200, "headers": []})

    def get_header(self, name: bytes) -> bytes | None:
        """Get header value by name (case-insensitive)."""
        name_lower = name.lower()
        for key, value in self.response_headers:
            if key.lower() == name_lower:
                return value
        return None


class CompressionCapturingMiddleware:
    """Middleware that captures headers/body AFTER compression middleware processes them."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.captured_headers: list[tuple[bytes, bytes]] = []
        self.captured_body: bytes = b""
        self.captured_status: int = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Wrap send() to capture final headers/body after compression."""

        async def capturing_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.captured_status = message["status"]
                self.captured_headers = message.get("headers", [])
            elif message["type"] == "http.response.body":
                self.captured_body += message.get("body", b"")

            # Also call the original send
            await send(message)

        await self.app(scope, receive, capturing_send)

    def get_header(self, name: bytes) -> bytes | None:
        """Get header value by name (case-insensitive)."""
        name_lower = name.lower()
        for key, value in self.captured_headers:
            if key.lower() == name_lower:
                return value
        return None


@pytest.mark.asyncio
async def test_send_json_response_no_content_length():
    """Test that _send_streamable_http_json_response does NOT set Content-Length.

    Regression test for issue #5457 (line 1312 fix).
    """
    sent_messages = []

    async def mock_send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    payload = {"jsonrpc": "2.0", "result": {"status": "ok"}}
    await _send_streamable_http_json_response(mock_send, status_code=200, payload=payload)

    # Verify we got http.response.start and http.response.body
    assert len(sent_messages) == 2
    assert sent_messages[0]["type"] == "http.response.start"
    assert sent_messages[1]["type"] == "http.response.body"

    # Check headers - should only have content-type, NOT content-length
    headers = dict(sent_messages[0]["headers"])
    assert b"content-type" in headers
    assert headers[b"content-type"] == b"application/json"

    # CRITICAL: Content-Length must NOT be present (let compression middleware set it)
    assert b"content-length" not in headers, "Content-Length must not be manually set (issue #5457)"


@pytest.mark.asyncio
async def test_compression_middleware_sets_content_length_correctly():
    """Test that compression middleware sets correct Content-Length after compression.

    This test verifies the complete flow:
    1. Transport layer sends response WITHOUT Content-Length
    2. Compression middleware compresses the body
    3. Compression middleware sets Content-Length to match compressed size

    Regression test for issue #5457.
    """
    # Create a response body that will compress significantly
    uncompressed_payload = {"data": "x" * 1000}  # ~1KB of repeated chars

    # Create test app
    app_called = False

    async def test_app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal app_called
        app_called = True

        # Simulate what the transport layer does: send response WITHOUT Content-Length
        await _send_streamable_http_json_response(send, status_code=200, payload=uncompressed_payload)

    # Wrap with compression middleware
    compression_middleware = SSEAwareCompressMiddleware(
        test_app,
        minimum_size=100,  # Low threshold to ensure compression happens
        gzip_level=6,
    )

    # Create capturing middleware to intercept final output
    capturing = CompressionCapturingMiddleware(compression_middleware)

    # Simulate ASGI request
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "query_string": b"",
        "headers": [(b"accept-encoding", b"gzip")],  # Request gzip compression
    }

    received_messages = []

    async def mock_receive() -> dict[str, Any]:
        if not received_messages:
            received_messages.append(True)
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    final_output = []

    async def mock_send(message: dict[str, Any]) -> None:
        final_output.append(message)

    # Execute the request through the middleware stack
    await capturing(scope, mock_receive, mock_send)

    # Verify the app was called
    assert app_called

    # Verify we got output
    assert len(final_output) >= 2

    # Get the final headers after compression
    start_message = final_output[0]
    assert start_message["type"] == "http.response.start"

    final_headers = dict(start_message["headers"])

    # CRITICAL ASSERTIONS:
    # 1. Content-Length MUST be present (set by compression middleware)
    assert b"content-length" in final_headers, "Compression middleware should set Content-Length"

    # 2. Content-Length must match the actual compressed body size
    content_length = int(final_headers[b"content-length"].decode())

    # Collect all body chunks
    compressed_body = b""
    for msg in final_output[1:]:
        if msg["type"] == "http.response.body":
            compressed_body += msg.get("body", b"")

    actual_body_size = len(compressed_body)

    assert content_length == actual_body_size, (
        f"Content-Length ({content_length}) must match actual compressed body size ({actual_body_size}). "
        f"This is the bug from issue #5457!"
    )

    # 3. Verify compression actually happened (compressed size < uncompressed size)
    import orjson

    uncompressed_size = len(orjson.dumps(uncompressed_payload))
    assert actual_body_size < uncompressed_size, "Body should be compressed (smaller than uncompressed)"

    # 4. Verify the compressed body is valid gzip
    if b"content-encoding" in final_headers and final_headers[b"content-encoding"] == b"gzip":
        try:
            decompressed = gzip.decompress(compressed_body)
            assert len(decompressed) == uncompressed_size, "Decompressed size should match original"
        except Exception as e:
            pytest.fail(f"Failed to decompress body: {e}")


@pytest.mark.asyncio
async def test_loopback_rpc_routing_no_content_length():
    """Test that loopback /rpc routing does NOT manually set Content-Length.

    Regression test for issue #5457 (line 4182 and 4348 fixes).
    This tests the code path where requests are routed to the internal /rpc endpoint.
    """
    # This is tested indirectly through integration tests, but we document
    # the requirement here: when routing to /rpc, response_headers should NOT
    # include Content-Length.

    # The fixed code should look like:
    # response_headers = [
    #     (b"content-type", b"application/json"),
    #     # NO (b"content-length", ...) here!
    # ]

    # Verify by checking the actual source code (static analysis)
    import inspect

    from mcpgateway.transports import streamablehttp_transport

    source = inspect.getsource(streamablehttp_transport)

    # Count occurrences of manual Content-Length setting (should be 0)
    # Pattern: (b"content-length", str(len(...)).encode())
    import re

    pattern = r'b["\']content-length["\'].*str\(len\('
    matches = re.findall(pattern, source, re.IGNORECASE)

    assert len(matches) == 0, (
        f"Found {len(matches)} manual Content-Length header(s) in streamablehttp_transport.py. "
        f"All manual Content-Length settings should be removed (issue #5457). "
        f"Matches: {matches}"
    )


@pytest.mark.asyncio
async def test_redis_forwarded_response_no_content_length():
    """Test that Redis-forwarded responses do NOT manually add Content-Length.

    Regression test for issue #5457 (line 4246 fix).
    When forwarding responses from owner workers via Redis, the transport
    should NOT add Content-Length to the response_headers.
    """
    # This is tested indirectly through integration tests with Redis.
    # The key requirement: after filtering out transfer-encoding, content-encoding,
    # and content-length from forwarded headers, we must NOT re-add content-length.

    # The fixed code should look like:
    # response_headers = [(k.encode(), v.encode()) for k, v in response["headers"].items()
    #                     if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")]
    # # NO response_headers.append((b"content-length", ...)) here!

    # This is covered by the static analysis test above (test_loopback_rpc_routing_no_content_length)
    pass


@pytest.mark.asyncio
async def test_content_length_with_compression_disabled():
    """Test that responses work correctly even when compression is disabled.

    When compression is disabled, the ASGI server (uvicorn/gunicorn) will
    automatically set Content-Length based on the body size. Our transport
    should still NOT manually set it.
    """
    sent_messages = []

    async def mock_send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    payload = {"result": "test"}
    await _send_streamable_http_json_response(mock_send, status_code=200, payload=payload)

    # Verify headers
    assert len(sent_messages) == 2
    headers = dict(sent_messages[0]["headers"])

    # Content-Length should NOT be present (even with compression disabled)
    assert b"content-length" not in headers, "Content-Length must never be manually set by transport layer"

    # The ASGI server will add it automatically when serving the response


@pytest.mark.asyncio
async def test_large_response_with_compression():
    """Test that large responses are compressed correctly with proper Content-Length.

    This test verifies the fix works for large responses that benefit most from compression.
    """
    # Create a large payload (10KB of repeated data - highly compressible)
    large_payload = {"data": "x" * 10000, "items": [{"id": i, "value": "test" * 10} for i in range(100)]}

    app_called = False

    async def test_app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal app_called
        app_called = True
        await _send_streamable_http_json_response(send, status_code=200, payload=large_payload)

    compression_middleware = SSEAwareCompressMiddleware(test_app, minimum_size=500, gzip_level=6)
    capturing = CompressionCapturingMiddleware(compression_middleware)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "query_string": b"",
        "headers": [(b"accept-encoding", b"gzip")],
    }

    async def mock_receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    final_output = []

    async def mock_send(message: dict[str, Any]) -> None:
        final_output.append(message)

    await capturing(scope, mock_receive, mock_send)

    assert app_called
    assert len(final_output) >= 2

    # Check final headers
    final_headers = dict(final_output[0]["headers"])
    assert b"content-length" in final_headers

    content_length = int(final_headers[b"content-length"].decode())

    # Collect body
    compressed_body = b""
    for msg in final_output[1:]:
        if msg["type"] == "http.response.body":
            compressed_body += msg.get("body", b"")

    actual_size = len(compressed_body)

    # CRITICAL: Content-Length must match actual body size
    assert content_length == actual_size, (
        f"Content-Length mismatch: declared {content_length} but actual {actual_size}. "
        f"This is the bug from issue #5457!"
    )

    # Verify significant compression (should be < 50% of original for this test data)
    import orjson

    uncompressed_size = len(orjson.dumps(large_payload))
    compression_ratio = actual_size / uncompressed_size

    assert compression_ratio < 0.5, f"Expected compression ratio < 0.5, got {compression_ratio:.2%}"
