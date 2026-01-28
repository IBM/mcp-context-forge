# -*- coding: utf-8 -*-
"""Tests for log_aggregator.py.

Tests SQL-based and Python-based percentile computation paths.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.log_aggregator import _is_postgresql, LogAggregator


class TestIsPostgresql:
    """Tests for _is_postgresql helper function."""

    def test_is_postgresql_true(self):
        """Test PostgreSQL detection returns True for PostgreSQL."""
        with patch("mcpgateway.services.log_aggregator.engine") as mock_engine:
            mock_engine.dialect.name = "postgresql"
            assert _is_postgresql() is True

    def test_is_postgresql_false_sqlite(self):
        """Test PostgreSQL detection returns False for SQLite."""
        with patch("mcpgateway.services.log_aggregator.engine") as mock_engine:
            mock_engine.dialect.name = "sqlite"
            assert _is_postgresql() is False

    def test_is_postgresql_false_mysql(self):
        """Test PostgreSQL detection returns False for MySQL."""
        with patch("mcpgateway.services.log_aggregator.engine") as mock_engine:
            mock_engine.dialect.name = "mysql"
            assert _is_postgresql() is False


class TestLogAggregatorPercentiles:
    """Tests for LogAggregator percentile computation."""

    def test_percentile_empty_list(self):
        """Test percentile calculation with empty list."""
        aggregator = LogAggregator()
        result = aggregator._percentile([], 0.50)
        assert result == 0.0

    def test_percentile_single_value(self):
        """Test percentile calculation with single value."""
        aggregator = LogAggregator()
        result = aggregator._percentile([42.0], 0.50)
        assert result == 42.0

    def test_percentile_p50(self):
        """Test p50 (median) calculation."""
        aggregator = LogAggregator()
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = aggregator._percentile(values, 0.50)
        assert result == 3.0

    def test_percentile_p95(self):
        """Test p95 calculation."""
        aggregator = LogAggregator()
        values = list(range(1, 101))  # 1 to 100
        result = aggregator._percentile(values, 0.95)
        assert 94.0 <= result <= 96.0  # Approximate

    def test_percentile_p99(self):
        """Test p99 calculation."""
        aggregator = LogAggregator()
        values = list(range(1, 101))  # 1 to 100
        result = aggregator._percentile(values, 0.99)
        assert 98.0 <= result <= 100.0  # Approximate


class TestLogAggregatorInit:
    """Tests for LogAggregator initialization."""

    def test_init_with_postgresql(self):
        """Test that PostgreSQL mode is detected correctly."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=True):
            aggregator = LogAggregator()
            assert aggregator._use_sql_percentiles is True

    def test_init_with_sqlite(self):
        """Test that SQLite mode falls back to Python."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()
            assert aggregator._use_sql_percentiles is False


class TestComputeStatsPython:
    """Tests for Python-based statistics computation."""

    def test_compute_stats_python_no_results(self):
        """Test Python stats computation returns None when no data."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()
            mock_db = MagicMock()
            mock_db.execute.return_value.scalars.return_value.all.return_value = []

            result = aggregator._compute_stats_python(
                db=mock_db,
                component="test",
                operation_type="test_op",
                window_start=datetime.now(timezone.utc) - timedelta(hours=1),
                window_end=datetime.now(timezone.utc),
            )
            assert result is None

    def test_compute_stats_python_with_data(self):
        """Test Python stats computation with data."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()
            mock_db = MagicMock()

            # Create mock log entries
            mock_entries = []
            for i in range(100):
                entry = MagicMock()
                entry.duration_ms = float(i + 1)  # 1 to 100
                entry.level = "INFO"
                entry.error_details = None
                mock_entries.append(entry)

            # Add some errors
            mock_entries[50].level = "ERROR"
            mock_entries[51].error_details = {"message": "test error"}

            mock_db.execute.return_value.scalars.return_value.all.return_value = mock_entries

            result = aggregator._compute_stats_python(
                db=mock_db,
                component="test",
                operation_type="test_op",
                window_start=datetime.now(timezone.utc) - timedelta(hours=1),
                window_end=datetime.now(timezone.utc),
            )

            assert result is not None
            assert result["count"] == 100
            assert result["min_duration"] == 1.0
            assert result["max_duration"] == 100.0
            assert 49.0 <= result["avg_duration"] <= 51.0  # Approximate mean
            assert 49.0 <= result["p50"] <= 51.0  # Approximate median
            assert result["error_count"] == 2


class TestComputeStatsPostgresql:
    """Tests for PostgreSQL-based statistics computation."""

    def test_compute_stats_postgresql_no_results(self):
        """Test PostgreSQL stats computation returns None when no data."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=True):
            aggregator = LogAggregator()
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 0

            result = aggregator._compute_stats_postgresql(
                db=mock_db,
                component="test",
                operation_type="test_op",
                window_start=datetime.now(timezone.utc) - timedelta(hours=1),
                window_end=datetime.now(timezone.utc),
            )
            assert result is None

    def test_compute_stats_postgresql_with_data(self):
        """Test PostgreSQL stats computation with mocked SQL results."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=True):
            aggregator = LogAggregator()
            mock_db = MagicMock()

            # Mock the count query
            mock_db.execute.return_value.scalar.side_effect = [100, 5]  # count, error_count

            # Mock the stats query result
            mock_row = MagicMock()
            mock_row.cnt = 100
            mock_row.avg_duration = 50.5
            mock_row.min_duration = 1.0
            mock_row.max_duration = 100.0
            mock_row.p50 = 50.0
            mock_row.p95 = 95.0
            mock_row.p99 = 99.0
            mock_db.execute.return_value.fetchone.return_value = mock_row

            result = aggregator._compute_stats_postgresql(
                db=mock_db,
                component="test",
                operation_type="test_op",
                window_start=datetime.now(timezone.utc) - timedelta(hours=1),
                window_end=datetime.now(timezone.utc),
            )

            assert result is not None
            assert result["count"] == 100
            assert result["avg_duration"] == 50.5
            assert result["min_duration"] == 1.0
            assert result["max_duration"] == 100.0
            assert result["p50"] == 50.0
            assert result["p95"] == 95.0
            assert result["p99"] == 99.0
            assert result["error_count"] == 5


class TestAggregatePerformanceMetrics:
    """Tests for aggregate_performance_metrics method."""

    def test_aggregate_disabled(self):
        """Test aggregation returns None when disabled."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()
            aggregator.enabled = False

            result = aggregator.aggregate_performance_metrics(component="test", operation_type="test_op")
            assert result is None

    def test_aggregate_no_component(self):
        """Test aggregation returns None when no component provided."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()

            result = aggregator.aggregate_performance_metrics(component=None, operation_type="test_op")
            assert result is None

    def test_aggregate_routes_to_python(self):
        """Test aggregation uses Python path for SQLite."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()

            with patch.object(aggregator, "_compute_stats_python", return_value=None) as mock_python:
                with patch.object(aggregator, "_compute_stats_postgresql") as mock_pg:
                    with patch("mcpgateway.services.log_aggregator.SessionLocal") as mock_session:
                        mock_db = MagicMock()
                        mock_session.return_value = mock_db

                        aggregator.aggregate_performance_metrics(component="test", operation_type="test_op")

                        mock_python.assert_called_once()
                        mock_pg.assert_not_called()

    def test_aggregate_routes_to_postgresql(self):
        """Test aggregation uses PostgreSQL path when available."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=True):
            aggregator = LogAggregator()

            with patch.object(aggregator, "_compute_stats_python") as mock_python:
                with patch.object(aggregator, "_compute_stats_postgresql", return_value=None) as mock_pg:
                    with patch("mcpgateway.services.log_aggregator.SessionLocal") as mock_session:
                        mock_db = MagicMock()
                        mock_session.return_value = mock_db

                        aggregator.aggregate_performance_metrics(component="test", operation_type="test_op")

                        mock_pg.assert_called_once()
                        mock_python.assert_not_called()


class TestCalculateErrorCount:
    """Tests for _calculate_error_count static method."""

    def test_error_count_empty(self):
        """Test error count with empty list."""
        result = LogAggregator._calculate_error_count([])
        assert result == 0

    def test_error_count_no_errors(self):
        """Test error count with no error entries."""
        entries = []
        for _ in range(5):
            entry = MagicMock()
            entry.level = "INFO"
            entry.error_details = None
            entries.append(entry)

        result = LogAggregator._calculate_error_count(entries)
        assert result == 0

    def test_error_count_with_error_level(self):
        """Test error count with ERROR level entries."""
        entries = []
        for i in range(5):
            entry = MagicMock()
            entry.level = "ERROR" if i < 2 else "INFO"
            entry.error_details = None
            entries.append(entry)

        result = LogAggregator._calculate_error_count(entries)
        assert result == 2

    def test_error_count_with_critical_level(self):
        """Test error count with CRITICAL level entries."""
        entries = []
        entry = MagicMock()
        entry.level = "CRITICAL"
        entry.error_details = None
        entries.append(entry)

        result = LogAggregator._calculate_error_count(entries)
        assert result == 1

    def test_error_count_with_error_details(self):
        """Test error count with error_details populated."""
        entries = []
        entry = MagicMock()
        entry.level = "INFO"
        entry.error_details = {"message": "Something went wrong"}
        entries.append(entry)

        result = LogAggregator._calculate_error_count(entries)
        assert result == 1


class TestAggregateAllComponentsBatch:
    """Tests for aggregate_all_components_batch method."""

    def test_batch_returns_empty_when_disabled(self):
        """Test batch aggregation returns empty list when disabled."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()
            aggregator.enabled = False

            window_starts = [datetime.now(timezone.utc) - timedelta(hours=1)]
            result = aggregator.aggregate_all_components_batch(window_starts=window_starts, window_minutes=5)
            assert result == []

    def test_batch_returns_empty_when_no_windows(self):
        """Test batch aggregation returns empty list when no windows provided."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()

            result = aggregator.aggregate_all_components_batch(window_starts=[], window_minutes=5)
            assert result == []

    def test_batch_postgresql_path_called(self):
        """Test batch aggregation uses PostgreSQL path when available."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=True):
            aggregator = LogAggregator()

            with patch("mcpgateway.services.log_aggregator.SessionLocal") as mock_session:
                mock_db = MagicMock()
                mock_session.return_value = mock_db
                # Mock empty result set
                mock_db.execute.return_value.fetchall.return_value = []

                window_starts = [datetime.now(timezone.utc) - timedelta(hours=1)]
                result = aggregator.aggregate_all_components_batch(window_starts=window_starts, window_minutes=5)

                assert result == []
                # Verify SQL was executed (PostgreSQL path)
                mock_db.execute.assert_called()

    def test_batch_postgresql_with_data(self):
        """Test PostgreSQL batch aggregation with mocked SQL results."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=True):
            aggregator = LogAggregator()

            with patch("mcpgateway.services.log_aggregator.SessionLocal") as mock_session:
                mock_db = MagicMock()
                mock_session.return_value = mock_db

                # Create mock row result
                window_start = datetime.now(timezone.utc) - timedelta(hours=1)
                mock_row = MagicMock()
                mock_row.window_start = window_start
                mock_row.component = "test_component"
                mock_row.operation_type = "test_op"
                mock_row.cnt = 50
                mock_row.avg_duration = 25.5
                mock_row.min_duration = 1.0
                mock_row.max_duration = 100.0
                mock_row.p50 = 25.0
                mock_row.p95 = 90.0
                mock_row.p99 = 98.0
                mock_row.error_count = 2

                mock_db.execute.return_value.fetchall.return_value = [mock_row]

                # Mock _upsert_metric to return a mock metric
                mock_metric = MagicMock()
                with patch.object(aggregator, "_upsert_metric", return_value=mock_metric):
                    result = aggregator.aggregate_all_components_batch(
                        window_starts=[window_start],
                        window_minutes=5,
                        db=mock_db,
                    )

                    assert len(result) == 1
                    assert result[0] == mock_metric

    def test_batch_python_fallback_path(self):
        """Test batch aggregation uses Python fallback for non-PostgreSQL."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()

            with patch("mcpgateway.services.log_aggregator.SessionLocal") as mock_session:
                mock_db = MagicMock()
                mock_session.return_value = mock_db

                # Mock empty pairs result (no component/operation combinations)
                mock_db.execute.return_value.all.return_value = []

                window_starts = [datetime.now(timezone.utc) - timedelta(hours=1)]
                result = aggregator.aggregate_all_components_batch(window_starts=window_starts, window_minutes=5)

                assert result == []

    def test_batch_python_fallback_with_data(self):
        """Test Python fallback batch aggregation with mocked entries."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()

            mock_db = MagicMock()

            # Mock pairs query result
            mock_db.execute.return_value.all.return_value = [("test_component", "test_op")]

            # Create mock log entries with timestamps in the window
            window_start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            mock_entries = []
            for i in range(10):
                entry = MagicMock()
                entry.duration_ms = float(i + 1)  # 1 to 10
                entry.level = "INFO"
                entry.error_details = None
                entry.timestamp = window_start + timedelta(minutes=i % 5)  # Within window
                mock_entries.append(entry)

            # Add one error entry
            mock_entries[5].level = "ERROR"

            # Mock scalars().all() for entries query
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = mock_entries
            mock_db.execute.return_value.scalars.return_value = mock_scalars

            # Mock _upsert_metric
            mock_metric = MagicMock()
            upsert_called = False

            def track_upsert(**kwargs):
                nonlocal upsert_called
                upsert_called = True
                return mock_metric

            with patch.object(aggregator, "_upsert_metric", side_effect=track_upsert):
                result = aggregator.aggregate_all_components_batch(
                    window_starts=[window_start],
                    window_minutes=5,
                    db=mock_db,
                )

                # Verify upsert was called and metric was returned
                assert upsert_called, "Expected _upsert_metric to be called"
                assert len(result) == 1
                assert result[0] == mock_metric

    def test_batch_error_count_consistency_with_duration_filter(self):
        """Test that error_count only includes entries with duration_ms (consistency with per-window path)."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()

            mock_db = MagicMock()

            # Mock pairs
            mock_db.execute.return_value.all.return_value = [("comp", "op")]

            window_start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

            # Create entries - some with duration_ms, some without
            mock_entries = []

            # Entry with duration_ms and ERROR level - should be counted
            entry1 = MagicMock()
            entry1.duration_ms = 10.0
            entry1.level = "ERROR"
            entry1.error_details = None
            entry1.timestamp = window_start + timedelta(minutes=1)
            mock_entries.append(entry1)

            # Entry with duration_ms and INFO level - should NOT be counted as error
            entry2 = MagicMock()
            entry2.duration_ms = 20.0
            entry2.level = "INFO"
            entry2.error_details = None
            entry2.timestamp = window_start + timedelta(minutes=2)
            mock_entries.append(entry2)

            # Note: The query already filters for duration_ms IS NOT NULL,
            # so entries without duration_ms won't be in the result set

            mock_scalars = MagicMock()
            mock_scalars.all.return_value = mock_entries
            mock_db.execute.return_value.scalars.return_value = mock_scalars

            # Capture the upsert call to verify error_count
            upsert_calls = []

            def capture_upsert(**kwargs):
                upsert_calls.append(kwargs)
                return MagicMock()

            with patch.object(aggregator, "_upsert_metric", side_effect=capture_upsert):
                aggregator.aggregate_all_components_batch(
                    window_starts=[window_start],
                    window_minutes=5,
                    db=mock_db,
                )

            # Verify upsert was called with correct error_count
            assert len(upsert_calls) == 1, f"Expected 1 upsert call, got {len(upsert_calls)}"
            assert upsert_calls[0]["error_count"] == 1, "error_count should only count ERROR entry"
            assert upsert_calls[0]["request_count"] == 2, "request_count should include both entries"

    def test_batch_large_range_warning_logged(self):
        """Test that large aggregation ranges log a warning."""
        with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
            aggregator = LogAggregator()

            with patch("mcpgateway.services.log_aggregator.SessionLocal") as mock_session:
                mock_db = MagicMock()
                mock_session.return_value = mock_db
                mock_db.execute.return_value.all.return_value = []

                # Create window starts spanning more than 168 hours (1 week)
                now = datetime.now(timezone.utc)
                window_starts = [
                    now - timedelta(hours=200),  # Start 200 hours ago
                    now,  # End now
                ]

                with patch("mcpgateway.services.log_aggregator.logger") as mock_logger:
                    aggregator.aggregate_all_components_batch(window_starts=window_starts, window_minutes=5)

                    # Verify warning was logged for large range
                    mock_logger.warning.assert_called()
                    warning_call = mock_logger.warning.call_args
                    assert "Large aggregation range" in warning_call[0][0]


