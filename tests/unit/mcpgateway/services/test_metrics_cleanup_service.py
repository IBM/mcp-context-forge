# -*- coding: utf-8 -*-
"""Tests for the metrics cleanup service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.db import (
    A2AAgentMetric,
    PromptMetric,
    ResourceMetric,
    ServerMetric,
    ToolMetric,
)
from mcpgateway.services.metrics_cleanup_service import (
    CleanupResult,
    CleanupSummary,
    MetricsCleanupService,
    delete_metrics_in_batches,
    get_metrics_cleanup_service,
    pause_rollup_during_purge,
)


class TestMetricsCleanupService:
    """Tests for MetricsCleanupService."""

    def test_init_defaults(self):
        """Test service initialization with defaults."""
        service = MetricsCleanupService()

        assert service.enabled is True
        assert service.retention_days == 7
        assert service.batch_size == 10000
        assert service.cleanup_interval_hours == 1
        assert service.delete_raw_after_rollup is True
        assert service.delete_raw_after_rollup_hours == 1

    def test_init_custom_values(self):
        """Test service initialization with custom values."""
        service = MetricsCleanupService(
            retention_days=14,
            batch_size=500,
            cleanup_interval_hours=12,
            enabled=False,
        )

        assert service.enabled is False
        assert service.retention_days == 14
        assert service.batch_size == 500
        assert service.cleanup_interval_hours == 12

    def test_get_stats(self):
        """Test getting service statistics."""
        service = MetricsCleanupService(retention_days=14, batch_size=1000)
        stats = service.get_stats()

        assert "enabled" in stats
        assert "retention_days" in stats
        assert stats["retention_days"] == 14
        assert stats["batch_size"] == 1000
        assert stats["total_cleaned"] == 0
        assert stats["cleanup_runs"] == 0


class TestCleanupResult:
    """Tests for CleanupResult dataclass."""

    def test_cleanup_result_creation(self):
        """Test creating a CleanupResult."""
        result = CleanupResult(
            table_name="tool_metrics",
            deleted_count=100,
            remaining_count=500,
            cutoff_date=datetime.now(timezone.utc),
            duration_seconds=1.5,
        )

        assert result.table_name == "tool_metrics"
        assert result.deleted_count == 100
        assert result.remaining_count == 500
        assert result.duration_seconds == 1.5
        assert result.error is None

    def test_cleanup_result_with_error(self):
        """Test creating a CleanupResult with an error."""
        result = CleanupResult(
            table_name="resource_metrics",
            deleted_count=0,
            remaining_count=-1,
            cutoff_date=datetime.now(timezone.utc),
            duration_seconds=0.1,
            error="Database error",
        )

        assert result.error == "Database error"


class TestCleanupSummary:
    """Tests for CleanupSummary dataclass."""

    def test_cleanup_summary_creation(self):
        """Test creating a CleanupSummary."""
        now = datetime.now(timezone.utc)
        result = CleanupResult(
            table_name="tool_metrics",
            deleted_count=100,
            remaining_count=500,
            cutoff_date=now,
            duration_seconds=1.5,
        )

        summary = CleanupSummary(
            total_deleted=100,
            tables={"tool_metrics": result},
            duration_seconds=2.0,
            started_at=now,
            completed_at=now + timedelta(seconds=2),
        )

        assert summary.total_deleted == 100
        assert "tool_metrics" in summary.tables
        assert summary.duration_seconds == 2.0


class TestGetMetricsCleanupService:
    """Tests for the singleton getter."""

    def test_singleton_returns_same_instance(self):
        """Test that the singleton returns the same instance."""
        # Reset singleton for test
        import mcpgateway.services.metrics_cleanup_service as module

        module._metrics_cleanup_service = None

        service1 = get_metrics_cleanup_service()
        service2 = get_metrics_cleanup_service()

        assert service1 is service2


@pytest.fixture
def db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = []
    session.execute.return_value.scalar.return_value = 0
    return session


@pytest.fixture
def cleanup_service():
    """Create a cleanup service for testing."""
    return MetricsCleanupService(
        retention_days=7,
        batch_size=100,
        cleanup_interval_hours=1,
        enabled=True,
    )


class TestCleanupTable:
    """Tests for _cleanup_table method."""

    def test_cleanup_table_empty(self, cleanup_service):
        """Test cleanup when table is empty."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch(
            "mcpgateway.services.metrics_cleanup_service.fresh_db_session",
            return_value=mock_session,
        ):
            result = cleanup_service._cleanup_table(
                ToolMetric,
                "tool_metrics",
                datetime.now(timezone.utc) - timedelta(days=7),
            )

        assert result.deleted_count == 0
        assert result.table_name == "tool_metrics"
        assert result.error is None


