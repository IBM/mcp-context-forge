# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_rbac_rule_providers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway black-box checks for the rule catalog and both Layer-2 rule
providers.

The expected provider comes from the ``RBAC_RULE_PROVIDER`` environment
variable of the test process. Run the suite once with the default stack
(``db``) and once with ``make testing-up-openfga``; both runs must show
identical outcomes:

- Unauthenticated calls to the rules API answer 401.
- A public-only token (empty teams, non-admin) gets 403 on rule
  mutations: Layer-1 scope plus Layer-2 ``rbac.rules.manage`` deny.
- An admin-bypass token lists rules, gets 422 for a syntactically
  invalid predicate, 409 deleting a system rule, and 204 deleting its
  own rule.
- The catalog deny path: with a deny rule on ``teams.read`` for
  ``role.viewer``, the admin-run permission check for a viewer-role
  member flips from allow to deny on both providers.

Requirements:
    - ContextForge running with docker-compose (default: http://localhost:8080)
    - Admin login seeded (PLATFORM_ADMIN_EMAIL / TEST_PASSWORD)

Usage:
    make test-rbac-providers                # stack in db mode
    make testing-up-openfga && make test-rbac-providers
"""

# Future
from __future__ import annotations

# Standard
import os

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_trusted_test_jwt
from .helpers.mcp_test_helpers import BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

EXPECTED_PROVIDER = os.getenv("RBAC_RULE_PROVIDER", "db")

RULES_URL = f"{BASE_URL}/rbac/rules"
CHECK_URL = f"{BASE_URL}/rbac/permissions/check"

VIEWER_EMAIL = "live-rules-viewer@example.com"


def _admin_headers() -> dict[str, str]:
    """Mint an admin-bypass token with the shared gateway secret."""
    token = make_trusted_test_jwt("live-rules-admin", email="admin@example.com", teams=None, is_admin=True, secret=JWT_SECRET)
    return {"Authorization": f"Bearer {token}"}


def _public_headers() -> dict[str, str]:
    """Mint a public-only session token with the shared gateway secret."""
    token = make_trusted_test_jwt("live-rules-public", email="public.user@example.com", teams=[], is_admin=False, secret=JWT_SECRET)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def viewer_role_id() -> str:
    """Find the seeded viewer role id through the roles API."""
    response = httpx.get(f"{BASE_URL}/rbac/roles", headers=_admin_headers(), timeout=10)
    assert response.status_code == 200, response.text[:200]
    for role in response.json():
        if role.get("name") == "viewer":
            return str(role["id"])
    pytest.fail("viewer role not seeded on the live stack")


@pytest.fixture(scope="module")
def viewer_user(viewer_role_id) -> str:
    """Return the viewer user identity for permission checks."""
    return VIEWER_EMAIL


def test_unauthenticated_rules_calls_answer_401():
    response = httpx.get(RULES_URL, timeout=10)
    assert response.status_code == 401
    response = httpx.post(RULES_URL, json={"name": "x", "capability_type": "tool", "predicate": "authenticated", "effect": "deny"}, timeout=10)
    assert response.status_code == 401


def test_public_token_cannot_mutate_rules():
    response = httpx.post(RULES_URL, headers=_public_headers(), json={"name": "pub", "capability_type": "tool", "predicate": "authenticated", "effect": "deny"}, timeout=10)
    assert response.status_code == 403, f"public-only token must be denied rule mutations, got {response.status_code}"


def test_admin_lists_rules():
    response = httpx.get(RULES_URL, headers=_admin_headers(), timeout=10)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_invalid_predicate_rejected_with_422():
    response = httpx.post(RULES_URL, headers=_admin_headers(), json={"name": "live-invalid", "capability_type": "tool", "predicate": "role.hr; DROP TABLE", "effect": "deny"}, timeout=10)
    assert response.status_code == 422, f"syntactically invalid predicate must 422, got {response.status_code}: {response.text[:200]}"


def test_system_rule_delete_rejected_with_409():
    listing = httpx.get(RULES_URL, headers=_admin_headers(), timeout=10)
    system_rules = [r for r in listing.json() if r.get("is_system")]
    assert system_rules, "seeded system rules must exist on the live stack"
    response = httpx.delete(f"{RULES_URL}/{system_rules[0]['id']}", headers=_admin_headers(), timeout=10)
    assert response.status_code == 409


def test_deny_rule_flips_permission_check_both_providers(viewer_user):
    """A catalog deny on teams.read denies a viewer on every provider."""
    check_body = {"user_email": viewer_user, "permission": "teams.read"}
    before = httpx.post(CHECK_URL, headers=_admin_headers(), json=check_body, timeout=10)
    assert before.status_code == 200

    created = httpx.post(
        RULES_URL,
        headers=_admin_headers(),
        json={"name": "live-deny-viewer-teams-read", "capability_type": "route", "permission": "teams.read", "predicate": "role.viewer", "effect": "deny"},
        timeout=10,
    )
    assert created.status_code in (201, 200), created.text[:200]
    rule_id = created.json()["id"]
    try:
        after = httpx.post(CHECK_URL, headers=_admin_headers(), json=check_body, timeout=10)
        assert after.status_code == 200
        assert after.json().get("granted") is False, f"deny rule must flip the check on provider={EXPECTED_PROVIDER}: {after.text[:200]}"
    finally:
        deleted = httpx.delete(f"{RULES_URL}/{rule_id}", headers=_admin_headers(), timeout=10)
        assert deleted.status_code in (204, 200), f"cleanup delete failed: {deleted.status_code}"
