# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_openapi_schema_generation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box tests for ``POST /v1/tools/generate-schemas-from-openapi``.

Covers the auth gate, the outbound-fetch failure mapping, and the spec-cache
regression from issue #6835: repeated failing fetches must not degrade the
endpoint, because every failed fetch drops its single-flight lock.
"""

# Standard
import concurrent.futures
import uuid

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

ENDPOINT = f"{BASE_URL}/v1/tools/generate-schemas-from-openapi"


def _post(payload: dict, token: str | None = None) -> httpx.Response:
    """POST the schema-generation payload, optionally authenticated.

    Args:
        payload: Request body for the endpoint.
        token: Bearer token, or ``None`` for an unauthenticated call.

    Returns:
        The HTTP response.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.post(ENDPOINT, headers=headers, json=payload, timeout=30.0)


def _unreachable_payload() -> dict:
    """Build a payload whose spec URL can never be fetched.

    Returns:
        Request body pointing at a unique unresolvable host.
    """
    host = f"{uuid.uuid4().hex}.invalid"
    return {"url": f"https://{host}/calculate", "request_type": "GET", "openapi_url": f"https://{host}/openapi.json"}


def test_requires_authentication() -> None:
    """Unauthenticated callers are rejected before any outbound fetch."""
    response = _post(_unreachable_payload())

    assert response.status_code in (401, 403), response.text


def test_unreachable_spec_url_is_not_a_server_error() -> None:
    """An unfetchable spec URL maps to a client/upstream error, never a 500."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)

    response = _post(_unreachable_payload(), token)

    assert response.status_code in (400, 502), response.text
    assert response.json()["success"] is False


def test_repeated_failing_fetches_stay_stable() -> None:
    """Many failing spec URLs leave the endpoint behaving identically.

    Regression guard for the failure path: a failed fetch writes a short-lived
    negative cache entry, and neither that entry nor its lock may accumulate.
    """
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    baseline = _post(_unreachable_payload(), token)

    for _ in range(30):
        _post(_unreachable_payload(), token)

    after = _post(_unreachable_payload(), token)
    assert after.status_code == baseline.status_code, after.text
    assert after.json()["success"] is False


def test_concurrent_identical_requests_agree() -> None:
    """Concurrent callers for one spec URL all observe the same outcome."""
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=JWT_SECRET)
    payload = _unreachable_payload()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: _post(payload, token), range(8)))

    statuses = {r.status_code for r in responses}
    assert len(statuses) == 1, [r.text for r in responses]
    assert statuses.pop() != 500
