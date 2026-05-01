# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_rust_mcp_runtime_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the experimental Rust MCP runtime proxy.
"""

# Standard
import base64
from contextlib import contextmanager
import json
import re
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import httpx
import orjson
import pytest

# First-Party
import mcpgateway.transports.rust_mcp_runtime_proxy as proxy_mod
from mcpgateway.transports.rust_mcp_runtime_proxy import RustMCPRuntimeProxy


def _make_receive(body: bytes):
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


@pytest.mark.asyncio
async def test_post_requests_proxy_to_rust_runtime_and_forward_internal_server_header(monkeypatch):
    """POST MCP traffic should be proxied to Rust with server scope carried via an internal header."""
    captured = {}

    class FakeResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = httpx.Headers(
                {
                    "content-type": "application/json",
                    "mcp-session-id": "session-1",
                    "x-contextforge-mcp-runtime": "rust",
                }
            )

        async def aiter_bytes(self):
            yield b'{"jsonrpc":"2.0","id":1,'
            yield b'"result":{"ok":true}}'

    class FakeStreamContext:
        def __init__(self, *, content):
            self._content = content

        async def __aenter__(self):
            if isinstance(self._content, (bytes, bytearray)):
                captured["content"] = bytes(self._content)
            else:
                parts = []
                async for chunk in self._content:
                    parts.append(chunk)
                captured["content"] = b"".join(parts)
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def stream(self, method, url, *, content, headers, timeout, follow_redirects):  # noqa: ANN001
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["timeout"] = timeout
            captured["follow_redirects"] = follow_redirects
            return FakeStreamContext(content=content)

    async def mock_validate_server_id(match, path, scope, receive, send):
        """Mock validation that returns the server_id without database checks."""
        if match:
            return match.group("server_id")
        return None

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_timeout_seconds", 17)
    monkeypatch.setattr(
        "mcpgateway.transports.rust_mcp_runtime_proxy.get_streamable_http_auth_context",
        lambda: {
            "email": "user@example.com",
            "teams": ["team-a"],
            "auth_method": "jwt",
            "is_authenticated": True,
            "is_admin": False,
            "permission_is_admin": True,
            "token_use": "session",
            "scoped_permissions": ["tools.read"],
            "scoped_server_id": "server-scope-1",
        },
    )
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy._validate_server_id", mock_validate_server_id)
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.get_http_client", AsyncMock(return_value=FakeClient()))

    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)
    events = []

    async def send(message):
        events.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "modified_path": "/servers/123e4567-e89b-12d3-a456-426614174000/mcp",
        "query_string": b"session_id=abc123",
        "headers": [
            (b"content-type", b"application/json"),
            (b"authorization", b"Bearer test-token"),
            (b"cookie", b"jwt_token=cookie-token"),
            (b"mcp-protocol-version", b"2025-11-25"),
            (b"x-forwarded-for", b"203.0.113.10"),
            (b"x-forwarded-internally", b"true"),
            (b"x-mcp-session-id", b"internal-only"),
            (b"x-contextforge-server-id", b"spoofed-by-client"),
        ],
    }

    await proxy.handle_streamable_http(
        scope,
        _make_receive(b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'),
        send,
    )

    fallback.assert_not_awaited()
    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:8787/mcp/?session_id=abc123"
    assert captured["timeout"].connect == 17
    assert captured["follow_redirects"] is False

    forwarded_headers = dict(captured["headers"])
    assert forwarded_headers["authorization"] == "Bearer test-token"
    assert forwarded_headers["cookie"] == "jwt_token=cookie-token"
    assert forwarded_headers["mcp-protocol-version"] == "2025-11-25"
    assert "x-forwarded-for" not in forwarded_headers
    assert "x-forwarded-internally" not in forwarded_headers
    assert "x-mcp-session-id" not in forwarded_headers
    assert forwarded_headers["x-contextforge-server-id"] == "123e4567-e89b-12d3-a456-426614174000"
    auth_context = orjson.loads(base64.urlsafe_b64decode(f"{forwarded_headers['x-contextforge-auth-context']}=="))
    assert auth_context == {
        "email": "user@example.com",
        "teams": ["team-a"],
        "auth_method": "jwt",
        "is_authenticated": True,
        "is_admin": False,
        "permission_is_admin": True,
        "token_use": "session",
        "scoped_permissions": ["tools.read"],
        "scoped_server_id": "server-scope-1",
    }
    assert json.loads(captured["content"].decode()) == {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 200
    assert (b"mcp-session-id", b"session-1") in events[0]["headers"]
    assert (b"x-contextforge-mcp-runtime", b"rust") in events[0]["headers"]
    assert events[1]["type"] == "http.response.body"
    assert events[1]["more_body"] is True
    assert events[2]["type"] == "http.response.body"
    assert events[2]["more_body"] is True
    assert events[3] == {"type": "http.response.body", "body": b"", "more_body": False}
    streamed_body = b"".join(event["body"] for event in events[1:3])
    assert json.loads(streamed_body.decode()) == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


@pytest.mark.asyncio
async def test_post_requests_without_server_scope_stream_body_to_rust(monkeypatch):
    """Plain /mcp POSTs should stream the request body through without JSON mutation."""
    captured = {}

    class FakeResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = httpx.Headers({"content-type": "application/json"})

        async def aiter_bytes(self):
            yield b'{"jsonrpc":"2.0","id":1,"result":{}}'

    class FakeStreamContext:
        def __init__(self, *, content):
            self._content = content

        async def __aenter__(self):
            parts = []
            async for chunk in self._content:
                parts.append(chunk)
            captured["content"] = b"".join(parts)
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def stream(self, method, url, *, content, headers, timeout, follow_redirects):  # noqa: ANN001
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["timeout"] = timeout
            captured["follow_redirects"] = follow_redirects
            return FakeStreamContext(content=content)

    async def receive():
        if not hasattr(receive, "calls"):
            receive.calls = 0
        receive.calls += 1
        if receive.calls == 1:
            return {"type": "http.request", "body": b'{"jsonrpc":"2.0","id":1,', "more_body": True}
        if receive.calls == 2:
            return {"type": "http.request", "body": b'"method":"ping","params":{}}', "more_body": False}
        return {"type": "http.disconnect"}

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_timeout_seconds", 17)
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.get_http_client", AsyncMock(return_value=FakeClient()))

    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)
    events = []

    async def send(message):
        events.append(message)

    await proxy.handle_streamable_http(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "modified_path": "/mcp/",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
        send,
    )

    fallback.assert_not_awaited()
    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:8787/mcp/"
    assert captured["content"] == b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'
    assert captured["follow_redirects"] is False
    assert events[-1] == {"type": "http.response.body", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_loopback_internal_forward_marks_affinity_for_rust(monkeypatch):
    """Loopback owner-worker forwards should be marked for Rust without exposing spoofable headers."""
    captured = {}

    class FakeResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = httpx.Headers({"content-type": "application/json"})

        async def aiter_bytes(self):
            yield b'{"jsonrpc":"2.0","id":1,"result":{}}'

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def stream(self, method, url, *, content, headers, timeout, follow_redirects):  # noqa: ANN001
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = dict(headers)
            captured["timeout"] = timeout
            captured["follow_redirects"] = follow_redirects
            return FakeStreamContext()

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_timeout_seconds", 17)
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.get_http_client", AsyncMock(return_value=FakeClient()))
    monkeypatch.setattr(
        "mcpgateway.transports.rust_mcp_runtime_proxy.get_streamable_http_auth_context",
        lambda: {"email": "owner@example.com", "token_use": "session"},
    )

    proxy = RustMCPRuntimeProxy(AsyncMock())
    events = []

    async def send(message):
        events.append(message)

    await proxy.handle_streamable_http(
        {
            "type": "http",
            "client": ("127.0.0.1", 40123),
            "method": "GET",
            "path": "/mcp",
            "modified_path": "/mcp",
            "query_string": b"session_id=session-1",
            "headers": [
                (b"accept", b"text/event-stream"),
                (b"x-forwarded-internally", b"true"),
                (b"x-original-worker", b"worker-123"),
            ],
        },
        _make_receive(b""),
        send,
    )

    assert captured["method"] == "GET"
    assert captured["url"] == "http://127.0.0.1:8787/mcp/?session_id=session-1"
    assert captured["follow_redirects"] is False
    assert captured["headers"]["x-contextforge-affinity-forwarded"] == "rust"
    assert "x-forwarded-internally" not in captured["headers"]
    assert "x-original-worker" not in captured["headers"]
    assert "x-contextforge-auth-context" in captured["headers"]
    assert events[0]["status"] == 200


@pytest.mark.asyncio
async def test_get_requests_proxy_to_rust_runtime(monkeypatch):
    """GET MCP transport traffic should be proxied to Rust instead of falling back to Python."""
    captured = {}

    class FakeResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = httpx.Headers(
                {
                    "content-type": "text/event-stream",
                    "x-contextforge-mcp-runtime": "rust",
                    "mcp-session-id": "session-1",
                }
            )

        async def aiter_bytes(self):
            yield b"data: ping\\n\\n"

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def stream(self, method, url, *, content, headers, timeout, follow_redirects):  # noqa: ANN001
            captured["method"] = method
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            captured["timeout"] = timeout
            captured["follow_redirects"] = follow_redirects
            return FakeStreamContext()

    async def mock_validate_server_id(match, path, scope, receive, send):
        """Mock validation that returns the server_id without database checks."""
        if match:
            return match.group("server_id")
        return None

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_timeout_seconds", 17)
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy._validate_server_id", mock_validate_server_id)
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.get_http_client", AsyncMock(return_value=FakeClient()))

    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)
    events = []

    async def send(message):
        events.append(message)

    await proxy.handle_streamable_http(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "modified_path": "/servers/123e4567-e89b-12d3-a456-426614174000/mcp",
            "query_string": b"session_id=abc123",
            "headers": [
                (b"authorization", b"Bearer test-token"),
                (b"mcp-session-id", b"session-1"),
            ],
        },
        _make_receive(b""),
        send,
    )

    fallback.assert_not_awaited()
    assert captured["method"] == "GET"
    assert captured["url"] == "http://127.0.0.1:8787/mcp/?session_id=abc123"
    assert captured["content"] == b""
    assert captured["follow_redirects"] is False
    assert dict(captured["headers"])["x-contextforge-server-id"] == "123e4567-e89b-12d3-a456-426614174000"
    assert events[0]["status"] == 200
    assert (b"content-type", b"text/event-stream") in events[0]["headers"]
    assert (b"mcp-session-id", b"session-1") in events[0]["headers"]
    assert events[1]["body"] == b"data: ping\\n\\n"
    assert events[2] == {"type": "http.response.body", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_post_requests_use_uds_client_when_configured(monkeypatch):
    """Configured Rust runtime UDS should use a dedicated client instead of the shared HTTP client."""
    constructed = {}

    class FakeResponse:
        status_code = 200
        headers = httpx.Headers({"content-type": "application/json"})

        async def aiter_bytes(self):
            yield b'{"jsonrpc":"2.0","id":1,"result":{}}'

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            constructed["kwargs"] = kwargs

        def stream(self, method, url, *, content, headers, timeout, follow_redirects):  # noqa: ANN001
            constructed["method"] = method
            constructed["url"] = url
            constructed["headers"] = headers
            constructed["timeout"] = timeout
            constructed["follow_redirects"] = follow_redirects
            return FakeStreamContext()

    get_http_client_mock = AsyncMock()

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://localhost")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_uds", "/tmp/contextforge-mcp-rust.sock")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_timeout_seconds", 9)
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.get_http_client", get_http_client_mock)
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.httpx.AsyncClient", FakeAsyncClient)

    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)
    events = []

    async def send(message):
        events.append(message)

    await proxy.handle_streamable_http(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "modified_path": "/mcp/",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        _make_receive(b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'),
        send,
    )

    get_http_client_mock.assert_not_awaited()
    assert constructed["method"] == "POST"
    assert constructed["url"] == "http://localhost/mcp/"
    assert constructed["kwargs"]["transport"]._pool._uds == "/tmp/contextforge-mcp-rust.sock"  # pylint: disable=protected-access
    assert constructed["kwargs"]["follow_redirects"] is False
    assert constructed["follow_redirects"] is False
    assert events[-1] == {"type": "http.response.body", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_runtime_proxy_surfaces_redirect_without_following(monkeypatch):
    """Internal runtime redirects should be surfaced directly and never auto-followed."""
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(str(request.url))
        if request.url.path == "/mcp/":
            return httpx.Response(
                307,
                headers={"location": "http://127.0.0.1:8787/final"},
                request=request,
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"unexpected": True}}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.get_http_client", AsyncMock(return_value=client))

    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)
    events = []

    async def send(message):
        events.append(message)

    try:
        await proxy.handle_streamable_http(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "modified_path": "/mcp",
                "query_string": b"session_id=abc123",
                "headers": [],
            },
            _make_receive(b""),
            send,
        )
    finally:
        await client.aclose()

    fallback.assert_not_awaited()
    assert requests_seen == ["http://127.0.0.1:8787/mcp/?session_id=abc123"]
    assert events[0]["status"] == 307
    assert (b"location", b"http://127.0.0.1:8787/final") in events[0]["headers"]
    assert events[-1] == {"type": "http.response.body", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_unsupported_methods_fall_back_to_python_transport():
    """Unsupported MCP transport methods should keep using the Python transport."""
    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        return None

    await proxy.handle_streamable_http(
        {
            "type": "http",
            "method": "OPTIONS",
            "path": "/",
            "modified_path": "/mcp/",
            "headers": [],
            "query_string": b"",
        },
        receive,
        send,
    )

    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_http_scopes_fall_back_to_python_transport():
    """Non-HTTP ASGI scopes should be forwarded to the Python fallback app."""
    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)

    async def receive():
        return {"type": "websocket.disconnect"}

    async def send(_message):
        return None

    await proxy.handle_streamable_http(
        {
            "type": "websocket",
            "path": "/mcp/",
        },
        receive,
        send,
    )

    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_request_body_skips_non_request_messages_and_disconnects():
    """Request-body streaming should ignore non-request frames and stop on disconnect."""

    async def receive():
        if not hasattr(receive, "calls"):
            receive.calls = 0
        receive.calls += 1
        if receive.calls == 1:
            return {"type": "lifespan.startup"}
        if receive.calls == 2:
            return {"type": "http.request", "body": b"abc", "more_body": True}
        if receive.calls == 3:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"ignored", "more_body": False}

    chunks = []
    async for chunk in proxy_mod._stream_request_body(receive):
        chunks.append(chunk)

    assert chunks == [b"abc"]


def test_build_runtime_mcp_url_handles_empty_and_prefixed_base_paths(monkeypatch):
    """The Rust runtime target URL should normalize base paths consistently."""
    scope = {"query_string": b"session_id=sess-1"}

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
    assert proxy_mod._build_runtime_mcp_url(scope) == "http://127.0.0.1:8787/mcp/?session_id=sess-1"

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787/base")
    assert proxy_mod._build_runtime_mcp_url(scope) == "http://127.0.0.1:8787/base/mcp/?session_id=sess-1"

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787/base/mcp")
    assert proxy_mod._build_runtime_mcp_url(scope) == "http://127.0.0.1:8787/base/mcp/?session_id=sess-1"


def test_build_forward_headers_skips_malformed_and_non_bytes_headers(monkeypatch):
    """Malformed header tuples and non-bytes headers should be ignored safely."""
    monkeypatch.setattr(
        "mcpgateway.transports.rust_mcp_runtime_proxy.get_streamable_http_auth_context",
        lambda: {},
    )

    headers = proxy_mod._build_forward_headers(
        {
            "headers": [
                ("authorization", "bad-types"),
                (b"authorization", b"Bearer token"),
                (b"x-forwarded-for", b"203.0.113.10"),
                (b"x-contextforge-server-id", b"spoofed"),
                (b"cookie", b"jwt_token=cookie-token"),
                (b"broken",),
            ],
            "modified_path": "/servers/123e4567-e89b-12d3-a456-426614174000/mcp",
        }
    )

    assert ("authorization", "Bearer token") in headers
    assert ("cookie", "jwt_token=cookie-token") in headers
    assert ("x-contextforge-server-id", "123e4567-e89b-12d3-a456-426614174000") in headers
    assert not any(name == "x-forwarded-for" for name, _value in headers)


def test_build_forward_headers_marks_affinity_forwarded_for_loopback_internal_requests(monkeypatch):
    """Loopback requests forwarded internally should be marked for Rust affinity handling."""
    monkeypatch.setattr(
        "mcpgateway.transports.rust_mcp_runtime_proxy.get_streamable_http_auth_context",
        lambda: {},
    )

    headers = proxy_mod._build_forward_headers(
        {
            "headers": [(b"x-forwarded-internally", b"true")],
            "client": ("127.0.0.1", 4444),
            "modified_path": "/mcp/",
        }
    )

    assert ("x-contextforge-affinity-forwarded", "rust") in headers


@pytest.mark.asyncio
async def test_get_runtime_client_reuses_uds_client(monkeypatch):
    """Configured UDS clients should be constructed once and reused."""
    constructed = {"count": 0}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            constructed["count"] += 1

    proxy = RustMCPRuntimeProxy(AsyncMock())
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_uds", "/tmp/contextforge-mcp-rust.sock")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.httpx.AsyncClient", FakeAsyncClient)

    first = await proxy._get_runtime_client()
    second = await proxy._get_runtime_client()

    assert first is second
    assert constructed["count"] == 1


@pytest.mark.asyncio
async def test_runtime_failure_returns_jsonrpc_bad_gateway(monkeypatch):
    """Connection failures to the Rust sidecar should return a JSON-RPC 502 error."""

    class FailingClient:
        def stream(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise httpx.ConnectError("connect failed")

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.get_http_client", AsyncMock(return_value=FailingClient()))
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")

    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)
    events = []

    async def send(message):
        events.append(message)

    await proxy.handle_streamable_http(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "modified_path": "/mcp/",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
        },
        _make_receive(b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'),
        send,
    )

    fallback.assert_not_awaited()
    assert events[0]["status"] == 502
    body = json.loads(events[1]["body"].decode())
    assert body["error"]["code"] == -32000
    assert body["error"]["message"] == "Experimental Rust MCP runtime unavailable"
    assert body["error"]["data"] == "See server logs"


@pytest.mark.asyncio
async def test_validate_server_id_returns_server_id_when_exists(monkeypatch):
    """_validate_server_id should return the server_id string when the server exists."""
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = True
    mock_db.execute.return_value = mock_result

    @contextmanager
    def mock_fresh_db_session():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.fresh_db_session", mock_fresh_db_session)

    scope = {"type": "http", "method": "POST"}
    receive = _make_receive(b"")
    send = AsyncMock()

    match = re.match(r"/servers/(?P<server_id>[^/]+)/mcp", "/servers/aabbccdd11223344/mcp")
    result = await proxy_mod._validate_server_id(match, "/servers/aabbccdd11223344/mcp", scope, receive, send)

    assert result == "aabbccdd11223344"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_server_id_returns_404_when_server_not_found(monkeypatch):
    """_validate_server_id should return 404 when server doesn't exist in database."""
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = False
    mock_db.execute.return_value = mock_result

    @contextmanager
    def mock_fresh_db_session():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.fresh_db_session", mock_fresh_db_session)

    events = []

    async def send(message):
        events.append(message)

    scope = {"type": "http", "method": "POST"}
    receive = _make_receive(b"")

    match = re.match(r"/servers/(?P<server_id>[^/]+)/mcp", "/servers/nonexistent-server/mcp")

    result = await proxy_mod._validate_server_id(match, "/servers/nonexistent-server/mcp", scope, receive, send)

    assert result is proxy_mod._REJECT
    assert len(events) == 2
    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 404
    assert b"Server not found" in events[1]["body"]


