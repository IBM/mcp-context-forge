# -*- coding: utf-8 -*-
"""Tests for admin metrics helper functions."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

# First-Party
from mcpgateway import admin


def _mock_query(db: MagicMock, rows: list) -> None:
    query = MagicMock()
    query.filter.return_value.order_by.return_value.all.return_value = rows
    db.query.return_value = query


def test_get_latency_percentiles_postgresql_results():
    db = MagicMock()
    row = SimpleNamespace(
        bucket=datetime(2025, 1, 1, tzinfo=timezone.utc),
        p50=1.234,
        p90=2.5,
        p95=None,
        p99=9.876,
    )
    db.execute.return_value.fetchall.return_value = [row]

    result = admin._get_latency_percentiles_postgresql(db, datetime(2025, 1, 1, tzinfo=timezone.utc), 60)
    assert result["timestamps"] == [row.bucket.isoformat()]
    assert result["p50"] == [1.23]
    assert result["p90"] == [2.5]
    assert result["p95"] == [0]
    assert result["p99"] == [9.88]


def test_get_latency_percentiles_postgresql_empty():
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    result = admin._get_latency_percentiles_postgresql(db, datetime(2025, 1, 1, tzinfo=timezone.utc), 60)
    assert result == {"timestamps": [], "p50": [], "p90": [], "p95": [], "p99": []}


def test_get_latency_percentiles_python_buckets():
    db = MagicMock()
    start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    traces = [
        SimpleNamespace(start_time=start, duration_ms=100.0),
        SimpleNamespace(start_time=start + timedelta(minutes=10), duration_ms=200.0),
        SimpleNamespace(start_time=datetime(2025, 1, 1, 12, 20), duration_ms=300.0),
    ]
    _mock_query(db, traces)

    result = admin._get_latency_percentiles_python(db, start - timedelta(hours=1), 60)
    assert len(result["timestamps"]) == 1
    assert result["p50"][0] >= 100.0
    assert result["p99"][0] >= result["p50"][0]


def test_get_timeseries_metrics_postgresql_results():
    db = MagicMock()
    row = SimpleNamespace(
        bucket=datetime(2025, 1, 1, tzinfo=timezone.utc),
        total=4,
        success=3,
        error=1,
    )
    db.execute.return_value.fetchall.return_value = [row]

    result = admin._get_timeseries_metrics_postgresql(db, datetime(2025, 1, 1, tzinfo=timezone.utc), 60)
    assert result["request_count"] == [4]
    assert result["error_count"] == [1]
    assert result["error_rate"] == [25.0]


def test_get_timeseries_metrics_python_buckets():
    db = MagicMock()
    start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    traces = [
        SimpleNamespace(start_time=start, status="ok"),
        SimpleNamespace(start_time=start + timedelta(minutes=5), status="error"),
        SimpleNamespace(start_time=datetime(2025, 1, 1, 12, 10), status="ok"),
    ]
    _mock_query(db, traces)

    result = admin._get_timeseries_metrics_python(db, start - timedelta(hours=1), 60)
    assert result["request_count"] == [3]
    assert result["success_count"] == [2]
    assert result["error_count"] == [1]


def test_get_latency_heatmap_postgresql_shapes():
    db = MagicMock()
    stats_result = MagicMock()
    stats_result.fetchone.return_value = SimpleNamespace(min_d=10.0, max_d=10.0)
    rows_result = MagicMock()
    rows_result.fetchall.return_value = [SimpleNamespace(time_idx=0, latency_idx=0, cnt=2)]
    db.execute.side_effect = [stats_result, rows_result]

    result = admin._get_latency_heatmap_postgresql(db, datetime(2025, 1, 1, tzinfo=timezone.utc), hours=1, time_buckets=2, latency_buckets=2)
    assert len(result["data"]) == 2
    assert len(result["data"][0]) == 2
    assert result["data"][0][0] == 2


def test_get_latency_heatmap_python_shapes():
    db = MagicMock()
    start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    traces = [
        SimpleNamespace(start_time=start, duration_ms=100.0),
        SimpleNamespace(start_time=start + timedelta(minutes=30), duration_ms=200.0),
    ]
    _mock_query(db, traces)

    result = admin._get_latency_heatmap_python(db, start - timedelta(hours=1), hours=1, time_buckets=2, latency_buckets=2)
    assert len(result["data"]) == 2
    assert len(result["data"][0]) == 2
