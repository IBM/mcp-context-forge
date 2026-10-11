# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_gateway_registration_diagnostics.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway regression for gateway registration diagnostics (issue #6724).

The unit suite drives ``UrlPolicyError`` and ``extract_reason_code()`` directly.
These tests prove the same policy through the running HTTP boundary, where the
exception handler, the admin handler and the response serializer all take part:

1. ``POST /gateways`` rejects a malformed URL with ``422``.
2. ``POST /gateways`` keeps destination reason codes out of the response body.
3. ``POST /admin/gateways`` returns the same status and the same exposure for a
   form submission, so API and admin registration stay equivalent.
"""

# Future
from __future__ import annotations

# Standard
import os
import subprocess
import sys
import uuid

# Third-Party
import httpx
import pytest

# ---------------------------------------------------------------------------
# Configuration (mirrors helpers/mcp_test_helpers.py)
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("MCP_CLI_BASE_URL", "http://127.0.0.1:8080").replace("//localhost", "//127.0.0.1")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
TOKEN_EXPIRY = os.getenv("MCP_CLI_TOKEN_EXPIRY", "60")

# Codes safe to return to the caller (mcpgateway/utils/error_formatter.py::PUBLIC_REASON_CODES).
PUBLIC_REASON_CODES = {"url_invalid_syntax", "url_scheme_not_allowed"}

# Always blocked by SSRF policy, independent of SSRF_ALLOW_PRIVATE_NETWORKS: cloud metadata.
BLOCKED_DESTINATION = "http://169.254.169.254/mcp"

# Codes that must stay in the logs: echoing them tells the caller whether a submitted
# host resolved into a blocked internal range.
LOG_ONLY_REASON_CODES = (
    "url_destination_blocked",
    "url_private_network_blocked",
    "url_dns_resolution_failed",
    "url_dns_no_addresses",
)


def _gateway_reachable() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=5).status_code == 200
    except Exception:
        return False


skip_no_gateway = pytest.mark.skipif(not _gateway_reachable(), reason=f"Gateway not reachable at {BASE_URL}")


@pytest.fixture(scope="module")
def jwt_token() -> str:
    """Generate a short-lived admin JWT for the test module.

    ``--admin`` is required because ``/admin/gateways`` denies a non-admin token with 403,
    which would hide the registration status under an authorization status.
    """
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", ADMIN_EMAIL, "--admin", "--exp", TOKEN_EXPIRY, "--secret", JWT_SECRET],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "JWT_SECRET_KEY": JWT_SECRET},
    )
    assert result.returncode == 0, f"JWT generation failed: {result.stderr}"
    # ``--admin`` prints a development-only warning before the token; the token is the last line.
    return result.stdout.strip().splitlines()[-1].strip('"')


@pytest.fixture(scope="module")
def auth_headers(jwt_token: str) -> dict[str, str]:
    """Return the Authorization header dict."""
    return {"Authorization": f"Bearer {jwt_token}"}


def _gateway_name() -> str:
    """Return a unique gateway name so a rejected request never collides with a stored row."""
    return f"diag-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@skip_no_gateway
def test_malformed_url_rejected_with_422(auth_headers: dict[str, str]):
    """A URL that fails syntax validation is a client input fault: 422, never 500."""
    resp = httpx.post(
        f"{BASE_URL}/gateways",
        json={"name": _gateway_name(), "url": "not-a-url", "transport": "STREAMABLEHTTP"},
        headers=auth_headers,
        timeout=15,
    )
    assert resp.status_code == 422, f"Expected 422 for malformed URL, got {resp.status_code}: {resp.text}"

    reason_code = resp.json().get("reason_code")
    assert reason_code == "url_scheme_not_allowed", f"Expected the public reason_code for a malformed URL, got: {reason_code} ({resp.text})"


@skip_no_gateway
def test_blocked_destination_reason_code_stays_out_of_the_api_response(auth_headers: dict[str, str]):
    """A destination blocked by URL policy is rejected, and its reason code never reaches the caller."""
    resp = httpx.post(
        f"{BASE_URL}/gateways",
        json={"name": _gateway_name(), "url": BLOCKED_DESTINATION, "transport": "STREAMABLEHTTP"},
        headers=auth_headers,
        timeout=15,
    )
    assert resp.status_code == 422, f"Expected 422 for blocked destination, got {resp.status_code}: {resp.text}"

    for code in LOG_ONLY_REASON_CODES:
        assert code not in resp.text, f"Log-only reason code {code} leaked into the response body: {resp.text}"


@skip_no_gateway
def test_admin_registration_matches_api_status_and_exposure(auth_headers: dict[str, str]):
    """Admin form registration returns the same status and the same exposure as the API path."""
    resp = httpx.post(
        f"{BASE_URL}/admin/gateways",
        data={"name": _gateway_name(), "url": BLOCKED_DESTINATION, "transport": "STREAMABLEHTTP"},
        headers={**auth_headers, "Accept": "application/json"},
        timeout=15,
    )
    if resp.status_code == 404:
        pytest.skip("Admin API is disabled on this gateway (MCPGATEWAY_ADMIN_API_ENABLED=false)")

    assert resp.status_code == 422, f"Expected 422 for blocked destination, got {resp.status_code}: {resp.text}"

    for code in LOG_ONLY_REASON_CODES:
        assert code not in resp.text, f"Log-only reason code {code} leaked into the response body: {resp.text}"
