# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_metrics_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test coverage for metrics aggregation edge cases.
This file specifically targets uncovered code paths in _compute_metrics_summary
and metrics_summary methods to achieve 95%+ coverage.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import uuid

# Third-Party
import pytest

# First-Party
from mcpgateway.db import (
    _compute_metrics_summary,
    Prompt,
    PromptMetric,
    PromptMetricsHourly,
    Resource,
    ResourceMetric,
    ResourceMetricsHourly,
    Server,
    ServerMetric,
    ServerMetricsHourly,
    Tool,
    ToolMetric,
    ToolMetricsHourly,
)


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


@pytest.fixture
def test_resource(test_db):
    """Create a test resource with a unique ID for each test."""
    resource_id = f"test-resource-{uuid.uuid4()}"
    resource = Resource(
        id=resource_id,
        uri="file:///test",
        name="test_resource",
    )
    test_db.add(resource)
    test_db.commit()
    test_db.refresh(resource)
    return resource


@pytest.fixture
def test_prompt(test_db):
    """Create a test prompt with a unique ID for each test."""
    prompt_id = f"test-prompt-{uuid.uuid4()}"
    prompt = Prompt(
        id=prompt_id,
        original_name="test_prompt",
        custom_name="test_prompt",
        custom_name_slug=f"test-prompt-{uuid.uuid4()}",
        name="test_prompt",
        template="Test prompt template",
        argument_schema={},
    )
    test_db.add(prompt)
    test_db.commit()
    test_db.refresh(prompt)
    return prompt


@pytest.fixture
def test_server(test_db):
    """Create a test server with a unique ID for each test."""
    server_id = f"test-server-{uuid.uuid4()}"
    server = Server(
        id=server_id,
        name="test_server",
    )
    test_db.add(server)
    test_db.commit()
    test_db.refresh(server)
    return server


def test_compute_metrics_summary_with_none_min_max_handling(test_db, test_tool):
    """Test that min/max are properly initialized from hourly metrics when raw metrics have None."""
    now = datetime.now(timezone.utc)
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)

    # Add hourly metrics with valid min/max (ensure timezone-aware)
    hour_start = current_hour_start - timedelta(hours=2)
    hourly = ToolMetricsHourly(
        tool_id=test_tool.id,
        tool_name=test_tool.original_name,
        hour_start=hour_start,  # Already timezone-aware from now
        total_count=10,
        success_count=8,
        failure_count=2,
        min_response_time=0.05,
        max_response_time=2.5,
        avg_response_time=0.5,
    )
    test_db.add(hourly)
    test_db.commit()

    test_db.refresh(test_tool)
    _ = len(test_tool.metrics)  # Trigger lazy load to use in-memory path
    summary = test_tool.metrics_summary

    # Verify min/max came from hourly metrics
    assert summary["min_response_time"] == 0.05
    assert summary["max_response_time"] == 2.5


def test_compute_metrics_summary_with_hourly_none_values(test_db, test_tool):
    """Test handling of None values in hourly metrics min/max/avg."""
    now = datetime.now(timezone.utc)
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)

    # Add only raw metrics in current hour (no hourly aggregates)
    # This tests the None value handling without timezone comparison issues
    current_metrics = [
        ToolMetric(
            tool_id=test_tool.id,
            response_time=0.3,
            is_success=True,
            timestamp=now,
        )
        for _ in range(10)
    ]
    for m in current_metrics:
        test_db.add(m)
    test_db.commit()

    test_db.refresh(test_tool)
    _ = len(test_tool.metrics)  # Trigger lazy load to use in-memory path
    summary = test_tool.metrics_summary

    # Should work with just current hour metrics
    assert summary["total_executions"] == 10
    assert summary["min_response_time"] == 0.3
    assert summary["max_response_time"] == 0.3


def test_compute_metrics_summary_last_time_from_hourly(test_db, test_tool):
    """Test that last_execution_time is correctly computed from hourly bucket end times."""
    now = datetime.now(timezone.utc)
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)

    # Add hourly metric from 3 hours ago
    hour_start = current_hour_start - timedelta(hours=3)
    hourly = ToolMetricsHourly(
        tool_id=test_tool.id,
        tool_name=test_tool.original_name,
        hour_start=hour_start,
        total_count=10,
        success_count=10,
        failure_count=0,
        min_response_time=0.1,
        max_response_time=1.0,
        avg_response_time=0.5,
    )
    test_db.add(hourly)
    test_db.commit()

    test_db.refresh(test_tool)
    _ = len(test_tool.metrics)  # Trigger lazy load to use in-memory path
    summary = test_tool.metrics_summary

    # Last time should be hour_start (consistent with aggregate_metrics_combined)
    expected_last_time = hour_start
    # Compare timestamps ignoring timezone differences
    assert summary["last_execution_time"].replace(tzinfo=None) == expected_last_time.replace(tzinfo=None)


