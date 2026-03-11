#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Reproduction test for issue #3598: metrics API call count displayed as 0

This test demonstrates the bug where total_executions returns 0 after
raw metrics are rolled up into tool_metrics_hourly and deleted.

Root Cause:
- The metrics_summary property in db.py only queries tool_metrics table
- When raw metrics are deleted after rollup (default behavior), the query returns 0
- Historical data in tool_metrics_hourly is not consulted

Expected Behavior:
- API should aggregate from BOTH tool_metrics AND tool_metrics_hourly
- total_executions should reflect historical + recent executions

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
from datetime import datetime, timedelta, timezone

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from mcpgateway.db import Base, Tool, ToolMetric, ToolMetricsHourly


@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def test_metrics_with_rollup_and_deletion(test_db: Session):
    """
    Reproduce issue #3598: total_executions shows 0 after raw metrics are deleted.

    Steps:
    1. Create a tool
    2. Add raw metrics (tool_metrics)
    3. Rollup metrics into hourly table (tool_metrics_hourly)
    4. Delete raw metrics (simulating cleanup after rollup)
    5. Query tool.metrics_summary - BUG: returns total_executions=0

    Expected: Should return total_executions from hourly table
    Actual: Returns 0 because it only queries tool_metrics
    """
    # 1. Create a tool
    tool = Tool(
        id="test-tool-001",
        original_name="test_tool",
        url="http://localhost:8000/tool",
        description="Test tool for issue reproduction",
        integration_type="MCP",
        input_schema={"type": "object", "properties": {}},
    )
    test_db.add(tool)
    test_db.commit()

    # 2. Add 10 raw metrics (simulating tool executions from yesterday)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    for i in range(10):
        metric = ToolMetric(
            tool_id=tool.id,
            timestamp=yesterday + timedelta(minutes=i * 5),
            response_time=0.5 + (i * 0.1),
            is_success=True,
        )
        test_db.add(metric)
    test_db.commit()

    # Verify raw metrics exist and tool.metrics_summary works
    test_db.refresh(tool)
    assert tool.execution_count == 10, "Should have 10 executions before rollup"
    metrics_before = tool.metrics_summary
    assert metrics_before["total_executions"] == 10, "Should report 10 total executions"

    # 3. Rollup metrics into hourly table (simulating rollup job)
    hour_start = yesterday.replace(minute=0, second=0, microsecond=0)
    rollup = ToolMetricsHourly(
        tool_id=tool.id,
        tool_name="test_tool",
        hour_start=hour_start,
        total_count=10,
        success_count=10,
        failure_count=0,
        min_response_time=0.5,
        max_response_time=1.4,
        avg_response_time=0.95,
        p50_response_time=0.95,
        p95_response_time=1.3,
        p99_response_time=1.4,
    )
    test_db.add(rollup)
    test_db.commit()

    # 4. Delete raw metrics (simulating cleanup after rollup)
    test_db.query(ToolMetric).filter(ToolMetric.tool_id == tool.id).delete()
    test_db.commit()

    # 5. Query metrics_summary - THIS IS THE BUG
    test_db.refresh(tool)
    metrics_after = tool.metrics_summary

    # FIX VERIFICATION: Should now return 10 from hourly rollup
    print(f"\nFIX VERIFICATION:")
    print(f"  total_executions BEFORE deletion: {metrics_before['total_executions']}")
    print(f"  total_executions AFTER deletion: {metrics_after['total_executions']}")
    print(f"  Hourly rollup has: {rollup.total_count} executions")
    print(f"\n✅ Fix successful: API now queries BOTH tool_metrics AND tool_metrics_hourly\n")

    # This should now PASS after the fix
    assert metrics_after["total_executions"] == 10, "Should aggregate from hourly table"
    assert metrics_after["successful_executions"] == 10, "Should report 10 successful executions"
    assert metrics_after["failed_executions"] == 0, "Should report 0 failures"


if __name__ == "__main__":
    # Run the test directly
    pytest.main([__file__, "-v", "-s"])
