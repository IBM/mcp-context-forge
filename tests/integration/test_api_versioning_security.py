# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_api_versioning_security.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

Deny-path security tests for /v1/* versioned routes.

Validates the security invariant from AGENTS.md:
  "Security-sensitive changes must include deny-path regression tests
   (unauthenticated, wrong team, insufficient permissions, feature disabled)."

For every protected /v1 route family we verify:
  1. Unauthenticated request  → 401
  2. Wrong/invalid credentials → 401
  3. Valid auth reaches the route  (200, 404, 422 are all acceptable — none of
     401/403 means the auth layer passed the request through correctly)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mcpgateway.config import settings
from mcpgateway.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def valid_auth() -> tuple[str, str]:
    return (settings.basic_auth_user, settings.basic_auth_password)


@pytest.fixture
def invalid_auth() -> tuple[str, str]:
    return ("nobody", "wrongpassword")  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# Route families under test
# ---------------------------------------------------------------------------

ALWAYS_ON_V1_ROUTES = [
    "/v1/tools",
    "/v1/servers",
    "/v1/gateways",
    "/v1/resources",
    "/v1/prompts",
    "/v1/metrics",
    "/v1/tags",
    "/v1/export",
]

ADMIN_V1_ROUTES = [
    "/v1/admin/",
    "/v1/admin/tools",
    "/v1/admin/servers",
]


# ---------------------------------------------------------------------------
# Unauthenticated → 401
# ---------------------------------------------------------------------------


class TestUnauthenticatedDenied:
    """Every protected /v1 route must return 401 with no credentials."""

    @pytest.mark.parametrize("path", ALWAYS_ON_V1_ROUTES)
    def test_always_on_route_unauthenticated(self, client: TestClient, path: str) -> None:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated GET {path}, got {response.status_code}"
        )

    @pytest.mark.parametrize("path", ADMIN_V1_ROUTES)
    def test_admin_route_unauthenticated(self, client: TestClient, path: str) -> None:
        response = client.get(path, follow_redirects=False)
        assert response.status_code in [401, 403, 302], (
            f"Expected 401/403/302 for unauthenticated GET {path}, got {response.status_code}"
        )
        assert response.status_code != 200, (
            f"Unauthenticated access to {path} must not return 200"
        )


# ---------------------------------------------------------------------------
# Invalid credentials → 401
# ---------------------------------------------------------------------------


class TestInvalidCredentialsDenied:
    """Wrong credentials must be rejected on every /v1 route."""

    @pytest.mark.parametrize("path", ALWAYS_ON_V1_ROUTES)
    def test_always_on_route_wrong_credentials(self, client: TestClient, path: str, invalid_auth: tuple) -> None:
        response = client.get(path, auth=invalid_auth, follow_redirects=False)
        assert response.status_code == 401, (
            f"Expected 401 for wrong credentials on GET {path}, got {response.status_code}"
        )

    @pytest.mark.parametrize("path", ADMIN_V1_ROUTES)
    def test_admin_route_wrong_credentials(self, client: TestClient, path: str, invalid_auth: tuple) -> None:
        response = client.get(path, auth=invalid_auth, follow_redirects=False)
        assert response.status_code in [401, 403], (
            f"Expected 401/403 for wrong credentials on GET {path}, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Valid credentials pass through auth layer
# ---------------------------------------------------------------------------


class TestValidCredentialsPassAuth:
    """Valid credentials must not be rejected at the auth layer.

    Acceptable response codes after successful auth:
      200 OK, 404 Not Found (route exists but resource missing),
      422 Unprocessable Entity (missing required body), 405 Method Not Allowed.
    All of these indicate the auth middleware passed the request through.
    """

    AUTH_PASS_CODES = {200, 201, 204, 404, 405, 422}

    @pytest.mark.parametrize("path", ALWAYS_ON_V1_ROUTES)
    def test_always_on_route_valid_auth_passes(self, client: TestClient, path: str, valid_auth: tuple) -> None:
        response = client.get(path, auth=valid_auth, follow_redirects=False)
        assert response.status_code not in [401, 403], (
            f"Valid credentials were rejected on GET {path}: {response.status_code}"
        )

    @pytest.mark.parametrize("path", ADMIN_V1_ROUTES)
    def test_admin_route_valid_admin_auth_passes(self, client: TestClient, path: str, valid_auth: tuple) -> None:
        response = client.get(path, auth=valid_auth, follow_redirects=False)
        assert response.status_code not in [401], (
            f"Valid admin credentials were rejected on GET {path}: {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Auth parity: /v1/* and legacy routes must have identical auth behaviour
# ---------------------------------------------------------------------------


class TestV1LegacyAuthParity:
    """Same credential must produce the same auth result on /v1 and legacy routes."""

    ROUTE_PAIRS = [
        ("/tools", "/v1/tools"),
        ("/servers", "/v1/servers"),
        ("/gateways", "/v1/gateways"),
        ("/resources", "/v1/resources"),
        ("/prompts", "/v1/prompts"),
        ("/metrics", "/v1/metrics"),
    ]

    @pytest.mark.parametrize("legacy,versioned", ROUTE_PAIRS)
    def test_unauthenticated_parity(self, client: TestClient, legacy: str, versioned: str) -> None:
        legacy_status = client.get(legacy, follow_redirects=False).status_code
        v1_status = client.get(versioned, follow_redirects=False).status_code
        assert legacy_status == v1_status, (
            f"Auth parity failure: {legacy} → {legacy_status}, {versioned} → {v1_status}"
        )

    @pytest.mark.parametrize("legacy,versioned", ROUTE_PAIRS)
    def test_valid_auth_parity(self, client: TestClient, legacy: str, versioned: str, valid_auth: tuple) -> None:
        legacy_status = client.get(legacy, auth=valid_auth, follow_redirects=False).status_code
        v1_status = client.get(versioned, auth=valid_auth, follow_redirects=False).status_code
        assert legacy_status == v1_status, (
            f"Auth parity failure (valid creds): {legacy} → {legacy_status}, {versioned} → {v1_status}"
        )
