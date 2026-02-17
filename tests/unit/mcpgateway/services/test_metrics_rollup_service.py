# -*- coding: utf-8 -*-
"""Tests for the metrics rollup service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# First-Party
from mcpgateway.services import metrics_rollup_service
from mcpgateway.services.metrics_rollup_service import (
    get_metrics_rollup_service,
    get_metrics_rollup_service_if_initialized,
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

        assert service.enabled is False
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

    @pytest.mark.asyncio
    async def test_rollup_loop_timeout_triggers_second_cycle_uses_late_data_hours(self, monkeypatch):
        """Cover interval timeout (normal rollup) and late data hours path."""
        service = MetricsRollupService()

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(metrics_rollup_service.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(metrics_rollup_service.settings, "metrics_rollup_late_data_hours", 3, raising=False)

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

        hours_back_seen = []

        async def fake_rollup_all(hours_back, force_reprocess=False):
            hours_back_seen.append(hours_back)
            if len(hours_back_seen) == 2:
                service._shutdown_event.set()
            return summary

        async def fake_wait_for(awaitable, timeout=None):
            # Simulate interval timeout (no shutdown requested).
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError()

        monkeypatch.setattr(service, "rollup_all", fake_rollup_all)
        monkeypatch.setattr(service, "_detect_backfill_hours", lambda: 1)
        monkeypatch.setattr(metrics_rollup_service.asyncio, "wait_for", fake_wait_for)

        await service._rollup_loop()
        assert hours_back_seen == [1, 3]

    @pytest.mark.asyncio
    async def test_rollup_loop_pause_times_out_then_exits(self, monkeypatch):
        """Cover pause branch timeout handling."""
        service = MetricsRollupService()
        service._pause_event.set()
        service._pause_reason = "maintenance"

        calls = {"n": 0}

        async def fake_wait_for(awaitable, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                if hasattr(awaitable, "close"):
                    awaitable.close()
                raise asyncio.TimeoutError()
            service._shutdown_event.set()
            return await awaitable

        monkeypatch.setattr(metrics_rollup_service.asyncio, "wait_for", fake_wait_for)

        await service._rollup_loop()
        assert service._rollup_runs == 0

    @pytest.mark.asyncio
    async def test_rollup_loop_logs_when_backfill_large(self, monkeypatch):
        service = MetricsRollupService()

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(metrics_rollup_service.asyncio, "to_thread", fake_to_thread)

        summary = RollupSummary(
            total_hours_processed=1,
            total_records_aggregated=0,
            total_rollups_created=0,
            total_rollups_updated=0,
            tables={},
            duration_seconds=0.1,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )

        async def fake_rollup_all(hours_back, force_reprocess=False):
            service._shutdown_event.set()
            return summary

        monkeypatch.setattr(service, "rollup_all", fake_rollup_all)
        monkeypatch.setattr(service, "_detect_backfill_hours", lambda: 25)

        info = MagicMock()
        monkeypatch.setattr(metrics_rollup_service.logger, "info", info)

        await service._rollup_loop()
        assert any("Backfill detected" in str(call.args[0]) for call in info.call_args_list)

    @pytest.mark.asyncio
    async def test_rollup_loop_error_sleeps_and_continues(self, monkeypatch):
        service = MetricsRollupService()

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(metrics_rollup_service.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(service, "_detect_backfill_hours", lambda: 1)

        async def fake_rollup_all(hours_back, force_reprocess=False):
            raise RuntimeError("boom")

        async def fake_sleep(_secs):
            service._shutdown_event.set()

        monkeypatch.setattr(service, "rollup_all", fake_rollup_all)
        monkeypatch.setattr(metrics_rollup_service.asyncio, "sleep", fake_sleep)

        await service._rollup_loop()


class TestRollupAll:
    """Tests for rollup_all aggregation."""

    @pytest.mark.asyncio
    async def test_rollup_all_aggregates_table_results(self, monkeypatch):
        service = MetricsRollupService()

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        def fake_rollup_table(*_args, **_kwargs):
            return RollupResult(
                table_name="tool_metrics",
                hours_processed=1,
                records_aggregated=5,
                rollups_created=2,
                rollups_updated=1,
                raw_deleted=0,
                duration_seconds=0.01,
            )

        monkeypatch.setattr(metrics_rollup_service.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(service, "_rollup_table", fake_rollup_table)
        service.METRIC_TABLES = [("tool_metrics", MagicMock(), MagicMock(), MagicMock(), "tool_id", "name")]

        summary = await service.rollup_all(hours_back=1)

        assert summary.total_hours_processed == 1
        assert summary.total_records_aggregated == 5
        assert summary.total_rollups_created == 2
        assert summary.total_rollups_updated == 1


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

    def test_get_metrics_rollup_service_if_initialized(self):
        import mcpgateway.services.metrics_rollup_service as module

        module._metrics_rollup_service = None
        assert get_metrics_rollup_service_if_initialized() is None

        service = get_metrics_rollup_service()
        assert get_metrics_rollup_service_if_initialized() is service


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


class TestRollupInternals:
    """Tests for internal rollup helpers."""

    def test_delete_raw_metrics_returns_rowcount(self):
        service = MetricsRollupService()
        mock_db = MagicMock()
        mock_db.execute.return_value.rowcount = 5

        class _Timestamp:
            def __ge__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

        raw_model = MagicMock()
        raw_model.timestamp = _Timestamp()

        class _Delete:
            def where(self, *_args, **_kwargs):
                return self

        with patch.object(metrics_rollup_service, "delete", lambda _model: _Delete()):
            with patch.object(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock()):
                deleted = service._delete_raw_metrics(
                    mock_db,
                    raw_model,
                    datetime.now(timezone.utc) - timedelta(hours=1),
                    datetime.now(timezone.utc),
                )

        assert deleted == 5

    def test_rollup_table_processes_raw_metrics(self, monkeypatch):
        service = MetricsRollupService(delete_raw_after_rollup=True, delete_raw_after_rollup_hours=0)
        service.delete_raw_after_rollup_hours = 0

        start_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        end_hour = start_hour + timedelta(hours=1)

        agg = HourlyAggregation(
            entity_id="tool-1",
            entity_name="Tool",
            hour_start=start_hour,
            total_count=3,
            success_count=3,
            failure_count=0,
            min_response_time=0.1,
            max_response_time=0.3,
            avg_response_time=0.2,
            p50_response_time=0.2,
            p95_response_time=0.3,
            p99_response_time=0.3,
        )

        class _CountResult:
            def scalar(self):
                return 1

        class _FakeDB:
            def __init__(self):
                self.commit = MagicMock()

            def execute(self, _stmt):
                return _CountResult()

        @contextmanager
        def fake_session():
            yield _FakeDB()

        class _Select:
            def select_from(self, *_args, **_kwargs):
                return self

            def where(self, *_args, **_kwargs):
                return self

        class _Timestamp:
            def __ge__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

        monkeypatch.setattr(metrics_rollup_service, "select", lambda *_args, **_kwargs: _Select())
        monkeypatch.setattr(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(metrics_rollup_service, "fresh_db_session", fake_session)
        monkeypatch.setattr(service, "_aggregate_hour", lambda *args, **kwargs: [agg])
        monkeypatch.setattr(service, "_upsert_rollup", lambda *args, **kwargs: (1, 0))
        monkeypatch.setattr(service, "_delete_raw_metrics", lambda *args, **kwargs: 2)

        raw_model = MagicMock()
        raw_model.timestamp = _Timestamp()

        result = service._rollup_table(
            "tool_metrics",
            raw_model,
            MagicMock(),
            MagicMock(),
            "tool_id",
            "name",
            start_hour,
            end_hour,
            False,
        )

        assert result.hours_processed == 1
        assert result.records_aggregated == 3
        assert result.rollups_created == 1
        assert result.raw_deleted == 2

    def test_upsert_rollup_sqlite_path(self, monkeypatch):
        service = MetricsRollupService()

        class DummyHourly:
            hour_start = MagicMock()
            interaction_type = MagicMock()
            tool_id = MagicMock()
            tool_name = MagicMock()

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        class FakeInsert:
            def __init__(self):
                self.excluded = {}

            def values(self, **kwargs):
                self.excluded = {key: f"excluded-{key}" for key in kwargs}
                return self

            def on_conflict_do_update(self, index_elements, set_):
                return self

        monkeypatch.setattr(metrics_rollup_service, "sqlite_insert", lambda _model: FakeInsert())

        mock_db = MagicMock()
        mock_db.bind.dialect.name = "sqlite"

        agg = HourlyAggregation(
            entity_id="tool-1",
            entity_name="Tool",
            hour_start=datetime.now(timezone.utc),
            total_count=1,
            success_count=1,
            failure_count=0,
            min_response_time=0.1,
            max_response_time=0.1,
            avg_response_time=0.1,
            p50_response_time=0.1,
            p95_response_time=0.1,
            p99_response_time=0.1,
        )

        created, updated = service._upsert_rollup(mock_db, DummyHourly, "tool_id", agg, is_a2a=False)

        assert (created, updated) == (0, 1)
        mock_db.execute.assert_called()

    def test_aggregate_hour_postgresql_a2a(self, monkeypatch):
        service = MetricsRollupService()
        service._is_postgresql = True
        monkeypatch.setattr(metrics_rollup_service.settings, "use_postgresdb_percentiles", True, raising=False)
        monkeypatch.setattr(metrics_rollup_service.settings, "yield_batch_size", 1, raising=False)

        class FakeExpr:
            def within_group(self, *_args, **_kwargs):
                return self

            def label(self, _name):
                return self

        class FakeFunc:
            def __getattr__(self, _name):
                def _fn(*_args, **_kwargs):
                    return FakeExpr()

                return _fn

        class DummyCol:
            def label(self, _name):
                return self

            def is_(self, _other):
                return MagicMock()

            def __ge__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

            def __eq__(self, _other):
                return MagicMock()

        class RawModel:
            __name__ = "RawModel"
            timestamp = DummyCol()
            id = DummyCol()
            is_success = DummyCol()
            response_time = DummyCol()
            interaction_type = DummyCol()
            a2a_agent_id = DummyCol()

        class EntityModel:
            __name__ = "EntityModel"
            id = DummyCol()
            name = DummyCol()

        class _Select:
            def select_from(self, *_args, **_kwargs):
                return self

            def join(self, *_args, **_kwargs):
                return self

            def where(self, *_args, **_kwargs):
                return self

            def group_by(self, *_args, **_kwargs):
                return self

        monkeypatch.setattr(metrics_rollup_service, "select", lambda *_args, **_kwargs: _Select())
        monkeypatch.setattr(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(metrics_rollup_service, "case", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(metrics_rollup_service, "func", FakeFunc())

        hour_start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        hour_end = hour_start + timedelta(hours=1)

        row = MagicMock()
        row.entity_id = "agent-1"
        row.entity_name = "Agent"
        row.total_count = 2
        row.success_count = 1
        row.min_rt = 1.0
        row.max_rt = 2.0
        row.avg_rt = 1.5
        row.p50_rt = 1.5
        row.p95_rt = 2.0
        row.p99_rt = 2.0
        row.interaction_type = "invoke"

        mock_db = MagicMock()
        mock_db.execute.return_value.yield_per.return_value = [row]

        aggregations = service._aggregate_hour(
            db=mock_db,
            raw_model=RawModel,
            entity_model=EntityModel,
            entity_id_col="a2a_agent_id",
            entity_name_col="name",
            hour_start=hour_start,
            hour_end=hour_end,
            is_a2a=True,
        )

        assert len(aggregations) == 1
        assert aggregations[0].interaction_type == "invoke"

    def test_aggregate_hour_postgresql_non_a2a(self, monkeypatch):
        """Cover the PostgreSQL percentile path when is_a2a=False."""
        service = MetricsRollupService()
        service._is_postgresql = True
        monkeypatch.setattr(metrics_rollup_service.settings, "use_postgresdb_percentiles", True, raising=False)
        monkeypatch.setattr(metrics_rollup_service.settings, "yield_batch_size", 1, raising=False)

        class FakeExpr:
            def within_group(self, *_args, **_kwargs):
                return self

            def label(self, _name):
                return self

        class FakeFunc:
            def __getattr__(self, _name):
                def _fn(*_args, **_kwargs):
                    return FakeExpr()

                return _fn

        class DummyCol:
            def label(self, _name):
                return self

            def is_(self, _other):
                return MagicMock()

            def __ge__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

            def __eq__(self, _other):
                return MagicMock()

        class RawModel:
            __name__ = "RawModel"
            timestamp = DummyCol()
            id = DummyCol()
            is_success = DummyCol()
            response_time = DummyCol()
            tool_id = DummyCol()

        class EntityModel:
            __name__ = "EntityModel"
            id = DummyCol()
            name = DummyCol()

        class _Select:
            def select_from(self, *_args, **_kwargs):
                return self

            def join(self, *_args, **_kwargs):
                return self

            def where(self, *_args, **_kwargs):
                return self

            def group_by(self, *_args, **_kwargs):
                return self

        monkeypatch.setattr(metrics_rollup_service, "select", lambda *_args, **_kwargs: _Select())
        monkeypatch.setattr(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(metrics_rollup_service, "case", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(metrics_rollup_service, "func", FakeFunc())

        hour_start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        hour_end = hour_start + timedelta(hours=1)

        row = MagicMock()
        row.entity_id = "tool-1"
        row.entity_name = "Tool"
        row.total_count = 2
        row.success_count = 1
        row.min_rt = 1.0
        row.max_rt = 2.0
        row.avg_rt = 1.5
        row.p50_rt = 1.5
        row.p95_rt = 2.0
        row.p99_rt = 2.0

        mock_db = MagicMock()
        mock_db.execute.return_value.yield_per.return_value = [row]

        aggregations = service._aggregate_hour(
            db=mock_db,
            raw_model=RawModel,
            entity_model=EntityModel,
            entity_id_col="tool_id",
            entity_name_col="name",
            hour_start=hour_start,
            hour_end=hour_end,
            is_a2a=False,
        )

        assert len(aggregations) == 1
        assert aggregations[0].interaction_type is None

    def test_aggregate_hour_python_path_empty_response_times(self, monkeypatch):
        service = MetricsRollupService()
        service._is_postgresql = False
        monkeypatch.setattr(metrics_rollup_service.settings, "use_postgresdb_percentiles", False, raising=False)
        monkeypatch.setattr(metrics_rollup_service.settings, "yield_batch_size", 1, raising=False)

        class DummyCol:
            def label(self, _name):
                return self

            def is_(self, _other):
                return MagicMock()

            def __ge__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

            def __eq__(self, _other):
                return MagicMock()

            def in_(self, _other):
                return MagicMock()

        class RawModel:
            __name__ = "RawModel"
            timestamp = DummyCol()
            id = DummyCol()
            is_success = DummyCol()
            response_time = DummyCol()
            tool_id = DummyCol()

        class EntityModel:
            __name__ = "EntityModel"
            id = DummyCol()
            name = DummyCol()

        class _Select:
            def where(self, *_args, **_kwargs):
                return self

            def group_by(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

        monkeypatch.setattr(metrics_rollup_service, "select", lambda *_args, **_kwargs: _Select())
        monkeypatch.setattr(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock())

        hour_start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        hour_end = hour_start + timedelta(hours=1)

        class AggRow:
            total_count = 2
            success_count = 1
            min_rt = 1.0
            max_rt = 2.0
            avg_rt = 1.5

            def __getitem__(self, idx):
                return "tool-1" if idx == 0 else None

        class RtRow:
            def __init__(self, entity_id, response_time):
                self._entity_id = entity_id
                self.response_time = response_time

            def __getitem__(self, idx):
                return self._entity_id if idx == 0 else None

        agg_result = MagicMock()
        agg_result.yield_per.return_value = [AggRow()]

        entity_result = [("tool-1", "Tool")]

        rt_result = MagicMock()
        rt_result.yield_per.return_value = []

        mock_db = MagicMock()
        mock_db.execute.side_effect = [agg_result, entity_result, rt_result]

        aggregations = service._aggregate_hour(
            db=mock_db,
            raw_model=RawModel,
            entity_model=EntityModel,
            entity_id_col="tool_id",
            entity_name_col="name",
            hour_start=hour_start,
            hour_end=hour_end,
            is_a2a=False,
        )

        assert len(aggregations) == 1
        assert aggregations[0].p50_response_time is None

    def test_aggregate_hour_python_path_a2a_with_response_times(self, monkeypatch):
        service = MetricsRollupService()
        service._is_postgresql = False
        monkeypatch.setattr(metrics_rollup_service.settings, "use_postgresdb_percentiles", False, raising=False)
        monkeypatch.setattr(metrics_rollup_service.settings, "yield_batch_size", 1, raising=False)

        class DummyCol:
            def label(self, _name):
                return self

            def is_(self, _other):
                return MagicMock()

            def __ge__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

            def __eq__(self, _other):
                return MagicMock()

            def in_(self, _other):
                return MagicMock()

        class RawModel:
            __name__ = "RawModel"
            timestamp = DummyCol()
            id = DummyCol()
            is_success = DummyCol()
            response_time = DummyCol()
            a2a_agent_id = DummyCol()
            interaction_type = DummyCol()

        class EntityModel:
            __name__ = "EntityModel"
            id = DummyCol()
            name = DummyCol()

        class _Select:
            def where(self, *_args, **_kwargs):
                return self

            def group_by(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

        monkeypatch.setattr(metrics_rollup_service, "select", lambda *_args, **_kwargs: _Select())
        monkeypatch.setattr(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock())

        hour_start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        hour_end = hour_start + timedelta(hours=1)

        class AggRow:
            total_count = 2
            success_count = 1
            min_rt = 1.0
            max_rt = 2.0
            avg_rt = 1.5

            def __getitem__(self, idx):
                if idx == 0:
                    return "agent-1"
                return "invoke"

        class RtRow:
            def __init__(self, response_time):
                self._rt = response_time

            def __getitem__(self, idx):
                if idx == 0:
                    return "agent-1"
                if idx == 1:
                    return "invoke"
                return self._rt

        agg_result = MagicMock()
        agg_result.yield_per.return_value = [AggRow()]

        entity_result = [("agent-1", "Agent")]

        rt_result = MagicMock()
        rt_result.yield_per.return_value = [RtRow(1.0), RtRow(2.0)]

        mock_db = MagicMock()
        mock_db.execute.side_effect = [agg_result, entity_result, rt_result]

        aggregations = service._aggregate_hour(
            db=mock_db,
            raw_model=RawModel,
            entity_model=EntityModel,
            entity_id_col="a2a_agent_id",
            entity_name_col="name",
            hour_start=hour_start,
            hour_end=hour_end,
            is_a2a=True,
        )

        assert len(aggregations) == 1
        assert aggregations[0].p50_response_time is not None

    def test_aggregate_hour_python_path_empty_agg_results_returns_empty(self, monkeypatch):
        service = MetricsRollupService()
        service._is_postgresql = False
        monkeypatch.setattr(metrics_rollup_service.settings, "use_postgresdb_percentiles", False, raising=False)
        monkeypatch.setattr(metrics_rollup_service.settings, "yield_batch_size", 1, raising=False)

        class DummyTime:
            def __ge__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

        raw_model = SimpleNamespace(
            __name__="Raw",
            timestamp=DummyTime(),
            tool_id=MagicMock(),
            response_time=MagicMock(),
            is_success=MagicMock(),
            id=MagicMock(),
        )
        entity_model = SimpleNamespace(__name__="Entity", name=MagicMock())

        class _Select:
            def where(self, *_args, **_kwargs):
                return self

            def group_by(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

        monkeypatch.setattr(metrics_rollup_service, "select", lambda *_args, **_kwargs: _Select())
        monkeypatch.setattr(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock())

        agg_result = MagicMock()
        agg_result.yield_per.return_value = []
        mock_db = MagicMock()
        mock_db.execute.return_value = agg_result

        assert (
            service._aggregate_hour(
                db=mock_db,
                raw_model=raw_model,
                entity_model=entity_model,
                entity_id_col="tool_id",
                entity_name_col="name",
                hour_start=datetime.now(timezone.utc),
                hour_end=datetime.now(timezone.utc) + timedelta(hours=1),
                is_a2a=False,
            )
            == []
        )

    def test_aggregate_hour_logs_and_raises(self, monkeypatch):
        service = MetricsRollupService()
        service._is_postgresql = False
        monkeypatch.setattr(metrics_rollup_service.settings, "use_postgresdb_percentiles", False, raising=False)

        mock_db = MagicMock()
        mock_db.execute.side_effect = RuntimeError("boom")

        class DummyTime:
            def __ge__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

        raw_model = SimpleNamespace(
            __name__="Raw",
            timestamp=DummyTime(),
            tool_id=MagicMock(),
            response_time=MagicMock(),
            is_success=MagicMock(),
            id=MagicMock(),
        )
        entity_model = SimpleNamespace(__name__="Entity", name=MagicMock())

        monkeypatch.setattr(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock())
        monkeypatch.setattr(
            metrics_rollup_service,
            "select",
            lambda *_args, **_kwargs: SimpleNamespace(where=lambda *_a, **_k: SimpleNamespace(group_by=lambda *_b, **_k2: SimpleNamespace(order_by=lambda *_c, **_k3: SimpleNamespace()))),
        )
        monkeypatch.setattr(
            metrics_rollup_service,
            "func",
            SimpleNamespace(
                count=lambda *_a, **_k: MagicMock(), sum=lambda *_a, **_k: MagicMock(), min=lambda *_a, **_k: MagicMock(), max=lambda *_a, **_k: MagicMock(), avg=lambda *_a, **_k: MagicMock()
            ),
        )
        monkeypatch.setattr(metrics_rollup_service, "case", lambda *_a, **_k: MagicMock())

        with patch.object(metrics_rollup_service.logger, "exception") as mock_logger:
            with pytest.raises(RuntimeError):
                service._aggregate_hour(
                    db=mock_db,
                    raw_model=raw_model,
                    entity_model=entity_model,
                    entity_id_col="tool_id",
                    entity_name_col="name",
                    hour_start=datetime.now(timezone.utc),
                    hour_end=datetime.now(timezone.utc) + timedelta(hours=1),
                    is_a2a=False,
                )

            mock_logger.assert_called_once()

    def test_upsert_rollup_postgresql_path(self, monkeypatch):
        service = MetricsRollupService()

        class DummyHourly:
            hour_start = MagicMock()
            interaction_type = MagicMock()
            a2a_agent_id = MagicMock()
            agent_name = MagicMock()

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        class FakeInsert:
            def __init__(self):
                self.excluded = {}

            def values(self, **kwargs):
                self.excluded = {key: f"excluded-{key}" for key in kwargs}
                return self

            def on_conflict_do_update(self, index_elements, set_):
                return self

        monkeypatch.setattr(metrics_rollup_service, "pg_insert", lambda _model: FakeInsert())

        mock_db = MagicMock()
        mock_db.bind.dialect.name = "postgresql"

        agg = HourlyAggregation(
            entity_id="agent-1",
            entity_name="Agent",
            hour_start=datetime.now(timezone.utc),
            total_count=1,
            success_count=1,
            failure_count=0,
            min_response_time=0.1,
            max_response_time=0.1,
            avg_response_time=0.1,
            p50_response_time=0.1,
            p95_response_time=0.1,
            p99_response_time=0.1,
            interaction_type="invoke",
        )

        created, updated = service._upsert_rollup(mock_db, DummyHourly, "a2a_agent_id", agg, is_a2a=True)

        assert (created, updated) == (0, 1)
        mock_db.execute.assert_called()

    def test_upsert_rollup_fallback_paths(self):
        service = MetricsRollupService()

        class DummyHourly:
            hour_start = MagicMock()
            interaction_type = MagicMock()
            tool_id = MagicMock()
            tool_name = MagicMock()

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        agg = HourlyAggregation(
            entity_id="tool-1",
            entity_name="Tool",
            hour_start=datetime.now(timezone.utc),
            total_count=1,
            success_count=1,
            failure_count=0,
            min_response_time=0.1,
            max_response_time=0.1,
            avg_response_time=0.1,
            p50_response_time=0.1,
            p95_response_time=0.1,
            p99_response_time=0.1,
        )

        mock_db = MagicMock()
        mock_db.bind.dialect.name = "oracle"

        savepoint = MagicMock()
        mock_db.begin_nested.return_value = savepoint

        class _Select:
            def where(self, *_args, **_kwargs):
                return self

        with patch.object(metrics_rollup_service, "select", lambda *_args, **_kwargs: _Select()):
            with patch.object(metrics_rollup_service, "and_", lambda *_args, **_kwargs: MagicMock()):
                created, updated = service._upsert_rollup(mock_db, DummyHourly, "tool_id", agg, is_a2a=False)
                assert (created, updated) == (1, 0)

                mock_db.add.side_effect = IntegrityError("statement", {}, Exception("integrity"))
                existing = MagicMock()
                mock_db.execute.return_value.scalar_one.return_value = existing

                created, updated = service._upsert_rollup(mock_db, DummyHourly, "tool_id", agg, is_a2a=False)
                assert (created, updated) == (0, 1)
                assert existing.total_count == 1

    def test_upsert_rollup_fallback_paths_a2a_adds_interaction_type_filter(self):
        service = MetricsRollupService()

        class _Col:
            def __init__(self, ret):
                self._ret = ret

            def __eq__(self, _other):
                return self._ret

        sentinel = object()

        class DummyHourly:
            hour_start = MagicMock()
            interaction_type = _Col(sentinel)
            a2a_agent_id = MagicMock()
            agent_name = MagicMock()

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        agg = HourlyAggregation(
            entity_id="agent-1",
            entity_name="Agent",
            hour_start=datetime.now(timezone.utc),
            total_count=1,
            success_count=1,
            failure_count=0,
            min_response_time=0.1,
            max_response_time=0.1,
            avg_response_time=0.1,
            p50_response_time=0.1,
            p95_response_time=0.1,
            p99_response_time=0.1,
            interaction_type="invoke",
        )

        mock_db = MagicMock()
        mock_db.bind.dialect.name = "oracle"
        savepoint = MagicMock()
        mock_db.begin_nested.return_value = savepoint

        mock_db.add.side_effect = IntegrityError("statement", {}, Exception("integrity"))
        existing = MagicMock()
        mock_db.execute.return_value.scalar_one.return_value = existing

        seen = {"args": ()}

        def _fake_and(*args):  # noqa: ANN001
            seen["args"] = args
            return MagicMock()

        class _Select:
            def where(self, *_args, **_kwargs):
                return self

        with patch.object(metrics_rollup_service, "select", lambda *_args, **_kwargs: _Select()):
            with patch.object(metrics_rollup_service, "and_", _fake_and):
                created, updated = service._upsert_rollup(mock_db, DummyHourly, "a2a_agent_id", agg, is_a2a=True)

        assert (created, updated) == (0, 1)
        assert sentinel in seen["args"]

    def test_upsert_rollup_sqlalchemy_error(self):
        service = MetricsRollupService()

        class DummyHourly:
            hour_start = MagicMock()
            interaction_type = MagicMock()
            tool_id = MagicMock()
            tool_name = MagicMock()

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        agg = HourlyAggregation(
            entity_id="tool-1",
            entity_name="Tool",
            hour_start=datetime.now(timezone.utc),
            total_count=1,
            success_count=1,
            failure_count=0,
            min_response_time=0.1,
            max_response_time=0.1,
            avg_response_time=0.1,
            p50_response_time=0.1,
            p95_response_time=0.1,
            p99_response_time=0.1,
        )

        mock_db = MagicMock()
        mock_db.bind.dialect.name = "oracle"
        mock_db.add.side_effect = SQLAlchemyError("boom")

        with pytest.raises(SQLAlchemyError):
            service._upsert_rollup(mock_db, DummyHourly, "tool_id", agg, is_a2a=False)