def test_delete_metrics_in_batches_counts_rows():
    """Test delete_metrics_in_batches aggregates row counts and stops."""
    db = MagicMock()
    # Simulate two batches then stop
    first = MagicMock()
    first.rowcount = 5
    second = MagicMock()
    second.rowcount = 2
    db.execute.side_effect = [first, second]

    deleted = delete_metrics_in_batches(db, ToolMetric, ToolMetric.id, "tool-1", batch_size=5)

    assert deleted == 7
    assert db.execute.call_count == 2


def test_delete_metrics_in_batches_handles_non_int_rowcount():
    """Test delete_metrics_in_batches handles non-int rowcount gracefully."""
    db = MagicMock()
    result = MagicMock()
    result.rowcount = None
    db.execute.return_value = result

    deleted = delete_metrics_in_batches(db, ToolMetric, ToolMetric.id, "tool-1", batch_size=5)

    assert deleted == 0


def test_pause_rollup_during_purge_calls_pause_resume(monkeypatch: pytest.MonkeyPatch):
    """Ensure rollup pause/resume is invoked when available."""
    calls = []

    class DummyRollup:
        def pause(self, reason):
            calls.append(("pause", reason))

        def resume(self):
            calls.append(("resume", None))

    monkeypatch.setattr("mcpgateway.services.metrics_cleanup_service.get_metrics_rollup_service_if_initialized", lambda: DummyRollup())

    with pause_rollup_during_purge("testing"):
        assert calls[0] == ("pause", "testing")

    assert calls[-1][0] == "resume"


@pytest.mark.asyncio
async def test_cleanup_all_retention_zero_includes_rollup(monkeypatch: pytest.MonkeyPatch):
    """Test cleanup_all uses rollup tables and retention=0 branch."""
    service = MetricsCleanupService()
    monkeypatch.setattr(service, "METRIC_TABLES", [("tool_metrics", ToolMetric, ToolMetric, "tool_id")])

    def fake_cleanup(model_class, table_name, cutoff, timestamp_column="timestamp"):
        return CleanupResult(table_name=table_name, deleted_count=1, remaining_count=0, cutoff_date=cutoff, duration_seconds=0.01)

    monkeypatch.setattr(service, "_cleanup_table", fake_cleanup)
    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("mcpgateway.services.metrics_cleanup_service.asyncio.to_thread", fake_to_thread)

    summary = await service.cleanup_all(retention_days=0, include_rollup=True)

    assert summary.total_deleted == 2
    assert "tool_metrics" in summary.tables
    assert "tool_metrics_hourly" in summary.tables


@pytest.mark.asyncio
async def test_cleanup_table_invalid_type(cleanup_service):
    """Test cleanup_table raises for unknown table types."""
    with pytest.raises(ValueError, match="Unknown table type"):
        await cleanup_service.cleanup_table("unknown")


@pytest.mark.asyncio
async def test_get_table_sizes(monkeypatch: pytest.MonkeyPatch):
    """Test get_table_sizes returns counts for raw and hourly tables."""
    service = MetricsCleanupService()
    monkeypatch.setattr(service, "METRIC_TABLES", [("tool_metrics", ToolMetric, ToolMetric, "tool_id")])

    db = MagicMock()
    db.execute.side_effect = [MagicMock(scalar=MagicMock(return_value=5)), MagicMock(scalar=MagicMock(return_value=2))]
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr("mcpgateway.services.metrics_cleanup_service.fresh_db_session", lambda: db)

    sizes = await service.get_table_sizes()

    assert sizes["tool_metrics"] == 5
    assert sizes["tool_metrics_hourly"] == 2


class TestStartShutdown:
    """Tests for start and shutdown methods."""

    @pytest.mark.asyncio
    async def test_start_when_disabled(self, cleanup_service):
        """Test that start does nothing when disabled."""
        cleanup_service.enabled = False
        await cleanup_service.start()

        assert cleanup_service._cleanup_task is None

    @pytest.mark.asyncio
    async def test_start_when_enabled(self, cleanup_service):
        """Test that start creates a background task."""
        await cleanup_service.start()

        assert cleanup_service._cleanup_task is not None
        assert not cleanup_service._cleanup_task.done()

        # Clean up
        await cleanup_service.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown(self, cleanup_service):
        """Test proper shutdown."""
        await cleanup_service.start()
        await cleanup_service.shutdown()

        assert cleanup_service._shutdown_event.is_set()
