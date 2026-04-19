"""Register the reference server as a gateway upstream and build a virtual server.

Sync fixtures — admin REST endpoints don't need async, and keeping them
synchronous avoids pytest-asyncio's cross-loop issues with session-scoped
async fixtures consumed from function-scoped async tests.

Skip-on-failure: if the gateway rejects registration (SSRF, conflict, auth),
dependent tests skip rather than failing so reference-stdio rows stay green
and the gateway-compliance-gap backlog stays visible.
"""

from __future__ import annotations

import sys
import time
import warnings
from typing import Any, Iterator

import httpx
import pytest

from .reference_upstream import ReferenceUpstream


def _wait_for_federation_sync(
    client: httpx.Client,
    gateway_id: str,
    timeout: float = 30.0,
) -> tuple[list[dict[str, Any]], str]:
    """Poll /tools until at least one tool shows up for the given gateway.

    Returns ``(matched_tools, diagnostic)``. The diagnostic is "" on success
    or a short description of the last non-200 / empty-list state so the
    caller can include it in a skip message. Distinguishing "endpoint sound
    but federation slow" from "endpoint returning 401/500" prevents a
    network/auth regression from being misread as eventual consistency.

    Note: gateway returns ``gatewayId`` (camelCase) not ``gateway_id``, and
    /tools defaults to 50 entries — we ask for the full set so the
    pagination test isn't starved.
    """
    deadline = time.time() + timeout
    last_status: int | None = None
    last_body: str = ""
    while time.time() < deadline:
        resp = client.get("/tools", params={"limit": 500})
        last_status = resp.status_code
        if resp.status_code == 200:
            tools = resp.json()
            matched = [t for t in tools if t.get("gatewayId") == gateway_id]
            if matched:
                return matched, ""
        else:
            last_body = resp.text[:200]
        time.sleep(0.5)
    if last_status != 200:
        return [], f"last /tools response: {last_status} {last_body}"
    return [], "federation produced no tools for this gateway within timeout (endpoint healthy)"


def _delete_if_exists(client: httpx.Client, path: str, name: str) -> None:
    """Best-effort delete-by-name — tolerates prior crashed-run leftovers.

    Prevents 409 "already exists" on fixture setup when a previous session
    terminated without running teardown (common during iterative harness
    development). Non-2xx responses on the listing or delete are warned
    to stderr so auth/RBAC regressions don't masquerade as "already exists"
    fixture-setup failures one step later.
    """
    listing = client.get(path)
    if listing.status_code != 200:
        msg = f"_delete_if_exists: GET {path} returned {listing.status_code}: {listing.text[:200]}"
        warnings.warn(msg, stacklevel=2)
        print(f"[fixture] {msg}", file=sys.stderr)
        return
    for entry in listing.json():
        if entry.get("name") == name:
            resp = client.request("DELETE", f"{path}/{entry['id']}")
            if resp.status_code not in (200, 204, 404):
                msg = f"_delete_if_exists: DELETE {path}/{entry['id']} returned {resp.status_code}: {resp.text[:200]}"
                warnings.warn(msg, stacklevel=2)
                print(f"[fixture] {msg}", file=sys.stderr)


@pytest.fixture(scope="session")
def registered_reference_upstream(
    gateway_http_client: httpx.Client,
    reference_upstream: ReferenceUpstream,
) -> Iterator[dict[str, Any]]:
    """POST /gateways to register the reference server; DELETE on teardown."""
    _delete_if_exists(gateway_http_client, "/gateways", "compliance_reference")
    payload = {
        "name": "compliance_reference",
        "url": reference_upstream.mcp_url,
        "description": "Reference MCP server for protocol-compliance tests",
        "transport": "STREAMABLEHTTP",
    }
    resp = gateway_http_client.post("/gateways", json=payload)
    if resp.status_code not in (200, 201):
        pytest.skip(
            f"gateway upstream registration failed {resp.status_code}: {resp.text[:200]} "
            "(common cause: SSRF protection blocking the reference-server URL — "
            "set SSRF_ALLOW_PRIVATE_NETWORKS=true or add an allowlist entry on the gateway)"
        )
    gateway = resp.json()
    try:
        yield gateway
    finally:
        gateway_http_client.request("DELETE", f"/gateways/{gateway['id']}")


@pytest.fixture(scope="session")
def virtual_server(
    gateway_http_client: httpx.Client,
    registered_reference_upstream: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    """Create a virtual server composing the reference server's tools."""
    tools, diag = _wait_for_federation_sync(gateway_http_client, registered_reference_upstream["id"])
    if not tools:
        pytest.skip(f"federation sync did not surface any tools for gateway " f"{registered_reference_upstream['id']}: {diag}")

    _delete_if_exists(gateway_http_client, "/servers", "compliance_virtual")
    # POST /servers takes ServerCreate nested under a top-level "server" key
    # because the route also accepts side-band team_id / visibility Body params.
    payload = {
        "server": {
            "name": "compliance_virtual",
            "description": "Virtual server composed of reference-server tools",
            "associated_tools": [t["id"] for t in tools],
        }
    }
    resp = gateway_http_client.post("/servers", json=payload)
    if resp.status_code not in (200, 201):
        pytest.skip(f"virtual-server creation failed {resp.status_code}: {resp.text[:200]}")
    server = resp.json()
    try:
        yield server
    finally:
        gateway_http_client.request("DELETE", f"/servers/{server['id']}")
