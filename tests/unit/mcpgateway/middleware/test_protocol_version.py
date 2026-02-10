# -*- coding: utf-8 -*-
"""Tests for MCP protocol version middleware."""

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
