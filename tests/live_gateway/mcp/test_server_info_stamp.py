# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_server_info_stamp.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box tests for the ``serverInfo`` stamp served at the /mcp endpoint.

The streamable HTTP server is constructed with ``settings.app_name`` and the
package ``__version__``. These tests pin that identity on the wire:

- A modern ``2026-07-28`` request receives ``io.modelcontextprotocol/serverInfo``
  in ``result._meta`` with the configured application name and package version.
- A legacy ``initialize`` request without modern protocol metadata still succeeds
  and returns no modern ``serverInfo`` stamp.

Environment variables consumed:
    MCP_CLI_BASE_URL        Gateway URL (default: http://127.0.0.1:8080)
    JWT_SECRET_KEY          JWT signing secret of the target gateway.
    PLATFORM_ADMIN_EMAIL    Bootstrap admin email.
    APP_NAME                Application name configured on the target gateway
                            (default: ContextForge).

Usage:
    pytest tests/live_gateway/mcp/test_server_info_stamp.py -v
"""

# Future
from __future__ import annotations

# Standard
import json
import os
from typing import Any

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway import __version__
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, build_initialize, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

MODERN_PROTOCOL_VERSION = "2026-07-28"
SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"
MCP_URL = f"{BASE_URL}/mcp/"
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
}
EXPECTED_APP_NAME = os.getenv("APP_NAME", "ContextForge")


def _headers(*, protocol_version: str | None, mcp_method: str | None = None) -> dict[str, str]:
    """Build authenticated MCP Streamable HTTP request headers.

    Args:
        protocol_version: MCP-Protocol-Version value, or None to omit the header.
        mcp_method: Mcp-Method value required by the modern-era entry.

    Returns:
        Header dict for httpx.
    """
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, secret=JWT_SECRET)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
    }
    if protocol_version is not None:
        headers["MCP-Protocol-Version"] = protocol_version
    if mcp_method is not None:
        headers["Mcp-Method"] = mcp_method
    return headers


def _jsonrpc_payload(response: httpx.Response) -> dict[str, Any]:
    """Parse a JSON or SSE Streamable HTTP response into its JSON-RPC envelope.

    Args:
        response: A Streamable HTTP response.

    Returns:
        The decoded JSON-RPC message.

    Raises:
        AssertionError: If the body carries no JSON-RPC envelope.
    """
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"no JSON-RPC envelope in response: {response.text[:300]}")


def test_modern_response_stamps_app_name_and_version() -> None:
    """A modern server/discover response carries the configured name and package version."""
    resp = httpx.post(
        MCP_URL,
        headers=_headers(protocol_version=MODERN_PROTOCOL_VERSION, mcp_method="server/discover"),
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": MODERN_META}},
        timeout=15.0,
    )
    if resp.status_code == 400 and "Unsupported protocol version" in resp.text:
        pytest.skip("gateway runs with MCP_INBOUND_PROTOCOL_MODE=legacy")
    assert resp.status_code == 200, f"modern server/discover failed: {resp.status_code} {resp.text[:300]}"
    server_info = _jsonrpc_payload(resp)["result"]["_meta"][SERVER_INFO_META_KEY]
    assert server_info["name"] == EXPECTED_APP_NAME, server_info
    assert server_info["version"] == __version__, server_info


def test_legacy_initialize_succeeds_without_modern_stamp() -> None:
    """A legacy initialize without modern _meta succeeds and gets no modern serverInfo stamp."""
    resp = httpx.post(
        MCP_URL,
        headers=_headers(protocol_version=None),
        json=build_initialize(),
        timeout=15.0,
    )
    assert resp.status_code == 200, f"legacy initialize failed: {resp.status_code} {resp.text[:300]}"
    result = _jsonrpc_payload(resp)["result"]
    assert result["protocolVersion"] != MODERN_PROTOCOL_VERSION, result
    assert SERVER_INFO_META_KEY not in (result.get("_meta") or {}), result
