# -*- coding: utf-8 -*-
"""Tests for observability router SQL functions.

Tests SQL-based and Python-based computation paths for query performance metrics.
"""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.routers.observability import (
    _get_query_performance_postgresql,
    _get_query_performance_python,
)


@pytest.fixture
def allow_permission(monkeypatch):
    """Allow permission checks in require_permission wrapper."""

    class DummyPermissionService:
        def __init__(self, _db):
            pass

        async def check_permission(self, **_kwargs):
            return True

    monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService", DummyPermissionService)
    monkeypatch.setattr("mcpgateway.plugins.framework.get_plugin_manager", lambda: None)



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

    @pytest.mark.asyncio
    async def test_routes_to_postgresql(self):
        """Test that PostgreSQL path is selected for PostgreSQL dialect."""
        # First-Party
        from mcpgateway.config import settings

        mock_db = MagicMock()

        # Mock the session's bind dialect
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.get_bind.return_value = mock_bind

        with patch("mcpgateway.routers.observability._get_query_performance_postgresql") as mock_pg:
            with patch("mcpgateway.routers.observability._get_query_performance_python") as mock_py:
                mock_pg.return_value = {"total_traces": 100}

                from mcpgateway.routers.observability import get_query_performance

                result = await get_query_performance(
                    hours=1,
                    db=mock_db,
                    _user={"email": settings.platform_admin_email, "db": mock_db},
                )

                # Verify PostgreSQL path was called
                mock_pg.assert_called_once()
                mock_py.assert_not_called()
                assert result["total_traces"] == 100

    @pytest.mark.asyncio
    async def test_routes_to_python(self):
        """Test that Python path is selected for SQLite dialect."""
        # First-Party
        from mcpgateway.config import settings

        mock_db = MagicMock()

        # Mock the session's bind dialect
        mock_bind = MagicMock()
        mock_bind.dialect.name = "sqlite"
        mock_db.get_bind.return_value = mock_bind

        with patch("mcpgateway.routers.observability._get_query_performance_postgresql") as mock_pg:
            with patch("mcpgateway.routers.observability._get_query_performance_python") as mock_py:
                mock_py.return_value = {"total_traces": 50}

                from mcpgateway.routers.observability import get_query_performance

                result = await get_query_performance(
                    hours=1,
                    db=mock_db,
                    _user={"email": settings.platform_admin_email, "db": mock_db},
                )

                # Verify Python path was called
                mock_py.assert_called_once()
                mock_pg.assert_not_called()
                assert result["total_traces"] == 50


