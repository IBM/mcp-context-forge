# -*- coding: utf-8 -*-
"""Unit tests for InstrumentationQueue in SQLAlchemy instrumentation."""

import queue

from mcpgateway.instrumentation.sqlalchemy import InstrumentationQueue


def test_queue_drop_rate_when_full():
    q = InstrumentationQueue(maxsize=2)

    assert q.drop_rate == 0.0

    # Put two items - should succeed
    assert q.put({"a": 1}) is True
    assert q.put({"a": 2}) is True

    # Now queue is full; next put should be dropped
    assert q.put({"a": 3}) is False

    # Total should be 3, dropped 1 -> drop_rate = 1/3
    dr = q.drop_rate
    assert dr == 1.0 / 3.0

    # Cleanup: drain queue
    try:
        while True:
            q.get(timeout=0.001)
            q.task_done()
    except queue.Empty:
        pass


def test_queue_stats_property():
    """Test that stats property returns all metrics in one call."""
    q = InstrumentationQueue(maxsize=100)

    # Initial stats
    stats = q.stats
    assert stats["total"] == 0
    assert stats["dropped"] == 0
    assert stats["drop_rate"] == 0.0
    assert stats["maxsize"] == 100

    # Add some items
    assert q.put({"span": "data1"}) is True
    assert q.put({"span": "data2"}) is True

    stats = q.stats
    assert stats["total"] == 2
    assert stats["dropped"] == 0
    assert stats["drop_rate"] == 0.0
    assert stats["maxsize"] == 100

    # Cleanup
    try:
        while True:
            q.get(timeout=0.001)
            q.task_done()
    except queue.Empty:
        pass


def test_queue_stats_with_drops():
    """Test stats property when queue has drops."""
    q = InstrumentationQueue(maxsize=2)

    # Fill queue
    assert q.put({"a": 1}) is True
    assert q.put({"a": 2}) is True

    # Try to add more (should drop)
    assert q.put({"a": 3}) is False
    assert q.put({"a": 4}) is False

    stats = q.stats
    assert stats["total"] == 4
    assert stats["dropped"] == 2
    assert stats["drop_rate"] == 0.5
    assert stats["maxsize"] == 2

    # Cleanup
    try:
        while True:
            q.get(timeout=0.001)
            q.task_done()
    except queue.Empty:
        pass


def test_queue_put_optimized_lock():
    """Test that optimized put() method works correctly."""
    q = InstrumentationQueue(maxsize=10)

    # Successful puts should increment total only
    for i in range(5):
        assert q.put({"item": i}) is True

    assert q.stats["total"] == 5
    assert q.stats["dropped"] == 0

    # Fill the queue
    for i in range(5, 10):
        assert q.put({"item": i}) is True

    # Now it's full - drops should increment both counters
    assert q.put({"item": 10}) is False
    assert q.put({"item": 11}) is False

    stats = q.stats
    assert stats["total"] == 12
    assert stats["dropped"] == 2
    assert stats["drop_rate"] == 2.0 / 12.0

    # Cleanup
    try:
        while True:
            q.get(timeout=0.001)
            q.task_done()
    except queue.Empty:
        pass
