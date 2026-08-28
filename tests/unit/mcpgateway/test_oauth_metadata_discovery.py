# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_oauth_metadata_discovery.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

API tests for secure OAuth issuer metadata discovery.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import _safe_oauth_issuer_for_audit, app
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.services.dcr_service import DcrError, DcrService


@pytest.fixture
def allow_gateway_create(monkeypatch):
    """Allow the route's gateway-create permission check."""
    permission_service = MagicMock()
    permission_service.check_permission = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda _db: permission_service)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
    app.dependency_overrides[get_current_user_with_permissions] = lambda: {"email": "operator@example.com"}
    yield
    app.dependency_overrides.pop(get_current_user_with_permissions, None)


def test_discover_metadata_returns_form_safe_values(monkeypatch, allow_gateway_create):
    """Successful discovery exposes only metadata needed for form autofill."""
    discover = AsyncMock(
        return_value={
            "issuer": "https://issuer.example.com",
            "authorization_endpoint": "https://issuer.example.com/authorize",
            "token_endpoint": "https://issuer.example.com/token",
            "registration_endpoint": "https://issuer.example.com/register",
            "scopes_supported": ["openid", "profile"],
        }
    )
    audit = MagicMock()
    monkeypatch.setattr(DcrService, "discover_public_metadata", discover)
    monkeypatch.setattr("mcpgateway.main.get_audit_trail_service", lambda: audit)

    response = TestClient(app).post("/v1/gateways/discover-metadata", json={"issuer_url": "https://issuer.example.com"})

    assert response.status_code == 200
    assert response.json() == {
        "discovered": True,
        "authorizationUrl": "https://issuer.example.com/authorize",
        "tokenUrl": "https://issuer.example.com/token",
        "registrationEndpoint": "https://issuer.example.com/register",
        "scopesSupported": ["openid", "profile"],
        "error": None,
        "errorCode": None,
    }
    discover.assert_awaited_once_with("https://issuer.example.com")
    assert audit.log_action.call_args.kwargs["details"] == {"outcome": "success", "error_code": None}


def test_discover_metadata_returns_safe_nonblocking_failure(monkeypatch, allow_gateway_create):
    """Blocked issuer errors do not expose raw outbound-validation details."""
    audit = MagicMock()
    monkeypatch.setattr(DcrService, "discover_public_metadata", AsyncMock(side_effect=DcrError("loopback host", code="blocked")))
    monkeypatch.setattr("mcpgateway.main.get_audit_trail_service", lambda: audit)

    response = TestClient(app).post("/v1/gateways/discover-metadata", json={"issuer_url": "https://localhost.example.com"})

    assert response.status_code == 200
    assert response.json() == {
        "discovered": False,
        "authorizationUrl": None,
        "tokenUrl": None,
        "registrationEndpoint": None,
        "scopesSupported": [],
        "error": "This issuer URL is blocked by the outbound security policy.",
        "errorCode": "blocked",
    }
    assert audit.log_action.call_args.kwargs["details"] == {"outcome": "failure", "error_code": "blocked"}


def test_discover_metadata_requires_gateway_create_permission(monkeypatch):
    """Caller lacking gateway creation permission cannot use the discovery oracle."""
    permission_service = MagicMock()
    permission_service.check_permission = AsyncMock(return_value=False)
    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", lambda _db: permission_service)
    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))
    app.dependency_overrides[get_current_user_with_permissions] = lambda: {"email": "viewer@example.com"}
    try:
        response = TestClient(app).post("/v1/gateways/discover-metadata", json={"issuer_url": "https://issuer.example.com"})
    finally:
        app.dependency_overrides.pop(get_current_user_with_permissions, None)

    assert response.status_code == 403


def test_discover_metadata_requires_authentication():
    """Unauthenticated callers cannot use the outbound discovery endpoint."""
    response = TestClient(app).post("/v1/gateways/discover-metadata", json={"issuer_url": "https://issuer.example.com"})

    assert response.status_code == 401


@pytest.mark.parametrize("issuer", ["not-a-url", "https://issuer.example.com:invalid"])
def test_discover_metadata_rejects_malformed_issuer_url(issuer, allow_gateway_create):
    """Malformed input returns FastAPI validation error, never a discovery result."""
    response = TestClient(app).post("/v1/gateways/discover-metadata", json={"issuer_url": issuer})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "issuer",
    [
        "https://127.0.0.1",
        "https://169.254.1.1",
        "https://169.254.169.254",
    ],
)
def test_discover_metadata_blocks_ssrf_targets(issuer, allow_gateway_create):
    """Real outbound policy blocks loopback, link-local, and cloud metadata IPs."""
    response = TestClient(app).post("/v1/gateways/discover-metadata", json={"issuer_url": issuer})

    assert response.status_code == 200
    assert response.json()["errorCode"] == "blocked"


@pytest.mark.parametrize("issuer", ["not-a-url", "https://issuer.example.com:invalid"])
def test_safe_oauth_issuer_for_audit_rejects_malformed_issuer(issuer):
    """Audit records never retain malformed issuer input."""
    assert _safe_oauth_issuer_for_audit(issuer) == "invalid-issuer"
