# -*- coding: utf-8 -*-
"""Location: ./tests/protocol_compliance/test_jsonrpc_envelope.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

JSON-RPC 2.0 envelope invariants from MCP 2025-11-25 § Base Protocol / Messages.

These tests probe the live gateway with raw httpx so they catch envelope
regressions the high-level FastMCP Client would hide. They cover the
small-but-normative clauses that tend to silently decay:

- Error responses carry integer ``error.code`` (REQ-015).
- Error responses carry ``error.message`` (REQ-014).
- Error / result envelopes echo the request ``id`` (REQ-010, REQ-013).
- Result responses include a ``result`` field (REQ-011).
- Notifications produce no response (REQ-016) — asserted via "the HTTP
  response to a notification is 202 Accepted with no JSON body".

Scope: run against the live gateway via ``gateway_http_client`` (the same
sync httpx client the admin fixtures use; it already carries the bearer
token). Reference target is exercised implicitly — the FastMCP SDK
enforces these at the sender side, so a round-trip through it is a weak
test of the *server's* conformance.
"""

from __future__ import annotations

import json

import httpx
import pytest

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_base]


# Small helpers — keep the envelope tests self-contained.
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
            "clientInfo": {"name": "envelope-probe", "version": "0.1"},
        },
    }


def _parse_first_jsonrpc_message(resp: httpx.Response) -> dict:
    """Return the first JSON-RPC envelope from a response, whether JSON or SSE.

    The gateway may respond with ``content-type: application/json`` (single
    envelope) or ``text/event-stream`` (one or more ``data:`` events).
    """
    ctype = resp.headers.get("content-type", "").lower()
    if ctype.startswith("application/json"):
        return resp.json()
    if ctype.startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AssertionError(f"SSE response had no data line: {resp.text[:200]}")
    raise AssertionError(f"unexpected content-type: {ctype!r}: {resp.text[:200]}")


def test_initialize_result_envelope_shape(gateway_http_client: httpx.Client) -> None:
    """REQ-010, REQ-011: result response echoes id and includes a result field."""
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body(42))
    assert resp.status_code == 200, f"initialize → {resp.status_code}: {resp.text[:200]}"
    envelope = _parse_first_jsonrpc_message(resp)
    assert envelope.get("jsonrpc") == "2.0", f"missing/invalid jsonrpc: {envelope}"
    assert envelope.get("id") == 42, f"id not echoed: {envelope}"
    assert "result" in envelope, f"result field missing: {envelope}"
    # The result itself must be an object per the initialize schema.
    assert isinstance(envelope["result"], dict), f"result is not an object: {envelope['result']!r}"


def test_invalid_method_error_envelope_shape(gateway_http_client: httpx.Client) -> None:
    """REQ-013, REQ-014, REQ-015: error responses echo id and carry integer code + message."""
    # Send a bogus method via a standalone request (no session state required).
    body = {"jsonrpc": "2.0", "id": 99, "method": "nonexistent/method", "params": {}}
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=body)
    # Either HTTP-level rejection (>=400) or a JSON-RPC error envelope is spec-valid;
    # we require one of them, and if it's an envelope we inspect its shape.
    if resp.status_code >= 400:
        # HTTP-level rejection: acceptable.
        return
    envelope = _parse_first_jsonrpc_message(resp)
    assert envelope.get("id") == 99, f"id not echoed on error: {envelope}"
    assert "error" in envelope, f"error field missing: {envelope}"
    err = envelope["error"]
    assert isinstance(err.get("code"), int), f"error.code must be integer, got {err.get('code')!r}"
    assert isinstance(err.get("message"), str) and err["message"], f"error.message must be non-empty string, got {err.get('message')!r}"


def test_notification_receives_no_response_body(gateway_http_client: httpx.Client) -> None:
    """REQ-016: the receiver MUST NOT send a response to a notification.

    Asserts the HTTP response is 202 Accepted (the Streamable HTTP spec's way
    of acknowledging receipt with no body). Any envelope in the body would
    be a spec violation.

    Per the MCP Streamable HTTP spec, clients MUST include the
    ``Mcp-Session-Id`` header on all requests after initialization, so we
    first establish a session via ``initialize`` before sending the
    notification.
    """
    # Establish a session — the spec requires Mcp-Session-Id on all
    # post-initialization messages, including notifications.
    init_resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body())
    assert init_resp.status_code == 200, f"initialize failed: {init_resp.status_code}: {init_resp.text[:200]}"
    session_id = init_resp.headers.get("mcp-session-id")

    notify_headers = dict(_MCP_HEADERS)
    if session_id:
        notify_headers["mcp-session-id"] = session_id

    # notifications/initialized is the canonical always-safe notification.
    body = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    resp = gateway_http_client.post("/mcp/", headers=notify_headers, json=body)
    assert resp.status_code == 202, f"notification should produce 202 Accepted, got {resp.status_code}: {resp.text[:200]}"
    # The body may be empty, an empty JSON object, or omitted — but it MUST NOT contain
    # a JSON-RPC response envelope keyed by an id.
    if resp.content:
        try:
            parsed = resp.json()
            assert "id" not in parsed, f"notification must not produce an id-bearing response: {parsed}"
        except (ValueError, json.JSONDecodeError):
            pass  # empty or non-JSON body is acceptable


