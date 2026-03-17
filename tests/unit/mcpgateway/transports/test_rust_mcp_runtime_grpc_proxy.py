# -*- coding: utf-8 -*-
"""Unit tests for the gRPC-over-UDS Rust MCP runtime proxy (ADR-044)."""

# Standard
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import orjson
import pytest

# First-Party
import mcpgateway.transports.rust_mcp_runtime_grpc_proxy as grpc_proxy_mod
from mcpgateway.transports.grpc_gen import mcp_runtime_pb2
from mcpgateway.transports.rust_mcp_runtime_grpc_proxy import (
    RustMCPRuntimeGrpcProxy,
    _build_mcp_request,
    _build_safe_headers,
    _extract_server_id,
    _extract_session_id,
    _is_affinity_forwarded,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTH_CONTEXT = {
    "email": "user@example.com",
    "teams": ["team-a"],
    "is_authenticated": True,
    "is_admin": False,
    "permission_is_admin": True,
    "token_use": "session",
    "scoped_permissions": ["tools.read"],
    "scoped_server_id": "server-scope-1",
}

_SCOPE_POST = {
    "type": "http",
    "method": "POST",
    "path": "/mcp/",
    "modified_path": "/servers/123e4567-e89b-12d3-a456-426614174000/mcp",
    "query_string": b"session_id=abc123",
    "client": ("203.0.113.10", 9000),
    "headers": [
        (b"content-type", b"application/json"),
        (b"authorization", b"Bearer test-token"),
        (b"mcp-protocol-version", b"2025-11-25"),
        (b"mcp-session-id", b"sess-xyz"),
        (b"x-forwarded-for", b"203.0.113.10"),
        (b"x-forwarded-internally", b"true"),
        (b"x-mcp-session-id", b"internal-only"),
        (b"x-contextforge-server-id", b"spoofed-by-client"),
    ],
}


def _make_receive(body: bytes):
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _make_unary_response(status: int = 200, headers: dict | None = None, body: bytes = b"") -> mcp_runtime_pb2.McpResponse:
    resp = mcp_runtime_pb2.McpResponse()
    resp.status = status
    resp.body = body
    for k, v in (headers or {}).items():
        resp.headers[k] = v
    return resp


def _make_chunk(data: bytes, done: bool = False, error_status: int = 0) -> mcp_runtime_pb2.McpChunk:
    chunk = mcp_runtime_pb2.McpChunk()
    chunk.data = data
    chunk.done = done
    chunk.error_status = error_status
    return chunk


# ---------------------------------------------------------------------------
# Unit tests: header helpers
# ---------------------------------------------------------------------------


def test_extract_server_id_from_servers_path():
    scope = {"modified_path": "/servers/123e4567-e89b-12d3-a456-426614174000/mcp"}
    assert _extract_server_id(scope) == "123e4567-e89b-12d3-a456-426614174000"


def test_extract_server_id_returns_empty_for_plain_mcp():
    scope = {"path": "/mcp/"}
    assert _extract_server_id(scope) == ""


def test_extract_session_id_from_headers():
    scope = {"headers": [(b"mcp-session-id", b"sess-abc")]}
    assert _extract_session_id(scope) == "sess-abc"


def test_extract_session_id_returns_empty_when_absent():
    scope = {"headers": [(b"content-type", b"application/json")]}
    assert _extract_session_id(scope) == ""


def test_safe_headers_strips_internal_and_hop_by_hop():
    scope = {
        "headers": [
            (b"authorization", b"Bearer tok"),
            (b"content-type", b"application/json"),
            (b"host", b"localhost"),
            (b"connection", b"keep-alive"),
            (b"x-forwarded-for", b"1.2.3.4"),
            (b"x-mcp-session-id", b"internal"),
            (b"x-contextforge-server-id", b"spoofed"),
            (b"x-contextforge-auth-context", b"spoofed-auth"),
        ]
    }
    headers = _build_safe_headers(scope)
    assert headers["authorization"] == "Bearer tok"
    assert headers["content-type"] == "application/json"
    assert "host" not in headers
    assert "connection" not in headers
    assert "x-forwarded-for" not in headers
    assert "x-mcp-session-id" not in headers
    assert "x-contextforge-server-id" not in headers
    assert "x-contextforge-auth-context" not in headers


def test_affinity_forwarded_true_for_loopback_with_header():
    scope = {
        "client": ("127.0.0.1", 1234),
        "headers": [(b"x-forwarded-internally", b"true")],
    }
    assert _is_affinity_forwarded(scope) is True


def test_affinity_forwarded_false_for_external_client():
    scope = {
        "client": ("203.0.113.5", 1234),
        "headers": [(b"x-forwarded-internally", b"true")],
    }
    assert _is_affinity_forwarded(scope) is False


# ---------------------------------------------------------------------------
# Unit tests: McpRequest construction
# ---------------------------------------------------------------------------


def test_build_mcp_request_populates_all_fields(monkeypatch):
    monkeypatch.setattr(
        grpc_proxy_mod,
        "get_streamable_http_auth_context",
        lambda: _AUTH_CONTEXT,
    )
    body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
    req = _build_mcp_request(_SCOPE_POST, "POST", body)

    assert req.method == "POST"
    assert req.path == "/mcp/"
    assert req.query == "session_id=abc123"
    assert req.body == body
    assert req.server_id == "123e4567-e89b-12d3-a456-426614174000"
    assert req.session_id == "sess-xyz"
    assert req.affinity_forwarded is False  # client is external IP

    # Auth context encoded correctly
    assert req.auth_context.encoded != ""
    decoded = orjson.loads(base64.urlsafe_b64decode(req.auth_context.encoded + "=="))
    assert decoded["email"] == "user@example.com"
    assert decoded["teams"] == ["team-a"]

    # Safe headers only
    assert "authorization" in req.headers
    assert "content-type" in req.headers
    assert "x-contextforge-server-id" not in req.headers
    assert "x-forwarded-for" not in req.headers


def test_build_mcp_request_no_auth_context(monkeypatch):
    monkeypatch.setattr(grpc_proxy_mod, "get_streamable_http_auth_context", lambda: None)
    req = _build_mcp_request({"type": "http", "method": "GET", "path": "/mcp/", "query_string": b"", "headers": [], "client": None}, "GET", b"")
    assert not req.HasField("auth_context")


# ---------------------------------------------------------------------------
# Integration tests: proxy ASGI flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_proxied_via_grpc_unary(monkeypatch):
    """POST /mcp should call Invoke and stream the response body back."""
    grpc_response = _make_unary_response(
        status=200,
        headers={"content-type": "application/json", "mcp-session-id": "sess-1"},
        body=b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}',
    )

    mock_stub = MagicMock()
    mock_stub.Invoke = AsyncMock(return_value=grpc_response)

    monkeypatch.setattr(grpc_proxy_mod, "get_streamable_http_auth_context", lambda: None)
    monkeypatch.setattr(grpc_proxy_mod.settings, "experimental_rust_mcp_runtime_grpc_uds", "/tmp/test.sock")

    fallback = AsyncMock()
    proxy = RustMCPRuntimeGrpcProxy(fallback)
    proxy._stub = mock_stub

    events = []

    async def send(msg):
        events.append(msg)

    await proxy.handle_streamable_http(
        _SCOPE_POST,
        _make_receive(b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'),
        send,
    )

    fallback.assert_not_awaited()
    mock_stub.Invoke.assert_awaited_once()

    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 200
    assert events[1]["type"] == "http.response.body"
    assert events[1]["more_body"] is False
    assert json.loads(events[1]["body"]) == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}


