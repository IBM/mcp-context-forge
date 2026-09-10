# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_trust_mode_multi_worker.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Multi-worker revocation propagation for JWT trust mode (issue #5905, suite b).

Two gateway workers share one database and one Redis blocklist. A trust-mode
token revoked on worker A must be rejected by worker B within the documented
negative-cache window (``auth_cache_revocation_ttl``, default 30 s): the
trust branch re-checks the configured revocation claim on every request.

Requirements (same pattern as ``run_primary_worker_multiinstance.sh``):
    - docker compose stack with the gateway scaled to 2 replicas, sharing one
      Postgres database and one Redis instance, started with
      ``JWT_TRUST_MODE=jwt-trust``
    - ``JWT_SECRET_KEY`` identical on both workers (shared signing key)
    - ``TRUST_MULTI_WORKER_URLS``: comma-separated base URL per worker, e.g.
      ``http://127.0.0.1:8080,http://127.0.0.1:8081``

Run:
    JWT_TRUST_MODE=jwt-trust \
    TRUST_MULTI_WORKER_URLS=http://127.0.0.1:8080,http://127.0.0.1:8081 \
        uv run pytest tests/live_gateway/test_trust_mode_multi_worker.py

The suite self-skips when no gateway is reachable, when fewer than two
worker URLs are configured, or when the stack is not in trust mode.
"""

# Future
from __future__ import annotations

# Standard
import os

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_trusted_test_jwt
from .helpers.mcp_test_helpers import (
    BASE_URL,
    JWT_SECRET,
    skip_no_gateway,
)

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# Expected gateway mode for this run; must match the stack configuration.
EXPECTED_TRUST_MODE = os.getenv("JWT_TRUST_MODE", "db")

# One base URL per worker. With the single-node default stack this list has
# one entry and the multi-worker test skips; the standard live stack still
# runs the single-worker revocation sanity check.
WORKER_URLS = [url.strip() for url in os.getenv("TRUST_MULTI_WORKER_URLS", "").split(",") if url.strip()] or [BASE_URL]

skip_unless_trust_mode = pytest.mark.skipif(EXPECTED_TRUST_MODE != "jwt-trust", reason="requires the stack started with JWT_TRUST_MODE=jwt-trust")
skip_unless_multi_worker = pytest.mark.skipif(len(WORKER_URLS) < 2, reason="multi-worker stack not configured (set TRUST_MULTI_WORKER_URLS to one base URL per worker)")

TRUST_USER_ID = "live-mw-trust-subject-0001"
TRUST_EMAIL = "live.mw.trust.user@example.com"
REVOKE_JTI = "live-mw-revoke-jti-0001"
CONTROL_JTI = "live-mw-control-jti-0001"


def _trust_token(jti: str) -> str:
    """Mint a trust-marker token with a known revocation identifier."""
    return make_trusted_test_jwt(
        TRUST_USER_ID,
        email=TRUST_EMAIL,
        teams=[],
        roles=[],
        revocation_id=jti,
        secret=JWT_SECRET,
    )


def _get_tools(worker_url: str, token: str) -> httpx.Response:
    """Issue an authenticated read against one worker."""
    return httpx.get(f"{worker_url}/tools", headers=make_auth_headers(token), timeout=10)


def _logout(worker_url: str, token: str) -> httpx.Response:
    """Revoke the token through the logout endpoint on one worker."""
    return httpx.post(f"{worker_url}/auth/logout", headers=make_auth_headers(token), timeout=10)


@skip_unless_trust_mode
def test_revocation_visible_on_single_worker() -> None:
    """Sanity: logout revokes a trust token on the standard single-worker stack."""
    token = _trust_token(REVOKE_JTI)

    response = _get_tools(WORKER_URLS[0], token)
    assert response.status_code == 200, f"trust token rejected before revocation: {response.status_code} {response.text[:200]}"

    logout_response = _logout(WORKER_URLS[0], token)
    assert logout_response.status_code == 200, f"logout failed: {logout_response.status_code} {logout_response.text[:200]}"
    assert logout_response.json().get("revoked_token") == REVOKE_JTI

    response = _get_tools(WORKER_URLS[0], token)
    assert response.status_code == 401, f"revoked trust token still accepted: {response.status_code}"


@skip_unless_trust_mode
@skip_unless_multi_worker
def test_revocation_propagates_across_workers() -> None:
    """Revoke on worker A; the same jti is rejected on worker B.

    Revocation lands in the shared database (and the shared Redis blocklist),
    so worker B rejects the token immediately — well within the documented
    30 s negative-cache window.
    """
    worker_a, worker_b = WORKER_URLS[0], WORKER_URLS[1]
    token = _trust_token(REVOKE_JTI)

    # The token authenticates against both workers before revocation.
    for url in (worker_a, worker_b):
        response = _get_tools(url, token)
        assert response.status_code == 200, f"trust token rejected by {url} before revocation: {response.status_code} {response.text[:200]}"

    # Revoke on worker A via the logout endpoint (writes the blocklist row).
    logout_response = _logout(worker_a, token)
    assert logout_response.status_code == 200, f"logout on worker A failed: {logout_response.status_code} {logout_response.text[:200]}"
    assert logout_response.json().get("revoked_token") == REVOKE_JTI

    # Worker B must reject the same jti. The trust branch checks the
    # revocation store on every request, so no cache wait is needed; the
    # assertion runs well inside the 30 s negative-cache window.
    response = _get_tools(worker_b, token)
    assert response.status_code == 401, f"worker B accepted a token revoked on worker A: {response.status_code}"

    # Control: a different, unrevoked jti still authenticates on both workers.
    control = _trust_token(CONTROL_JTI)
    for url in (worker_a, worker_b):
        response = _get_tools(url, control)
        assert response.status_code == 200, f"unrevoked control token rejected by {url}: {response.status_code} {response.text[:200]}"
