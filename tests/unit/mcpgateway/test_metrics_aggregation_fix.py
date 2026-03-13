# -*- coding: utf-8 -*-
"""Test for metrics aggregation combining raw and hourly metrics.

Tests issue #3598: Ensure metrics_summary queries both raw and hourly tables.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timedelta, timezone
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Tool, ToolMetric, ToolMetricsHourly


@pytest.fixture
def test_tool(test_db):
    """Create a test tool with a unique ID for each test."""
    tool_id = f"test-tool-{uuid.uuid4()}"
    tool = Tool(
        id=tool_id,
        original_name="test_tool",
        custom_name="test_tool",
        custom_name_slug=f"test-tool-{uuid.uuid4()}",
        input_schema={},
    )
    test_db.add(tool)
    test_db.commit()
    test_db.refresh(tool)
    return tool


def test_metrics_summary_with_only_raw_metrics(test_db, test_tool):
    """Test metrics_summary when only raw metrics exist."""
    # Add raw metrics
    now = datetime.now(timezone.utc)
    metrics = [
        ToolMetric(tool_id=test_tool.id, response_time=0.1, is_success=True, timestamp=now),
        ToolMetric(tool_id=test_tool.id, response_time=0.2, is_success=True, timestamp=now),
        ToolMetric(tool_id=test_tool.id, response_time=0.3, is_success=False, timestamp=now),
    ]
    for m in metrics:
        test_db.add(m)
    test_db.commit()

    # Get metrics summary
    test_db.refresh(test_tool)
    summary = test_tool.metrics_summary

    assert summary["total_executions"] == 3
    assert summary["successful_executions"] == 2
    assert summary["failed_executions"] == 1
    assert summary["min_response_time"] == 0.1
    assert summary["max_response_time"] == 0.3
    assert abs(summary["avg_response_time"] - 0.2) < 0.01  # (0.1 + 0.2 + 0.3) / 3


def test_metrics_summary_with_only_hourly_metrics(test_db, test_tool):
    """Test metrics_summary when only hourly metrics exist (raw deleted after rollup)."""
    # Add hourly aggregated metrics (simulating raw metrics were deleted)
    hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    hourly = ToolMetricsHourly(
        tool_id=test_tool.id,
        tool_name=test_tool.original_name,
        hour_start=hour_start,
        total_count=100,
        success_count=95,
        failure_count=5,
        min_response_time=0.05,
        max_response_time=2.5,
        avg_response_time=0.5,
        p50_response_time=0.4,
        p95_response_time=1.2,
        p99_response_time=2.0,
    )
    test_db.add(hourly)
    test_db.commit()

    # Get metrics summary
    test_db.refresh(test_tool)
    summary = test_tool.metrics_summary

    assert summary["total_executions"] == 100
    assert summary["successful_executions"] == 95
    assert summary["failed_executions"] == 5
    assert summary["min_response_time"] == 0.05
    assert summary["max_response_time"] == 2.5
    assert abs(summary["avg_response_time"] - 0.5) < 0.01


def test_metrics_summary_with_both_raw_and_hourly(test_db, test_tool):
    """Test metrics_summary correctly combines raw and hourly metrics without double-counting.

    This is the main fix for issue #3598.
    CRITICAL: Only raw metrics from the current hour should be counted to avoid
    double-counting when rollup has happened but cleanup hasn't yet.
    """
    now = datetime.now(timezone.utc)
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)

    # Add hourly aggregated metrics (historical data from 2 hours ago - completed hour)
    hour_start = current_hour_start - timedelta(hours=2)
    hourly = ToolMetricsHourly(
        tool_id=test_tool.id,
        tool_name=test_tool.original_name,
        hour_start=hour_start,
        total_count=100,
        success_count=95,
        failure_count=5,
        min_response_time=0.05,
        max_response_time=2.5,
        avg_response_time=0.5,  # weighted sum = 0.5 * 100 = 50.0
        p50_response_time=0.4,
        p95_response_time=1.2,
        p99_response_time=2.0,
    )
    test_db.add(hourly)

    # Add raw metrics from CURRENT hour (not yet rolled up) - should be counted
    metrics_current_hour = [
        ToolMetric(tool_id=test_tool.id, response_time=0.02, is_success=True, timestamp=now),  # new min
        ToolMetric(tool_id=test_tool.id, response_time=0.15, is_success=True, timestamp=now),
        ToolMetric(tool_id=test_tool.id, response_time=3.0, is_success=False, timestamp=now),  # new max
    ]
    for m in metrics_current_hour:
        test_db.add(m)

    # Add raw metrics from OLD hour (already rolled up) - should NOT be counted (double-count prevention)
    old_hour_timestamp = current_hour_start - timedelta(hours=2, minutes=30)
    metrics_old_hour = [
        ToolMetric(tool_id=test_tool.id, response_time=0.1, is_success=True, timestamp=old_hour_timestamp),
        ToolMetric(tool_id=test_tool.id, response_time=0.2, is_success=True, timestamp=old_hour_timestamp),
    ]
    for m in metrics_old_hour:
        test_db.add(m)

    test_db.commit()

    # Get metrics summary
    test_db.refresh(test_tool)
    summary = test_tool.metrics_summary

    # Total counts: 100 (hourly) + 3 (current hour raw) = 103
    # The 2 old raw metrics should NOT be counted (would be double-counting)
    assert summary["total_executions"] == 103  # 100 + 3 (NOT + 2 from old hour)
    assert summary["successful_executions"] == 97  # 95 + 2
    assert summary["failed_executions"] == 6  # 5 + 1

    # Min/max should be from either raw or hourly
    assert summary["min_response_time"] == 0.02  # from current hour raw (0.02 < 0.05)
    assert summary["max_response_time"] == 3.0  # from current hour raw (3.0 > 2.5)

    # Average should be weighted: (50.0 + 0.02 + 0.15 + 3.0) / 103
    expected_avg = (50.0 + 0.02 + 0.15 + 3.0) / 103
    assert abs(summary["avg_response_time"] - expected_avg) < 0.01

    # Failure rate should be correct
    assert abs(summary["failure_rate"] - (6 / 103)) < 0.01


def test_no_double_counting_when_rollup_done_but_cleanup_pending(test_db, test_tool):
    """Test that metrics from completed hours aren't double-counted.

    Scenario: METRICS_DELETE_RAW_AFTER_ROLLUP=true, METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS=1
    - Rollup happened for hour 10-11 at 11:00
    - It's now 11:30, cleanup hasn't run yet (runs at 12:00)
    - Both raw and hourly metrics exist for hour 10-11
    - Should only count hourly (not both)
    """
    now = datetime.now(timezone.utc)
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)
    completed_hour_start = current_hour_start - timedelta(hours=1)

    # Hourly aggregate for completed hour (10-11)
    hourly = ToolMetricsHourly(
        tool_id=test_tool.id,
        tool_name=test_tool.original_name,
        hour_start=completed_hour_start,
        total_count=50,
        success_count=48,
        failure_count=2,
        min_response_time=0.1,
        max_response_time=1.0,
        avg_response_time=0.5,
    )
    test_db.add(hourly)

    # Raw metrics from completed hour (not yet cleaned up) - should be IGNORED
    old_timestamp = completed_hour_start + timedelta(minutes=30)
    old_metrics = [
        ToolMetric(tool_id=test_tool.id, response_time=0.2, is_success=True, timestamp=old_timestamp),
        ToolMetric(tool_id=test_tool.id, response_time=0.3, is_success=True, timestamp=old_timestamp),
    ]
    for m in old_metrics:
        test_db.add(m)

    # Raw metrics from current hour - should be counted
    current_metrics = [
        ToolMetric(tool_id=test_tool.id, response_time=0.1, is_success=True, timestamp=now),
    ]
    for m in current_metrics:
        test_db.add(m)

    test_db.commit()

    # Get metrics summary
    test_db.refresh(test_tool)
    summary = test_tool.metrics_summary

    # Should be 50 (hourly) + 1 (current hour) = 51
    # NOT 50 + 2 (old raw) + 1 (current raw) = 53
    assert summary["total_executions"] == 51
    assert summary["successful_executions"] == 49
    assert summary["failed_executions"] == 2


def test_metrics_summary_with_multiple_hourly_buckets(test_db, test_tool):
    """Test metrics_summary with multiple hourly aggregation buckets."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # Add multiple hourly buckets
    hourly_buckets = [
        ToolMetricsHourly(
            tool_id=test_tool.id,
            tool_name=test_tool.original_name,
            hour_start=now - timedelta(hours=i),
            total_count=10,
            success_count=8,
            failure_count=2,
            min_response_time=0.1,
            max_response_time=1.0,
            avg_response_time=0.5,
        )
        for i in range(1, 4)  # 3 hourly buckets
    ]
    for h in hourly_buckets:
        test_db.add(h)
    test_db.commit()

    # Get metrics summary
    test_db.refresh(test_tool)
    summary = test_tool.metrics_summary

    assert summary["total_executions"] == 30  # 10 * 3
    assert summary["successful_executions"] == 24  # 8 * 3
    assert summary["failed_executions"] == 6  # 2 * 3
    assert summary["min_response_time"] == 0.1
    assert summary["max_response_time"] == 1.0
    assert abs(summary["avg_response_time"] - 0.5) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