class TestObservabilityRouterEndpoints:
    """Tests for observability router endpoints."""

    def test_get_db_commit_and_close(self, monkeypatch):
        """get_db commits and closes on success."""
        from mcpgateway.routers.observability import get_db

        mock_db = MagicMock()
        monkeypatch.setattr("mcpgateway.routers.observability.SessionLocal", lambda: mock_db)

        gen = get_db()
        db = next(gen)
        assert db is mock_db

        with pytest.raises(StopIteration):
            next(gen)

        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    def test_get_db_rollback_invalidate(self, monkeypatch):
        """get_db rolls back and invalidates on error."""
        from mcpgateway.routers.observability import get_db

        mock_db = MagicMock()
        mock_db.rollback.side_effect = Exception("rollback error")
        monkeypatch.setattr("mcpgateway.routers.observability.SessionLocal", lambda: mock_db)

        gen = get_db()
        next(gen)

        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("boom"))

        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()
        mock_db.close.assert_called_once()

    def test_get_db_rollback_and_invalidate_failure_ignored(self, monkeypatch):
        """get_db suppresses invalidate failures during error cleanup."""
        from mcpgateway.routers.observability import get_db

        mock_db = MagicMock()
        mock_db.rollback.side_effect = Exception("rollback error")
        mock_db.invalidate.side_effect = Exception("invalidate error")
        monkeypatch.setattr("mcpgateway.routers.observability.SessionLocal", lambda: mock_db)

        gen = get_db()
        next(gen)

        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("boom"))

        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()
        mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_traces_returns_service_results(self, allow_permission):
        """list_traces returns query results."""
        from mcpgateway.routers.observability import list_traces

        mock_db = MagicMock()
        fake_trace = SimpleNamespace(trace_id="t1")

        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.query_traces.return_value = [fake_trace]

            result = await list_traces(db=mock_db, _user={"email": "admin", "db": mock_db})

        assert result == [fake_trace]

    @pytest.mark.asyncio
    async def test_query_traces_advanced_parses_dates(self, allow_permission):
        """query_traces_advanced parses ISO datetime strings."""
        from mcpgateway.routers.observability import query_traces_advanced

        mock_db = MagicMock()
        fake_trace = SimpleNamespace(trace_id="t1", name="n")

        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.query_traces.return_value = [fake_trace]

            result = await query_traces_advanced(
                {"start_time": "2025-01-01T00:00:00Z", "end_time": "2025-01-02T00:00:00Z"},
                db=mock_db,
                _user={"email": "admin", "db": mock_db},
            )

        assert result == [fake_trace]
        call_kwargs = mock_service.return_value.query_traces.call_args.kwargs
        assert isinstance(call_kwargs["start_time"], datetime)
        assert isinstance(call_kwargs["end_time"], datetime)

    @pytest.mark.asyncio
    async def test_query_traces_advanced_invalid_date(self, allow_permission):
        """query_traces_advanced returns 400 on invalid date."""
        from mcpgateway.routers.observability import query_traces_advanced

        with pytest.raises(HTTPException) as exc_info:
            await query_traces_advanced({"start_time": "not-a-date"}, db=MagicMock(), _user={"email": "admin", "db": MagicMock()})

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_trace_missing(self, allow_permission):
        """get_trace returns 404 when missing."""
        from mcpgateway.routers.observability import get_trace

        mock_db = MagicMock()
        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.get_trace_with_spans.return_value = None

            with pytest.raises(HTTPException) as exc_info:
                await get_trace("missing", db=mock_db, _user={"email": "admin", "db": mock_db})

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_trace_found(self, allow_permission):
        """get_trace returns trace when found."""
        from mcpgateway.routers.observability import get_trace

        mock_db = MagicMock()
        trace = {"trace_id": "t1"}
        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.get_trace_with_spans.return_value = trace

            result = await get_trace("t1", db=mock_db, _user={"email": "admin", "db": mock_db})

        assert result == trace

    @pytest.mark.asyncio
    async def test_list_spans_returns_service_results(self, allow_permission):
        """list_spans returns query results."""
        from mcpgateway.routers.observability import list_spans

        mock_db = MagicMock()
        fake_span = SimpleNamespace(span_id="s1")

        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.query_spans.return_value = [fake_span]

            result = await list_spans(db=mock_db, _user={"email": "admin", "db": mock_db})

        assert result == [fake_span]

    @pytest.mark.asyncio
    async def test_cleanup_old_traces(self, allow_permission):
        """cleanup_old_traces returns deleted count."""
        from mcpgateway.routers.observability import cleanup_old_traces

        mock_db = MagicMock()
        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.delete_old_traces.return_value = 5

            result = await cleanup_old_traces(days=3, db=mock_db, _user={"email": "admin", "db": mock_db})

        assert result["deleted"] == 5

    @pytest.mark.asyncio
    async def test_get_stats(self, allow_permission):
        """get_stats returns aggregated counts and slowest endpoints."""
        from mcpgateway.routers.observability import get_stats

        mock_db = MagicMock()

        query_total = MagicMock()
        query_total.filter.return_value.scalar.return_value = 10
        query_success = MagicMock()
        query_success.filter.return_value.scalar.return_value = 7
        query_error = MagicMock()
        query_error.filter.return_value.scalar.return_value = 3
        query_avg = MagicMock()
        query_avg.filter.return_value.scalar.return_value = 12.345
        query_slowest = MagicMock()
        query_slowest.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = [("GET /", 50.5, 2)]

        mock_db.query.side_effect = [query_total, query_success, query_error, query_avg, query_slowest]

        result = await get_stats(hours=24, db=mock_db, _user={"email": "admin", "db": mock_db})

        assert result["total_traces"] == 10
        assert result["success_count"] == 7
        assert result["error_count"] == 3
        assert result["avg_duration_ms"] == 12.35
        assert result["slowest_endpoints"][0]["name"] == "GET /"

    @pytest.mark.asyncio
    async def test_export_traces_invalid_format(self, allow_permission):
        """export_traces raises on invalid format."""
        from mcpgateway.routers.observability import export_traces

        with pytest.raises(HTTPException) as exc_info:
            await export_traces({}, format="xml", db=MagicMock(), _user={"email": "admin", "db": MagicMock()})

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_export_traces_json_csv_ndjson(self, allow_permission):
        """export_traces supports json, csv, and ndjson formats."""
        from mcpgateway.routers.observability import export_traces

        mock_db = MagicMock()
        fake_trace = SimpleNamespace(
            trace_id="t1",
            name="name",
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_time=None,
            duration_ms=100,
            status="ok",
            http_method="GET",
            http_url="/",
            http_status_code=200,
            user_email="user@example.com",
        )

        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.query_traces.return_value = [fake_trace]

            json_resp = await export_traces({}, format="json", db=mock_db, _user={"email": "admin", "db": mock_db})
            assert json_resp[0]["trace_id"] == "t1"

            csv_resp = await export_traces({}, format="csv", db=mock_db, _user={"email": "admin", "db": mock_db})
            assert csv_resp.media_type == "text/csv"
            assert b"trace_id" in csv_resp.body

            ndjson_resp = await export_traces({}, format="ndjson", db=mock_db, _user={"email": "admin", "db": mock_db})
            chunks = [chunk async for chunk in ndjson_resp.body_iterator]
            first_chunk = chunks[0]
            assert "trace_id" in (first_chunk.decode() if isinstance(first_chunk, bytes) else first_chunk)

    @pytest.mark.asyncio
    async def test_export_traces_parses_iso_start_end(self, allow_permission):
        """export_traces parses ISO datetime strings in request body."""
        from mcpgateway.routers.observability import export_traces

        mock_db = MagicMock()
        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.query_traces.return_value = []

            await export_traces(
                {"start_time": "2025-01-01T00:00:00Z", "end_time": "2025-01-02T00:00:00Z"},
                format="json",
                db=mock_db,
                _user={"email": "admin", "db": mock_db},
            )

        kwargs = mock_service.return_value.query_traces.call_args.kwargs
        assert isinstance(kwargs["start_time"], datetime)
        assert isinstance(kwargs["end_time"], datetime)

    @pytest.mark.asyncio
    async def test_export_traces_wraps_failures_in_http_400(self, allow_permission):
        """export_traces returns HTTP 400 when service query fails."""
        from mcpgateway.routers.observability import export_traces

        with patch("mcpgateway.routers.observability.ObservabilityService") as mock_service:
            mock_service.return_value.query_traces.side_effect = RuntimeError("boom")

            with pytest.raises(HTTPException) as exc_info:
                await export_traces({}, format="json", db=MagicMock(), _user={"email": "admin", "db": MagicMock()})

        assert exc_info.value.status_code == 400
        assert "Export failed:" in exc_info.value.detail