@pytest.mark.asyncio
async def test_delete_proxied_via_grpc_close_session(monkeypatch):
    """DELETE /mcp should call CloseSession."""
    grpc_response = _make_unary_response(status=200, body=b"")

    mock_stub = MagicMock()
    mock_stub.CloseSession = AsyncMock(return_value=grpc_response)

    monkeypatch.setattr(grpc_proxy_mod, "get_streamable_http_auth_context", lambda: None)
    monkeypatch.setattr(grpc_proxy_mod.settings, "experimental_rust_mcp_runtime_grpc_uds", "/tmp/test.sock")

    scope = {**_SCOPE_POST, "method": "DELETE"}
    fallback = AsyncMock()
    proxy = RustMCPRuntimeGrpcProxy(fallback)
    proxy._stub = mock_stub

    events = []

    async def send(msg):
        events.append(msg)

    await proxy.handle_streamable_http(scope, _make_receive(b""), send)

    mock_stub.CloseSession.assert_awaited_once()
    assert events[0]["status"] == 200


@pytest.mark.asyncio
async def test_get_proxied_via_grpc_server_streaming(monkeypatch):
    """GET /mcp should call InvokeStream and forward chunks as SSE body parts."""

    async def fake_stream(_req):
        yield _make_chunk(b"data: {}\n\n", done=False)
        yield _make_chunk(b"data: done\n\n", done=True)

    mock_stub = MagicMock()
    mock_stub.InvokeStream = fake_stream

    monkeypatch.setattr(grpc_proxy_mod, "get_streamable_http_auth_context", lambda: None)
    monkeypatch.setattr(grpc_proxy_mod.settings, "experimental_rust_mcp_runtime_grpc_uds", "/tmp/test.sock")

    scope = {**_SCOPE_POST, "method": "GET"}
    fallback = AsyncMock()
    proxy = RustMCPRuntimeGrpcProxy(fallback)
    proxy._stub = mock_stub

    events = []

    async def send(msg):
        events.append(msg)

    await proxy.handle_streamable_http(scope, _make_receive(b""), send)

    fallback.assert_not_awaited()
    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 200

    body_events = [e for e in events if e["type"] == "http.response.body" and e.get("body")]
    assert body_events[0]["body"] == b"data: {}\n\n"
    assert body_events[1]["body"] == b"data: done\n\n"


