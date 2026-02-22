# -*- coding: utf-8 -*-
"""Tests for policy_decisions_api router."""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.routers.policy_decisions_api import health_router, router, PolicyDecisionResponse


def _make_app(auth_override=True):
    """Create a test app with the policy decisions router.

    If auth_override is True, admin auth is bypassed.
    If False, the original dependency is kept (requests should fail with 401).
    """
    app = FastAPI()
    if auth_override:
        # Override the admin auth dependency to allow all requests
        from mcpgateway.utils.verify_credentials import require_admin_auth  # pylint: disable=import-outside-toplevel

        app.dependency_overrides[require_admin_auth] = lambda: {"email": "admin@test.com", "is_admin": True}
    app.include_router(router)
    app.include_router(health_router)
    return app


class FakeDecision:
    """Minimal stand-in for PolicyDecision ORM object."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "test-id")
        self.timestamp = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
        self.request_id = kwargs.get("request_id")
        self.gateway_node = kwargs.get("gateway_node")
        self.subject_type = kwargs.get("subject_type", "user")
        self.subject_id = kwargs.get("subject_id", "user@example.com")
        self.subject_email = kwargs.get("subject_email", "user@example.com")
        self.subject_roles = kwargs.get("subject_roles", [])
        self.subject_teams = kwargs.get("subject_teams", [])
        self.action = kwargs.get("action", "tools.invoke")
        self.resource_type = kwargs.get("resource_type", "tool")
        self.resource_id = kwargs.get("resource_id", "tool-1")
        self.resource_server = kwargs.get("resource_server")
        self.decision = kwargs.get("decision", "allow")
        self.reason = kwargs.get("reason")
        self.matching_policies = kwargs.get("matching_policies", [])
        self.duration_ms = kwargs.get("duration_ms")
        self.severity = kwargs.get("severity", "info")
        self.risk_score = kwargs.get("risk_score", 0)
        self.anomaly_detected = kwargs.get("anomaly_detected", False)


def test_endpoints_require_auth():
    """Endpoints return 401/403 without authentication when auth is not overridden."""
    # Create app WITHOUT auth override — the real require_admin_auth dependency will reject
    # We patch require_admin_auth to raise 401
    from mcpgateway.utils.verify_credentials import require_admin_auth  # pylint: disable=import-outside-toplevel
    from fastapi import HTTPException, status  # pylint: disable=import-outside-toplevel

    app = FastAPI()

    async def _reject():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    app.dependency_overrides[require_admin_auth] = _reject
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/api/policy-decisions/decisions").status_code == 401
    assert client.get("/api/policy-decisions/statistics").status_code == 401
    assert client.post("/api/policy-decisions/decisions/query", json={}).status_code == 401


@patch("mcpgateway.routers.policy_decisions_api.policy_decision_service")
def test_get_decisions_returns_list(mock_svc):
    """GET /decisions returns list of decisions."""
    mock_svc.query_decisions.return_value = [FakeDecision(), FakeDecision(decision="deny")]

    app = _make_app()
    client = TestClient(app)

    response = client.get("/api/policy-decisions/decisions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["decision"] == "allow"
    assert data[1]["decision"] == "deny"


@patch("mcpgateway.routers.policy_decisions_api.policy_decision_service")
def test_post_query_filters(mock_svc):
    """POST /decisions/query passes filters to service."""
    mock_svc.query_decisions.return_value = [FakeDecision(decision="deny")]

    app = _make_app()
    client = TestClient(app)

    response = client.post(
        "/api/policy-decisions/decisions/query",
        json={"decision": "deny", "limit": 10},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1

    # Verify the service was called with the filter params
    call_kwargs = mock_svc.query_decisions.call_args[1]
    assert call_kwargs["decision"] == "deny"
    assert call_kwargs["limit"] == 10


@patch("mcpgateway.routers.policy_decisions_api.policy_decision_service")
def test_get_statistics_returns_structure(mock_svc):
    """GET /statistics returns stats structure."""
    mock_svc.get_statistics.return_value = {
        "total_decisions": 42,
        "allowed": 40,
        "denied": 2,
        "avg_duration_ms": 1.5,
        "time_range": {"start": None, "end": None},
    }

    app = _make_app()
    client = TestClient(app)

    response = client.get("/api/policy-decisions/statistics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_decisions"] == 42
    assert data["allowed"] == 40
    assert data["denied"] == 2


@patch("mcpgateway.routers.policy_decisions_api.settings")
def test_health_check_no_auth(mock_settings):
    """GET /health works without any auth — health_router has no auth dependency."""
    mock_settings.policy_audit_enabled = True

    # Only include health_router (no auth dependency), NOT the admin router
    app = FastAPI()
    app.include_router(health_router)
    client = TestClient(app)

    response = client.get("/api/policy-decisions/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "policy-decision-logging"


@patch("mcpgateway.routers.policy_decisions_api.policy_decision_service")
def test_get_decisions_error_returns_500(mock_svc):
    """GET /decisions returns 500 when service raises."""
    mock_svc.query_decisions.side_effect = RuntimeError("db error")
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/policy-decisions/decisions")
    assert response.status_code == 500


@patch("mcpgateway.routers.policy_decisions_api.policy_decision_service")
def test_post_query_error_returns_500(mock_svc):
    """POST /decisions/query returns 500 when service raises."""
    mock_svc.query_decisions.side_effect = RuntimeError("db error")
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/policy-decisions/decisions/query", json={})
    assert response.status_code == 500


@patch("mcpgateway.routers.policy_decisions_api.policy_decision_service")
def test_get_statistics_error_returns_500(mock_svc):
    """GET /statistics returns 500 when service raises."""
    mock_svc.get_statistics.side_effect = RuntimeError("db error")
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/policy-decisions/statistics")
    assert response.status_code == 500
