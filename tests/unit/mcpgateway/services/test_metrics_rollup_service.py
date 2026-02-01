# -*- coding: utf-8 -*-
"""Tests for the metrics rollup service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

# Third-Party
import pytest

# First-Party
from mcpgateway.services import metrics_rollup_service
from mcpgateway.services.metrics_rollup_service import (
    get_metrics_rollup_service,
    HourlyAggregation,
    MetricsRollupService,
    RollupResult,
    RollupSummary,
)


class TestMetricsRollupService:
    """Tests for MetricsRollupService."""

    def test_init_defaults(self):
        """Test service initialization with defaults."""
        service = MetricsRollupService()

        assert service.enabled is True
        assert service.rollup_interval_hours == 1
        assert service.delete_raw_after_rollup is True
        assert service.delete_raw_after_rollup_hours == 1

    def test_init_custom_values(self):
        """Test service initialization with custom values."""
        service = MetricsRollupService(
            rollup_interval_hours=6,
            enabled=False,
            delete_raw_after_rollup=True,
            delete_raw_after_rollup_hours=14,
        )

        assert service.enabled is False
        assert service.rollup_interval_hours == 6
        assert service.delete_raw_after_rollup is True
        assert service.delete_raw_after_rollup_hours == 14

    def test_get_stats(self):
        """Test getting service statistics."""
        service = MetricsRollupService(rollup_interval_hours=4)
        stats = service.get_stats()

        assert "enabled" in stats
        assert "rollup_interval_hours" in stats
        assert stats["rollup_interval_hours"] == 4
        assert stats["total_rollups"] == 0
        assert stats["rollup_runs"] == 0

    def test_pause_and_resume(self):
        service = MetricsRollupService()
        service.pause(reason="maintenance")
        assert service._pause_event.is_set()
        assert service._pause_reason == "maintenance"
        assert service._pause_count == 1

        service.pause()
        assert service._pause_count == 2

        service.resume()
        assert service._pause_event.is_set()
        assert service._pause_count == 1

        service.resume()
        assert service._pause_count == 0
        assert service._pause_reason is None
        assert not service._pause_event.is_set()

    def test_pause_during_context(self):
        service = MetricsRollupService()
        with service.pause_during("upgrade"):
            assert service._pause_event.is_set()
            assert service._pause_reason == "upgrade"
        assert service._pause_reason is None
        assert not service._pause_event.is_set()

    @pytest.mark.asyncio
    async def test_start_disabled(self):
        service = MetricsRollupService(enabled=False)
        await service.start()
        assert service._rollup_task is None


class TestHourlyAggregation:
    """Tests for HourlyAggregation dataclass."""

    def test_hourly_aggregation_creation(self):
        """Test creating an HourlyAggregation."""
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        agg = HourlyAggregation(
            entity_id="test-id",
            entity_name="test-tool",
            hour_start=now,
            total_count=100,
            success_count=95,
            failure_count=5,
            min_response_time=0.01,
            max_response_time=1.5,
            avg_response_time=0.25,
            p50_response_time=0.2,
            p95_response_time=0.8,
            p99_response_time=1.2,
        )

        assert agg.entity_id == "test-id"
        assert agg.entity_name == "test-tool"
        assert agg.total_count == 100
        assert agg.success_count == 95
        assert agg.failure_count == 5
        assert agg.avg_response_time == 0.25

    def test_hourly_aggregation_a2a(self):
        """Test creating an HourlyAggregation for A2A agents."""
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        agg = HourlyAggregation(
            entity_id="agent-id",
            entity_name="test-agent",
            hour_start=now,
            total_count=50,
            success_count=48,
            failure_count=2,
            min_response_time=0.05,
            max_response_time=2.0,
            avg_response_time=0.5,
            p50_response_time=0.4,
            p95_response_time=1.5,
            p99_response_time=1.8,
            interaction_type="invoke",
        )

        assert agg.interaction_type == "invoke"


class TestRollupResult:
    """Tests for RollupResult dataclass."""

    def test_rollup_result_creation(self):
        """Test creating a RollupResult."""
        result = RollupResult(
            table_name="tool_metrics",
            hours_processed=24,
            records_aggregated=1000,
            rollups_created=50,
            rollups_updated=10,
            raw_deleted=0,
            duration_seconds=2.5,
        )

        assert result.table_name == "tool_metrics"
        assert result.hours_processed == 24
        assert result.records_aggregated == 1000
        assert result.rollups_created == 50
        assert result.error is None

    def test_rollup_result_with_error(self):
        """Test creating a RollupResult with an error."""
        result = RollupResult(
            table_name="resource_metrics",
            hours_processed=0,
            records_aggregated=0,
            rollups_created=0,
            rollups_updated=0,
            raw_deleted=0,
            duration_seconds=0.1,
            error="Database error",
        )

        assert result.error == "Database error"


class TestRollupSummary:
    """Tests for RollupSummary dataclass."""

    def test_rollup_summary_creation(self):
        """Test creating a RollupSummary."""
        now = datetime.now(timezone.utc)
        result = RollupResult(
            table_name="tool_metrics",
            hours_processed=24,
            records_aggregated=1000,
            rollups_created=50,
            rollups_updated=10,
            raw_deleted=0,
            duration_seconds=2.5,
        )

        summary = RollupSummary(
            total_hours_processed=24,
            total_records_aggregated=1000,
            total_rollups_created=50,
            total_rollups_updated=10,
            tables={"tool_metrics": result},
            duration_seconds=3.0,
            started_at=now,
            completed_at=now + timedelta(seconds=3),
        )

        assert summary.total_hours_processed == 24
        assert summary.total_rollups_created == 50
        assert summary.total_rollups_updated == 10
        assert "tool_metrics" in summary.tables


class TestPercentileCalculation:
    """Tests for percentile calculation."""

    def test_percentile_empty(self):
        """Test percentile calculation with empty data."""
        service = MetricsRollupService()
        result = service._percentile([], 50)
        assert result == 0.0

    def test_percentile_single_value(self):
        """Test percentile calculation with single value."""
        service = MetricsRollupService()
        result = service._percentile([5.0], 50)
        assert result == 5.0

    def test_percentile_multiple_values(self):
        """Test percentile calculation with multiple values."""
        service = MetricsRollupService()
        data = sorted([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])

        p50 = service._percentile(data, 50)
        assert 5.0 <= p50 <= 6.0

        p95 = service._percentile(data, 95)
        assert p95 >= 9.0

        p99 = service._percentile(data, 99)
        assert p99 >= 9.5


class TestBackfillDetection:
    """Tests for backfill detection logic."""

    def test_detect_backfill_no_metrics(self, monkeypatch):
        service = MetricsRollupService()

        class _Result:
            def scalar(self):
                return None

        db = type("DB", (), {"execute": lambda _self, _stmt: _Result()})()

        @contextmanager
        def fake_session():
            yield db

        monkeypatch.setattr(metrics_rollup_service, "fresh_db_session", fake_session)
        assert service._detect_backfill_hours() == 24

    def test_detect_backfill_clamped_to_retention(self, monkeypatch):
        service = MetricsRollupService()
        now = datetime.now(timezone.utc)
        earliest = now - timedelta(hours=200)

        def _result(value):
            class _Result:
                def scalar(self):
                    return value

            return _Result()

        db = type("DB", (), {"execute": lambda _self, _stmt: _result(earliest)})()

        @contextmanager
        def fake_session():
            yield db

        monkeypatch.setattr(metrics_rollup_service, "fresh_db_session", fake_session)
        monkeypatch.setattr(metrics_rollup_service.settings, "metrics_retention_days", 2)
        assert service._detect_backfill_hours() == 48

    def test_detect_backfill_error_returns_default(self, monkeypatch):
        service = MetricsRollupService()

        @contextmanager
        def fake_session():
            raise RuntimeError("boom")

        monkeypatch.setattr(metrics_rollup_service, "fresh_db_session", fake_session)
        assert service._detect_backfill_hours() == 24


class TestRollupLoop:
    """Tests for rollup loop behavior."""

    @pytest.mark.asyncio
    async def test_rollup_loop_runs_once(self, monkeypatch):
        service = MetricsRollupService()
        summary = RollupSummary(
            total_hours_processed=1,
            total_records_aggregated=1,
            total_rollups_created=1,
            total_rollups_updated=0,
            tables={},
            duration_seconds=0.1,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )

        async def fake_rollup_all(hours_back, force_reprocess=False):
            return summary

        async def fake_wait_for(awaitable, timeout):
            service._shutdown_event.set()
            return await awaitable

        monkeypatch.setattr(service, "rollup_all", fake_rollup_all)
        monkeypatch.setattr(service, "_detect_backfill_hours", lambda: 1)
        monkeypatch.setattr(metrics_rollup_service.asyncio, "wait_for", fake_wait_for)

        await service._rollup_loop()
        assert service._rollup_runs == 1
        assert service._total_rollups == 1

    @pytest.mark.asyncio
    async def test_rollup_loop_paused(self, monkeypatch):
        service = MetricsRollupService()
        service._pause_event.set()
        service._pause_reason = "maintenance"

        async def fake_wait_for(awaitable, timeout):
            service._shutdown_event.set()
            return await awaitable

        monkeypatch.setattr(metrics_rollup_service.asyncio, "wait_for", fake_wait_for)

        await service._rollup_loop()
        assert service._rollup_runs == 0


class TestGetMetricsRollupService:
    """Tests for the singleton getter."""

    def test_singleton_returns_same_instance(self):
        """Test that the singleton returns the same instance."""
        # Reset singleton for test
        import mcpgateway.services.metrics_rollup_service as module

        module._metrics_rollup_service = None

        service1 = get_metrics_rollup_service()
        service2 = get_metrics_rollup_service()

        assert service1 is service2


@pytest.fixture
def rollup_service():
    """Create a rollup service for testing."""
    return MetricsRollupService(
        rollup_interval_hours=1,
        enabled=True,
        delete_raw_after_rollup=False,
    )


class TestStartShutdown:
    """Tests for start and shutdown methods."""

    @pytest.mark.asyncio
    async def test_start_when_disabled(self, rollup_service):
        """Test that start does nothing when disabled."""
        rollup_service.enabled = False
        await rollup_service.start()

        assert rollup_service._rollup_task is None

    @pytest.mark.asyncio
    async def test_start_when_enabled(self, rollup_service):
        """Test that start creates a background task."""
        await rollup_service.start()

        assert rollup_service._rollup_task is not None
        assert not rollup_service._rollup_task.done()

        # Clean up
        await rollup_service.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown(self, rollup_service):
        """Test proper shutdown."""
        await rollup_service.start()
        await rollup_service.shutdown()

        assert rollup_service._shutdown_event.is_set()