class TestAggregateCustomWindowsFallback:
    """Tests for fallback behavior in _aggregate_custom_windows."""

    def test_fallback_on_batch_exception(self):
        """Test that per-window fallback is used when batch aggregation fails."""
        from mcpgateway.routers.log_search import _aggregate_custom_windows

        mock_aggregator = MagicMock()
        mock_aggregator.aggregate_all_components_batch.side_effect = Exception("Batch failed")
        mock_db = MagicMock()

        # Mock the prerequisite queries
        mock_db.execute.return_value.first.return_value = None
        mock_db.execute.return_value.scalar.return_value = datetime.now(timezone.utc) - timedelta(hours=1)

        with patch("mcpgateway.routers.log_search.logger"):
            _aggregate_custom_windows(
                aggregator=mock_aggregator,
                window_minutes=5,
                db=mock_db,
            )

        # Verify batch was attempted
        mock_aggregator.aggregate_all_components_batch.assert_called_once()

        # Verify rollback was called
        mock_db.rollback.assert_called_once()

        # Verify fallback to per-window aggregation was used
        assert mock_aggregator.aggregate_all_components.call_count > 0

    def test_no_fallback_when_batch_succeeds(self):
        """Test that per-window fallback is not used when batch succeeds."""
        from mcpgateway.routers.log_search import _aggregate_custom_windows

        mock_aggregator = MagicMock()
        mock_aggregator.aggregate_all_components_batch.return_value = [MagicMock()]
        mock_db = MagicMock()

        # Mock the prerequisite queries
        mock_db.execute.return_value.first.return_value = None
        mock_db.execute.return_value.scalar.return_value = datetime.now(timezone.utc) - timedelta(hours=1)

        _aggregate_custom_windows(
            aggregator=mock_aggregator,
            window_minutes=5,
            db=mock_db,
        )

        # Verify batch was called
        mock_aggregator.aggregate_all_components_batch.assert_called_once()

        # Verify per-window fallback was NOT called
        mock_aggregator.aggregate_all_components.assert_not_called()

    def test_fallback_when_batch_method_missing(self):
        """Test fallback to per-window when aggregator lacks batch method."""
        from mcpgateway.routers.log_search import _aggregate_custom_windows

        mock_aggregator = MagicMock(spec=["aggregate_all_components"])  # No batch method
        mock_db = MagicMock()

        # Mock the prerequisite queries
        mock_db.execute.return_value.first.return_value = None
        mock_db.execute.return_value.scalar.return_value = datetime.now(timezone.utc) - timedelta(hours=1)

        _aggregate_custom_windows(
            aggregator=mock_aggregator,
            window_minutes=5,
            db=mock_db,
        )

        # Verify per-window aggregation was used as fallback
        assert mock_aggregator.aggregate_all_components.call_count > 0
