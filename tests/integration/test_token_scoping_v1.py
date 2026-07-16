# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_token_scoping_v1.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

tests/integration/test_token_scoping_v1.py
Integration tests verifying that token scope path normalization strips /v1
before RBAC pattern matching, so a scope pattern like ``^/tools`` grants
access to both ``/tools`` (legacy) and ``/v1/tools`` (canonical).

These tests complement the unit-level tests in
``tests/unit/mcpgateway/middleware/test_token_scoping_normalization.py``,
which exercise the normalizer in isolation. Here we verify the behaviour
through the full ASGI middleware stack.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mcpgateway.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestV1LegacyAuthParity:
    """Verify identical auth behaviour between /v1/* and legacy routes.

    If the token-scoping middleware did NOT strip the /v1 prefix before
    pattern matching, a scope of ``^/tools`` would allow ``/tools`` but
    block ``/v1/tools`` with 403.  Both routes must return the same
    HTTP status for the same credential.
    """

    ROUTE_PAIRS = [
        ("/tools", "/v1/tools"),
        ("/servers", "/v1/servers"),
        ("/gateways", "/v1/gateways"),
        ("/resources", "/v1/resources"),
        ("/prompts", "/v1/prompts"),
        ("/metrics", "/v1/metrics"),
    ]

    @pytest.mark.parametrize("legacy,versioned", ROUTE_PAIRS)
    def test_unauthenticated_returns_same_status(self, client: TestClient, legacy: str, versioned: str) -> None:
        """Both legacy and /v1 routes must reject unauthenticated requests identically."""
        legacy_resp = client.get(legacy, follow_redirects=False)
        v1_resp = client.get(versioned, follow_redirects=False)

        assert legacy_resp.status_code == v1_resp.status_code, (
            f"Auth response mismatch: {legacy} → {legacy_resp.status_code}, "
            f"{versioned} → {v1_resp.status_code}. "
            "Token-scope normalizer may not be stripping /v1 before pattern matching."
        )

    @pytest.mark.parametrize("legacy,versioned", ROUTE_PAIRS)
    def test_basic_auth_returns_same_status(self, client: TestClient, legacy: str, versioned: str) -> None:
        """With the same credentials, legacy and /v1 routes must return the same status."""
        from mcpgateway.config import settings

        auth = (settings.basic_auth_user, settings.basic_auth_password)

        legacy_resp = client.get(legacy, auth=auth, follow_redirects=False)
        v1_resp = client.get(versioned, auth=auth, follow_redirects=False)

        assert legacy_resp.status_code == v1_resp.status_code, (
            f"Auth response mismatch with valid credentials: {legacy} → {legacy_resp.status_code}, "
            f"{versioned} → {v1_resp.status_code}."
        )

    @pytest.mark.parametrize("legacy,versioned", ROUTE_PAIRS)
    def test_wrong_credentials_returns_same_status(self, client: TestClient, legacy: str, versioned: str) -> None:
        """Wrong credentials must produce identical errors on both route variants."""
        auth = ("nobody", "wrongpassword")  # pragma: allowlist secret

        legacy_resp = client.get(legacy, auth=auth, follow_redirects=False)
        v1_resp = client.get(versioned, auth=auth, follow_redirects=False)

        assert legacy_resp.status_code == v1_resp.status_code, (
            f"Wrong-credentials response mismatch: {legacy} → {legacy_resp.status_code}, "
            f"{versioned} → {v1_resp.status_code}."
        )
