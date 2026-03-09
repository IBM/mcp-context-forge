# -*- coding: utf-8 -*-
"""Unit tests for the experimental Rust MCP runtime proxy."""

# Standard
import json
from unittest.mock import AsyncMock

# Third-Party
import httpx
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
async def test_post_requests_proxy_to_rust_runtime_and_inject_server_id(monkeypatch):
    """POST MCP traffic should be proxied to Rust with server-scoped params preserved."""
    captured = {}

    class FakeClient:
        async def post(self, url, *, content, headers, timeout):  # noqa: ANN001
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            captured["timeout"] = timeout
            return httpx.Response(
                200,
                headers={"content-type": "application/json", "mcp-session-id": "session-1"},
                json={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
            )

    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")
    monkeypatch.setattr("mcpgateway.transports.rust_mcp_runtime_proxy.settings.experimental_rust_mcp_runtime_timeout_seconds", 17)
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
            (b"x-forwarded-internally", b"true"),
            (b"x-mcp-session-id", b"internal-only"),
        ],
    }

    await proxy.handle_streamable_http(
        scope,
        _make_receive(b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'),
        send,
    )

    fallback.assert_not_awaited()
    assert captured["url"] == "http://127.0.0.1:8787/mcp/?session_id=abc123"
    assert captured["timeout"].connect == 17

    forwarded_headers = dict(captured["headers"])
    assert forwarded_headers["authorization"] == "Bearer test-token"
    assert forwarded_headers["cookie"] == "jwt_token=cookie-token"
    assert forwarded_headers["mcp-protocol-version"] == "2025-11-25"
    assert "x-forwarded-internally" not in forwarded_headers
    assert "x-mcp-session-id" not in forwarded_headers

    payload = json.loads(captured["content"].decode())
    assert payload["params"]["server_id"] == "123e4567-e89b-12d3-a456-426614174000"

    assert events[0]["type"] == "http.response.start"
    assert events[0]["status"] == 200
    assert (b"mcp-session-id", b"session-1") in events[0]["headers"]
    assert events[1]["type"] == "http.response.body"
    assert json.loads(events[1]["body"].decode()) == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


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
        async def post(self, *args, **kwargs):  # noqa: ANN002, ANN003
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
