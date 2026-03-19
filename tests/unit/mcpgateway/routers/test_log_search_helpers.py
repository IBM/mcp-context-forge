# -*- coding: utf-8 -*-
"""Tests for log_search helper functions."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

# Third-Party
import pytest

# First-Party
from mcpgateway.routers import log_search


def test_align_to_window():
    dt = datetime(2025, 1, 1, 12, 7, tzinfo=timezone.utc)
    aligned = log_search._align_to_window(dt, 5)
    assert aligned.minute == 5


def test_deduplicate_metrics():
    base = datetime.now(timezone.utc)
    m1 = SimpleNamespace(component="c", operation_type="op", window_start=base, timestamp=base)
    m2 = SimpleNamespace(component="c", operation_type="op", window_start=base, timestamp=base + timedelta(seconds=5))

    deduped = log_search._deduplicate_metrics([m1, m2])
    assert deduped[0] is m2


def test_expand_component_filters():
    expanded = log_search._expand_component_filters(["gateway"])
    assert "http_gateway" in expanded


def test_aggregate_custom_windows_batch(monkeypatch: pytest.MonkeyPatch):
    class DummyAgg:
        def __init__(self):
            self.called = False

        def aggregate_all_components_batch(self, window_starts, window_minutes, db):
            self.called = True

    class DummyResult:
        def __init__(self, first=None, scalar=None):
            self._first = first
            self._scalar = scalar

        def first(self):
            return self._first

        def scalar(self):
            return self._scalar

    earliest = datetime.now(timezone.utc) - timedelta(minutes=10)

    db = SimpleNamespace()
    db_calls = []

    def execute_side_effect(*args, **kwargs):
        db_calls.append(args)
        if len(db_calls) == 1:
            return DummyResult(first=None)
        if len(db_calls) == 2:
            return DummyResult(scalar=None)
        return DummyResult(scalar=earliest)

    db.execute = execute_side_effect
    db.commit = lambda: None
    db.rollback = lambda: None

    aggregator = DummyAgg()

    log_search._aggregate_custom_windows(aggregator, window_minutes=5, db=db)

    assert aggregator.called is True
