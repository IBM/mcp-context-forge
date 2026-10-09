# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_protocol_version.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for MCP protocol version middleware.
"""

# Standard
from typing import Dict, Iterable, Tuple

# Third-Party
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
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
async def test_default_protocol_version_applied(monkeypatch):
    monkeypatch.setattr("mcpgateway.config.settings.mcp_inbound_protocol_mode", "auto")
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/rpc")

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    assert request.state.mcp_protocol_version == DEFAULT_PROTOCOL_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "requested", "expected_supported"),
    [
        ("legacy", "1999-01-01", list(HANDSHAKE_PROTOCOL_VERSIONS)),
        ("auto", "1999-01-01", SUPPORTED_PROTOCOL_VERSIONS),
        # Dual-era clients must be told that a legacy-mode gateway does not serve 2026-07-28.
        ("legacy", "2026-07-28", list(HANDSHAKE_PROTOCOL_VERSIONS)),
    ],
)
async def test_unsupported_protocol_version_rejected(monkeypatch, mode, requested, expected_supported):
    """An unserved version gets JSON-RPC -32022 naming the mode's supported list."""
    monkeypatch.setattr("mcpgateway.config.settings.mcp_inbound_protocol_mode", mode)
    middleware = MCPProtocolVersionMiddleware(app=None)
    request = _make_request("/rpc", headers=[(b"mcp-protocol-version", requested.encode())])

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 400
    payload = orjson.loads(response.body)
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] is None
    assert payload["error"]["code"] == -32022
    assert payload["error"]["data"] == {"supported": expected_supported, "requested": requested}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_advertised_supported_versions_are_accepted_on_retry(monkeypatch, mode):
    """Every version named in ``data.supported`` must succeed when the client retries with it.

    A spec-compliant dual-era client opens at the modern revision, so the -32022
    rejection is a negotiation step rather than a terminal error: the client reads
    ``data.supported`` and retries. The advertised list is only useful if the
    gateway actually serves every version in it.
    """
    monkeypatch.setattr("mcpgateway.config.settings.mcp_inbound_protocol_mode", mode)
    middleware = MCPProtocolVersionMiddleware(app=None)

    async def call_next(req):
        return Response("ok")

    rejection = await middleware.dispatch(_make_request("/rpc", headers=[(b"mcp-protocol-version", b"1999-01-01")]), call_next)
    advertised = orjson.loads(rejection.body)["error"]["data"]["supported"]
    assert advertised, "rejection must advertise at least one version for the client to retry with"

    for version in advertised:
        retry = _make_request("/rpc", headers=[(b"mcp-protocol-version", version.encode())])
        response = await middleware.dispatch(retry, call_next)
        assert response.status_code == 200, f"{mode} mode advertised {version} but rejected the retry"
        assert retry.state.mcp_protocol_version == version


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
