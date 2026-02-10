# -*- coding: utf-8 -*-
"""Tests for admin observability SQL functions.

Tests SQL-based and Python-based computation paths for:
- Latency percentiles
- Time-series metrics
- Latency heatmap
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# Local
from tests.utils.rbac_mocks import create_mock_user_context

# First-Party
from mcpgateway.admin import (
    _get_latency_heatmap_postgresql,
    _get_latency_heatmap_python,
    _get_latency_percentiles_postgresql,
    _get_latency_percentiles_python,
    _get_timeseries_metrics_postgresql,
    _get_timeseries_metrics_python,
)


class TestLatencyPercentilesPostgresql:
    """Tests for PostgreSQL latency percentiles computation."""

    def test_percentiles_no_results(self):
        """Test PostgreSQL percentiles returns empty when no data."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_percentiles_postgresql(mock_db, cutoff_time, 5)

        assert result == {"timestamps": [], "p50": [], "p90": [], "p95": [], "p99": []}

    def test_percentiles_with_data(self):
        """Test PostgreSQL percentiles with mocked SQL results."""
        mock_db = MagicMock()

        # Mock the SQL result
        mock_row = MagicMock()
        mock_row.bucket = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_row.p50 = 50.0
        mock_row.p90 = 90.0
        mock_row.p95 = 95.0
        mock_row.p99 = 99.0

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_percentiles_postgresql(mock_db, cutoff_time, 5)

        assert len(result["timestamps"]) == 1
        assert result["p50"][0] == 50.0
        assert result["p90"][0] == 90.0
        assert result["p95"][0] == 95.0
        assert result["p99"][0] == 99.0


class TestLatencyPercentilesPython:
    """Tests for Python latency percentiles computation (SQLite fallback)."""

    def test_percentiles_no_results(self):
        """Test Python percentiles returns empty when no data."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_percentiles_python(mock_db, cutoff_time, 5)

        assert result == {"timestamps": [], "p50": [], "p90": [], "p95": [], "p99": []}

    def test_percentiles_with_data(self):
        """Test Python percentiles with mocked trace data."""
        mock_db = MagicMock()

        # Create mock traces
        mock_traces = []
        base_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        for i in range(100):
            trace = MagicMock()
            trace.start_time = base_time
            trace.duration_ms = float(i + 1)  # 1 to 100
            mock_traces.append(trace)

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_traces

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_percentiles_python(mock_db, cutoff_time, 60)

        assert len(result["timestamps"]) >= 1
        assert len(result["p50"]) >= 1
        assert len(result["p95"]) >= 1


class TestTimeseriesMetricsPostgresql:
    """Tests for PostgreSQL time-series metrics computation."""

    def test_timeseries_no_results(self):
        """Test PostgreSQL timeseries returns empty when no data."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_timeseries_metrics_postgresql(mock_db, cutoff_time, 5)

        assert result == {"timestamps": [], "request_count": [], "success_count": [], "error_count": [], "error_rate": []}

    def test_timeseries_with_data(self):
        """Test PostgreSQL timeseries with mocked SQL results."""
        mock_db = MagicMock()

        # Mock the SQL result
        mock_row = MagicMock()
        mock_row.bucket = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_row.total = 100
        mock_row.success = 90
        mock_row.error = 10

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_timeseries_metrics_postgresql(mock_db, cutoff_time, 5)

        assert len(result["timestamps"]) == 1
        assert result["request_count"][0] == 100
        assert result["success_count"][0] == 90
        assert result["error_count"][0] == 10
        assert result["error_rate"][0] == 10.0


