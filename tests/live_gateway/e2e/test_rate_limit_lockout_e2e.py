# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_rate_limit_lockout_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway test for rate limit lockout scoping.

Drives the real ``RateLimitMiddleware`` on a running gateway by tripping the
CRITICAL_SSO tier (``/auth/sso/*``, 10 rpm by default) until the client is
locked out, then verifies that:

* the abused tier returns the lockout response,
* orchestrator probes and static assets from the same client stay reachable,
* an unrelated tier (CRITICAL auth login) from the same client is not blocked.

The SSO tier is used rather than the login endpoint so that the lockout this
test leaves behind (15 minutes by default, keyed on the runner's IP) does not
interfere with other suites that log in. Rate limiting must be enabled on the
gateway; the test skips if no 429 is ever observed.
"""

# Future
from __future__ import annotations

# Standard
import os

# Third-Party
import httpx
import pytest

# Local
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

ABUSED_PATH = "/auth/sso/providers"
LOGIN_PATH = "/auth/email/login"
PROBE_PATHS = ("/health", "/ready", "/static/admin.js", "/v1/version")

# Generous upper bound: with several replicas sharing no Redis, each replica
# counts on its own, so it can take more than limit + threshold requests.
MAX_ATTEMPTS = int(os.getenv("RATE_LIMIT_E2E_MAX_ATTEMPTS", "120"))


def _is_lockout(resp: httpx.Response) -> bool:
    return resp.status_code == 429 and "Rate limit lockout" in resp.text


@pytest.fixture(scope="module")
def locked_out_client() -> httpx.Client:
    """Hammer the abused tier until the gateway reports a lockout."""
    client = httpx.Client(base_url=BASE_URL, timeout=10)
    saw_429 = False
    for _ in range(MAX_ATTEMPTS):
        resp = client.get(ABUSED_PATH)
        if resp.status_code == 429:
            saw_429 = True
        if _is_lockout(resp):
            break
    else:
        client.close()
        if not saw_429:
            pytest.skip("Rate limiting is not enabled on the target gateway")
        pytest.fail(f"Never observed a lockout response after {MAX_ATTEMPTS} requests to {ABUSED_PATH}")
    yield client
    client.close()


def test_abused_tier_is_locked_out(locked_out_client: httpx.Client) -> None:
    """Once locked, the abused tier keeps returning the lockout response."""
    resp = locked_out_client.get(ABUSED_PATH)
    assert _is_lockout(resp), f"Expected lockout on {ABUSED_PATH}, got {resp.status_code}: {resp.text}"
    assert resp.headers.get("X-Lockout-Remaining")
    assert "account" not in resp.text.lower()


@pytest.mark.parametrize("path", PROBE_PATHS)
def test_probe_and_static_paths_stay_reachable(locked_out_client: httpx.Client, path: str) -> None:
    """Probes and static assets from the locked client are never locked out."""
    resp = locked_out_client.get(path)
    assert resp.status_code != 429, f"{path} was blocked by a lockout on {ABUSED_PATH}: {resp.text}"


def test_other_tier_is_not_locked_out(locked_out_client: httpx.Client) -> None:
    """A lockout on the SSO tier does not block the login tier from the same client."""
    resp = locked_out_client.post(LOGIN_PATH, json={"email": "nobody@example.com", "password": "wrong"})  # pragma: allowlist secret
    assert not _is_lockout(resp), f"Login tier was locked out by abuse of {ABUSED_PATH}: {resp.text}"
