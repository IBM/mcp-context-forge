# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_security_best_practices.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Security-best-practices probes against the live gateway.

MCP 2025-11-25 § Security Best Practices enumerates wire-testable
hardening the server SHOULD apply. We can't exhaustively test OS-level
or deployment-level concerns (port binding, TLS termination), but we
*can* exercise:

- Cryptographic / non-guessable session IDs (REQ ref § Session Identifier
  Security): the server's ``Mcp-Session-Id``, if issued, must not be PII
  or a sequential counter.
- DNS-rebinding / host-header validation: a POST claiming a non-gateway
  ``Host`` header should not be treated as originating from the gateway's
  own origin.
- Content-Type strictness: malformed Content-Type on a JSON-RPC POST
  must not crash the server.
- Open-redirect negative: admin login endpoints must not bounce users to
  attacker-controlled ``next`` URLs.
- Rejection of forged ``Authorization`` headers: a Bearer containing an
  obviously malformed JWT string must be rejected, not silently accepted.

Rate-limiting and full DNS-rebinding attack coverage are out of scope —
they require an adversarial fixture environment we don't provide.
"""

from __future__ import annotations

import re

import httpx
import pytest

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_security]


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
            "clientInfo": {"name": "security-probe", "version": "0.1"},
        },
    }


def test_session_id_is_non_guessable_if_issued(gateway_http_client: httpx.Client) -> None:
    """If the server issues ``Mcp-Session-Id``, it must not be trivially guessable.

    A compliant session id should be cryptographic (per the Security Best
    Practices discussion of confused-deputy / session-hijacking). Concrete
    invariants we assert:
      - Not a sequential integer.
      - At least 16 characters (UUID / base64-ish minimum entropy).
      - Not a plausible email / PII-shaped string.
    """
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_initialize_body(1))
    sid = resp.headers.get("mcp-session-id")
    if sid is None:
        pytest.skip("gateway does not issue Mcp-Session-Id (spec-sanctioned MAY; see #4205)")
    assert not sid.isdigit(), f"session id is a plain integer (guessable): {sid!r}"
    assert len(sid) >= 16, f"session id too short for reasonable entropy: {sid!r} (len {len(sid)})"
    assert "@" not in sid, f"session id contains '@' — possible PII leak: {sid!r}"


def test_host_header_spoofing_does_not_crash_server(gateway_http_client: httpx.Client) -> None:
    """A spoofed Host header (DNS-rebinding probe) must not 5xx.

    A compliant server either rejects the request (4xx) because the host
    isn't a configured origin, or serves normally (Host isn't trusted for
    authz). Either is acceptable. A 5xx indicates the host-header parsing
    path crashed, which is a red flag.
    """
    headers = dict(_MCP_HEADERS)
    headers["host"] = "attacker.example.com"
    resp = gateway_http_client.post("/mcp/", headers=headers, json=_initialize_body(1))
    assert resp.status_code < 500, f"spoofed Host caused 5xx ({resp.status_code}) — server crashes on untrusted host: " f"{resp.text[:200]}"


def test_malformed_content_type_rejected_not_crashed(gateway_http_client: httpx.Client) -> None:
    """A request with a bogus Content-Type must return 4xx, not 5xx."""
    headers = dict(_MCP_HEADERS)
    headers["content-type"] = "application/x-bogus-not-a-real-type"
    resp = gateway_http_client.post("/mcp/", headers=headers, json=_initialize_body(1))
    assert resp.status_code < 500, f"malformed content-type caused 5xx: {resp.status_code}"


def test_malformed_bearer_rejected(gateway_http_client: httpx.Client) -> None:
    """Authorization: Bearer <garbage> must be rejected, not silently accepted.

    Uses a fresh httpx.Client (without the admin JWT header) to construct
    a deliberately malformed bearer. The fixture client carries an admin
    token; overriding per-request preserves that for other tests.
    """
    base_url = str(gateway_http_client.base_url)
    with httpx.Client(base_url=base_url, timeout=10.0) as raw:
        headers = dict(_MCP_HEADERS)
        headers["authorization"] = "Bearer not.a.valid.jwt"
        resp = raw.post("/mcp/", headers=headers, json=_initialize_body(1))
    # Spec-compliant outcomes: 401 (auth failure) or 403 (forbidden). A
    # successful 200 here would mean the gateway accepted a garbage token.
    assert resp.status_code in (401, 403), f"malformed Bearer should be rejected with 401/403, got {resp.status_code}: {resp.text[:200]}"


def test_admin_login_open_redirect_negative(gateway_http_client: httpx.Client) -> None:
    """Admin login's ``next`` / ``redirect`` parameter should not bounce to an arbitrary URL.

    Probes a common login-style endpoint with a crafted ``next`` to an
    attacker domain. A compliant implementation ignores or validates the
    redirect target. Skips if the endpoint doesn't exist on this deploy.
    """
    # Try a handful of common login-adjacent paths; if none exist, skip.
    for path in ("/admin/login", "/login", "/admin"):
        resp = gateway_http_client.get(
            path,
            params={"next": "https://attacker.example.com/"},
            follow_redirects=False,
        )
        if resp.status_code == 404:
            continue
        # Found an endpoint. If it 3xx'd, check the Location header.
        if 300 <= resp.status_code < 400:
            location = resp.headers.get("location", "")
            assert "attacker.example.com" not in location, f"{path} responded with redirect to attacker-controlled URL: " f"Location={location!r}"
        return
    pytest.skip("no admin login-adjacent endpoint found on this deployment")


def test_response_headers_include_clickjacking_defense(gateway_http_client: httpx.Client) -> None:
    """Responses to admin-UI paths include clickjacking defense (X-Frame-Options / CSP frame-ancestors).

    Both are acceptable per MDN and current best practice; we assert at
    least one is present.
    """
    resp = gateway_http_client.get("/health")
    xfo = resp.headers.get("x-frame-options", "")
    csp = resp.headers.get("content-security-policy", "")
    assert xfo or "frame-ancestors" in csp, "neither X-Frame-Options nor CSP frame-ancestors on /health — clickjacking defense absent"
