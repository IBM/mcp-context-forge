# -*- coding: utf-8 -*-
"""Unit tests for metrics_query_service.

Tests cover:
- Retention cutoff calculation
- Current hour start calculation
- Helper merge functions
- Current hour aggregation
- Three-source merging logic
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services import metrics_query_service as mqs


def test_get_retention_cutoff_uses_hours(monkeypatch):
    monkeypatch.setattr(mqs.settings, "metrics_retention_days", 7)
    monkeypatch.setattr(mqs.settings, "metrics_delete_raw_after_rollup", True)
    monkeypatch.setattr(mqs.settings, "metrics_delete_raw_after_rollup_hours", 1)

    now = datetime.now(timezone.utc)
    cutoff = mqs.get_retention_cutoff()

    assert cutoff.minute == 0
    assert cutoff.second == 0
    assert cutoff.microsecond == 0

    delta = now - cutoff
    assert timedelta(hours=1) <= delta < timedelta(hours=2)


def test_get_retention_cutoff_uses_days_when_raw_delete_disabled(monkeypatch):
    monkeypatch.setattr(mqs.settings, "metrics_retention_days", 7)
    monkeypatch.setattr(mqs.settings, "metrics_delete_raw_after_rollup", False)

    now = datetime.now(timezone.utc)
    cutoff = mqs.get_retention_cutoff()

    delta = now - cutoff
    assert timedelta(days=7) <= delta < timedelta(days=8)


# ============================================================================
# Tests for get_current_hour_start()
# ============================================================================


def test_get_current_hour_start_returns_hour_boundary():
    """Test that get_current_hour_start returns hour-aligned timestamp."""
    result = mqs.get_current_hour_start()

    assert result.minute == 0
    assert result.second == 0
    assert result.microsecond == 0
    assert result.tzinfo == timezone.utc


def test_get_current_hour_start_is_not_future():
    """Test that current hour start is not in the future.

    Note: We call get_current_hour_start() before capturing `now` to avoid
    a race condition at hour boundaries where the hour could flip between
    the two calls, causing result > now.
    """
    result = mqs.get_current_hour_start()
    now = datetime.now(timezone.utc)

    assert result <= now


# ============================================================================
# Tests for helper merge functions
# ============================================================================


class TestMergeMin:
    """Tests for _merge_min helper function."""

    def test_both_none(self):
        assert mqs._merge_min(None, None) is None

    def test_first_none(self):
        assert mqs._merge_min(None, 5.0) == 5.0

    def test_second_none(self):
        assert mqs._merge_min(3.0, None) == 3.0

    def test_both_present_first_smaller(self):
        assert mqs._merge_min(2.0, 5.0) == 2.0

    def test_both_present_second_smaller(self):
        assert mqs._merge_min(5.0, 2.0) == 2.0

    def test_both_equal(self):
        assert mqs._merge_min(3.0, 3.0) == 3.0


class TestMergeMax:
    """Tests for _merge_max helper function."""

    def test_both_none(self):
        assert mqs._merge_max(None, None) is None

    def test_first_none(self):
        assert mqs._merge_max(None, 5.0) == 5.0

    def test_second_none(self):
        assert mqs._merge_max(3.0, None) == 3.0

    def test_both_present_first_larger(self):
        assert mqs._merge_max(5.0, 2.0) == 5.0

    def test_both_present_second_larger(self):
        assert mqs._merge_max(2.0, 5.0) == 5.0

    def test_both_equal(self):
        assert mqs._merge_max(3.0, 3.0) == 3.0


class TestMergeWeightedAvg:
    """Tests for _merge_weighted_avg helper function."""

    def test_both_zero_counts(self):
        assert mqs._merge_weighted_avg(10.0, 0, 20.0, 0) is None

    def test_first_zero_count(self):
        assert mqs._merge_weighted_avg(10.0, 0, 20.0, 5) == 20.0

    def test_second_zero_count(self):
        assert mqs._merge_weighted_avg(10.0, 5, 20.0, 0) == 10.0

    def test_both_present_equal_counts(self):
        # (10 * 5 + 20 * 5) / 10 = 150 / 10 = 15
        result = mqs._merge_weighted_avg(10.0, 5, 20.0, 5)
        assert result == pytest.approx(15.0)

    def test_both_present_unequal_counts(self):
        # (10 * 3 + 20 * 7) / 10 = (30 + 140) / 10 = 17
        result = mqs._merge_weighted_avg(10.0, 3, 20.0, 7)
        assert result == pytest.approx(17.0)

    def test_first_none_avg_with_count(self):
        # When avg is None but count > 0, treat as no contribution
        assert mqs._merge_weighted_avg(None, 5, 20.0, 5) == 20.0

    def test_second_none_avg_with_count(self):
        assert mqs._merge_weighted_avg(10.0, 5, None, 5) == 10.0

    def test_both_none_avgs(self):
        assert mqs._merge_weighted_avg(None, 5, None, 5) is None


class TestMergeLastTime:
    """Tests for _merge_last_time helper function."""

    def test_both_none(self):
        assert mqs._merge_last_time(None, None) is None

    def test_first_none(self):
        t = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        assert mqs._merge_last_time(None, t) == t

    def test_second_none(self):
        t = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        assert mqs._merge_last_time(t, None) == t

    def test_both_present_first_later(self):
        t1 = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        assert mqs._merge_last_time(t1, t2) == t1

    def test_both_present_second_later(self):
        t1 = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
        assert mqs._merge_last_time(t1, t2) == t2

    def test_both_equal(self):
        t = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        assert mqs._merge_last_time(t, t) == t


# ============================================================================
# Tests for get_current_hour_aggregation()
# ============================================================================


class TestGetCurrentHourAggregation:
    """Tests for get_current_hour_aggregation function."""

    def test_invalid_metric_type_raises(self):
        """Test that invalid metric type raises ValueError."""
        db = MagicMock()
        with pytest.raises(ValueError, match="Unknown metric type"):
            mqs.get_current_hour_aggregation(db, "invalid_type")

    def test_returns_none_when_no_data(self):
        """Test that function returns None when no current hour data exists."""
        db = MagicMock()
        # Mock execute to return a result with total=0
        mock_result = MagicMock()
        mock_result.total = 0
        db.execute.return_value.one.return_value = mock_result

        result = mqs.get_current_hour_aggregation(db, "tool")

        assert result is None

    def test_returns_aggregation_when_data_exists(self):
        """Test that function returns AggregatedMetrics when data exists."""
        db = MagicMock()
        # Mock execute to return a result with data
        mock_result = MagicMock()
        mock_result.total = 100
        mock_result.successful = 90
        mock_result.failed = 10
        mock_result.min_rt = 0.01
        mock_result.max_rt = 1.5
        mock_result.avg_rt = 0.25
        mock_result.last_time = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        db.execute.return_value.one.return_value = mock_result

        result = mqs.get_current_hour_aggregation(db, "tool")

        assert result is not None
        assert result.total_executions == 100
        assert result.successful_executions == 90
        assert result.failed_executions == 10
        assert result.failure_rate == pytest.approx(0.1)
        assert result.min_response_time == 0.01
        assert result.max_response_time == 1.5
        assert result.avg_response_time == 0.25
        assert result.raw_count == 100
        assert result.rollup_count == 0

    def test_entity_id_adds_filter_clause(self):
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.total = 0
        db.execute.return_value.one.return_value = mock_result

        # We don't assert on SQLAlchemy internals; we just cover the entity_id path.
        assert mqs.get_current_hour_aggregation(db, "tool", entity_id="tool-1") is None


# ============================================================================
# Tests for AggregatedMetrics dataclass
# ============================================================================


class TestAggregatedMetrics:
    """Tests for AggregatedMetrics dataclass."""

    def test_to_dict(self):
        """Test that to_dict returns correct dictionary."""
        metrics = mqs.AggregatedMetrics(
            total_executions=100,
            successful_executions=90,
            failed_executions=10,
            failure_rate=0.1,
            min_response_time=0.01,
            max_response_time=1.5,
            avg_response_time=0.25,
            last_execution_time=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
            raw_count=50,
            rollup_count=50,
        )

        result = metrics.to_dict()

        assert result["total_executions"] == 100
        assert result["successful_executions"] == 90
        assert result["failed_executions"] == 10
        assert result["failure_rate"] == 0.1
        assert result["min_response_time"] == 0.01
        assert result["max_response_time"] == 1.5
        assert result["avg_response_time"] == 0.25
        # raw_count and rollup_count should not be in the dict (internal only)
        assert "raw_count" not in result
        assert "rollup_count" not in result


# ============================================================================
# Tests for METRIC_MODELS mapping
# ============================================================================


class TestMetricModels:
    """Tests for METRIC_MODELS mapping."""

    def test_all_expected_types_present(self):
        """Test that all expected metric types are in METRIC_MODELS."""
        expected_types = ["tool", "resource", "prompt", "server", "a2a_agent"]
        for metric_type in expected_types:
            assert metric_type in mqs.METRIC_MODELS

    def test_each_model_has_four_elements(self):
        """Test that each model tuple has 4 elements."""
        for metric_type, model_tuple in mqs.METRIC_MODELS.items():
            assert len(model_tuple) == 4, f"{metric_type} should have 4 elements"


# ============================================================================
# Tests for aggregate_metrics_combined() three-source merge
# ============================================================================


class TestAggregateMetricsCombined:
    """Tests for aggregate_metrics_combined with three-source merging."""

    def test_invalid_metric_type_raises(self):
        """Test that invalid metric type raises ValueError."""
        db = MagicMock()
        with pytest.raises(ValueError, match="Unknown metric type"):
            mqs.aggregate_metrics_combined(db, "invalid_type")

    def test_combines_all_three_sources(self):
        """Test that metrics from rollup, completed hours, and current hour are combined.

        This test verifies the core fix: metrics are available immediately during
        benchmarks even before the hourly rollup job processes the current hour.
        """
        db = MagicMock()

        # Mock three separate query results (one for each source)
        # Query 1: Rollup data (historical)
        rollup_result = MagicMock()
        rollup_result.total = 100
        rollup_result.successful = 90
        rollup_result.failed = 10
        rollup_result.min_rt = 0.05
        rollup_result.max_rt = 2.0
        rollup_result.avg_rt = 0.5
        rollup_result.last_time = datetime(2024, 1, 14, 12, 0, tzinfo=timezone.utc)

        # Query 2: Raw completed hours
        raw_result = MagicMock()
        raw_result.total = 50
        raw_result.successful = 45
        raw_result.failed = 5
        raw_result.min_rt = 0.03
        raw_result.max_rt = 1.5
        raw_result.avg_rt = 0.3
        raw_result.last_time = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)

        # Query 3: Current hour (the key fix - this data should be included immediately)
        current_result = MagicMock()
        current_result.total = 25
        current_result.successful = 20
        current_result.failed = 5
        current_result.min_rt = 0.01  # New minimum
        current_result.max_rt = 3.0   # New maximum
        current_result.avg_rt = 0.2
        current_result.last_time = datetime(2024, 1, 15, 10, 45, tzinfo=timezone.utc)  # Most recent

        # Setup mock to return different results for each query
        db.execute.return_value.one.side_effect = [rollup_result, raw_result, current_result]

        result = mqs.aggregate_metrics_combined(db, "tool")

        # Verify totals are summed across all three sources
        assert result.total_executions == 175  # 100 + 50 + 25
        assert result.successful_executions == 155  # 90 + 45 + 20
        assert result.failed_executions == 20  # 10 + 5 + 5

        # Verify min/max pick the correct extremes
        assert result.min_response_time == 0.01  # From current hour
        assert result.max_response_time == 3.0   # From current hour

        # Verify weighted average: (0.5*100 + 0.3*50 + 0.2*25) / 175 = 70/175 = 0.4
        assert result.avg_response_time == pytest.approx(0.4)

        # Verify last_execution_time is from current hour (most recent)
        assert result.last_execution_time == datetime(2024, 1, 15, 10, 45, tzinfo=timezone.utc)

        # Verify raw_count includes both completed hours and current hour
        assert result.raw_count == 75  # 50 + 25
        assert result.rollup_count == 100

    def test_handles_empty_sources(self):
        """Test that empty sources are handled gracefully."""
        db = MagicMock()

        # All sources return no data
        empty_result = MagicMock()
        empty_result.total = 0
        empty_result.successful = 0
        empty_result.failed = 0
        empty_result.min_rt = None
        empty_result.max_rt = None
        empty_result.avg_rt = None
        empty_result.last_time = None

        db.execute.return_value.one.return_value = empty_result

        result = mqs.aggregate_metrics_combined(db, "tool")

        assert result.total_executions == 0
        assert result.successful_executions == 0
        assert result.failed_executions == 0
        assert result.failure_rate == 0.0
        assert result.min_response_time is None
        assert result.max_response_time is None
        assert result.avg_response_time is None
        assert result.last_execution_time is None

    def test_current_hour_only(self):
        """Test that current hour data is included even when other sources are empty.

        This is the critical scenario the PR fixes: during a short benchmark,
        only current hour data exists and it should be visible immediately.
        """
        db = MagicMock()

        # Rollup: empty
        rollup_result = MagicMock()
        rollup_result.total = 0
        rollup_result.successful = 0
        rollup_result.failed = 0
        rollup_result.min_rt = None
        rollup_result.max_rt = None
        rollup_result.avg_rt = None
        rollup_result.last_time = None

        # Raw completed hours: empty
        raw_result = MagicMock()
        raw_result.total = 0
        raw_result.successful = 0
        raw_result.failed = 0
        raw_result.min_rt = None
        raw_result.max_rt = None
        raw_result.avg_rt = None
        raw_result.last_time = None

        # Current hour: has data (this is what the benchmark just generated)
        current_result = MagicMock()
        current_result.total = 50
        current_result.successful = 48
        current_result.failed = 2
        current_result.min_rt = 0.01
        current_result.max_rt = 0.5
        current_result.avg_rt = 0.1
        current_result.last_time = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)

        db.execute.return_value.one.side_effect = [rollup_result, raw_result, current_result]

        result = mqs.aggregate_metrics_combined(db, "tool")

        # Current hour data should be visible immediately
        assert result.total_executions == 50
        assert result.successful_executions == 48
        assert result.failed_executions == 2
        assert result.min_response_time == 0.01
        assert result.max_response_time == 0.5
        assert result.avg_response_time == 0.1
        assert result.raw_count == 50  # All from current hour
        assert result.rollup_count == 0

    def test_combined_with_entity_id_adds_filters(self):
        db = MagicMock()

        empty_result = MagicMock()
        empty_result.total = 0
        empty_result.successful = 0
        empty_result.failed = 0
        empty_result.min_rt = None
        empty_result.max_rt = None
        empty_result.avg_rt = None
        empty_result.last_time = None

        db.execute.return_value.one.side_effect = [empty_result, empty_result, empty_result]

        result = mqs.aggregate_metrics_combined(db, "tool", entity_id="tool-1")
        assert result.total_executions == 0


class TestGetTopEntitiesCombined:
    def test_invalid_metric_type_raises(self):
        db = MagicMock()
        with pytest.raises(ValueError, match="Unknown metric type"):
            mqs.get_top_entities_combined(db, "invalid_type", entity_model=object)

    def test_include_deleted_and_failure_rate_order(self):
        """Covers include_deleted union path, failure_rate ordering, and result dict construction."""
        from mcpgateway.db import Tool

        db = MagicMock()

        row = SimpleNamespace(
            id="tool-1",
            name="Tool One",
            execution_count=10,
            successful=7,
            failed=3,
            avg_response_time=0.5,
            last_execution=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            is_deleted=True,
        )

        class _Result:
            def fetchall(self):
                return [row]

        db.execute.return_value = _Result()

        results = mqs.get_top_entities_combined(
            db=db,
            metric_type="tool",
            entity_model=Tool,
            limit=10,
            order_by="failure_rate",
            include_deleted=True,
        )

        assert results[0]["id"] == "tool-1"
        assert results[0]["is_deleted"] is True
        assert results[0]["success_rate"] == pytest.approx(70.0)

    def test_order_by_avg_response_time(self):
        """Cover the avg_response_time ordering branch."""
        from mcpgateway.db import Tool

        db = MagicMock()

        class _Result:
            def fetchall(self):
                return []

        db.execute.return_value = _Result()

        assert mqs.get_top_entities_combined(db, "tool", entity_model=Tool, order_by="avg_response_time") == []
