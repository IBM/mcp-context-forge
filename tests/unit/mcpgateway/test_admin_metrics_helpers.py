# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_metrics_helpers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for admin metrics helper functions.
"""

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


def test_get_token_spend_postgresql_results():
    db = MagicMock()
    row = SimpleNamespace(
        bucket=datetime(2025, 1, 1, tzinfo=timezone.utc),
        input_tokens=1200,
        output_tokens=800,
        cost_usd=0.0123456789,
    )
    db.execute.return_value.fetchall.return_value = [row]

    result = admin._get_token_spend_postgresql(db, datetime(2025, 1, 1, tzinfo=timezone.utc), 60)
    assert result["timestamps"] == [row.bucket.isoformat()]
    assert result["input_tokens"] == [1200]
    assert result["output_tokens"] == [800]
    # Cost rounded to 6 decimals
    assert result["cost_usd"] == [0.012346]


def test_get_token_spend_postgresql_empty():
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    result = admin._get_token_spend_postgresql(db, datetime(2025, 1, 1, tzinfo=timezone.utc), 60)
    assert result == {"timestamps": [], "input_tokens": [], "output_tokens": [], "cost_usd": []}


def test_get_token_spend_python_buckets():
    db = MagicMock()
    start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    # Two rows in the same hourly bucket, one row in the next
    rows = [
        SimpleNamespace(name="llm.tokens.input", value=1000.0, timestamp=start),
        SimpleNamespace(name="llm.tokens.output", value=500.0, timestamp=start + timedelta(minutes=5)),
        SimpleNamespace(name="llm.cost", value=0.05, timestamp=start + timedelta(minutes=10)),
        SimpleNamespace(name="llm.tokens.input", value=200.0, timestamp=start + timedelta(hours=1)),
    ]
    _mock_query(db, rows)

    result = admin._get_token_spend_python(db, start - timedelta(hours=1), 60)
    assert len(result["timestamps"]) == 2
    assert result["input_tokens"] == [1000, 200]
    assert result["output_tokens"] == [500, 0]
    assert result["cost_usd"] == [0.05, 0.0]


def test_get_token_spend_python_ignores_unrelated_names():
    # in.filter is a MagicMock so it doesn't actually filter — the Python
    # aggregation must itself route only known llm.* names into buckets and
    # silently drop anything unexpected.
    db = MagicMock()
    start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(name="llm.tokens.input", value=100.0, timestamp=start),
        SimpleNamespace(name="http.request.duration", value=42.0, timestamp=start),
    ]
    _mock_query(db, rows)

    result = admin._get_token_spend_python(db, start - timedelta(hours=1), 60)
    assert result["input_tokens"] == [100]
    assert result["output_tokens"] == [0]
    assert result["cost_usd"] == [0.0]


def test_get_token_spend_python_empty():
    db = MagicMock()
    _mock_query(db, [])
    result = admin._get_token_spend_python(db, datetime(2025, 1, 1, tzinfo=timezone.utc), 60)
    assert result == {"timestamps": [], "input_tokens": [], "output_tokens": [], "cost_usd": []}


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
