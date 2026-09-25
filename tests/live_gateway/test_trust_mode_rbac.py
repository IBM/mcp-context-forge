# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_trust_mode_rbac.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway RBAC checks for JWT trust mode (issue #5900).

The expected mode comes from the ``JWT_TRUST_MODE`` environment variable of
the test process; run the suite once with the gateway stack in default mode
and once with the stack started with ``JWT_TRUST_MODE=jwt-trust``.

- Trust mode OFF (``db``): a ``token_use="trusted"`` token is rejected with
  401 at both Layer-1 scoping and the authentication choke point, so the
  marker never enters the default funnel.
- Trust mode ON (``jwt-trust``): the same token authenticates from its
  claims alone. A role-less claims principal is denied by RBAC Layer-2
  with 403 (never 401), and a claims role of ``developer`` grants
  ``tools.read`` for a 200 listing.

Requirements:
    - ContextForge running with docker-compose (default: http://localhost:8080)

Usage:
    make test-mcp-rbac            # gateway in default (db) mode
    JWT_TRUST_MODE=jwt-trust ...  # gateway restarted in trust mode
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
from .helpers.mcp_test_helpers import (
    BASE_URL,
    JWT_SECRET,
    skip_no_gateway,
)

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# Expected gateway mode for this run; must match the stack configuration.
EXPECTED_TRUST_MODE = os.getenv("JWT_TRUST_MODE", "db")

TRUST_USER_ID = "live-trust-subject-0001"
TRUST_EMAIL = "live.trust.user@example.com"
TRUST_TEAMS = ["live-trust-team"]


def _trust_token(roles: list[str]) -> str:
    """Mint a trust-marker token with the shared gateway secret."""
    return make_trusted_test_jwt(
        TRUST_USER_ID,
        email=TRUST_EMAIL,
        teams=TRUST_TEAMS,
        roles=roles,
        secret=JWT_SECRET,
    )


def test_trust_token_dispatches_per_mode() -> None:
    """A trust-marker token gets 401 in db mode and claims-derived RBAC in jwt-trust mode."""
    token = _trust_token(roles=[])
    response = httpx.get(f"{BASE_URL}/tools", headers={"Authorization": f"Bearer {token}"}, timeout=10)

    if EXPECTED_TRUST_MODE == "jwt-trust":
        # Claims-derived principal authenticated: RBAC Layer-2, not
        # authentication, denies the role-less token.
        assert response.status_code == 403, f"role-less trust token must hit RBAC deny, got: {response.status_code} {response.text[:200]}"
        authorized = httpx.get(f"{BASE_URL}/tools", headers={"Authorization": f"Bearer {_trust_token(roles=['developer'])}"}, timeout=10)
        assert authorized.status_code == 200, f"developer-role trust token rejected in jwt-trust mode: {authorized.status_code} {authorized.text[:200]}"
    else:
        # The marker must never enter the default funnel.
        assert response.status_code == 401, f"trust token not rejected in db mode: {response.status_code}"
