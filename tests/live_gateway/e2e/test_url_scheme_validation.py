# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_url_scheme_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway smoke tests for URL scheme enforcement (issue #6264).

The startup ``_check_url_scheme_compliance()`` scan is a boot-time lifecycle
event and cannot be re-triggered through the API.  These tests verify the
related runtime validation layer on a running gateway:

1. The gateway is healthy — implying the startup scheme check passed.
2. URL scheme validation rejects a disallowed scheme at the API boundary.
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

# ---------------------------------------------------------------------------
# Configuration (mirrors helpers/mcp_test_helpers.py)
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("MCP_CLI_BASE_URL", "http://127.0.0.1:8080").replace("//localhost", "//127.0.0.1")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
TOKEN_EXPIRY = os.getenv("MCP_CLI_TOKEN_EXPIRY", "60")


def _gateway_reachable() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=5).status_code == 200
    except Exception:
        return False


skip_no_gateway = pytest.mark.skipif(not _gateway_reachable(), reason=f"Gateway not reachable at {BASE_URL}")


@pytest.fixture(scope="module")
def jwt_token() -> str:
    """Generate a short-lived admin JWT for the test module."""
    result = subprocess.run(
        [sys.executable, "-m", "mcpgateway.utils.create_jwt_token", "--username", ADMIN_EMAIL, "--exp", TOKEN_EXPIRY, "--secret", JWT_SECRET],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"JWT generation failed: {result.stderr}"
    return result.stdout.strip().strip('"')


@pytest.fixture(scope="module")
def auth_headers(jwt_token: str) -> dict[str, str]:
    """Return the Authorization header dict."""
    return {"Authorization": f"Bearer {jwt_token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@skip_no_gateway
def test_gateway_healthy_implies_startup_scheme_check_passed():
    """A healthy gateway means ``_check_url_scheme_compliance()`` did not raise ``SystemExit``."""
    resp = httpx.get(f"{BASE_URL}/health", timeout=5)
    assert resp.status_code == 200


@skip_no_gateway
def test_disallowed_url_scheme_rejected_by_api(auth_headers: dict[str, str]):
    """POST /mcp-servers/test with an ftp:// URL is rejected at the validation boundary."""
    resp = httpx.post(
        f"{BASE_URL}/mcp-servers/test",
        json={"method": "GET", "base_url": "ftp://evil.example.com", "path": "/"},
        headers=auth_headers,
        timeout=10,
    )
    assert resp.status_code == 422, f"Expected 422 for disallowed scheme, got {resp.status_code}: {resp.text}"