@pytest.mark.asyncio
async def test_unsupported_method_falls_back_to_python(monkeypatch):
    """PUT /mcp is not a supported MCP method and should fall back to Python."""
    monkeypatch.setattr(grpc_proxy_mod, "get_streamable_http_auth_context", lambda: None)
    monkeypatch.setattr(grpc_proxy_mod.settings, "experimental_rust_mcp_runtime_grpc_uds", "/tmp/test.sock")

    scope = {**_SCOPE_POST, "method": "PUT"}
    fallback = AsyncMock()
    proxy = RustMCPRuntimeGrpcProxy(fallback)

    await proxy.handle_streamable_http(scope, _make_receive(b""), AsyncMock())
    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_http_scope_falls_back_to_python(monkeypatch):
    """WebSocket and other non-HTTP scopes should be forwarded to Python."""
    monkeypatch.setattr(grpc_proxy_mod, "get_streamable_http_auth_context", lambda: None)
    monkeypatch.setattr(grpc_proxy_mod.settings, "experimental_rust_mcp_runtime_grpc_uds", "/tmp/test.sock")

    scope = {"type": "websocket"}
    fallback = AsyncMock()
    proxy = RustMCPRuntimeGrpcProxy(fallback)

    await proxy.handle_streamable_http(scope, AsyncMock(), AsyncMock())
    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_grpc_error_returns_502(monkeypatch):
    """gRPC transport errors should produce a 502 JSON-RPC error response."""
    import grpc

    mock_stub = MagicMock()
    mock_stub.Invoke = AsyncMock(side_effect=grpc.aio.AioRpcError(grpc.StatusCode.UNAVAILABLE, MagicMock(), MagicMock()))

    monkeypatch.setattr(grpc_proxy_mod, "get_streamable_http_auth_context", lambda: None)
    monkeypatch.setattr(grpc_proxy_mod.settings, "experimental_rust_mcp_runtime_grpc_uds", "/tmp/test.sock")

    fallback = AsyncMock()
    proxy = RustMCPRuntimeGrpcProxy(fallback)
    proxy._stub = mock_stub

    events = []

    async def send(msg):
        events.append(msg)

    await proxy.handle_streamable_http(_SCOPE_POST, _make_receive(b"{}"), send)

    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 502
    body = orjson.loads(events[1]["body"])
    assert body["error"]["code"] == -32000
    assert "gRPC" in body["error"]["message"]
