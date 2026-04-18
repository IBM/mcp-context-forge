"""JSON-RPC 2.0 envelope invariants from MCP 2025-11-25 § Base Protocol / Messages.

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
    """
    # notifications/initialized is the canonical always-safe notification.
    body = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=body)
    assert resp.status_code == 202, f"notification should produce 202 Accepted, got {resp.status_code}: {resp.text[:200]}"
    # The body may be empty, an empty JSON object, or omitted — but it MUST NOT contain
    # a JSON-RPC response envelope keyed by an id.
    if resp.content:
        try:
            parsed = resp.json()
            assert "id" not in parsed, f"notification must not produce an id-bearing response: {parsed}"
        except (ValueError, json.JSONDecodeError):
            pass  # empty or non-JSON body is acceptable


def test_request_without_id_is_rejected_or_treated_as_notification(
    gateway_http_client: httpx.Client,
) -> None:
    """REQ-007, REQ-008: requests MUST include a non-null id.

    A payload that looks like a request but omits ``id`` is either rejected
    (>=400) or silently treated as a notification (202 with no id-bearing
    response). Either is spec-compatible; a *successful* id-bearing response
    would be a violation.
    """
    body = {"jsonrpc": "2.0", "method": "ping", "params": {}}  # no id
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=body)
    if resp.status_code >= 400:
        return  # acceptable: server rejected the malformed request
    # Otherwise it was accepted as a notification; body must not echo an id.
    if resp.status_code == 202 and not resp.content:
        return
    envelope = _parse_first_jsonrpc_message(resp)
    assert "id" not in envelope or envelope.get("id") is None, f"request without id must not receive an id-bearing response: {envelope}"