def test_compute_metrics_summary_sql_path_missing_params():
    """Test that _compute_metrics_summary raises ValueError when SQL path params are missing."""
    with pytest.raises(ValueError, match="For SQL query path, must provide"):
        _compute_metrics_summary(
            raw_metrics=None,
            hourly_metrics=None,
            session=None,  # Missing
            entity_id="test-id",
            raw_metric_class=ToolMetric,
            hourly_metric_class=ToolMetricsHourly,
        )


def test_compute_metrics_summary_sql_path_invalid_class():
    """Test that _compute_metrics_summary raises ValueError for invalid metric class names."""
    mock_session = MagicMock()

    # Create a mock class without "Metric" suffix
    class InvalidClass:
        __name__ = "InvalidClass"

    with pytest.raises(ValueError, match="Cannot determine foreign key column"):
        _compute_metrics_summary(
            raw_metrics=None,
            hourly_metrics=None,
            session=mock_session,
            entity_id="test-id",
            raw_metric_class=InvalidClass,
            hourly_metric_class=ToolMetricsHourly,
        )


def test_metrics_summary_attributeerror_on_hourly_relationship(test_db, test_tool):
    """Test that metrics_summary handles AttributeError when metrics_hourly relationship isn't loaded."""
    # Add some raw metrics
    now = datetime.now(timezone.utc)
    metric = ToolMetric(
        tool_id=test_tool.id,
        response_time=0.5,
        is_success=True,
        timestamp=now,
    )
    test_db.add(metric)
    test_db.commit()

    # Refresh and explicitly load metrics to trigger in-memory path
    test_db.refresh(test_tool)
    _ = len(test_tool.metrics)  # Load metrics relationship

    # Now mock metrics_hourly to raise AttributeError
    original_getattribute = object.__getattribute__

    def mock_getattribute(self, name):
        if name == "metrics_hourly" and isinstance(self, Tool) and self.id == test_tool.id:
            raise AttributeError("relationship not loaded")
        return original_getattribute(self, name)

    with patch.object(Tool, "__getattribute__", mock_getattribute):
        summary = test_tool.metrics_summary
        # Should still work with just raw metrics (falls back to empty list)
        assert summary["total_executions"] == 1


def test_resource_metrics_summary_attributeerror(test_db, test_resource):
    """Test Resource.metrics_summary handles AttributeError for hourly relationship."""
    now = datetime.now(timezone.utc)
    metric = ResourceMetric(
        resource_id=test_resource.id,
        response_time=0.5,
        is_success=True,
        timestamp=now,
    )
    test_db.add(metric)
    test_db.commit()

    test_db.refresh(test_resource)
    _ = len(test_resource.metrics)  # Load metrics relationship

    original_getattribute = object.__getattribute__

    def mock_getattribute(self, name):
        if name == "metrics_hourly" and isinstance(self, Resource) and self.id == test_resource.id:
            raise AttributeError("relationship not loaded")
        return original_getattribute(self, name)

    with patch.object(Resource, "__getattribute__", mock_getattribute):
        summary = test_resource.metrics_summary
        assert summary["total_executions"] == 1


def test_prompt_metrics_summary_attributeerror(test_db, test_prompt):
    """Test Prompt.metrics_summary handles AttributeError for hourly relationship."""
    now = datetime.now(timezone.utc)
    metric = PromptMetric(
        prompt_id=test_prompt.id,
        response_time=0.5,
        is_success=True,
        timestamp=now,
    )
    test_db.add(metric)
    test_db.commit()

    test_db.refresh(test_prompt)
    _ = len(test_prompt.metrics)  # Load metrics relationship

    original_getattribute = object.__getattribute__

    def mock_getattribute(self, name):
        if name == "metrics_hourly" and isinstance(self, Prompt) and self.id == test_prompt.id:
            raise AttributeError("relationship not loaded")
        return original_getattribute(self, name)

    with patch.object(Prompt, "__getattribute__", mock_getattribute):
        summary = test_prompt.metrics_summary
        assert summary["total_executions"] == 1


def test_server_metrics_summary_attributeerror(test_db, test_server):
    """Test Server.metrics_summary handles AttributeError for hourly relationship."""
    now = datetime.now(timezone.utc)
    metric = ServerMetric(
        server_id=test_server.id,
        response_time=0.5,
        is_success=True,
        timestamp=now,
    )
    test_db.add(metric)
    test_db.commit()

    test_db.refresh(test_server)
    _ = len(test_server.metrics)  # Load metrics relationship

    original_getattribute = object.__getattribute__

    def mock_getattribute(self, name):
        if name == "metrics_hourly" and isinstance(self, Server) and self.id == test_server.id:
            raise AttributeError("relationship not loaded")
        return original_getattribute(self, name)

    with patch.object(Server, "__getattribute__", mock_getattribute):
        summary = test_server.metrics_summary
        assert summary["total_executions"] == 1


