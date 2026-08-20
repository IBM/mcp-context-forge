# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_protocol_version.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for MCP protocol version middleware.
"""

# Standard
from typing import Dict, Iterable, Tuple

# Third-Party
import orjson
import pytest
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.middleware.protocol_version import DEFAULT_PROTOCOL_VERSION, MCPProtocolVersionMiddleware


def _make_request(path: str, headers: Iterable[Tuple[bytes, bytes]] | None = None) -> Request:
    scope: Dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": list(headers or []),
    }

    async def receive():
        return {"type": "http.request"}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_non_mcp_endpoint_skips_validation():
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/health")

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_default_protocol_version_applied():
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/rpc")

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    assert request.state.mcp_protocol_version == DEFAULT_PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_unsupported_protocol_version_rejected():
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/rpc", headers=[(b"mcp-protocol-version", b"1999-01-01")])

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 400
    payload = orjson.loads(response.body)
    assert "Unsupported protocol version" in payload["message"]


class TestMCPProtocolVersionMiddlewareASGICall:
    """Pure-ASGI ``__call__`` entry point coverage (passthrough and 400 rejection)."""

    @pytest.mark.asyncio
    async def test_call_ignores_non_http_scope(self):
        called = []

        async def app(scope, receive, send):
            called.append(scope["type"])

        middleware = MCPProtocolVersionMiddleware(app)

        async def noop(*_args):
            return None

        await middleware({"type": "lifespan"}, noop, noop)
        assert called == ["lifespan"]

    @pytest.mark.asyncio
    async def test_call_sends_400_rejection_directly_without_calling_downstream(self):
        downstream_called = False

        async def app(scope, receive, send):
            nonlocal downstream_called
            downstream_called = True

        middleware = MCPProtocolVersionMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/rpc",
            "headers": [(b"mcp-protocol-version", b"1999-01-01")],
        }

        async def receive():
            return {"type": "http.request", "body": b""}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

        assert downstream_called is False
        assert sent[0]["status"] == 400

    @pytest.mark.asyncio
    async def test_call_invokes_downstream_when_version_supported(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = MCPProtocolVersionMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/rpc",
            "headers": [],
            "state": {},
        }

        async def receive():
            return {"type": "http.request", "body": b""}

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

        assert sent[0]["status"] == 200
        assert scope["state"]["mcp_protocol_version"] == DEFAULT_PROTOCOL_VERSION
