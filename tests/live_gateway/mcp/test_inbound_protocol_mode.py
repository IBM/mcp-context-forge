# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_inbound_protocol_mode.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box tests for the inbound MCP protocol mode at the /mcp endpoint.

``MCP_INBOUND_PROTOCOL_MODE`` defaults to ``auto``, so an unconfigured gateway
serves the modern ``2026-07-28`` entry to clients. These tests pin that default
plus the deny paths that stay in force on the modern-era entry:

- ``auto`` (the default) answers a ``2026-07-28`` ``server/discover`` request.
- ``legacy`` rejects the ``2026-07-28`` header with 400 and a supported-version list.
- A request without the header stays on the legacy handshake path, because era
  routing reads the raw header and an absent header is not a modern revision.
- A modern-era request without a bearer token is rejected with 401.
- A modern-era request from a principal without ``servers.use`` is rejected with
  403 on a server-scoped MCP path.

The suite detects which mode the target gateway runs in by probing the modern
header once, so it covers both the unconfigured default and an explicit
``MCP_INBOUND_PROTOCOL_MODE=legacy`` deployment.

Environment variables consumed:
    MCP_CLI_BASE_URL        Gateway URL (default: http://127.0.0.1:8080)
    JWT_SECRET_KEY          JWT signing secret of the target gateway.
    PLATFORM_ADMIN_EMAIL    Bootstrap admin email.

Usage:
    pytest tests/live_gateway/mcp/test_inbound_protocol_mode.py -v
"""

# Future
from __future__ import annotations

# Standard
import json
from typing import Any
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, build_initialize, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

MODERN_PROTOCOL_VERSION = "2026-07-28"
HANDSHAKE_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MCP_URL = f"{BASE_URL}/mcp/"
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _admin_jwt() -> str:
    """Mint a platform-admin JWT for the bootstrap user.

    Returns:
        Signed JWT string.
    """
    return make_test_jwt(ADMIN_EMAIL, is_admin=True, secret=JWT_SECRET)


def _headers(*, token: str | None, protocol_version: str | None, mcp_method: str | None = None) -> dict[str, str]:
    """Build MCP Streamable HTTP request headers.

    Args:
        token: Bearer token, or None to omit Authorization.
        protocol_version: MCP-Protocol-Version value, or None to omit the header.
        mcp_method: Mcp-Method value required by the modern-era entry.

    Returns:
        Header dict for httpx.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if protocol_version is not None:
        headers["MCP-Protocol-Version"] = protocol_version
    if mcp_method is not None:
        headers["Mcp-Method"] = mcp_method
    return headers


def _discover_request() -> dict[str, Any]:
    """Build a modern-era ``server/discover`` request.

    Returns:
        JSON-RPC request body carrying the modern ``_meta`` envelope.
    """
    return {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": MODERN_META}}


def _post_discover(url: str, token: str | None) -> httpx.Response:
    """POST a modern-era ``server/discover`` request.

    Args:
        url: Target MCP endpoint.
        token: Bearer token, or None for an unauthenticated probe.

    Returns:
        The raw httpx response.
    """
    return httpx.post(
        url,
        headers=_headers(token=token, protocol_version=MODERN_PROTOCOL_VERSION, mcp_method="server/discover"),
        json=_discover_request(),
        timeout=15.0,
    )


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


def _gateway_in_legacy_mode() -> bool:
    """Return True when the gateway refuses the modern protocol header.

    Returns:
        True for a gateway running MCP_INBOUND_PROTOCOL_MODE=legacy.
    """
    try:
        resp = _post_discover(MCP_URL, _admin_jwt())
    except Exception:  # pylint: disable=broad-except
        return False
    return resp.status_code == 400 and "Unsupported protocol version" in resp.text


_LEGACY_MODE = _gateway_in_legacy_mode()
skip_unless_auto = pytest.mark.skipif(_LEGACY_MODE, reason="gateway runs with MCP_INBOUND_PROTOCOL_MODE=legacy")
skip_unless_legacy = pytest.mark.skipif(not _LEGACY_MODE, reason="gateway runs with MCP_INBOUND_PROTOCOL_MODE=auto")


@skip_unless_auto
def test_auto_mode_serves_modern_discover() -> None:
    """The default mode answers a 2026-07-28 server/discover request."""
    resp = _post_discover(MCP_URL, _admin_jwt())
    assert resp.status_code == 200, f"auto mode rejected {MODERN_PROTOCOL_VERSION}: {resp.status_code} {resp.text[:300]}"
    result = _jsonrpc_payload(resp)["result"]
    assert MODERN_PROTOCOL_VERSION in result["supportedVersions"], f"server/discover omitted {MODERN_PROTOCOL_VERSION}: {result}"


@skip_unless_legacy
def test_legacy_mode_rejects_modern_protocol_header() -> None:
    """Legacy mode answers the 2026-07-28 header with -32022 and the supported list."""
    resp = _post_discover(MCP_URL, _admin_jwt())
    assert resp.status_code == 400, f"legacy mode accepted {MODERN_PROTOCOL_VERSION}: {resp.status_code} {resp.text[:300]}"
    error = resp.json()["error"]
    assert error["code"] == -32022, error
    assert error["data"]["requested"] == MODERN_PROTOCOL_VERSION, error
    advertised = error["data"]["supported"]
    assert MODERN_PROTOCOL_VERSION not in advertised, f"legacy mode advertises the modern version as supported: {advertised}"
    assert set(advertised) == set(HANDSHAKE_PROTOCOL_VERSIONS), f"legacy mode must advertise exactly the handshake versions: {advertised}"


@skip_unless_legacy
def test_dual_era_client_falls_back_to_initialize_after_rejection() -> None:
    """A dual-era client recovers from -32022 by retrying initialize at an advertised version.

    This is the full negotiation round trip a spec-compliant client performs
    against a legacy-mode gateway: it opens at the modern revision, reads
    ``data.supported`` off the rejection, and completes the handshake.
    """
    token = _admin_jwt()
    rejected = _post_discover(MCP_URL, token)
    assert rejected.status_code == 400, f"legacy mode accepted {MODERN_PROTOCOL_VERSION}: {rejected.status_code} {rejected.text[:300]}"
    advertised = rejected.json()["error"]["data"]["supported"]

    fallback = max(advertised)
    handshake = build_initialize()
    handshake["params"]["protocolVersion"] = fallback
    resp = httpx.post(
        MCP_URL,
        headers=_headers(token=token, protocol_version=fallback),
        json=handshake,
        timeout=15.0,
    )
    assert resp.status_code == 200, f"initialize at advertised version {fallback} failed: {resp.status_code} {resp.text[:300]}"
    negotiated = _jsonrpc_payload(resp)["result"]["protocolVersion"]
    assert negotiated == fallback, f"initialize at {fallback} negotiated {negotiated}"


def test_headerless_request_stays_on_legacy_handshake() -> None:
    """A request without MCP-Protocol-Version negotiates a handshake-era version.

    Era routing reads the raw header, so an absent header never reaches the
    modern entry, whatever MCP_INBOUND_PROTOCOL_MODE is set to.
    """
    resp = httpx.post(
        MCP_URL,
        headers=_headers(token=_admin_jwt(), protocol_version=None),
        json=build_initialize(),
        timeout=15.0,
    )
    assert resp.status_code == 200, f"headerless initialize failed: {resp.status_code} {resp.text[:300]}"
    negotiated = _jsonrpc_payload(resp)["result"]["protocolVersion"]
    assert negotiated in HANDSHAKE_PROTOCOL_VERSIONS, f"headerless initialize negotiated {negotiated}; expected a handshake-era version"


def test_modern_request_without_token_is_rejected() -> None:
    """A modern-era request without a bearer token is rejected with 401."""
    resp = _post_discover(MCP_URL, None)
    assert resp.status_code == 401, f"unauthenticated modern request returned {resp.status_code}: {resp.text[:300]}"


def test_modern_request_without_servers_use_permission_is_denied() -> None:
    """A principal without servers.use is rejected with 403 on a scoped MCP path.

    The RBAC check runs before the server-existence lookup, so an unknown server
    id still exercises the authorization deny path.
    """
    token = make_test_jwt(f"inbound-mode-{uuid.uuid4().hex[:8]}@test.com", is_admin=False, teams=[], secret=JWT_SECRET)
    resp = _post_discover(f"{BASE_URL}/servers/{uuid.uuid4().hex}/mcp/", token)
    assert resp.status_code == 403, f"expected 403 from the servers.use check, got {resp.status_code}: {resp.text[:300]}"
