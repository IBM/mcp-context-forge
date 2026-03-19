# -*- coding: utf-8 -*-
"""Tests for metrics maintenance router."""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.utils.verify_credentials import require_admin_auth


def test_metrics_config_includes_delete_raw_after_rollup_hours(app):
    """Test config endpoint includes delete_raw_after_rollup_hours."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    response = client.get("/api/metrics/config")

    assert response.status_code == 200
    payload = response.json()
    assert "rollup" in payload
    assert "delete_raw_after_rollup_hours" in payload["rollup"]

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_config_includes_all_settings(app):
    """Test config endpoint returns all expected settings."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    response = client.get("/api/metrics/config")

    assert response.status_code == 200
    payload = response.json()
    assert "cleanup" in payload
    assert "rollup" in payload
    # Check cleanup keys
    assert "enabled" in payload["cleanup"]
    assert "retention_days" in payload["cleanup"]
    assert "interval_hours" in payload["cleanup"]
    assert "batch_size" in payload["cleanup"]
    # Check rollup keys
    assert "enabled" in payload["rollup"]
    assert "interval_hours" in payload["rollup"]
    assert "retention_days" in payload["rollup"]
    assert "late_data_hours" in payload["rollup"]
    assert "delete_raw_after_rollup" in payload["rollup"]

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_cleanup_disabled(app):
    """Test cleanup endpoint returns 400 when disabled."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    with patch("mcpgateway.routers.metrics_maintenance.settings") as mock_settings:
        mock_settings.metrics_cleanup_enabled = False

        response = client.post("/api/metrics/cleanup", json={})

        assert response.status_code == 400
        assert "disabled" in response.json()["detail"].lower()

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_cleanup_all_tables(app):
    """Test cleanup endpoint cleans all tables when enabled."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    with patch("mcpgateway.routers.metrics_maintenance.settings") as mock_settings:
        mock_settings.metrics_cleanup_enabled = True

        # Create mock result for cleanup_all
        mock_table_result = MagicMock()
        mock_table_result.table_name = "tool_metric"
        mock_table_result.deleted_count = 10
        mock_table_result.remaining_count = 100
        mock_table_result.cutoff_date = datetime.now(timezone.utc)
        mock_table_result.duration_seconds = 0.5
        mock_table_result.error = None

        mock_summary = MagicMock()
        mock_summary.total_deleted = 10
        mock_summary.tables = {"tool_metric": mock_table_result}
        mock_summary.duration_seconds = 0.5
        mock_summary.started_at = datetime.now(timezone.utc)
        mock_summary.completed_at = datetime.now(timezone.utc)

        with patch("mcpgateway.services.metrics_cleanup_service.get_metrics_cleanup_service") as mock_get_service:
            mock_service = MagicMock()
            mock_service.cleanup_all = AsyncMock(return_value=mock_summary)
            mock_get_service.return_value = mock_service

            response = client.post("/api/metrics/cleanup", json={})

            assert response.status_code == 200
            data = response.json()
            assert data["total_deleted"] == 10
            assert "tool_metric" in data["tables"]

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_cleanup_specific_table(app):
    """Test cleanup endpoint for specific table."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    with patch("mcpgateway.routers.metrics_maintenance.settings") as mock_settings:
        mock_settings.metrics_cleanup_enabled = True

        mock_result = MagicMock()
        mock_result.table_name = "prompt_metric"
        mock_result.deleted_count = 5
        mock_result.remaining_count = 50
        mock_result.cutoff_date = datetime.now(timezone.utc)
        mock_result.duration_seconds = 0.3
        mock_result.error = None

        with patch("mcpgateway.services.metrics_cleanup_service.get_metrics_cleanup_service") as mock_get_service:
            mock_service = MagicMock()
            mock_service.cleanup_table = AsyncMock(return_value=mock_result)
            mock_get_service.return_value = mock_service

            response = client.post("/api/metrics/cleanup", json={"table_type": "prompt"})

            assert response.status_code == 200
            data = response.json()
            assert data["total_deleted"] == 5
            assert "prompt_metric" in data["tables"]

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_cleanup_invalid_table_type(app):
    """Test cleanup endpoint returns 400 for invalid table type."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    with patch("mcpgateway.routers.metrics_maintenance.settings") as mock_settings:
        mock_settings.metrics_cleanup_enabled = True

        with patch("mcpgateway.services.metrics_cleanup_service.get_metrics_cleanup_service") as mock_get_service:
            mock_service = MagicMock()
            mock_service.cleanup_table = AsyncMock(side_effect=ValueError("Invalid table type"))
            mock_get_service.return_value = mock_service

            response = client.post("/api/metrics/cleanup", json={"table_type": "invalid"})

            assert response.status_code == 400
            assert "Invalid table type" in response.json()["detail"]

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_rollup_disabled(app):
    """Test rollup endpoint returns 400 when disabled."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    with patch("mcpgateway.routers.metrics_maintenance.settings") as mock_settings:
        mock_settings.metrics_rollup_enabled = False

        response = client.post("/api/metrics/rollup", json={})

        assert response.status_code == 400
        assert "disabled" in response.json()["detail"].lower()

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_rollup_success(app):
    """Test rollup endpoint success."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    with patch("mcpgateway.routers.metrics_maintenance.settings") as mock_settings:
        mock_settings.metrics_rollup_enabled = True

        mock_table_result = MagicMock()
        mock_table_result.table_name = "tool_metric"
        mock_table_result.hours_processed = 24
        mock_table_result.records_aggregated = 100
        mock_table_result.rollups_created = 24
        mock_table_result.rollups_updated = 0
        mock_table_result.raw_deleted = 100
        mock_table_result.duration_seconds = 1.0
        mock_table_result.error = None

        mock_summary = MagicMock()
        mock_summary.total_hours_processed = 24
        mock_summary.total_records_aggregated = 100
        mock_summary.total_rollups_created = 24
        mock_summary.total_rollups_updated = 0
        mock_summary.tables = {"tool_metric": mock_table_result}
        mock_summary.duration_seconds = 1.0
        mock_summary.started_at = datetime.now(timezone.utc)
        mock_summary.completed_at = datetime.now(timezone.utc)

        with patch("mcpgateway.services.metrics_rollup_service.get_metrics_rollup_service") as mock_get_service:
            mock_service = MagicMock()
            mock_service.rollup_all = AsyncMock(return_value=mock_summary)
            mock_get_service.return_value = mock_service

            response = client.post("/api/metrics/rollup", json={"hours_back": 24})

            assert response.status_code == 200
            data = response.json()
            assert data["total_hours_processed"] == 24
            assert data["total_records_aggregated"] == 100
            assert "tool_metric" in data["tables"]

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_stats_disabled(app):
    """Test stats endpoint when services are disabled."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    with patch("mcpgateway.routers.metrics_maintenance.settings") as mock_settings:
        mock_settings.metrics_cleanup_enabled = False
        mock_settings.metrics_rollup_enabled = False

        response = client.get("/api/metrics/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["cleanup"]["enabled"] is False
        assert data["rollup"]["enabled"] is False
        assert data["table_sizes"] == {}

    app.dependency_overrides.pop(require_admin_auth, None)


def test_metrics_stats_enabled(app):
    """Test stats endpoint when services are enabled."""
    app.dependency_overrides[require_admin_auth] = lambda: "test_admin"
    client = TestClient(app)

    with patch("mcpgateway.routers.metrics_maintenance.settings") as mock_settings:
        mock_settings.metrics_cleanup_enabled = True
        mock_settings.metrics_rollup_enabled = True

        with (
            patch("mcpgateway.services.metrics_cleanup_service.get_metrics_cleanup_service") as mock_cleanup,
            patch("mcpgateway.services.metrics_rollup_service.get_metrics_rollup_service") as mock_rollup,
        ):
            mock_cleanup_service = MagicMock()
            mock_cleanup_service.get_stats.return_value = {"enabled": True, "last_run": None}
            mock_cleanup_service.get_table_sizes = AsyncMock(return_value={"tool_metric": 100})
            mock_cleanup.return_value = mock_cleanup_service

            mock_rollup_service = MagicMock()
            mock_rollup_service.get_stats.return_value = {"enabled": True, "last_run": None}
            mock_rollup.return_value = mock_rollup_service

            response = client.get("/api/metrics/stats")

            assert response.status_code == 200
            data = response.json()
            assert data["cleanup"]["enabled"] is True
            assert data["rollup"]["enabled"] is True
            assert data["table_sizes"]["tool_metric"] == 100

    app.dependency_overrides.pop(require_admin_auth, None)
