# -*- coding: utf-8 -*-
"""Unit tests for the experimental Rust MCP runtime proxy."""

# Standard
import base64
import json
from unittest.mock import AsyncMock

# Third-Party
import httpx
import orjson
import pytest

# First-Party
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
        def stream(self, method, url, *, content, headers, timeout):  # noqa: ANN001
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["timeout"] = timeout
            return FakeStreamContext(content=content)

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_timeout_seconds", 17)
    monkeypatch.setattr(
        "mcpgateway.transports.rust_mcp_runtime_proxy.get_streamable_http_auth_context",
        lambda: {
            "email": "user@example.com",
            "teams": ["team-a"],
            "is_authenticated": True,
            "is_admin": False,
            "permission_is_admin": True,
            "token_use": "session",
            "scoped_permissions": ["tools.read"],
            "scoped_server_id": "server-scope-1",
        },
    )
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
        def stream(self, method, url, *, content, headers, timeout):  # noqa: ANN001
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            captured["timeout"] = timeout
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
    assert events[-1] == {"type": "http.response.body", "body": b"", "more_body": False}


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

        def stream(self, method, url, *, content, headers, timeout):  # noqa: ANN001
            constructed["method"] = method
            constructed["url"] = url
            constructed["headers"] = headers
            constructed["timeout"] = timeout
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
    assert events[-1] == {"type": "http.response.body", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_non_post_requests_fall_back_to_python_transport():
    """Non-POST MCP requests should keep using the Python transport."""
    fallback = AsyncMock()
    proxy = RustMCPRuntimeProxy(fallback)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        return None

    await proxy.handle_streamable_http(
        {
            "type": "http",
            "method": "GET",
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
