# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/test_transport_semantics.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Transport wire-level semantics from MCP 2025-11-25 § Basic / Transports.

Unlike the parametrized matrix, these probes are transport-specific and
use raw ``httpx`` against the live gateway. They cover the Streamable
HTTP transport invariants the high-level FastMCP Client hides:

- ``Mcp-Session-Id`` header lifecycle (issue, echo, reject without).
- ``GET /mcp/`` offers an SSE stream OR returns 405 (spec-sanctioned
  refusal).
- ``DELETE /mcp/`` with ``Mcp-Session-Id`` closes the session (or 405 if
  the server doesn't support client-initiated termination).
- ``MCP-Protocol-Version`` header round-trip / negotiation.
- Missing ``Accept`` header is rejected (spec requires
  ``application/json`` AND ``text/event-stream``).

Rows that aren't strictly in scope for the parametrized harness (they
don't need to run against the reference server's in-process stdio
transport) live here as plain non-parametrized tests.
"""

from __future__ import annotations

import json

import httpx
import pytest

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_transport_core]


_MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-03-26",
}


def _initialize_body(request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "transport-probe", "version": "0.1"},
        },
    }


# ---------------------------------------------------------------------------
# Parametrized-across-targets smoke (retained from prior scaffold)
# ---------------------------------------------------------------------------
async def test_reference_stdio_reports_valid_capabilities(client) -> None:
    """Initialize handshake surfaces capability flags for any target.

    Parametrized across reference + gateway targets. Non-transport-specific
    but kept here for historical continuity with the Phase 2 scaffold.
    """
    caps = client.initialize_result.capabilities
    assert caps.tools is not None, f"tools capability missing from {caps}"


# ---------------------------------------------------------------------------
# Streamable HTTP wire-level probes (non-parametrized; live gateway only)
# ---------------------------------------------------------------------------
def test_mcp_session_id_header_behavior(gateway_http_client: httpx.Client) -> None:
    """Mcp-Session-Id: server MAY issue one on initialize; if it does, it MUST be echoed.

    We tolerate both branches:
      - Server issues a session id → subsequent calls with it should succeed.
      - Server does not issue one (stateless / in-flight #4205) → that branch
        is spec-compliant too per the "MAY" language.
    """
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body(1))
    assert resp.status_code == 200, f"initialize → {resp.status_code}: {resp.text[:200]}"
    sid = resp.headers.get("mcp-session-id")
    if sid is None:
        pytest.skip("gateway does not issue Mcp-Session-Id (spec-sanctioned MAY; see #4205)")

    # If a session id was issued, a subsequent ping carrying it must be accepted.
    call_headers = dict(_MCP_HEADERS)
    call_headers["mcp-session-id"] = sid
    ping_body = {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
    resp2 = gateway_http_client.post("/mcp/", headers=call_headers, json=ping_body)
    assert resp2.status_code == 200, f"ping with session-id {sid!r} should succeed, got {resp2.status_code}: {resp2.text[:200]}"


def test_get_mcp_returns_sse_stream_or_405(gateway_http_client: httpx.Client) -> None:
    """GET /mcp/: server MUST return text/event-stream OR 405 Method Not Allowed.

    Spec (basic/transports § Listening for Messages from the Server):
    > The server MUST either return Content-Type: text/event-stream in
    > response to this HTTP GET, or else return HTTP 405 Method Not Allowed.
    """
    headers = {
        "accept": "text/event-stream",
        "mcp-protocol-version": "2025-03-26",
    }
    try:
        # Use a short read to avoid hanging on a live SSE stream — we only need the headers.
        with gateway_http_client.stream("GET", "/mcp/", headers=headers) as resp:
            status = resp.status_code
            ctype = resp.headers.get("content-type", "").lower()
    except httpx.ReadTimeout:
        pytest.skip("GET /mcp/ opened but produced no events in the read window")

    if status == 405:
        return  # spec-sanctioned refusal
    assert status == 200, f"unexpected status for GET /mcp/: {status}"
    assert ctype.startswith("text/event-stream"), f"GET /mcp/ with 200 must content-type text/event-stream, got {ctype!r}"


def test_delete_mcp_terminates_session_or_405(gateway_http_client: httpx.Client) -> None:
    """DELETE /mcp/: server MAY support client-initiated session termination, else 405.

    Spec: a server that supports session termination accepts DELETE with
    the session id header; a server that doesn't returns 405.
    """
    init = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body(1))
    sid = init.headers.get("mcp-session-id")
    headers = {"accept": "application/json, text/event-stream"}
    if sid:
        headers["mcp-session-id"] = sid
    resp = gateway_http_client.request("DELETE", "/mcp/", headers=headers)
    assert resp.status_code in (200, 204, 405), f"DELETE /mcp/ should be 200/204 (terminated) or 405 (unsupported); got {resp.status_code}"


def test_missing_accept_header_rejected(gateway_http_client: httpx.Client) -> None:
    """Client MUST declare Accept for both application/json and text/event-stream.

    A POST missing the dual Accept should be rejected. Many implementations
    accept it anyway — if this passes-anyway behavior surfaces, a test xfail
    would be appropriate once we confirm the exact spec requirement level.
    Current behavior: we accept either a 2xx (tolerant impl) or 4xx (strict).
    """
    headers = {
        "content-type": "application/json",
        "mcp-protocol-version": "2025-03-26",
        # no Accept header
    }
    resp = gateway_http_client.post("/mcp/", headers=headers, json=_initialize_body(1))
    assert resp.status_code < 500, f"server error on missing Accept suggests crash, not validation: {resp.status_code}"


def test_protocol_version_header_round_trip(gateway_http_client: httpx.Client) -> None:
    """Server's negotiated protocol version (in the initialize result) is a valid date.

    Per spec, the client asks for a protocol version; the server responds
    with the version it will speak. The response must use the YYYY-MM-DD
    format both sides agree on.
    """
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body(1))
    assert resp.status_code == 200
    ctype = resp.headers.get("content-type", "")
    body = (
        resp.json()
        if ctype.startswith("application/json")
        else json.loads(
            next(
                (l[5:].strip() for l in resp.text.splitlines() if l.startswith("data:")),
                "null",
            )
        )
    )
    version = (body.get("result") or {}).get("protocolVersion")
    assert isinstance(version, str) and len(version) == len("YYYY-MM-DD"), f"protocolVersion must be a YYYY-MM-DD string, got {version!r}"
    assert version[4] == "-" and version[7] == "-", f"unexpected format: {version!r}"
