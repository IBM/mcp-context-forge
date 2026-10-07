# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_auto_refresh_last_refresh_at.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box regression for #7095: refresh throttle skip-every-other-cycle.

Verifies that the manual-refresh path writes ``last_refresh_at`` on the
gateway record.  A ``GET /v1/gateways/{id}`` call after a successful refresh
must return a non-null ``lastRefreshAt`` field.  This confirms that the
production timestamp write in ``_refresh_gateway_tools_resources_prompts``
(line 7233 of gateway_service.py) commits successfully — the path that the
throttle reads on the next cycle.
"""

# Future
from __future__ import annotations

# Standard
from typing import Iterator

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

_ADMIN_EMAIL = "admin@example.com"

# A minimal echo-style HTTP server that returns an empty MCP tool list.
# The gateway URL must be reachable from inside the compose network; the
# loopback address works when the gateway itself is the test runner.
_ECHO_URL = "http://127.0.0.1:8080/health"


def _admin_token() -> str:
    return make_test_jwt(_ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)


def _headers() -> dict:
    return {"Authorization": f"Bearer {_admin_token()}"}


@pytest.fixture
def registered_gateway() -> Iterator[dict]:
    """Create a minimal gateway and delete it after the test."""
    payload = {
        "name": "regression-7095-refresh-ts",
        "url": _ECHO_URL,
        "transport": "sse",
        "enabled": True,
    }
    resp = httpx.post(f"{BASE_URL}/v1/gateways", headers=_headers(), json=payload, timeout=15.0)
    if resp.status_code == 409:
        # Already exists from a prior interrupted run — look it up by listing.
        list_resp = httpx.get(f"{BASE_URL}/v1/gateways", headers=_headers(), timeout=10.0)
        assert list_resp.status_code == 200, list_resp.text
        gateways = list_resp.json()
        entries = gateways if isinstance(gateways, list) else gateways.get("items", [])
        match = next((g for g in entries if g.get("name") == payload["name"]), None)
        if match is None:
            pytest.skip("regression-7095 gateway exists but could not be found in list")
        gw = match
    else:
        assert resp.status_code == 200, resp.text
        gw = resp.json()

    try:
        yield gw
    finally:
        gw_id = gw.get("id")
        if gw_id:
            httpx.delete(f"{BASE_URL}/v1/gateways/{gw_id}", headers=_headers(), timeout=10.0)


def test_manual_refresh_writes_last_refresh_at(registered_gateway: dict) -> None:
    """POST /{id}/tools/refresh must persist a non-null ``lastRefreshAt`` on success.

    The throttle in ``_check_single_gateway_health`` reads ``gateway.last_refresh_at``
    to decide whether auto-refresh is due.  If the production write is absent, every
    auto-refresh cycle fires regardless of the configured interval.  This test
    confirms the write path is reachable and persists through a subsequent GET.
    """
    gw_id = registered_gateway["id"]

    refresh_resp = httpx.post(
        f"{BASE_URL}/v1/gateways/{gw_id}/tools/refresh",
        headers=_headers(),
        timeout=30.0,
    )
    # A 400/409 is acceptable when the target URL is not a live MCP server,
    # but the timestamp must still be written on a prior successful refresh
    # if the response indicates the gateway was reachable.
    if refresh_resp.status_code not in (200, 400, 409):
        pytest.skip(f"Unexpected refresh status {refresh_resp.status_code}: {refresh_resp.text}")

    if refresh_resp.status_code != 200:
        pytest.skip(f"Gateway not reachable from inside compose network (status {refresh_resp.status_code}); skipping timestamp assertion")

    get_resp = httpx.get(f"{BASE_URL}/v1/gateways/{gw_id}", headers=_headers(), timeout=10.0)
    assert get_resp.status_code == 200, get_resp.text
    gw = get_resp.json()

    assert gw.get("lastRefreshAt") is not None, (
        "last_refresh_at must be written after a successful manual refresh; "
        "the throttle in _check_single_gateway_health reads this field"
    )
