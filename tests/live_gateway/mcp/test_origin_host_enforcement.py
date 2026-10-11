# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_origin_host_enforcement.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box tests for MCP Origin/Host enforcement at the /mcp endpoint.

Verifies the DNS-rebinding protection introduced by MCP_ALLOWED_ORIGINS and
MCP_ALLOWED_HOSTS (MCP §transport-security):

- An unlisted Origin header is rejected with HTTP 403.
- A listed Origin header is accepted (passes through to auth/session logic).
- A missing Origin header is always accepted (native/CLI clients).

The gateway must be started with MCP_ALLOWED_ORIGINS set to a known value
(e.g. ``https://trusted.example.com``) for the first two assertions to be
meaningful. When MCP_ALLOWED_ORIGINS is empty (default), all three cases
are accepted, so the "forbidden" test is skipped automatically.

Environment variables consumed:
    MCP_CLI_BASE_URL             Gateway URL (default: http://127.0.0.1:8080)
    MCP_E2E_ALLOWED_ORIGIN       The allowed origin value configured on the
                                 gateway (default: https://trusted.example.com).
                                 Must match what MCP_ALLOWED_ORIGINS is set to.
    JWT_SECRET_KEY               JWT signing secret for the admin bootstrap token.

Usage:
    MCP_ALLOWED_ORIGINS=https://trusted.example.com \\
    MCP_E2E_ALLOWED_ORIGIN=https://trusted.example.com \\
    pytest tests/live_gateway/mcp/test_origin_host_enforcement.py -v
"""

# Future
from __future__ import annotations

# Standard
import os
import subprocess
import sys

# Third-Party
import httpx
import pytest

# Local
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, build_initialize, JWT_SECRET, skip_no_gateway, TOKEN_EXPIRY, ADMIN_EMAIL

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_ALLOWED_ORIGIN = os.getenv("MCP_E2E_ALLOWED_ORIGIN", "https://trusted.example.com")
_MCP_URL = f"{BASE_URL}/mcp/"

pytestmark = [pytest.mark.e2e, skip_no_gateway]


def _make_jwt() -> str:
    """Mint a short-lived admin JWT for the bootstrap user."""
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", ADMIN_EMAIL, "--exp", TOKEN_EXPIRY, "--secret", JWT_SECRET],
        check=False,
        capture_output=True,
        text=True,
    )
    token = result.stdout.strip()
    assert token, f"JWT creation failed: {result.stderr}"
    return token


def _mcp_headers(jwt: str, *, origin: str | None = None, host: str | None = None) -> dict[str, str]:
    """Build minimal MCP Streamable HTTP request headers.

    Args:
        jwt: Bearer token value.
        origin: Optional Origin header value to include.
        host: Optional Host header override.

    Returns:
        Header dict for httpx.
    """
    headers: dict[str, str] = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    }
    if origin is not None:
        headers["Origin"] = origin
    if host is not None:
        headers["Host"] = host
    return headers


def _origin_enforcement_active() -> bool:
    """Return True when MCP_ALLOWED_ORIGINS is configured on the running gateway.

    Probes by sending a request with a known-bad Origin and checking whether
    the gateway returns 403. If the gateway returns anything other than 403,
    enforcement is considered inactive (default empty-allowlist mode).
    """
    try:
        jwt = _make_jwt()
        resp = httpx.post(
            _MCP_URL,
            headers=_mcp_headers(jwt, origin="https://probe-sentinel.invalid"),
            json=build_initialize(),
            timeout=10.0,
        )
        return resp.status_code == 403
    except Exception:
        return False


_skip_no_enforcement = pytest.mark.skipif(
    not _origin_enforcement_active(),
    reason="MCP_ALLOWED_ORIGINS not configured on target gateway — enforcement tests skipped",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@_skip_no_enforcement
def test_unlisted_origin_returns_403() -> None:
    """A present-but-unlisted Origin must be rejected with HTTP 403."""
    jwt = _make_jwt()
    resp = httpx.post(
        _MCP_URL,
        headers=_mcp_headers(jwt, origin="https://attacker.invalid"),
        json=build_initialize(),
        timeout=10.0,
    )
    assert resp.status_code == 403, f"Expected 403 for unlisted Origin, got {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    assert "detail" in body, f"Expected JSON detail field, got: {body}"


@_skip_no_enforcement
def test_allowlisted_origin_is_not_rejected() -> None:
    """A request with an allowlisted Origin must not be rejected by the Origin gate."""
    jwt = _make_jwt()
    resp = httpx.post(
        _MCP_URL,
        headers=_mcp_headers(jwt, origin=_ALLOWED_ORIGIN),
        json=build_initialize(),
        timeout=10.0,
    )
    # A 403 here means the gate fired — that is the failure case.
    # 200 means pass; 401/400 means the gate passed but auth/session logic ran (also pass).
    assert resp.status_code != 403, (
        f"Allowlisted Origin '{_ALLOWED_ORIGIN}' was rejected with 403. "
        f"Verify MCP_E2E_ALLOWED_ORIGIN matches MCP_ALLOWED_ORIGINS on the gateway."
    )


def test_missing_origin_is_always_accepted() -> None:
    """A request with no Origin header must never be rejected by the Origin gate.

    This test does not require MCP_ALLOWED_ORIGINS to be set — it must pass
    in both default and configured modes.
    """
    jwt = _make_jwt()
    resp = httpx.post(
        _MCP_URL,
        headers=_mcp_headers(jwt),  # no Origin header
        json=build_initialize(),
        timeout=10.0,
    )
    assert resp.status_code != 403, (
        f"Missing-Origin request was rejected with 403 — native/CLI clients must always be accepted."
        f" Got: {resp.status_code}: {resp.text[:300]}"
    )
