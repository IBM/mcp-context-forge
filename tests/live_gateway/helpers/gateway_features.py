# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/helpers/gateway_features.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Probes that report which optional features the live gateway has enabled.

A live-gateway suite must read feature state from the gateway under test. The
environment of the pytest process only mirrors the gateway when the operator
sets the same variables in both places, and a stale default there skips tests
the gateway can run. Each probe sends one request and returns ``False`` when the
gateway is unreachable, so ``skip_no_gateway`` stays the one reachability policy.
"""

# Future
from __future__ import annotations

# Standard
from functools import cache
from typing import Any

# Third-Party
import httpx

# First-Party
from tests.helpers.auth import make_test_jwt

# Local
from .mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET

MODERN_PROTOCOL_VERSION = "2026-07-28"
MCP_APPS_EXTENSION = "io.modelcontextprotocol/ui"
_PROBE_TIMEOUT_SECONDS = 10.0
_MODERN_ENVELOPE: dict[str, Any] = {
    "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": {"name": "feature-probe", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _probe_headers(protocol_version: str, method: str | None = None) -> dict[str, str]:
    """Build the headers for a probe request to ``/mcp/``.

    Args:
        protocol_version: Value for the ``MCP-Protocol-Version`` header.
        method: Value for the ``Mcp-Method`` header, or ``None`` to omit it.

    Returns:
        dict[str, str]: Request headers carrying an admin bearer token.
    """
    token = make_test_jwt(ADMIN_EMAIL, is_admin=True, include_user_data=True, expires_in_minutes=5, secret=JWT_SECRET)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": protocol_version,
    }
    if method:
        headers["Mcp-Method"] = method
    return headers


@cache
def gateway_accepts_modern_inbound() -> bool:
    """Return whether the gateway accepts inbound 2026-07-28 clients.

    The gateway runs in ``MCP_INBOUND_PROTOCOL_MODE=auto`` when it answers a
    modern ``server/discover`` request with 200. Mode ``legacy`` rejects that
    request with 400.

    Returns:
        bool: True when the gateway accepts the modern protocol revision.
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": _MODERN_ENVELOPE}}
    try:
        response = httpx.post(f"{BASE_URL}/mcp/", headers=_probe_headers(MODERN_PROTOCOL_VERSION, "server/discover"), json=body, timeout=_PROBE_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@cache
def gateway_advertises_mcp_apps() -> bool:
    """Return whether the gateway advertises the MCP Apps extension.

    The gateway lists the extension in its ``initialize`` capabilities only when
    ``MCPGATEWAY_MCP_APPS_ENABLED`` is true.

    Returns:
        bool: True when ``capabilities.extensions`` holds the MCP Apps entry.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "feature-probe", "version": "1"}},
    }
    try:
        response = httpx.post(f"{BASE_URL}/mcp/", headers=_probe_headers("2025-03-26"), json=body, timeout=_PROBE_TIMEOUT_SECONDS)
        extensions = response.json().get("result", {}).get("capabilities", {}).get("extensions", {})
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
    return response.status_code == 200 and MCP_APPS_EXTENSION in extensions