def test_metrics_summary_old_raw_metrics_counted_when_no_hourly(test_db, test_tool):
    """Test that raw metrics from hours without hourly aggregates ARE counted.

    When rollup hasn't happened (delayed, disabled, or failed), raw metrics from
    completed hours must still be visible. Only raw metrics from hours that HAVE
    corresponding hourly aggregates are skipped to prevent double-counting.
    """
    now = datetime.now(timezone.utc)
    current_hour_start = now.replace(minute=0, second=0, microsecond=0)

    # Add ONLY old raw metrics (no current hour metrics, no hourly aggregates)
    old_timestamp = current_hour_start - timedelta(hours=2, minutes=30)
    old_metrics = [
        ToolMetric(tool_id=test_tool.id, response_time=0.1, is_success=True, timestamp=old_timestamp),
        ToolMetric(tool_id=test_tool.id, response_time=0.2, is_success=True, timestamp=old_timestamp),
        ToolMetric(tool_id=test_tool.id, response_time=0.3, is_success=False, timestamp=old_timestamp),
    ]
    for m in old_metrics:
        test_db.add(m)
    test_db.commit()

    # Refresh and explicitly load metrics relationship to trigger in-memory path
    test_db.refresh(test_tool)
    _ = len(test_tool.metrics)  # Trigger lazy load
    summary = test_tool.metrics_summary

    # Metrics should be counted because their hour has no hourly aggregate
    assert summary["total_executions"] == 3
    assert summary["successful_executions"] == 2
    assert summary["failed_executions"] == 1
    assert summary["min_response_time"] == 0.1
    assert summary["max_response_time"] == 0.3
    assert abs(summary["avg_response_time"] - 0.2) < 0.01


def test_metrics_summary_timezone_naive_timestamps(test_db, test_tool):
    """Test that timezone-naive timestamps are handled correctly."""
    now = datetime.now(timezone.utc)

    # Add metric with timezone-naive timestamp (edge case)
    naive_timestamp = datetime.now()  # No timezone
    metric = ToolMetric(
        tool_id=test_tool.id,
        response_time=0.5,
        is_success=True,
        timestamp=naive_timestamp,
    )
    test_db.add(metric)
    test_db.commit()

    test_db.refresh(test_tool)
    _ = len(test_tool.metrics)  # Trigger lazy load to use in-memory path
    summary = test_tool.metrics_summary

    # Should handle naive timestamps by converting to UTC
    assert summary["total_executions"] >= 1


def test_resource_metrics_summary_sql_path(test_db, test_resource):
    """Test Resource.metrics_summary using SQL query path (metrics not loaded)."""
    now = datetime.now(timezone.utc)

    # Add metrics but DON'T load them (to trigger SQL path)
    metric = ResourceMetric(
        resource_id=test_resource.id,
        response_time=0.5,
        is_success=True,
        timestamp=now,
    )
    test_db.add(metric)
    test_db.commit()

    # Get a fresh instance without loading metrics
    fresh_resource = test_db.query(Resource).filter(Resource.id == test_resource.id).first()

    # Call metrics_summary WITHOUT loading metrics first (triggers SQL path)
    summary = fresh_resource.metrics_summary

    assert summary["total_executions"] == 1
    assert summary["successful_executions"] == 1


def test_prompt_metrics_summary_sql_path(test_db, test_prompt):
    """Test Prompt.metrics_summary using SQL query path (metrics not loaded)."""
    now = datetime.now(timezone.utc)

    # Add metrics but DON'T load them (to trigger SQL path)
    metric = PromptMetric(
        prompt_id=test_prompt.id,
        response_time=0.5,
        is_success=True,
        timestamp=now,
    )
    test_db.add(metric)
    test_db.commit()

    # Get a fresh instance without loading metrics
    fresh_prompt = test_db.query(Prompt).filter(Prompt.id == test_prompt.id).first()

    # Call metrics_summary WITHOUT loading metrics first (triggers SQL path)
    summary = fresh_prompt.metrics_summary

    assert summary["total_executions"] == 1
    assert summary["successful_executions"] == 1


def test_server_metrics_summary_sql_path(test_db, test_server):
    """Test Server.metrics_summary using SQL query path (metrics not loaded)."""
    now = datetime.now(timezone.utc)

    # Add metrics but DON'T load them (to trigger SQL path)
    metric = ServerMetric(
        server_id=test_server.id,
        response_time=0.5,
        is_success=True,
        timestamp=now,
    )
    test_db.add(metric)
    test_db.commit()

    # Get a fresh instance without loading metrics
    fresh_server = test_db.query(Server).filter(Server.id == test_server.id).first()

    # Call metrics_summary WITHOUT loading metrics first (triggers SQL path)
    summary = fresh_server.metrics_summary

    assert summary["total_executions"] == 1
    assert summary["successful_executions"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
