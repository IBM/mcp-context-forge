# -*- coding: utf-8 -*-
"""Tests for log aggregator helper functions."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

# First-Party
from mcpgateway.services.log_aggregator import LogAggregator


def test_percentile_and_error_count():
    aggregator = LogAggregator()
    values = [1.0, 2.0, 3.0, 4.0]
    assert aggregator._percentile(values, 0.5) == 2.5

    entry_ok = SimpleNamespace(level="INFO", error_details=None)
    entry_err = SimpleNamespace(level="ERROR", error_details=None)
    assert aggregator._calculate_error_count([entry_ok, entry_err]) == 1


def test_resolve_window_bounds():
    aggregator = LogAggregator()
    start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = start - timedelta(minutes=1)

    resolved_start, resolved_end = aggregator._resolve_window_bounds(start, end)
    assert resolved_end > resolved_start