@pytest.mark.xfail(
    strict=False,
    reason=(
        "GAP-013: gateway auto-generates a UUID for id-less JSON-RPC messages "
        "instead of treating them as notifications (returns result with "
        "fabricated id rather than 202 Accepted or 4xx rejection)."
    ),
)
def test_request_without_id_is_rejected_or_treated_as_notification(
    gateway_http_client: httpx.Client,
) -> None:
    """REQ-007, REQ-008: requests MUST include a non-null id.

    A payload that looks like a request but omits ``id`` is either rejected
    (>=400) or silently treated as a notification (202 with no id-bearing
    response). Either is spec-compatible; a *successful* id-bearing response
    would be a violation.
    """
    # Establish a session so a missing session ID doesn't mask the real test.
    init_resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body())
    assert init_resp.status_code == 200, f"initialize failed: {init_resp.status_code}: {init_resp.text[:200]}"
    session_id = init_resp.headers.get("mcp-session-id")

    call_headers = dict(_MCP_HEADERS)
    if session_id:
        call_headers["mcp-session-id"] = session_id

    body = {"jsonrpc": "2.0", "method": "ping", "params": {}}  # no id
    resp = gateway_http_client.post("/mcp/", headers=call_headers, json=body)
    if resp.status_code >= 400:
        return  # acceptable: server rejected the malformed request
    # Otherwise it was accepted as a notification; body must not echo an id.
    if resp.status_code == 202 and not resp.content:
        return
    envelope = _parse_first_jsonrpc_message(resp)
    assert "id" not in envelope or envelope.get("id") is None, f"request without id must not receive an id-bearing response: {envelope}"


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 error-code semantics (§ 5.1 — reserved pre-defined errors)
#
# A generic -32603 ("internal") fallback masks real bugs in method dispatch
# and argument validation. These probes pin that the server picks the
# *specific* reserved code for the failure mode it's reporting, so a
# regression that reroutes everything to -32603 is caught.
# ---------------------------------------------------------------------------
def _unwrap_error(resp: httpx.Response) -> dict | None:
    """Return the JSON-RPC error object, or None if this is an HTTP-level rejection.

    HTTP >=400 with no JSON-RPC envelope is also spec-valid (§ Streamable
    HTTP transport), so tests that want to probe the envelope skip those
    responses with a caller-visible None.
    """
    if resp.status_code >= 400 and "json" not in resp.headers.get("content-type", "").lower() and "event-stream" not in resp.headers.get("content-type", "").lower():
        return None
    try:
        envelope = _parse_first_jsonrpc_message(resp)
    except (AssertionError, json.JSONDecodeError, ValueError):
        return None
    return envelope.get("error")


def test_parse_error_returns_32700(gateway_http_client: httpx.Client) -> None:
    """Malformed JSON body → JSON-RPC parse error code -32700.

    Per JSON-RPC 2.0 § 5.1, a server that receives invalid JSON MUST
    respond with this specific code. Servers that fall back to -32603
    ("internal error") mask a real client-side or transport-side bug.
    """
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, content=b"not valid json {")
    # 5xx indicates the server crashed parsing bad input instead of
    # cleanly rejecting it — that's a real bug, not spec-compliant.
    assert resp.status_code < 500, f"malformed JSON produced 5xx (server crash, not clean rejection): " f"{resp.status_code} {resp.text[:200]}"
    # 4xx with no JSON-RPC envelope is an acceptable HTTP-level rejection
    # (many servers reject at the Content-parse layer before JSON-RPC).
    if 400 <= resp.status_code < 500 and not _unwrap_error(resp):
        return
    err = _unwrap_error(resp)
    assert err is not None, f"expected JSON-RPC error envelope, got {resp.status_code}: {resp.text[:200]}"
    assert err.get("code") == -32700, f"parse-error should carry code=-32700, got {err.get('code')!r} (message: {err.get('message')!r})"