class TestTimeseriesMetricsPython:
    """Tests for Python time-series metrics computation (SQLite fallback)."""

    def test_timeseries_no_results(self):
        """Test Python timeseries returns empty when no data."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_timeseries_metrics_python(mock_db, cutoff_time, 5)

        assert result == {"timestamps": [], "request_count": [], "success_count": [], "error_count": [], "error_rate": []}

    def test_timeseries_with_data(self):
        """Test Python timeseries with mocked trace data."""
        mock_db = MagicMock()

        # Create mock traces
        mock_traces = []
        base_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        for i in range(50):
            trace = MagicMock()
            trace.start_time = base_time
            trace.status = "ok" if i % 5 != 0 else "error"
            mock_traces.append(trace)

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_traces

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_timeseries_metrics_python(mock_db, cutoff_time, 60)

        assert len(result["timestamps"]) >= 1
        assert len(result["request_count"]) >= 1


class TestLatencyHeatmapPostgresql:
    """Tests for PostgreSQL latency heatmap computation."""

    def test_heatmap_no_results(self):
        """Test PostgreSQL heatmap returns empty when no data."""
        mock_db = MagicMock()

        # First call returns stats, second returns heatmap data
        mock_stats_row = MagicMock()
        mock_stats_row.min_d = None
        mock_stats_row.max_d = None

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_stats_row
        mock_db.execute.return_value = mock_result

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_heatmap_postgresql(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert result == {"time_labels": [], "latency_labels": [], "data": []}

    def test_heatmap_with_data(self):
        """Test PostgreSQL heatmap with mocked SQL results."""
        mock_db = MagicMock()

        # Mock stats query result
        mock_stats_row = MagicMock()
        mock_stats_row.min_d = 10.0
        mock_stats_row.max_d = 100.0

        # Mock heatmap query result
        mock_heatmap_row = MagicMock()
        mock_heatmap_row.time_idx = 0
        mock_heatmap_row.latency_idx = 2
        mock_heatmap_row.cnt = 5

        stats_result = MagicMock()
        stats_result.fetchone.return_value = mock_stats_row

        heatmap_result = MagicMock()
        heatmap_result.fetchall.return_value = [mock_heatmap_row]

        mock_db.execute.side_effect = [stats_result, heatmap_result]

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_heatmap_postgresql(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert len(result["time_labels"]) == 10
        assert len(result["latency_labels"]) == 5
        assert len(result["data"]) == 5
        assert len(result["data"][0]) == 10
        # Check the populated cell
        assert result["data"][2][0] == 5


class TestLatencyHeatmapPython:
    """Tests for Python latency heatmap computation (SQLite fallback)."""

    def test_heatmap_no_results(self):
        """Test Python heatmap returns empty when no data."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _get_latency_heatmap_python(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert result == {"time_labels": [], "latency_labels": [], "data": []}

    def test_heatmap_with_data(self):
        """Test Python heatmap with mocked trace data."""
        mock_db = MagicMock()

        # Create mock traces
        mock_traces = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        for i in range(20):
            trace = MagicMock()
            trace.start_time = cutoff_time + timedelta(minutes=i * 3)
            trace.duration_ms = 10.0 + i * 5  # 10 to 105
            mock_traces.append(trace)

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_traces

        result = _get_latency_heatmap_python(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert len(result["time_labels"]) == 10
        assert len(result["latency_labels"]) == 5
        assert len(result["data"]) == 5
        assert len(result["data"][0]) == 10
        # Check that some cells are populated
        total_count = sum(sum(row) for row in result["data"])
        assert total_count == 20

    def test_heatmap_single_duration(self):
        """Test Python heatmap handles single duration value (all same)."""
        mock_db = MagicMock()

        # Create mock traces with same duration
        mock_traces = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        for i in range(10):
            trace = MagicMock()
            trace.start_time = cutoff_time + timedelta(minutes=i * 6)
            trace.duration_ms = 50.0  # All same duration
            mock_traces.append(trace)

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_traces

        result = _get_latency_heatmap_python(mock_db, cutoff_time, hours=1, time_buckets=10, latency_buckets=5)

        assert len(result["time_labels"]) == 10
        assert len(result["latency_labels"]) == 5
        # All should fall in one latency bucket
        total_count = sum(sum(row) for row in result["data"])
        assert total_count == 10




class TestToolUsageStatistics:
    """Tests for tool usage statistics with different databases."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_tool_usage_with_dialect(self, dialect):
        """Test tool usage works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.tool_name = "test_tool"
        mock_row.count = 10

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        # Import and call the function
        from mcpgateway.admin import get_tool_usage
        from fastapi import Request

        # Mock request and dependencies
        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        # This should not raise GroupingError
        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio
                result = asyncio.run(get_tool_usage(mock_request, hours=24, limit=20, _user=mock_user))

        assert "tools" in result
        assert result["tools"][0]["tool_name"] == "test_tool"


class TestToolErrorStatistics:
    """Tests for tool error statistics with different databases."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_tool_errors_with_dialect(self, dialect):
        """Test tool errors works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.tool_name = "test_tool"
        mock_row.total_count = 100
        mock_row.error_count = 5

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_tool_errors
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio
                result = asyncio.run(get_tool_errors(mock_request, hours=24, limit=20, _user=mock_user))

        assert "tools" in result
        assert result["tools"][0]["tool_name"] == "test_tool"
        assert result["tools"][0]["error_rate"] == 5.0


class TestToolChains:
    """Tests for tool chain statistics."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_tool_chains_with_dialect(self, dialect):
        """Test tool chains works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_span1 = MagicMock()
        mock_span1.trace_id = "trace1"
        mock_span1.tool_name = "tool_a"
        mock_span1.start_time = datetime.now(timezone.utc)

        mock_span2 = MagicMock()
        mock_span2.trace_id = "trace1"
        mock_span2.tool_name = "tool_b"
        mock_span2.start_time = datetime.now(timezone.utc) + timedelta(seconds=1)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [mock_span1, mock_span2]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_tool_chains
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio
                result = asyncio.run(get_tool_chains(mock_request, hours=24, limit=20, _user=mock_user))

        assert "chains" in result
        assert len(result["chains"]) > 0


class TestPromptStatistics:
    """Tests for prompt statistics with different databases."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_prompt_usage_with_dialect(self, dialect):
        """Test prompt usage works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.prompt_id = "test_prompt"
        mock_row.count = 15

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_prompt_usage
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio
                result = asyncio.run(get_prompt_usage(mock_request, hours=24, limit=20, _user=mock_user))

        assert "prompts" in result
        assert result["prompts"][0]["prompt_id"] == "test_prompt"

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_prompt_errors_with_dialect(self, dialect):
        """Test prompt errors works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.prompt_id = "test_prompt"
        mock_row.total_count = 50
        mock_row.error_count = 3

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_prompts_errors
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio
                result = asyncio.run(get_prompts_errors(hours=24, limit=20, _user=mock_user))

        assert "prompts" in result


class TestResourceStatistics:
    """Tests for resource statistics with different databases."""

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_resource_usage_with_dialect(self, dialect):
        """Test resource usage works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.resource_uri = "file:///test.txt"
        mock_row.count = 20

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_resource_usage
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio
                result = asyncio.run(get_resource_usage(mock_request, hours=24, limit=20, _user=mock_user))

        assert "resources" in result
        assert result["resources"][0]["resource_uri"] == "file:///test.txt"

    @pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
    def test_resource_errors_with_dialect(self, dialect):
        """Test resource errors works with PostgreSQL and SQLite."""
        mock_db = MagicMock()
        mock_bind = MagicMock()
        mock_bind.dialect.name = dialect
        mock_db.get_bind.return_value = mock_bind

        # Mock query chain
        mock_row = MagicMock()
        mock_row.resource_uri = "file:///test.txt"
        mock_row.total_count = 30
        mock_row.error_count = 2

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_db.query.return_value = mock_query

        from mcpgateway.admin import get_resources_errors
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_user = create_mock_user_context()
        mock_user["db"] = mock_db  # Use the same mock_db so dialect is consistent

        with patch("mcpgateway.admin.get_db", return_value=iter([mock_db])):
            with patch("mcpgateway.admin.get_current_user_with_permissions", return_value=mock_user):
                import asyncio
                result = asyncio.run(get_resources_errors(hours=24, limit=20, _user=mock_user))

        assert "resources" in result