@pytest.mark.asyncio
async def test_validate_server_id_returns_503_on_database_error(monkeypatch):
    """_validate_server_id should return 503 when database query fails."""

    @contextmanager
    def mock_fresh_db_session():
        raise Exception("Database connection failed")
        yield  # unreachable — required by contextmanager protocol

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.fresh_db_session", mock_fresh_db_session)

    events = []

    async def send(message):
        events.append(message)

    scope = {"type": "http", "method": "POST"}
    receive = _make_receive(b"")

    match = re.match(r"/servers/(?P<server_id>[^/]+)/mcp", "/servers/test-server/mcp")

    result = await proxy_mod._validate_server_id(match, "/servers/test-server/mcp", scope, receive, send)

    assert result is proxy_mod._REJECT
    assert len(events) == 2
    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 503
    assert b"Service unavailable" in events[1]["body"]


@pytest.mark.asyncio
async def test_validate_server_id_rejects_malformed_server_scoped_paths(monkeypatch):
    """_validate_server_id should reject server-scoped paths with unparseable server IDs."""
    events = []

    async def send(message):
        events.append(message)

    scope = {"type": "http", "method": "POST"}
    receive = _make_receive(b"")

    # No match (None) but path looks server-scoped (defense-in-depth)
    result = await proxy_mod._validate_server_id(None, "/servers//mcp", scope, receive, send)

    assert result is proxy_mod._REJECT
    assert len(events) == 2
    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 404
    assert b"Invalid server identifier" in events[1]["body"]


