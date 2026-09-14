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
from mcpgateway.middleware.protocol_version import DEFAULT_PROTOCOL_VERSION, MCPProtocolVersionMiddleware, SUPPORTED_PROTOCOL_VERSIONS


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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/servers/server-1/sse", True),
        ("/v1/virtual-servers/server-1/sse", True),
        ("/v1/virtual-servers/server-1/ws", True),
        ("/v1/virtual-servers/server-1/tools", False),
    ],
)
def test_mcp_endpoint_classification_handles_alias(path: str, expected: bool) -> None:
    """Versioned virtual servers share the standard transport classification."""
    middleware = MCPProtocolVersionMiddleware(app=None)
    assert middleware._is_mcp_endpoint(path) is expected


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


# --------------------------------------------------------------------------- #
#              Legacy inbound protocol mode tests                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_legacy_mode_rejects_modern_version(monkeypatch):
    """2026-07-28 must be rejected with 400 in legacy mode."""
    monkeypatch.setattr("mcpgateway.config.settings.mcp_inbound_protocol_mode", "legacy")
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/rpc", headers=[(b"mcp-protocol-version", b"2026-07-28")])

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 400
    payload = orjson.loads(response.body)
    assert "2026-07-28" in payload["message"]
    # Response must list handshake-era versions so dual-era clients know what to retry
    assert "2025-11-25" in payload["message"]


@pytest.mark.asyncio
async def test_legacy_mode_accepts_handshake_version(monkeypatch):
    """Handshake-era versions must still be accepted in legacy mode."""
    monkeypatch.setattr("mcpgateway.config.settings.mcp_inbound_protocol_mode", "legacy")
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/rpc", headers=[(b"mcp-protocol-version", b"2025-11-25")])

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    assert request.state.mcp_protocol_version == "2025-11-25"


@pytest.mark.asyncio
async def test_legacy_mode_defaults_missing_header_to_latest_handshake(monkeypatch):
    """Missing header in legacy mode must default to 2025-11-25, not 2026-07-28."""
    monkeypatch.setattr("mcpgateway.config.settings.mcp_inbound_protocol_mode", "legacy")
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/rpc")

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    assert request.state.mcp_protocol_version == "2025-11-25"


@pytest.mark.asyncio
async def test_auto_mode_accepts_modern_version(monkeypatch):
    """2026-07-28 must be accepted in auto mode (current default behavior)."""
    monkeypatch.setattr("mcpgateway.config.settings.mcp_inbound_protocol_mode", "auto")
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/rpc", headers=[(b"mcp-protocol-version", b"2026-07-28")])

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 200
    assert request.state.mcp_protocol_version == "2026-07-28"
