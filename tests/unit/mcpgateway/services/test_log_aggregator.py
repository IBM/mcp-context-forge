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