@pytest.mark.asyncio
async def test_handle_streamable_http_rejects_invalid_server_id(monkeypatch):
    """handle_streamable_http should reject requests when server validation fails."""
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = False
    mock_db.execute.return_value = mock_result

    @contextmanager
    def mock_fresh_db_session():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.fresh_db_session", mock_fresh_db_session)
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")

    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)
    events = []

    async def send(message):
        events.append(message)

    # Use a hex server ID (matches _SERVER_ID_RE) that doesn't exist in DB
    await proxy.handle_streamable_http(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "modified_path": "/servers/aabbccdd11223344aabbccdd11223344/mcp",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        _make_receive(b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'),
        send,
    )

    # Should not fall back to Python, should reject with 404
    fallback.assert_not_awaited()
    assert len(events) == 2
    assert events[0]["status"] == 404
    assert b"Server not found" in events[1]["body"]


@pytest.mark.asyncio
async def test_handle_streamable_http_rejects_non_hex_server_id_via_defense_in_depth(monkeypatch):
    """Proxy-level: non-hex server IDs should be rejected by the defense-in-depth guard without reaching fallback or Rust."""
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")

    get_http_client_mock = AsyncMock()
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.get_http_client", get_http_client_mock)

    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)
    events = []

    async def send(message):
        events.append(message)

    await proxy.handle_streamable_http(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "modified_path": "/servers/ndh45/mcp",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        _make_receive(b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'),
        send,
    )

    fallback.assert_not_awaited()
    get_http_client_mock.assert_not_awaited()
    assert len(events) == 2
    assert events[0]["status"] == 404
    assert b"Invalid server identifier" in events[1]["body"]
