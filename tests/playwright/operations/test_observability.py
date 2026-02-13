# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Observability & Metrics E2E Tests.

Tests health endpoints, metrics, and observability endpoints.
Observability endpoints may be disabled in test env (gracefully skipped).
"""

# Future
from __future__ import annotations

# Standard
import logging

# Third-Party
from playwright.sync_api import APIRequestContext
import pytest

logger = logging.getLogger(__name__)


def _observability_available(admin_api: APIRequestContext) -> bool:
    """Check if observability endpoints are enabled."""
    resp = admin_api.get("/observability/stats?hours=1")
    return resp.status != 404


class TestHealthEndpoints:
    """Test public health and readiness endpoints."""

    def test_health_check(self, admin_api: APIRequestContext):
        """Health endpoint returns status."""
        resp = admin_api.get("/health")
        assert resp.status == 200
        data = resp.json()
        assert data["status"] in ("healthy", "unhealthy")

    def test_readiness_check(self, admin_api: APIRequestContext):
        """Readiness endpoint returns status."""
        resp = admin_api.get("/ready")
        assert resp.status == 200
        data = resp.json()
        assert data["status"] in ("ready", "not ready")

    def test_security_health(self, admin_api: APIRequestContext):
        """Security health endpoint returns score and checks."""
        resp = admin_api.get("/health/security")
        assert resp.status == 200
        data = resp.json()
        assert "status" in data
        assert "score" in data or "checks" in data


class TestMetrics:
    """Test metrics endpoints."""

    def test_get_metrics(self, admin_api: APIRequestContext):
        """Admin can retrieve aggregated metrics."""
        resp = admin_api.get("/metrics")
        assert resp.status == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_non_admin_cannot_get_metrics(self, non_admin_api: APIRequestContext):
        """Non-admin user is denied metrics access."""
        resp = non_admin_api.get("/metrics")
        assert resp.status in (401, 403), f"Non-admin metrics should be denied, got {resp.status}"


class TestObservability:
    """Test observability endpoints (may be disabled)."""

    @pytest.fixture(autouse=True)
    def _skip_if_unavailable(self, admin_api: APIRequestContext):
        if not _observability_available(admin_api):
            pytest.skip("Observability not enabled in test environment")

    def test_get_stats(self, admin_api: APIRequestContext):
        """Admin can retrieve observability stats."""
        resp = admin_api.get("/observability/stats?hours=1")
        assert resp.status == 200
        data = resp.json()
        assert "total_traces" in data or isinstance(data, dict)

    def test_list_traces(self, admin_api: APIRequestContext):
        """Admin can list traces."""
        resp = admin_api.get("/observability/traces?limit=5")
        assert resp.status == 200

    def test_query_performance(self, admin_api: APIRequestContext):
        """Admin can query performance analytics."""
        resp = admin_api.get("/observability/analytics/query-performance?hours=1")
        assert resp.status == 200
