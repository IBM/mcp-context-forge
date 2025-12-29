# -*- coding: utf-8 -*-
"""Tests for observability router SQL functions.

Tests SQL-based and Python-based computation paths for query performance metrics.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.routers.observability import (
    _get_query_performance_postgresql,
    _get_query_performance_python,
)


class TestQueryPerformancePostgresql:
    """Tests for PostgreSQL query performance computation."""

    def test_performance_no_results(self):
        """Test PostgreSQL path returns empty stats when no data."""
        mock_db = MagicMock()

        # Mock empty result
        mock_row = MagicMock()
        mock_row.total_traces = 0
        mock_row.p50 = None
        mock_row.p75 = None
        mock_row.p90 = None
        mock_row.p95 = None
        mock_row.p99 = None
        mock_row.avg_duration = None
        mock_row.min_duration = None
        mock_row.max_duration = None

        mock_db.execute.return_value.fetchone.return_value = mock_row

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_query_performance_postgresql(mock_db, cutoff_time, hours=1)

        assert result["total_traces"] == 0
        assert result["percentiles"] == {}
        assert result["avg_duration_ms"] == 0

    def test_performance_with_data(self):
        """Test PostgreSQL path with mocked SQL results."""
        mock_db = MagicMock()

        # Mock the SQL result
        mock_row = MagicMock()
        mock_row.total_traces = 1000
        mock_row.p50 = 50.0
        mock_row.p75 = 75.0
        mock_row.p90 = 90.0
        mock_row.p95 = 95.0
        mock_row.p99 = 99.0
        mock_row.avg_duration = 55.5
        mock_row.min_duration = 5.0
        mock_row.max_duration = 500.0

        mock_db.execute.return_value.fetchone.return_value = mock_row

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_query_performance_postgresql(mock_db, cutoff_time, hours=24)

        assert result["total_traces"] == 1000
        assert result["percentiles"]["p50"] == 50.0
        assert result["percentiles"]["p75"] == 75.0
        assert result["percentiles"]["p90"] == 90.0
        assert result["percentiles"]["p95"] == 95.0
        assert result["percentiles"]["p99"] == 99.0
        assert result["avg_duration_ms"] == 55.5
        assert result["min_duration_ms"] == 5.0
        assert result["max_duration_ms"] == 500.0


class TestQueryPerformancePython:
    """Tests for Python query performance computation (SQLite fallback)."""

    def test_performance_no_results(self):
        """Test Python path returns empty stats when no data."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_query_performance_python(mock_db, cutoff_time, hours=1)

        assert result["total_traces"] == 0
        assert result["percentiles"] == {}
        assert result["avg_duration_ms"] == 0

    def test_performance_with_data(self):
        """Test Python path with mocked trace data."""
        mock_db = MagicMock()

        # Create mock traces - tuple of (duration_ms,)
        mock_traces = [(float(i + 1),) for i in range(100)]  # 1 to 100
        mock_db.query.return_value.filter.return_value.all.return_value = mock_traces

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_query_performance_python(mock_db, cutoff_time, hours=24)

        assert result["total_traces"] == 100
        assert 49 <= result["percentiles"]["p50"] <= 51  # Approximate median
        assert 94 <= result["percentiles"]["p95"] <= 96  # Approximate 95th percentile
        assert result["min_duration_ms"] == 1.0
        assert result["max_duration_ms"] == 100.0
        assert 49 <= result["avg_duration_ms"] <= 51

    def test_performance_single_value(self):
        """Test Python path with single trace."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [(42.0,)]

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_query_performance_python(mock_db, cutoff_time, hours=1)

        assert result["total_traces"] == 1
        assert result["percentiles"]["p50"] == 42.0
        assert result["percentiles"]["p99"] == 42.0
        assert result["min_duration_ms"] == 42.0
        assert result["max_duration_ms"] == 42.0


class TestQueryPerformanceRouting:
    """Tests for routing between PostgreSQL and Python paths."""

    def test_routes_to_postgresql(self):
        """Test that PostgreSQL path is selected for PostgreSQL dialect."""
        mock_db = MagicMock()

        # Mock the session's bind dialect
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.get_bind.return_value = mock_bind

        with patch("mcpgateway.routers.observability._get_query_performance_postgresql") as mock_pg:
            with patch("mcpgateway.routers.observability._get_query_performance_python") as mock_py:
                mock_pg.return_value = {"total_traces": 100}

                from mcpgateway.routers.observability import get_query_performance

                result = get_query_performance(hours=1, db=mock_db)

                # Verify PostgreSQL path was called
                mock_pg.assert_called_once()
                mock_py.assert_not_called()
                assert result["total_traces"] == 100

    def test_routes_to_python(self):
        """Test that Python path is selected for SQLite dialect."""
        mock_db = MagicMock()

        # Mock the session's bind dialect
        mock_bind = MagicMock()
        mock_bind.dialect.name = "sqlite"
        mock_db.get_bind.return_value = mock_bind

        with patch("mcpgateway.routers.observability._get_query_performance_postgresql") as mock_pg:
            with patch("mcpgateway.routers.observability._get_query_performance_python") as mock_py:
                mock_py.return_value = {"total_traces": 50}

                from mcpgateway.routers.observability import get_query_performance

                result = get_query_performance(hours=1, db=mock_db)

                # Verify Python path was called
                mock_py.assert_called_once()
                mock_pg.assert_not_called()
                assert result["total_traces"] == 50