def test_method_not_found_returns_32601(gateway_http_client: httpx.Client) -> None:
    """Unknown method → JSON-RPC code -32601 (Method not found)."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "definitely/not/a/real/method", "params": {}}
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=body)
    assert resp.status_code < 500, f"unknown method produced 5xx (server crash, not clean rejection): " f"{resp.status_code} {resp.text[:200]}"
    if 400 <= resp.status_code < 500 and not _unwrap_error(resp):
        return
    err = _unwrap_error(resp)
    assert err is not None, f"expected JSON-RPC error envelope, got {resp.status_code}: {resp.text[:200]}"
    assert err.get("code") == -32601, f"unknown-method should carry code=-32601, got {err.get('code')!r} (message: {err.get('message')!r})"


def test_invalid_params_returns_32602(gateway_http_client: httpx.Client) -> None:
    """Known method with malformed params → JSON-RPC code -32602 (Invalid params).

    A server that collapses this to -32603 loses the distinction the spec
    defines between "I don't know that method" and "I know it but your
    arguments are wrong" — an interop-meaningful distinction.
    """
    # initialize requires a structured params object; passing a primitive
    # is semantically invalid regardless of transport.
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": "not-an-object"}
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=body)
    assert resp.status_code < 500, f"invalid params produced 5xx (server crash, not clean rejection): " f"{resp.status_code} {resp.text[:200]}"
    if 400 <= resp.status_code < 500 and not _unwrap_error(resp):
        return
    err = _unwrap_error(resp)
    assert err is not None, f"expected JSON-RPC error envelope, got {resp.status_code}: {resp.text[:200]}"
    # -32602 is the spec-mandated code. Some servers return -32600 (Invalid
    # Request) if they class param-shape issues with the envelope itself,
    # which is a softer spec violation but common in practice. Accept
    # either and fail loudly on the -32603 fallback.
    assert err.get("code") in (-32602, -32600), (
        f"invalid-params should carry code=-32602 (or -32600 Invalid Request); "
        f"got {err.get('code')!r} (message: {err.get('message')!r}) — -32603 "
        f"'internal error' would mask argument-validation bugs."
    )


# ---------------------------------------------------------------------------
# Lifecycle safety rails
# ---------------------------------------------------------------------------
def test_initialize_rejected_when_called_twice(gateway_http_client: httpx.Client) -> None:
    """Second initialize on the same session MUST NOT succeed.

    Per the lifecycle spec, initialize is the first message on a session
    and negotiates capabilities; repeating it would let a mid-session
    attacker renegotiate downward or would leak server state across
    logical client-lifetimes. Servers SHOULD reject the second call.
    This test tolerates either a JSON-RPC error envelope or an HTTP 4xx.
    """
    first = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body(1))
    assert first.status_code == 200, f"first initialize must succeed: {first.status_code} {first.text[:200]}"
    sid = first.headers.get("mcp-session-id")
    call_headers = dict(_MCP_HEADERS)
    if sid:
        call_headers["mcp-session-id"] = sid

    second = gateway_http_client.post("/mcp/", headers=call_headers, json=_initialize_body(2))
    assert second.status_code < 500, f"second initialize produced 5xx (server crash, not clean rejection): " f"{second.status_code} {second.text[:200]}"
    if 400 <= second.status_code < 500:
        return  # acceptable: HTTP-level rejection
    # Otherwise there must be an error envelope — a plain success would mean
    # the server silently re-initialized mid-session.
    err = _unwrap_error(second)
    if err is None:
        # Some servers tolerate repeat initialize and simply return fresh
        # capabilities. The spec says SHOULD-reject, not MUST-reject, so
        # this is a softer probe: warn by xfail-style assertion if neither
        # error envelope nor 4xx surfaced. We don't want to be brittle.
        envelope = _parse_first_jsonrpc_message(second)
        if "result" in envelope:
            pytest.xfail("server accepts repeat initialize (spec says SHOULD reject, not MUST)")
        pytest.fail(f"unexpected second-initialize shape: {envelope}")
    assert isinstance(err.get("code"), int), f"error envelope must carry integer code: {err}"


def test_mcp_protocol_version_header_mismatch_handled(gateway_http_client: httpx.Client) -> None:
    """A bogus MCP-Protocol-Version must be rejected or negotiated, not silently ignored.

    Per the Streamable HTTP transport spec, the version header on a POST
    is the client's declared protocol. A server that receives a version
    it doesn't speak MUST either reject (4xx) or negotiate down (reply
    with its supported version in the initialize result). Silently
    proceeding to speak an unintended version is an interop bug.
    """
    headers = dict(_MCP_HEADERS)
    headers["mcp-protocol-version"] = "2099-01-01"  # far future, definitely not implemented
    resp = gateway_http_client.post("/mcp/", headers=headers, json=_initialize_body(1))

    assert resp.status_code < 500, f"bogus protocol version produced 5xx (server crash, not negotiation): " f"{resp.status_code} {resp.text[:200]}"
    if 400 <= resp.status_code < 500:
        return  # HTTP-level rejection is spec-compliant

    envelope = _parse_first_jsonrpc_message(resp)
    if "error" in envelope:
        return  # JSON-RPC error envelope is also fine

    # Otherwise the response must be a success with the *negotiated* version
    # in the result — and that version must not echo the bogus one.
    version = (envelope.get("result") or {}).get("protocolVersion")
    assert isinstance(version, str) and version != "2099-01-01", (
        f"server must negotiate a real protocolVersion in its initialize response, " f"got {version!r} — echoing the bogus client version silently is an interop bug."
    )
