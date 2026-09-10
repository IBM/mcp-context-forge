# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_trust_mode_rbac.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway RBAC checks for JWT trust mode (issue #5900).

The expected mode comes from the ``JWT_TRUST_MODE`` environment variable of
the test process; run the suite once with the gateway stack in default mode
and once with the stack started with ``JWT_TRUST_MODE=jwt-trust``.

- Trust mode OFF (``db``): a ``token_use="trusted"`` token is rejected with
  401 and never enters the default funnel.
- Trust mode ON (``jwt-trust``): the same token authenticates from its
  claims alone; ``token_teams`` on the request comes from the claims and the
  group-mapping resolver, and RBAC evaluation proceeds with the
  claims-derived identity.

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


def _trust_token() -> str:
    """Mint a trust-marker token with the shared gateway secret."""
    return make_trusted_test_jwt(
        TRUST_USER_ID,
        email=TRUST_EMAIL,
        teams=TRUST_TEAMS,
        roles=[],
        secret=JWT_SECRET,
    )


def test_trust_token_dispatches_per_mode() -> None:
    """A trust-marker token gets 401 in db mode and authenticates in jwt-trust mode."""
    token = _trust_token()
    response = httpx.get(f"{BASE_URL}/tools", headers={"Authorization": f"Bearer {token}"}, timeout=10)

    if EXPECTED_TRUST_MODE == "jwt-trust":
        # Claims-derived principal: the request is authenticated.
        assert response.status_code == 200, f"trust token rejected in jwt-trust mode: {response.status_code} {response.text[:200]}"
    else:
        # The marker must never enter the default funnel.
        assert response.status_code == 401, f"trust token not rejected in db mode: {response.status_code}"
