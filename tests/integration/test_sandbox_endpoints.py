# -*- coding: utf-8 -*-
"""Integration tests for sandbox API endpoints.
Location: ./tests/integration/test_sandbox_endpoints.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Hugh Hennelly

Tests the sandbox endpoints via HTTP using FastAPI's TestClient.
Verifies the full request/response cycle including routing, JSON
serialization, auth dependency overrides, and error handling.

Related to Issue #2226: Policy testing and simulation sandbox
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.routes.sandbox import SANDBOX_SERVICE_VERSION
from mcpgateway.schemas import (
    BatchSimulationResult,
    RegressionReport,
    SimulationResult,
    TestSuite,
)
from mcpgateway.services.sandbox_service import get_sandbox_service, SandboxService
from plugins.unified_pdp.pdp_models import Decision

# Local
from tests.utils.rbac_mocks import MockPermissionService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sandbox():
    """Return a fully mocked SandboxService."""
    svc = MagicMock(spec=SandboxService)
    svc.run_batch = AsyncMock()
    svc.run_regression = AsyncMock()
    svc.simulate_single = AsyncMock()
    # Suite CRUD (synchronous) - return sensible defaults
    svc.create_test_suite = MagicMock()
    svc.get_test_suite = MagicMock(return_value=None)
    svc.list_test_suites = MagicMock(return_value=[])
    return svc


def _make_simulation_result(**overrides):
    """Create a SimulationResult with sensible defaults."""
    defaults = {
        "test_case_id": "tc-1",
        "actual_decision": Decision.ALLOW,
        "expected_decision": Decision.ALLOW,
        "passed": True,
        "execution_time_ms": 15.0,
        "policy_draft_id": "draft-123",
        "reason": "All engines allowed",
    }
    defaults.update(overrides)
    return SimulationResult(**defaults)


def _make_batch_result(results=None, **overrides):
    """Create a BatchSimulationResult from a list of SimulationResults."""
    if results is None:
        results = [_make_simulation_result()]
    defaults = {
        "policy_draft_id": "draft-123",
        "total_tests": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "pass_rate": 100.0,
        "total_duration_ms": sum(r.execution_time_ms for r in results),
        "avg_duration_ms": 15.0,
        "results": results,
        "started_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return BatchSimulationResult(**defaults)


def _make_regression_report(**overrides):
    """Create a minimal RegressionReport."""
    defaults = {
        "policy_draft_id": "draft-123",
        "baseline_policy_version": "prod-v1",
        "total_decisions": 50,
        "matching_decisions": 48,
        "different_decisions": 2,
        "regression_rate": 4.0,
        "critical_regressions": 0,
        "high_regressions": 1,
        "medium_regressions": 1,
        "low_regressions": 0,
        "duration_ms": 350.0,
    }
    defaults.update(overrides)
    return RegressionReport(**defaults)


@pytest.fixture
def test_client(mock_sandbox, app):
    """FastAPI TestClient with sandbox service and auth overridden."""

    # Override auth to allow unauthenticated test requests
    async def mock_user():
        return {"email": "test@example.com", "is_admin": True}

    app.dependency_overrides[get_current_user] = mock_user
    app.dependency_overrides[get_sandbox_service] = lambda: mock_sandbox

    # Override RBAC
    # First-Party
    from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_permission_service

    async def mock_user_with_permissions():
        return {
            "email": "test@example.com",
            "is_admin": True,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
            "db": MagicMock(),
        }

    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = lambda *a, **kw: MockPermissionService(always_grant=True)

        client = TestClient(app)
        yield client

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Health & Info (no auth required)
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Integration tests for GET /api/sandbox/sandbox/health."""

    def test_health_returns_200(self, test_client):
        """Health endpoint returns 200 with expected fields."""
        response = test_client.get("/api/sandbox/sandbox/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "sandbox"
        assert data["version"] == SANDBOX_SERVICE_VERSION
        assert data["check_type"] == "liveness"


class TestInfoEndpoint:
    """Integration tests for GET /api/sandbox/sandbox/info."""

    def test_info_returns_200(self, test_client):
        """Info endpoint returns 200 with capabilities."""
        response = test_client.get("/api/sandbox/sandbox/info")
        assert response.status_code == 200

        data = response.json()
        assert "capabilities" in data
        assert "features" in data
        assert data["version"] == SANDBOX_SERVICE_VERSION


# ---------------------------------------------------------------------------
# Tests: Batch Endpoint
# ---------------------------------------------------------------------------


class TestBatchEndpoint:
    """Integration tests for POST /api/sandbox/sandbox/batch."""

    def test_batch_success(self, test_client, mock_sandbox):
        """Batch endpoint returns 200 with results on success."""
        mock_sandbox.run_batch.return_value = _make_batch_result()

        payload = {
            "policy_draft_id": "draft-123",
            "test_cases": [
                {
                    "subject": {"email": "dev@example.com", "roles": ["developer"]},
                    "action": "tools.invoke",
                    "resource": {"type": "tool", "id": "db-query"},
                    "expected_decision": "allow",
                }
            ],
        }

        response = test_client.post("/api/sandbox/sandbox/batch", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["total_tests"] == 1
        assert data["passed"] == 1
        assert "results" in data

    def test_batch_not_found(self, test_client, mock_sandbox):
        """Batch endpoint returns 404 when draft not found."""
        mock_sandbox.run_batch.side_effect = ValueError("not found")

        payload = {
            "policy_draft_id": "missing",
            "test_cases": [
                {
                    "subject": {"email": "dev@example.com", "roles": ["developer"]},
                    "action": "tools.invoke",
                    "resource": {"type": "tool", "id": "db-query"},
                    "expected_decision": "allow",
                }
            ],
        }

        response = test_client.post("/api/sandbox/sandbox/batch", json=payload)
        assert response.status_code == 404

    def test_batch_internal_error(self, test_client, mock_sandbox):
        """Batch endpoint returns 500 on unexpected errors."""
        mock_sandbox.run_batch.side_effect = RuntimeError("boom")

        payload = {
            "policy_draft_id": "draft-123",
            "test_cases": [
                {
                    "subject": {"email": "dev@example.com", "roles": ["developer"]},
                    "action": "tools.invoke",
                    "resource": {"type": "tool", "id": "db-query"},
                    "expected_decision": "allow",
                }
            ],
        }

        response = test_client.post("/api/sandbox/sandbox/batch", json=payload)
        assert response.status_code == 500

    def test_batch_missing_body(self, test_client):
        """Batch endpoint returns 422 on missing request body."""
        response = test_client.post("/api/sandbox/sandbox/batch")
        assert response.status_code == 422

    def test_batch_invalid_payload(self, test_client):
        """Batch endpoint returns 422 on invalid payload."""
        response = test_client.post(
            "/api/sandbox/sandbox/batch",
            json={"invalid": "payload"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Regression Endpoint
# ---------------------------------------------------------------------------


class TestRegressionEndpoint:
    """Integration tests for POST /api/sandbox/sandbox/regression."""

    def test_regression_success(self, test_client, mock_sandbox):
        """Regression endpoint returns 200 with report."""
        mock_sandbox.run_regression.return_value = _make_regression_report()

        payload = {
            "policy_draft_id": "draft-123",
            "baseline_policy_version": "prod-v1",
            "replay_last_days": 7,
        }

        response = test_client.post("/api/sandbox/sandbox/regression", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["total_decisions"] == 50
        assert data["regression_rate"] == 4.0

    def test_regression_not_found(self, test_client, mock_sandbox):
        """Regression endpoint returns 404 when policy not found."""
        mock_sandbox.run_regression.side_effect = ValueError("not found")

        payload = {"policy_draft_id": "missing"}

        response = test_client.post("/api/sandbox/sandbox/regression", json=payload)
        assert response.status_code == 404

    def test_regression_internal_error(self, test_client, mock_sandbox):
        """Regression endpoint returns 500 on unexpected errors."""
        mock_sandbox.run_regression.side_effect = RuntimeError("boom")

        payload = {"policy_draft_id": "draft-123"}

        response = test_client.post("/api/sandbox/sandbox/regression", json=payload)
        assert response.status_code == 500

    def test_regression_with_filters(self, test_client, mock_sandbox):
        """Regression endpoint accepts and passes filter parameters."""
        mock_sandbox.run_regression.return_value = _make_regression_report()

        payload = {
            "policy_draft_id": "draft-123",
            "filter_by_subject": "dev@example.com",
            "filter_by_action": "tools.invoke",
            "sample_size": 500,
        }

        response = test_client.post("/api/sandbox/sandbox/regression", json=payload)
        assert response.status_code == 200

        call_kwargs = mock_sandbox.run_regression.call_args[1]
        assert call_kwargs["filter_by_subject"] == "dev@example.com"
        assert call_kwargs["filter_by_action"] == "tools.invoke"
        assert call_kwargs["sample_size"] == 500

    def test_regression_default_values(self, test_client, mock_sandbox):
        """Regression endpoint uses defaults for optional fields."""
        mock_sandbox.run_regression.return_value = _make_regression_report()

        payload = {"policy_draft_id": "draft-123"}

        response = test_client.post("/api/sandbox/sandbox/regression", json=payload)
        assert response.status_code == 200

        call_kwargs = mock_sandbox.run_regression.call_args[1]
        assert call_kwargs["replay_last_days"] == 7  # default
        assert call_kwargs["sample_size"] == 1000  # default


# ---------------------------------------------------------------------------
# Tests: Test Suite Endpoints
# ---------------------------------------------------------------------------


class TestSuiteEndpoints:
    """Integration tests for test suite CRUD endpoints."""

    def test_create_suite_returns_201(self, test_client, mock_sandbox):
        """Create suite returns 201 with the suite data."""
        # First-Party
        from mcpgateway.schemas import TestCase as TC

        suite_payload = {
            "name": "dev-rbac-tests",
            "description": "RBAC tests for developers",
            "test_cases": [
                {
                    "subject": {"email": "dev@example.com", "roles": ["developer"]},
                    "action": "tools.invoke",
                    "resource": {"type": "tool", "id": "db-query"},
                    "expected_decision": "allow",
                }
            ],
            "tags": ["rbac", "developer"],
        }

        # Configure mock to return a proper TestSuite
        mock_sandbox.create_test_suite.return_value = TestSuite(
            name="dev-rbac-tests",
            description="RBAC tests for developers",
            test_cases=[
                TC(
                    subject={"email": "dev@example.com", "roles": ["developer"]},
                    action="tools.invoke",
                    resource={"type": "tool", "id": "db-query"},
                    expected_decision="allow",
                )
            ],
            tags=["rbac", "developer"],
        )

        response = test_client.post("/api/sandbox/sandbox/suites", json=suite_payload)
        assert response.status_code == 201

        data = response.json()
        assert data["name"] == "dev-rbac-tests"
        assert len(data["test_cases"]) == 1
        mock_sandbox.create_test_suite.assert_called_once()

    def test_get_suite_returns_404(self, test_client, mock_sandbox):
        """Get suite returns 404 when not found."""
        mock_sandbox.get_test_suite.return_value = None

        response = test_client.get("/api/sandbox/sandbox/suites/suite-1")
        assert response.status_code == 404

    def test_get_suite_returns_200(self, test_client, mock_sandbox):
        """Get suite returns 200 when found."""
        # First-Party
        from mcpgateway.schemas import TestCase as TC

        mock_sandbox.get_test_suite.return_value = TestSuite(
            id="suite-1",
            name="my-suite",
            test_cases=[
                TC(
                    subject={"email": "u@b.com", "roles": ["viewer"]},
                    action="resources.read",
                    resource={"type": "resource", "id": "doc-1"},
                    expected_decision="allow",
                )
            ],
        )

        response = test_client.get("/api/sandbox/sandbox/suites/suite-1")
        assert response.status_code == 200
        assert response.json()["name"] == "my-suite"

    def test_list_suites_returns_empty(self, test_client, mock_sandbox):
        """List suites returns empty list when no suites exist."""
        mock_sandbox.list_test_suites.return_value = []

        response = test_client.get("/api/sandbox/sandbox/suites")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_suites_with_tags(self, test_client, mock_sandbox):
        """List suites accepts tags query parameter."""
        mock_sandbox.list_test_suites.return_value = []

        response = test_client.get("/api/sandbox/sandbox/suites?tags=rbac,security")
        assert response.status_code == 200

        # Verify tags were parsed and passed to the service
        call_kwargs = mock_sandbox.list_test_suites.call_args[1]
        assert call_kwargs["tags"] == ["rbac", "security"]


# ---------------------------------------------------------------------------
# Tests: Error Response Format
# ---------------------------------------------------------------------------


class TestErrorResponses:
    """Test that error responses follow consistent format."""

    def test_404_has_detail(self, test_client, mock_sandbox):
        """404 errors include detail message."""
        mock_sandbox.run_batch.side_effect = ValueError("not found")

        payload = {
            "policy_draft_id": "missing",
            "test_cases": [
                {
                    "subject": {"email": "dev@example.com", "roles": ["developer"]},
                    "action": "tools.invoke",
                    "resource": {"type": "tool", "id": "db-query"},
                    "expected_decision": "allow",
                }
            ],
        }

        response = test_client.post("/api/sandbox/sandbox/batch", json=payload)
        assert response.status_code == 404
        assert "detail" in response.json()

    def test_500_has_detail(self, test_client, mock_sandbox):
        """500 errors include detail message."""
        mock_sandbox.run_batch.side_effect = RuntimeError("internal failure")

        payload = {
            "policy_draft_id": "draft-123",
            "test_cases": [
                {
                    "subject": {"email": "dev@example.com", "roles": ["developer"]},
                    "action": "tools.invoke",
                    "resource": {"type": "tool", "id": "db-query"},
                    "expected_decision": "allow",
                }
            ],
        }

        response = test_client.post("/api/sandbox/sandbox/batch", json=payload)
        assert response.status_code == 500
        assert "detail" in response.json()
