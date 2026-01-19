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
            q.get(timeout=0)
            q.task_done()
    except queue.Empty:
        pass
