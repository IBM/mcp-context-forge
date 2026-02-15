# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_db.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Standard
from datetime import datetime, timedelta, timezone
import logging
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.exc import SQLAlchemyError

# First-Party
import mcpgateway.db as db


# --- utc_now ---
def test_utc_now_returns_utc_datetime():
    now = db.utc_now()
    assert isinstance(now, datetime)
    assert now.tzinfo == timezone.utc


# --- Tool metrics properties ---
def make_tool_with_metrics(metrics):
    tool = db.Tool()
    tool.metrics = metrics
    return tool


def test_tool_metrics_properties():
    now = datetime.now(timezone.utc)
    metrics = [
        db.ToolMetric(response_time=1.0, is_success=True, timestamp=now),
        db.ToolMetric(response_time=2.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    tool = make_tool_with_metrics(metrics)
    assert tool.execution_count == 2
    assert tool.successful_executions == 1
    assert tool.failed_executions == 1
    assert tool.failure_rate == 0.5
    assert tool.min_response_time == 1.0
    assert tool.max_response_time == 2.0
    assert tool.avg_response_time == 1.5
    assert tool.last_execution_time == now + timedelta(seconds=1)
    summary = tool.metrics_summary
    assert summary["total_executions"] == 2
    assert summary["failure_rate"] == 0.5


def test_tool_metrics_properties_empty():
    tool = db.Tool()
    tool.metrics = []
    assert tool.execution_count == 0
    assert tool.successful_executions == 0
    assert tool.failed_executions == 0
    assert tool.failure_rate == 0.0
    assert tool.min_response_time is None
    assert tool.max_response_time is None
    assert tool.avg_response_time is None
    assert tool.last_execution_time is None


def test_tool_get_metric_counts_with_loaded_metrics():
    """Test _get_metric_counts returns correct tuple when metrics are loaded."""
    now = datetime.now(timezone.utc)
    metrics = [
        db.ToolMetric(response_time=1.0, is_success=True, timestamp=now),
        db.ToolMetric(response_time=2.0, is_success=True, timestamp=now),
        db.ToolMetric(response_time=3.0, is_success=False, timestamp=now),
    ]
    tool = make_tool_with_metrics(metrics)
    total, successful, failed = tool._get_metric_counts()
    assert total == 3
    assert successful == 2
    assert failed == 1


def test_tool_get_metric_counts_detached_returns_zeros():
    """Test _get_metric_counts returns (0, 0, 0) for detached object without session."""
    tool = db.Tool()
    # Don't set metrics - simulates detached object
    total, successful, failed = tool._get_metric_counts()
    assert total == 0
    assert successful == 0
    assert failed == 0


def test_tool_metrics_summary_all_fields():
    """Test metrics_summary returns all expected fields with correct values."""
    now = datetime.now(timezone.utc)
    metrics = [
        db.ToolMetric(response_time=1.0, is_success=True, timestamp=now),
        db.ToolMetric(response_time=3.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    tool = make_tool_with_metrics(metrics)
    summary = tool.metrics_summary
    assert summary["total_executions"] == 2
    assert summary["successful_executions"] == 1
    assert summary["failed_executions"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["min_response_time"] == 1.0
    assert summary["max_response_time"] == 3.0
    assert summary["avg_response_time"] == 2.0
    assert summary["last_execution_time"] == now + timedelta(seconds=1)


def test_tool_metrics_summary_empty():
    """Test metrics_summary returns zeros/None for empty metrics."""
    tool = db.Tool()
    tool.metrics = []
    summary = tool.metrics_summary
    assert summary["total_executions"] == 0
    assert summary["successful_executions"] == 0
    assert summary["failed_executions"] == 0
    assert summary["failure_rate"] == 0.0
    assert summary["min_response_time"] is None
    assert summary["max_response_time"] is None
    assert summary["avg_response_time"] is None
    assert summary["last_execution_time"] is None


def test_tool_metrics_summary_detached():
    """Test metrics_summary returns zeros/None for detached object without session."""
    tool = db.Tool()
    # Don't set metrics - simulates detached object without session
    summary = tool.metrics_summary
    assert summary["total_executions"] == 0
    assert summary["failure_rate"] == 0.0


def test_build_engine_mysql_branch(monkeypatch):
    monkeypatch.setattr(db, "backend", "mysql")
    monkeypatch.setattr(db.settings, "database_url", "mysql://user:pass@localhost/db")
    monkeypatch.setattr(db.settings, "db_pool_size", 5)
    monkeypatch.setattr(db.settings, "db_max_overflow", 10)
    monkeypatch.setattr(db.settings, "db_pool_timeout", 30)
    monkeypatch.setattr(db.settings, "db_pool_recycle", 300)
    monkeypatch.setattr(db, "connect_args", {"arg": "val"})

    with patch("mcpgateway.db.create_engine") as mock_create:
        db.build_engine()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["pool_pre_ping"] is True
        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 10


def test_build_engine_null_pool_branch(monkeypatch):
    monkeypatch.setattr(db, "backend", "postgresql")
    monkeypatch.setattr(db.settings, "database_url", "postgresql://user:pass@localhost/db")
    monkeypatch.setattr(db.settings, "db_pool_class", "null")
    monkeypatch.setattr(db, "connect_args", {})

    with patch("mcpgateway.db.create_engine") as mock_create:
        db.build_engine()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["poolclass"] == db.NullPool


def test_build_engine_auto_pgbouncer_branch(monkeypatch):
    monkeypatch.setattr(db, "backend", "postgresql")
    monkeypatch.setattr(db.settings, "database_url", "postgresql://user:pass@pgbouncer.example/db")
    monkeypatch.setattr(db.settings, "db_pool_class", "auto")
    monkeypatch.setattr(db.settings, "db_pool_pre_ping", "auto")
    monkeypatch.setattr(db, "connect_args", {})

    with patch("mcpgateway.db.create_engine") as mock_create:
        db.build_engine()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["poolclass"] == db.NullPool


def test_tool_get_metric_counts_sql_path(monkeypatch):
    """Test _get_metric_counts uses SQL aggregation when metrics not loaded but session exists."""
    tool = db.Tool()
    tool.id = "test-tool-id"

    # Mock the session and query result
    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([(10, 7)])  # total=10, successful=7
    mock_result.__getitem__ = lambda self, i: [10, 7][i]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.one.return_value = mock_result

    mock_session = MagicMock()
    mock_session.query.return_value = mock_query

    # Patch object_session where it's imported (in sqlalchemy.orm)
    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    # Call _get_metric_counts - should use SQL path
    total, successful, failed = tool._get_metric_counts()

    assert total == 10
    assert successful == 7
    assert failed == 3  # 10 - 7
    mock_session.query.assert_called_once()


def test_tool_metrics_summary_sql_path(monkeypatch):
    """Test metrics_summary uses SQL aggregation when metrics not loaded but session exists."""
    tool = db.Tool()
    tool.id = "test-tool-id"

    # Mock the session and query result for full aggregation
    # (count, sum_success, min_rt, max_rt, avg_rt, max_timestamp)
    mock_timestamp = datetime.now(timezone.utc)
    mock_result = MagicMock()
    mock_result.__getitem__ = lambda self, i: [5, 3, 1.0, 5.0, 2.5, mock_timestamp][i]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.one.return_value = mock_result

    mock_session = MagicMock()
    mock_session.query.return_value = mock_query

    # Patch object_session where it's imported (in sqlalchemy.orm)
    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    summary = tool.metrics_summary

    assert summary["total_executions"] == 5
    assert summary["successful_executions"] == 3
    assert summary["failed_executions"] == 2
    assert summary["failure_rate"] == 0.4
    assert summary["min_response_time"] == 1.0
    assert summary["max_response_time"] == 5.0
    assert summary["avg_response_time"] == 2.5
    assert summary["last_execution_time"] == mock_timestamp


# --- Resource metrics properties ---
def make_resource_with_metrics(metrics):
    resource = db.Resource()
    resource.metrics = metrics
    return resource


def test_resource_metrics_properties():
    now = datetime.now(timezone.utc)
    metrics = [
        db.ResourceMetric(response_time=1.0, is_success=True, timestamp=now),
        db.ResourceMetric(response_time=2.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    resource = make_resource_with_metrics(metrics)
    assert resource.execution_count == 2
    assert resource.successful_executions == 1
    assert resource.failed_executions == 1
    assert resource.failure_rate == 0.5
    assert resource.min_response_time == 1.0
    assert resource.max_response_time == 2.0
    assert resource.avg_response_time == 1.5
    assert resource.last_execution_time == now + timedelta(seconds=1)


def test_resource_metrics_summary_loaded():
    """Test metrics_summary uses loaded metrics path."""
    now = datetime.now(timezone.utc)
    metrics = [
        db.ResourceMetric(response_time=1.0, is_success=True, timestamp=now),
        db.ResourceMetric(response_time=3.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    resource = make_resource_with_metrics(metrics)
    summary = resource.metrics_summary
    assert summary["total_executions"] == 2
    assert summary["successful_executions"] == 1
    assert summary["failed_executions"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["min_response_time"] == 1.0
    assert summary["max_response_time"] == 3.0
    assert summary["avg_response_time"] == 2.0
    assert summary["last_execution_time"] == now + timedelta(seconds=1)


def test_resource_metrics_properties_empty():
    resource = db.Resource()
    resource.metrics = []
    assert resource.execution_count == 0
    assert resource.successful_executions == 0
    assert resource.failed_executions == 0
    assert resource.failure_rate == 0.0
    assert resource.min_response_time is None
    assert resource.max_response_time is None
    assert resource.avg_response_time is None
    assert resource.last_execution_time is None


def test_resource_get_metric_counts_sql_path(monkeypatch):
    """Test _get_metric_counts uses SQL aggregation when metrics not loaded but session exists."""
    resource = db.Resource()
    resource.id = "test-resource-id"

    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([(8, 5)])
    mock_result.__getitem__ = lambda self, i: [8, 5][i]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.one.return_value = mock_result

    mock_session = MagicMock()
    mock_session.query.return_value = mock_query

    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    total, successful, failed = resource._get_metric_counts()

    assert total == 8
    assert successful == 5
    assert failed == 3
    mock_session.query.assert_called_once()


def test_resource_metrics_summary_sql_path(monkeypatch):
    """Test metrics_summary uses SQL aggregation when metrics not loaded but session exists."""
    resource = db.Resource()
    resource.id = "test-resource-id"

    mock_timestamp = datetime.now(timezone.utc)
    mock_result = MagicMock()
    mock_result.__getitem__ = lambda self, i: [6, 4, 0.5, 3.0, 1.5, mock_timestamp][i]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.one.return_value = mock_result

    mock_session = MagicMock()
    mock_session.query.return_value = mock_query

    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    summary = resource.metrics_summary

    assert summary["total_executions"] == 6
    assert summary["successful_executions"] == 4
    assert summary["failed_executions"] == 2
    assert summary["failure_rate"] == pytest.approx(0.333, rel=0.01)
    assert summary["min_response_time"] == 0.5
    assert summary["max_response_time"] == 3.0
    assert summary["avg_response_time"] == 1.5
    assert summary["last_execution_time"] == mock_timestamp


# --- Prompt metrics properties ---
def make_prompt_with_metrics(metrics):
    prompt = db.Prompt()
    prompt.metrics = metrics
    return prompt


def test_prompt_metrics_properties():
    now = datetime.now(timezone.utc)
    metrics = [
        db.PromptMetric(response_time=1.0, is_success=True, timestamp=now),
        db.PromptMetric(response_time=2.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    prompt = make_prompt_with_metrics(metrics)
    assert prompt.execution_count == 2
    assert prompt.successful_executions == 1
    assert prompt.failed_executions == 1
    assert prompt.failure_rate == 0.5
    assert prompt.min_response_time == 1.0
    assert prompt.max_response_time == 2.0
    assert prompt.avg_response_time == 1.5
    assert prompt.last_execution_time == now + timedelta(seconds=1)


def test_prompt_metrics_summary_loaded():
    """Test metrics_summary uses loaded metrics path."""
    now = datetime.now(timezone.utc)
    metrics = [
        db.PromptMetric(response_time=2.0, is_success=True, timestamp=now),
        db.PromptMetric(response_time=4.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    prompt = make_prompt_with_metrics(metrics)
    summary = prompt.metrics_summary
    assert summary["total_executions"] == 2
    assert summary["successful_executions"] == 1
    assert summary["failed_executions"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["min_response_time"] == 2.0
    assert summary["max_response_time"] == 4.0
    assert summary["avg_response_time"] == 3.0
    assert summary["last_execution_time"] == now + timedelta(seconds=1)


def test_prompt_metrics_properties_empty():
    prompt = db.Prompt()
    prompt.metrics = []
    assert prompt.execution_count == 0
    assert prompt.successful_executions == 0
    assert prompt.failed_executions == 0
    assert prompt.failure_rate == 0.0
    assert prompt.min_response_time is None
    assert prompt.max_response_time is None
    assert prompt.avg_response_time is None
    assert prompt.last_execution_time is None


def test_prompt_get_metric_counts_sql_path(monkeypatch):
    """Test _get_metric_counts uses SQL aggregation when metrics not loaded but session exists."""
    prompt = db.Prompt()
    prompt.id = "test-prompt-id"

    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([(12, 9)])
    mock_result.__getitem__ = lambda self, i: [12, 9][i]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.one.return_value = mock_result

    mock_session = MagicMock()
    mock_session.query.return_value = mock_query

    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    total, successful, failed = prompt._get_metric_counts()

    assert total == 12
    assert successful == 9
    assert failed == 3
    mock_session.query.assert_called_once()


def test_prompt_metrics_summary_sql_path(monkeypatch):
    """Test metrics_summary uses SQL aggregation when metrics not loaded but session exists."""
    prompt = db.Prompt()
    prompt.id = "test-prompt-id"

    mock_timestamp = datetime.now(timezone.utc)
    mock_result = MagicMock()
    mock_result.__getitem__ = lambda self, i: [10, 8, 0.2, 4.0, 2.0, mock_timestamp][i]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.one.return_value = mock_result

    mock_session = MagicMock()
    mock_session.query.return_value = mock_query

    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    summary = prompt.metrics_summary

    assert summary["total_executions"] == 10
    assert summary["successful_executions"] == 8
    assert summary["failed_executions"] == 2
    assert summary["failure_rate"] == 0.2
    assert summary["min_response_time"] == 0.2
    assert summary["max_response_time"] == 4.0
    assert summary["avg_response_time"] == 2.0
    assert summary["last_execution_time"] == mock_timestamp


# --- Server metrics properties ---
def make_server_with_metrics(metrics):
    server = db.Server()
    server.metrics = metrics
    return server


def test_server_metrics_properties():
    now = datetime.now(timezone.utc)
    metrics = [
        db.ServerMetric(response_time=1.0, is_success=True, timestamp=now),
        db.ServerMetric(response_time=2.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    server = make_server_with_metrics(metrics)
    assert server.execution_count == 2
    assert server.successful_executions == 1
    assert server.failed_executions == 1
    assert server.failure_rate == 0.5
    assert server.min_response_time == 1.0
    assert server.max_response_time == 2.0
    assert server.avg_response_time == 1.5
    assert server.last_execution_time == now + timedelta(seconds=1)


def test_server_metrics_summary_loaded():
    """Test metrics_summary uses loaded metrics path."""
    now = datetime.now(timezone.utc)
    metrics = [
        db.ServerMetric(response_time=1.0, is_success=True, timestamp=now),
        db.ServerMetric(response_time=5.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    server = make_server_with_metrics(metrics)
    summary = server.metrics_summary
    assert summary["total_executions"] == 2
    assert summary["successful_executions"] == 1
    assert summary["failed_executions"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["min_response_time"] == 1.0
    assert summary["max_response_time"] == 5.0
    assert summary["avg_response_time"] == 3.0
    assert summary["last_execution_time"] == now + timedelta(seconds=1)


def test_server_metrics_properties_empty():
    server = db.Server()
    server.metrics = []
    assert server.execution_count == 0
    assert server.successful_executions == 0
    assert server.failed_executions == 0
    assert server.failure_rate == 0.0
    assert server.min_response_time is None
    assert server.max_response_time is None
    assert server.avg_response_time is None
    assert server.last_execution_time is None


def test_server_get_metric_counts_sql_path(monkeypatch):
    """Test _get_metric_counts uses SQL aggregation when metrics not loaded but session exists."""
    server = db.Server()
    server.id = "test-server-id"

    mock_result = MagicMock()
    mock_result.__iter__ = lambda self: iter([(15, 12)])
    mock_result.__getitem__ = lambda self, i: [15, 12][i]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.one.return_value = mock_result

    mock_session = MagicMock()
    mock_session.query.return_value = mock_query

    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    total, successful, failed = server._get_metric_counts()

    assert total == 15
    assert successful == 12
    assert failed == 3
    mock_session.query.assert_called_once()


def test_server_metrics_summary_sql_path(monkeypatch):
    """Test metrics_summary uses SQL aggregation when metrics not loaded but session exists."""
    server = db.Server()
    server.id = "test-server-id"

    mock_timestamp = datetime.now(timezone.utc)
    mock_result = MagicMock()
    mock_result.__getitem__ = lambda self, i: [20, 18, 0.1, 6.0, 3.0, mock_timestamp][i]

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.one.return_value = mock_result

    mock_session = MagicMock()
    mock_session.query.return_value = mock_query

    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    summary = server.metrics_summary

    assert summary["total_executions"] == 20
    assert summary["successful_executions"] == 18
    assert summary["failed_executions"] == 2
    assert summary["failure_rate"] == 0.1
    assert summary["min_response_time"] == 0.1
    assert summary["max_response_time"] == 6.0
    assert summary["avg_response_time"] == 3.0
    assert summary["last_execution_time"] == mock_timestamp


# --- Resource content property ---
def test_resource_content_text():
    resource = db.Resource()
    resource.text_content = "hello"
    resource.binary_content = None
    resource.uri = "uri"
    resource.mime_type = "text/plain"
    content = resource.content
    assert content.text == "hello"
    assert content.type == "resource"
    assert content.uri == "uri"
    assert content.mime_type == "text/plain"


def test_resource_content_binary():
    resource = db.Resource()
    resource.text_content = None
    resource.binary_content = b"data"
    resource.uri = "uri"
    resource.mime_type = None
    content = resource.content
    assert content.blob == b"data"
    assert content.mime_type == "application/octet-stream"


def test_resource_content_none():
    resource = db.Resource()
    resource.text_content = None
    resource.binary_content = None
    with pytest.raises(ValueError):
        _ = resource.content


def test_resource_content_text_and_binary():
    resource = db.Resource()
    resource.text_content = "text"
    resource.binary_content = b"binary"
    resource.uri = "uri"
    resource.mime_type = "text/plain"
    content = resource.content
    assert content.text == "text"
    assert not hasattr(content, "blob") or content.blob is None


# --- Prompt argument validation ---
def test_prompt_validate_arguments_valid():
    prompt = db.Prompt()
    prompt.argument_schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    prompt.validate_arguments({"a": "x"})


def test_prompt_validate_arguments_invalid():
    prompt = db.Prompt()
    prompt.argument_schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    with pytest.raises(ValueError):
        prompt.validate_arguments({})


def test_prompt_validate_arguments_missing_schema():
    prompt = db.Prompt()
    prompt.argument_schema = None
    with pytest.raises(Exception):
        prompt.validate_arguments({"a": "x"})


# --- Validation listeners ---
def test_validate_tool_schema_valid():
    class Target:
        input_schema = {"type": "object"}

    db.validate_tool_schema(None, None, Target())


def test_validate_tool_schema_invalid(caplog):
    class Target:
        input_schema = {"type": "invalid"}  # invalid JSON Schema

    # Capture warnings
    with caplog.at_level(logging.WARNING):
        # With strict mode enabled by default, this raises ValueError
        with pytest.raises(ValueError):
            db.validate_tool_schema(None, None, Target())

    # Check that a warning about invalid schema was logged (it logs then raises)
    assert any("Invalid tool input schema" in record.message for record in caplog.records)


def test_validate_tool_name_valid():
    class Target:
        name = "valid_name-123"

    db.validate_tool_name(None, None, Target())


def test_validate_tool_name_invalid():
    class Target:
        name = "invalid name!"

    with pytest.raises(ValueError):
        db.validate_tool_name(None, None, Target())


def test_validate_prompt_schema_valid():
    class Target:
        argument_schema = {"type": "object"}

    db.validate_prompt_schema(None, None, Target())


def test_validate_prompt_schema_invalid(caplog):
    class Target:
        argument_schema = {"type": "invalid"}  # invalid JSON Schema

    # Capture warnings
    with caplog.at_level(logging.WARNING):
        # With strict mode enabled by default, this raises ValueError
        with pytest.raises(ValueError):
            db.validate_prompt_schema(None, None, Target())

    # Check that a warning about invalid schema was logged
    assert any("Invalid prompt argument schema" in record.message for record in caplog.records)


def test_validate_tool_schema_missing(caplog):
    class Target:
        pass  # No input_schema

    # Should not log any warnings or raise
    with caplog.at_level(logging.WARNING):
        db.validate_tool_schema(None, None, Target())

    # There should be no warnings
    assert len(caplog.records) == 0


def test_validate_tool_schema_none(caplog):
    class Target:
        input_schema = None  # Explicitly None

    # Should not log any warnings or raise
    with caplog.at_level(logging.WARNING):
        db.validate_tool_schema(None, None, Target())

    # There should be no warnings
    assert len(caplog.records) == 0


def test_validate_tool_schema_draft4(caplog):
    """Test schema validation with Draft 4 style exclusiveMinimum."""

    class Target:
        input_schema = {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "type": "object",
            "properties": {"price": {"type": "number", "minimum": 0, "exclusiveMinimum": True}},
        }

    with caplog.at_level(logging.WARNING):
        db.validate_tool_schema(None, None, Target())

    # Valid Draft 4 schema should not log warnings
    assert not any("Invalid tool input schema" in record.message for record in caplog.records)


def test_validate_tool_schema_draft2020_12(caplog):
    """Test schema validation with Draft 2020-12 style schema."""

    class Target:
        input_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }

    with caplog.at_level(logging.WARNING):
        db.validate_tool_schema(None, None, Target())

    # Valid Draft 2020-12 schema should not log warnings
    assert not any("Invalid tool input schema" in record.message for record in caplog.records)


def test_validate_tool_schema_invalid_non_strict(caplog, monkeypatch):
    """Test that invalid schema only logs warning when strict mode is disabled."""
    monkeypatch.setattr(db.settings, "json_schema_validation_strict", False)

    class Target:
        input_schema = {"type": "invalid"}

    with caplog.at_level(logging.WARNING):
        db.validate_tool_schema(None, None, Target())

    assert any("Invalid tool input schema" in record.message for record in caplog.records)


def test_validate_prompt_schema_invalid_non_strict(caplog, monkeypatch):
    """Test that invalid prompt schema only logs warning when strict mode is disabled."""
    monkeypatch.setattr(db.settings, "json_schema_validation_strict", False)

    class Target:
        argument_schema = {"type": "invalid"}

    with caplog.at_level(logging.WARNING):
        db.validate_prompt_schema(None, None, Target())

    assert any("Invalid prompt argument schema" in record.message for record in caplog.records)


def test_validate_tool_schema_defaults_to_draft202012(caplog):
    """Test that schemas without $schema field use Draft 2020-12 validator."""

    class Target:
        input_schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    with caplog.at_level(logging.WARNING):
        db.validate_tool_schema(None, None, Target())

    assert not any("Unsupported" in record.message for record in caplog.records)
    assert not any("Invalid" in record.message for record in caplog.records)


def test_validate_tool_name_missing():
    class Target:
        pass

    db.validate_tool_name(None, None, Target())  # Should not raise


def test_validate_prompt_schema_missing(caplog):
    class Target:
        pass  # No argument_schema

    # Should not log any warnings or raise
    with caplog.at_level(logging.WARNING):
        db.validate_prompt_schema(None, None, Target())

    # There should be no warnings
    assert len(caplog.records) == 0


def test_validate_prompt_schema_none(caplog):
    class Target:
        argument_schema = None  # Explicitly None

    # Should not log any warnings or raise
    with caplog.at_level(logging.WARNING):
        db.validate_prompt_schema(None, None, Target())

    # There should be no warnings
    assert len(caplog.records) == 0


def test_validate_prompt_schema_draft4(caplog):
    """Test prompt schema validation with Draft 4 style exclusiveMinimum."""

    class Target:
        argument_schema = {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 0, "exclusiveMinimum": True}},
        }

    with caplog.at_level(logging.WARNING):
        db.validate_prompt_schema(None, None, Target())

    # Valid Draft 4 schema should not log warnings
    assert not any("Invalid prompt argument schema" in record.message for record in caplog.records)


def test_validate_prompt_schema_draft2020_12(caplog):
    """Test prompt schema validation with Draft 2020-12 style schema."""

    class Target:
        argument_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }

    with caplog.at_level(logging.WARNING):
        db.validate_prompt_schema(None, None, Target())

    # Valid Draft 2020-12 schema should not log warnings
    assert not any("Invalid prompt argument schema" in record.message for record in caplog.records)


# --- get_db generator ---
def test_get_db_yields_and_closes(monkeypatch):
    class DummySession:
        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    dummy = DummySession()
    monkeypatch.setattr(db, "SessionLocal", lambda: dummy)
    gen = db.get_db()
    session = next(gen)
    assert session is dummy
    try:
        next(gen)
    except StopIteration:
        pass
    assert hasattr(dummy, "closed")
    assert hasattr(dummy, "committed")


def test_get_db_closes_on_exception(monkeypatch):
    class DummySession:
        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    dummy = DummySession()
    monkeypatch.setattr(db, "SessionLocal", lambda: dummy)

    gen = db.get_db()
    session = next(gen)
    assert session is dummy

    try:
        gen.throw(Exception("fail"))
    except Exception:
        pass

    assert hasattr(dummy, "closed")
    assert hasattr(dummy, "rolled_back")


# --- init_db ---
def test_init_db_success(monkeypatch):
    monkeypatch.setattr(db.Base.metadata, "create_all", lambda bind: True)
    db.init_db()


def test_init_db_failure(monkeypatch):
    def fail(*a, **k):
        raise SQLAlchemyError("fail")

    monkeypatch.setattr(db.Base.metadata, "create_all", fail)
    with pytest.raises(Exception):
        db.init_db()


# --- Gateway event listener ---
def test_update_tool_names_on_gateway_update(monkeypatch):
    class DummyGateway:
        id = "gwid"
        name = "GatewayName"

    class DummyConnection:
        def execute(self, stmt):
            self.executed = True

    class DummyMapper:
        pass

    monkeypatch.setattr(db.Tool, "__table__", MagicMock())
    monkeypatch.setattr(db, "slugify", lambda name: "slug")
    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "-")
    dummy_gateway = DummyGateway()
    dummy_connection = DummyConnection()
    dummy_mapper = DummyMapper()

    # Simulate get_history returning an object with has_changes = True
    class DummyHistory:
        def has_changes(self):
            return True

    monkeypatch.setattr(db, "get_history", lambda target, name: DummyHistory())
    db.update_tool_names_on_gateway_update(dummy_mapper, dummy_connection, dummy_gateway)
    assert hasattr(dummy_connection, "executed")


def test_set_prompt_name_and_slug(monkeypatch):
    class DummyGateway:
        name = "Gateway A"

    class DummyPrompt:
        original_name = "Greeting"
        custom_name = None
        custom_name_slug = ""
        display_name = None
        name = ""
        gateway = DummyGateway()

    monkeypatch.setattr(db, "slugify", lambda name: name.lower().replace(" ", "-"))
    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")

    prompt = DummyPrompt()
    db.set_prompt_name_and_slug(None, None, prompt)

    assert prompt.custom_name == "Greeting"
    assert prompt.custom_name_slug == "greeting"
    assert prompt.display_name == "Greeting"
    assert prompt.name == "gateway-a__greeting"


def test_set_prompt_name_and_slug_two_gateways(monkeypatch):
    class DummyGatewayA:
        name = "Gateway A"

    class DummyGatewayB:
        name = "Gateway B"

    class DummyPrompt:
        def __init__(self, gateway):
            self.original_name = "Greeting"
            self.custom_name = None
            self.custom_name_slug = ""
            self.display_name = None
            self.name = ""
            self.gateway = gateway

    monkeypatch.setattr(db, "slugify", lambda name: name.lower().replace(" ", "-"))
    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")

    prompt_a = DummyPrompt(DummyGatewayA())
    prompt_b = DummyPrompt(DummyGatewayB())

    db.set_prompt_name_and_slug(None, None, prompt_a)
    db.set_prompt_name_and_slug(None, None, prompt_b)

    assert prompt_a.name == "gateway-a__greeting"
    assert prompt_b.name == "gateway-b__greeting"
    assert prompt_a.name != prompt_b.name


def test_update_prompt_names_on_gateway_update(monkeypatch):
    class DummyGateway:
        id = "gwid"
        name = "GatewayName"

    class DummyConnection:
        def execute(self, stmt):
            self.executed = True

    class DummyMapper:
        pass

    monkeypatch.setattr(db.Prompt, "__table__", MagicMock())
    monkeypatch.setattr(db, "slugify", lambda name: "slug")
    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "-")
    dummy_gateway = DummyGateway()
    dummy_connection = DummyConnection()
    dummy_mapper = DummyMapper()

    class DummyHistory:
        def has_changes(self):
            return True

    monkeypatch.setattr(db, "get_history", lambda target, name: DummyHistory())
    db.update_prompt_names_on_gateway_update(dummy_mapper, dummy_connection, dummy_gateway)
    assert hasattr(dummy_connection, "executed")


# --- SessionRecord and SessionMessageRecord ---
def test_session_record_and_message_record():
    session = db.SessionRecord()
    session.session_id = "sid"
    session.data = "data"
    session.created_at = datetime.now(timezone.utc)
    session.last_accessed = datetime.now(timezone.utc)
    msg = db.SessionMessageRecord()
    msg.session_id = "sid"
    msg.message = "msg"
    msg.created_at = datetime.now(timezone.utc)
    msg.last_accessed = datetime.now(timezone.utc)
    session.messages = [msg]
    msg.session = session
    assert session.session_id == msg.session_id
    assert session.messages[0].message == "msg"
    assert msg.session.data == "data"


# --- extract_json_field ---
def test_extract_json_field_sqlite(monkeypatch):
    # Third-Party
    from sqlalchemy import Column, String
    from sqlalchemy.dialects import sqlite

    col = Column("attributes", String)
    monkeypatch.setattr(db, "backend", "sqlite")
    expr = db.extract_json_field(col, '$."tool.name"')
    compiled = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    assert "json_extract" in compiled
    assert '$."tool.name"' in compiled


def test_extract_json_field_postgresql(monkeypatch):
    # Third-Party
    from sqlalchemy import Column, String
    from sqlalchemy.dialects import postgresql

    col = Column("attributes", String)
    monkeypatch.setattr(db, "backend", "postgresql")
    expr = db.extract_json_field(col, '$."tool.name"')
    compiled = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "->>" in compiled
    assert "tool.name" in compiled


# --- RBAC role helpers ---
def test_role_effective_permissions_includes_parent():
    parent = db.Role(permissions=["resources.read", "tools.read"])
    child = db.Role(permissions=["tools.write"])
    child.parent_role = parent
    assert child.get_effective_permissions() == ["resources.read", "tools.read", "tools.write"]


def test_user_role_is_expired():
    role = db.UserRole(expires_at=None)
    assert role.is_expired() is False

    role.expires_at = db.utc_now() - timedelta(minutes=5)
    assert role.is_expired() is True


def test_permissions_helpers():
    permissions = db.Permissions.get_all_permissions()
    assert "tools.read" in permissions
    assert db.Permissions.ALL_PERMISSIONS not in permissions

    by_resource = db.Permissions.get_permissions_by_resource()
    assert "tools" in by_resource
    assert "tools.read" in by_resource["tools"]


# --- Email user helpers ---
def test_email_user_account_helpers():
    user = db.EmailUser(email="user@example.com", password_hash="hash")
    assert user.is_email_verified() is False
    user.email_verified_at = db.utc_now()
    assert user.is_email_verified() is True

    assert user.is_account_locked() is False
    user.locked_until = db.utc_now() + timedelta(minutes=10)
    assert user.is_account_locked() is True
    user.failed_login_attempts = 5
    user.locked_until = db.utc_now() - timedelta(minutes=1)
    assert user.is_account_locked() is False
    assert user.failed_login_attempts == 0
    assert user.locked_until is None

    user.full_name = "Test User"
    assert user.get_display_name() == "Test User"
    user.full_name = None
    assert user.get_display_name() == "user"


def test_email_user_failed_attempts_flow():
    user = db.EmailUser(email="user@example.com", password_hash="hash", failed_login_attempts=2)
    user.locked_until = db.utc_now() + timedelta(minutes=5)
    user.reset_failed_attempts()
    assert user.failed_login_attempts == 0
    assert user.locked_until is None
    assert user.last_login is not None

    user.failed_login_attempts = 0
    assert user.increment_failed_attempts(max_attempts=2, lockout_duration_minutes=1) is False
    assert user.increment_failed_attempts(max_attempts=2, lockout_duration_minutes=1) is True
    assert user.locked_until is not None


def test_password_reset_token_helpers():
    token = db.PasswordResetToken(
        user_email="user@example.com",
        token_hash="abcd" * 16,
        expires_at=db.utc_now() + timedelta(minutes=10),
    )
    assert token.is_expired() is False
    assert token.is_used() is False

    token.expires_at = db.utc_now() - timedelta(minutes=1)
    token.used_at = db.utc_now()
    assert token.is_expired() is True
    assert token.is_used() is True


def test_email_user_team_helpers():
    team = db.EmailTeam(name="Team", slug="team", created_by="user@example.com", is_personal=False)
    personal_team = db.EmailTeam(name="Personal", slug="personal", created_by="user@example.com", is_personal=True)
    inactive_team = db.EmailTeam(name="Inactive", slug="inactive", created_by="user@example.com", is_personal=True)
    personal_team.is_active = True
    inactive_team.is_active = False

    member_active = db.EmailTeamMember(user_email="user@example.com", team_id="team-1", role="owner", is_active=True)
    member_active.team = team
    member_inactive = db.EmailTeamMember(user_email="user@example.com", team_id="team-2", role="member", is_active=False)
    member_inactive.team = inactive_team

    user = db.EmailUser(email="user@example.com", password_hash="hash")
    user.team_memberships = [member_active, member_inactive]
    user.created_teams = [personal_team, inactive_team]

    assert user.get_teams() == [team]
    assert user.get_personal_team() == personal_team
    assert user.is_team_member("team-1") is True
    assert user.is_team_member("team-2") is False
    assert user.get_team_role("team-1") == "owner"
    assert user.get_team_role("team-2") is None


# --- Email team helpers ---
def test_email_team_member_helpers_detached():
    team = db.EmailTeam(name="Team", slug="team", created_by="user@example.com")
    member_active = db.EmailTeamMember(user_email="user@example.com", team_id="team-1", role="owner", is_active=True)
    member_inactive = db.EmailTeamMember(user_email="user@example.com", team_id="team-1", role="member", is_active=False)
    team.members = [member_active, member_inactive]

    assert team.get_member_count() == 1
    assert team.is_member("user@example.com") is True
    assert team.get_member_role("user@example.com") == "owner"
    assert team.is_member("other@example.com") is False
    assert team.get_member_role("other@example.com") is None


def test_email_team_member_helpers_session_path(monkeypatch):
    team = db.EmailTeam(name="Team", slug="team", created_by="user@example.com")
    team.id = "team-1"

    count_query = MagicMock()
    count_query.filter.return_value = count_query
    count_query.scalar.return_value = 3

    exists_query = MagicMock()
    exists_query.filter.return_value = exists_query
    exists_query.first.return_value = object()

    role_query = MagicMock()
    role_query.filter.return_value = role_query
    role_query.first.return_value = ("owner",)

    mock_session = MagicMock()
    mock_session.query.side_effect = [count_query, exists_query, role_query]

    monkeypatch.setattr("sqlalchemy.orm.object_session", lambda obj: mock_session)

    assert team.get_member_count() == 3
    assert team.is_member("user@example.com") is True
    assert team.get_member_role("user@example.com") == "owner"


# --- API token helpers ---
def test_email_api_token_helpers():
    token = db.EmailApiToken(
        user_email="user@example.com",
        name="token",
        token_hash="hash",
        server_id="server-1",
        resource_scopes=["tools.read"],
    )
    assert token.is_scoped_to_server("server-1") is True
    assert token.is_scoped_to_server("server-2") is False
    assert token.has_permission("tools.read") is True
    assert token.has_permission("tools.write") is False
    assert token.is_team_token() is False

    token.team_id = "team-1"
    assert token.is_team_token() is True

    token.expires_at = db.utc_now() - timedelta(minutes=1)
    token.is_active = True
    assert token.is_expired() is True
    assert token.is_valid() is False

    token.expires_at = None
    token.is_active = True
    assert token.is_valid() is True


# --- SSO auth session helpers ---
def test_sso_auth_session_is_expired_handles_naive_datetime():
    session = db.SSOAuthSession(provider_id="github", state="state", redirect_uri="http://example.com")
    # Force timezone-naive expiration to exercise mismatch handling.
    session.expires_at = (db.utc_now() - timedelta(minutes=1)).replace(tzinfo=None)
    assert session.is_expired is True


def test_email_team_join_request_is_expired_timezone_mismatch():
    """Ensure timezone mismatch is handled in join request expiration."""
    # Force timezone-naive expires_at to exercise mismatch handling.
    expires_at = (db.utc_now() - timedelta(minutes=1)).replace(tzinfo=None)
    join_request = db.EmailTeamJoinRequest(team_id="team-1", user_email="user@example.com", expires_at=expires_at)
    assert join_request.is_expired() is True


def test_pending_user_approval_is_expired_timezone_mismatch():
    """Ensure timezone mismatch is handled in pending approval expiration."""
    # Force timezone-naive expires_at to exercise mismatch handling.
    expires_at = (db.utc_now() - timedelta(minutes=1)).replace(tzinfo=None)
    approval = db.PendingUserApproval(email="user@example.com", full_name="User", auth_provider="github", expires_at=expires_at, status="pending")
    assert approval.is_expired() is True


def test_set_custom_name_and_slug_gateway_lookup():
    """Ensure tool name/slug is built using gateway lookup when needed."""
    tool = db.Tool(original_name="My Tool", gateway_id="gw-1")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ("Gateway Name",)

    db.set_custom_name_and_slug(None, connection, tool)

    assert tool.custom_name == "My Tool"
    assert tool.display_name == "My Tool"
    assert tool.custom_name_slug == db.slugify("My Tool")
    assert tool.name.startswith(db.slugify("Gateway Name"))


def test_set_prompt_name_and_slug_gateway_lookup():
    """Ensure prompt name/slug is built using gateway lookup when needed."""
    prompt = db.Prompt(name="Prompt Name", gateway_id="gw-2")
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ("Gateway Prompt",)

    db.set_prompt_name_and_slug(None, connection, prompt)

    assert prompt.original_name == "Prompt Name"
    assert prompt.custom_name == "Prompt Name"
    assert prompt.display_name == "Prompt Name"
    assert prompt.custom_name_slug == db.slugify("Prompt Name")
    assert prompt.name.startswith(db.slugify("Gateway Prompt"))


# --- Tool/Prompt name listeners additional branches ---
def test_set_custom_name_and_slug_uses_loaded_gateway_relationship(monkeypatch):
    class DummyGateway:
        def __init__(self, name: str):
            self.name = name

    class DummyTool:
        def __init__(self):
            self.custom_name = None
            self.original_name = "My Tool"
            self.display_name = None
            self.custom_name_slug = ""
            self.gateway = DummyGateway("Gateway Name")
            self.gateway_id = "gw-1"
            self.name = ""

    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    tool = DummyTool()
    db.set_custom_name_and_slug(None, None, tool)

    assert tool.name == "gateway-name__my-tool"


def test_set_custom_name_and_slug_uses_gateway_name_cache(monkeypatch):
    class DummyTool:
        def __init__(self):
            self.custom_name = None
            self.original_name = "My Tool"
            self.display_name = None
            self.custom_name_slug = ""
            self.gateway = None
            self.gateway_id = "gw-1"
            self.gateway_name_cache = "Cached Gateway"
            self.name = ""

    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    tool = DummyTool()
    db.set_custom_name_and_slug(None, None, tool)

    assert tool.name == "cached-gateway__my-tool"


def test_set_custom_name_and_slug_db_lookup_failure_falls_back_to_unprefixed(monkeypatch):
    class DummyTool:
        def __init__(self):
            self.custom_name = None
            self.original_name = "My Tool"
            self.display_name = None
            self.custom_name_slug = ""
            self.gateway = None
            self.gateway_id = "gw-1"
            self.name = ""

    class FailingConn:
        def execute(self, *_a, **_k):
            raise RuntimeError("boom")

    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    tool = DummyTool()
    db.set_custom_name_and_slug(None, FailingConn(), tool)

    assert tool.name == "my-tool"


def test_set_prompt_name_and_slug_uses_gateway_name_cache(monkeypatch):
    class DummyPrompt:
        def __init__(self):
            self.name = "Prompt Name"
            self.original_name = None
            self.custom_name = None
            self.display_name = None
            self.custom_name_slug = ""
            self.gateway = None
            self.gateway_id = "gw-1"
            self.gateway_name_cache = "Cached Gateway"

    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    prompt = DummyPrompt()
    db.set_prompt_name_and_slug(None, None, prompt)

    assert prompt.original_name == "Prompt Name"
    assert prompt.name == "cached-gateway__prompt-name"


def test_set_prompt_name_and_slug_db_lookup_failure_falls_back_to_unprefixed(monkeypatch):
    class DummyPrompt:
        def __init__(self):
            self.name = "Prompt Name"
            self.original_name = None
            self.custom_name = None
            self.display_name = None
            self.custom_name_slug = ""
            self.gateway = None
            self.gateway_id = "gw-1"

    class FailingConn:
        def execute(self, *_a, **_k):
            raise RuntimeError("boom")

    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    prompt = DummyPrompt()
    db.set_prompt_name_and_slug(None, FailingConn(), prompt)

    assert prompt.name == "prompt-name"


# --- build_engine additional branches ---
def test_build_engine_queue_pool_pre_ping_true_logs_echo(monkeypatch, caplog):
    monkeypatch.setattr(db, "backend", "postgresql")
    monkeypatch.setattr(db.settings, "database_url", "postgresql://user:pass@localhost/db")
    monkeypatch.setattr(db.settings, "db_pool_class", "queue")
    monkeypatch.setattr(db.settings, "db_pool_pre_ping", "true")
    monkeypatch.setattr(db.settings, "db_pool_size", 5)
    monkeypatch.setattr(db.settings, "db_max_overflow", 10)
    monkeypatch.setattr(db.settings, "db_pool_timeout", 30)
    monkeypatch.setattr(db.settings, "db_pool_recycle", 300)
    monkeypatch.setattr(db, "connect_args", {})
    monkeypatch.setattr(db, "_sqlalchemy_echo", True)

    with patch("mcpgateway.db.create_engine") as mock_create, caplog.at_level(logging.INFO):
        db.build_engine()

    # Echo line should be logged when _sqlalchemy_echo is enabled.
    assert any("SQLALCHEMY_ECHO enabled" in record.message for record in caplog.records)
    assert mock_create.call_args.kwargs["pool_pre_ping"] is True


def test_build_engine_queue_pool_pre_ping_false(monkeypatch):
    monkeypatch.setattr(db, "backend", "postgresql")
    monkeypatch.setattr(db.settings, "database_url", "postgresql://user:pass@localhost/db")
    monkeypatch.setattr(db.settings, "db_pool_class", "queue")
    monkeypatch.setattr(db.settings, "db_pool_pre_ping", "false")
    monkeypatch.setattr(db.settings, "db_pool_size", 1)
    monkeypatch.setattr(db.settings, "db_max_overflow", 2)
    monkeypatch.setattr(db.settings, "db_pool_timeout", 3)
    monkeypatch.setattr(db.settings, "db_pool_recycle", 4)
    monkeypatch.setattr(db, "connect_args", {})

    with patch("mcpgateway.db.create_engine") as mock_create:
        db.build_engine()
        assert mock_create.call_args.kwargs["pool_pre_ping"] is False


def test_build_engine_queue_pool_pgbouncer_auto_pre_ping_logs_hint(monkeypatch, caplog):
    monkeypatch.setattr(db, "backend", "postgresql")
    monkeypatch.setattr(db.settings, "database_url", "postgresql://user:pass@pgbouncer.example/db")
    monkeypatch.setattr(db.settings, "db_pool_class", "queue")
    monkeypatch.setattr(db.settings, "db_pool_pre_ping", "auto")
    monkeypatch.setattr(db.settings, "db_pool_size", 1)
    monkeypatch.setattr(db.settings, "db_max_overflow", 2)
    monkeypatch.setattr(db.settings, "db_pool_timeout", 3)
    monkeypatch.setattr(db.settings, "db_pool_recycle", 4)
    monkeypatch.setattr(db, "connect_args", {})

    with patch("mcpgateway.db.create_engine"), caplog.at_level(logging.INFO):
        db.build_engine()

    assert any("PgBouncer with QueuePool" in record.message for record in caplog.records)


# --- get_db nested rollback/invalidate best-effort path ---
def test_get_db_rollback_failure_invalidates_best_effort(monkeypatch):
    class DummySession:
        def commit(self):
            self.committed = True

        def rollback(self):
            raise RuntimeError("rollback boom")

        def invalidate(self):
            raise RuntimeError("invalidate boom")

        def close(self):
            self.closed = True

    dummy = DummySession()
    monkeypatch.setattr(db, "SessionLocal", lambda: dummy)

    gen = db.get_db()
    _ = next(gen)
    with pytest.raises(Exception):
        gen.throw(Exception("fail"))

    assert hasattr(dummy, "closed")


# --- ResilientSession / pool resilience helpers ---
def test_resilient_session_is_connection_error_patterns_and_fallback():
    session = db.ResilientSession(bind=db.engine)
    assert session._is_connection_error(Exception("query_wait_timeout")) is True
    assert session._is_connection_error(Exception("some other error")) is False


def test_resilient_session_safe_rollback_best_effort(monkeypatch):
    session = db.ResilientSession(bind=db.engine)
    monkeypatch.setattr(session, "rollback", lambda: (_ for _ in ()).throw(RuntimeError("rb")))
    monkeypatch.setattr(session, "invalidate", lambda: (_ for _ in ()).throw(RuntimeError("inv")))
    session._safe_rollback()  # Should not raise


def test_resilient_session_scalar_rolls_back_on_connection_error(monkeypatch):
    class ProtocolViolation(Exception):
        pass

    def boom(_self, _statement, _params=None, **_kw):
        raise ProtocolViolation("server closed the connection unexpectedly")

    monkeypatch.setattr(db.Session, "scalar", boom)
    session = db.ResilientSession(bind=db.engine)
    rollback_spy = MagicMock()
    monkeypatch.setattr(session, "_safe_rollback", rollback_spy)

    with pytest.raises(ProtocolViolation):
        session.scalar("SELECT 1")

    rollback_spy.assert_called_once()


def test_resilient_session_scalars_rolls_back_on_connection_error(monkeypatch):
    class ProtocolViolation(Exception):
        pass

    def boom(_self, _statement, _params=None, **_kw):
        raise ProtocolViolation("connection reset by peer")

    monkeypatch.setattr(db.Session, "scalars", boom)
    session = db.ResilientSession(bind=db.engine)
    rollback_spy = MagicMock()
    monkeypatch.setattr(session, "_safe_rollback", rollback_spy)

    with pytest.raises(ProtocolViolation):
        session.scalars("SELECT 1")

    rollback_spy.assert_called_once()


def test_handle_pool_error_original_none_noop():
    class Ctx:
        def __init__(self):
            self.original_exception = None
            self.is_disconnect = False

    ctx = Ctx()
    db.handle_pool_error(ctx)
    assert ctx.is_disconnect is False


def test_handle_pool_error_marks_disconnect_on_pattern_match():
    class OperationalError(Exception):
        pass

    class Ctx:
        def __init__(self, original_exception):
            self.original_exception = original_exception
            self.is_disconnect = False

    ctx = Ctx(OperationalError("query_wait_timeout"))
    db.handle_pool_error(ctx)
    assert ctx.is_disconnect is True


def test_handle_pool_error_protocol_violation_always_disconnect():
    class ProtocolViolation(Exception):
        pass

    class Ctx:
        def __init__(self, original_exception):
            self.original_exception = original_exception
            self.is_disconnect = False

    ctx = Ctx(ProtocolViolation("some other message"))
    db.handle_pool_error(ctx)
    assert ctx.is_disconnect is True


def test_reset_connection_on_checkin_rolls_back_or_closes_best_effort():
    class Conn:
        def __init__(self):
            self.close_called = False

        def rollback(self):
            raise RuntimeError("rb failed")

        def close(self):
            self.close_called = True
            raise RuntimeError("close failed")

    conn = Conn()
    db.reset_connection_on_checkin(conn, None)
    assert conn.close_called is True


def test_reset_connection_on_reset_swallows_rollback_failure():
    class Conn:
        def rollback(self):
            raise RuntimeError("rb failed")

    db.reset_connection_on_reset(Conn(), None, None)


def test_before_commit_handler_flush_failure_is_swallowed():
    class DummySession:
        def flush(self):
            raise RuntimeError("boom")

    db.before_commit_handler(DummySession())


# --- Slug/name refresh helpers ---
def test_refresh_gateway_slugs_batched_updates_and_commits(monkeypatch):
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    class GatewayObj:
        def __init__(self, gid: str, name: str, slug: str):
            self.id = gid
            self.name = name
            self.slug = slug

    batch1 = [GatewayObj("1", "Gateway A", "wrong"), GatewayObj("2", "Gateway B", "gateway-b")]
    batch2 = []

    class DummyQuery:
        def __init__(self, session):
            self._session = session

        def order_by(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            self._session.filtered = True
            return self

        def limit(self, *_a, **_k):
            return self

        def all(self):
            batches = self._session.batches
            idx = self._session.batch_idx
            self._session.batch_idx += 1
            return batches[idx]

    class DummySession:
        def __init__(self):
            self.batches = [batch1, batch2]
            self.batch_idx = 0
            self.commits = 0
            self.expired = 0
            self.filtered = False

        def query(self, *_a, **_k):
            return DummyQuery(self)

        def commit(self):
            self.commits += 1

        def expire_all(self):
            self.expired += 1

    session = DummySession()
    db._refresh_gateway_slugs_batched(session, batch_size=100)

    assert session.filtered is True  # second loop iteration applied last_id filter
    assert session.commits == 1
    assert session.expired >= 1
    assert batch1[0].slug == "gateway-a"


def test_refresh_tool_names_batched_updates_and_commits(monkeypatch):
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))
    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")

    class GatewayObj:
        def __init__(self, name: str):
            self.name = name

    class ToolObj:
        def __init__(self, tid: str, original_name: str, name: str, gateway=None, custom_name_slug=None):
            self.id = tid
            self.original_name = original_name
            self.name = name
            self.gateway = gateway
            if custom_name_slug is not None:
                self.custom_name_slug = custom_name_slug

    tools_batch = [
        ToolObj("1", "Original", "old", gateway=GatewayObj("Gateway A"), custom_name_slug="custom-slug"),
        ToolObj("2", "Second Tool", "old2", gateway=None),
    ]

    class DummyScalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class DummyResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return DummyScalars(self._rows)

    class DummySession:
        def __init__(self):
            self.calls = 0
            self.commits = 0
            self.expired = 0

        def execute(self, _stmt):
            self.calls += 1
            return DummyResult(tools_batch if self.calls == 1 else [])

        def commit(self):
            self.commits += 1

        def expire_all(self):
            self.expired += 1

    session = DummySession()
    db._refresh_tool_names_batched(session, batch_size=100)

    assert session.commits == 1
    assert session.expired >= 1
    assert tools_batch[0].name == "gateway-a__custom-slug"
    assert tools_batch[1].name == "second-tool"


def test_refresh_prompt_names_batched_updates_and_commits(monkeypatch):
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))
    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")

    class GatewayObj:
        def __init__(self, name: str):
            self.name = name

    class PromptObj:
        def __init__(self, pid: str, original_name: str, name: str, gateway=None, custom_name_slug=None):
            self.id = pid
            self.original_name = original_name
            self.name = name
            self.gateway = gateway
            if custom_name_slug is not None:
                self.custom_name_slug = custom_name_slug

    prompts_batch = [
        PromptObj("1", "Original", "old", gateway=GatewayObj("Gateway A"), custom_name_slug="custom-slug"),
        PromptObj("2", "Second Prompt", "old2", gateway=None),
    ]

    class DummyScalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class DummyResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return DummyScalars(self._rows)

    class DummySession:
        def __init__(self):
            self.calls = 0
            self.commits = 0
            self.expired = 0

        def execute(self, _stmt):
            self.calls += 1
            return DummyResult(prompts_batch if self.calls == 1 else [])

        def commit(self):
            self.commits += 1

        def expire_all(self):
            self.expired += 1

    session = DummySession()
    db._refresh_prompt_names_batched(session, batch_size=100)

    assert session.commits == 1
    assert session.expired >= 1
    assert prompts_batch[0].name == "gateway-a__custom-slug"
    assert prompts_batch[1].name == "second-prompt"


def test_refresh_slugs_on_startup_tool_and_prompt_missing_tables(monkeypatch, caplog):
    # Third-Party
    from sqlalchemy.exc import OperationalError, ProgrammingError

    class DummySession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(db, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(db, "_refresh_gateway_slugs_batched", lambda *_a, **_k: None)
    monkeypatch.setattr(db, "_refresh_tool_names_batched", lambda *_a, **_k: (_ for _ in ()).throw(ProgrammingError("stmt", {}, Exception("orig"))))
    monkeypatch.setattr(db, "_refresh_prompt_names_batched", lambda *_a, **_k: (_ for _ in ()).throw(OperationalError("stmt", {}, Exception("orig"))))

    with caplog.at_level(logging.INFO):
        db.refresh_slugs_on_startup(batch_size=10)

    assert any("Tool table not found" in record.message for record in caplog.records)
    assert any("Prompt table not found" in record.message for record in caplog.records)


def test_refresh_slugs_on_startup_outer_sqlalchemy_error(monkeypatch, caplog):
    # Third-Party
    from sqlalchemy.exc import SQLAlchemyError

    class DummySession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(db, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(db, "_refresh_gateway_slugs_batched", lambda *_a, **_k: (_ for _ in ()).throw(SQLAlchemyError("boom")))

    with caplog.at_level(logging.WARNING):
        db.refresh_slugs_on_startup(batch_size=10)

    assert any("database error" in record.message for record in caplog.records)


def test_refresh_slugs_on_startup_outer_unexpected_error(monkeypatch, caplog):
    class DummySession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(db, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(db, "_refresh_gateway_slugs_batched", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))

    with caplog.at_level(logging.WARNING):
        db.refresh_slugs_on_startup(batch_size=10)

    assert any("unexpected error" in record.message for record in caplog.records)


# --- Metrics: detached/no-session paths not covered by loaded/SQL tests ---
def test_tool_timing_properties_return_none_when_metrics_not_loaded():
    tool = db.Tool()
    assert tool.min_response_time is None
    assert tool.max_response_time is None
    assert tool.avg_response_time is None
    assert tool.last_execution_time is None


def test_resource_metric_counts_and_timing_are_safe_when_detached():
    resource = db.Resource()
    assert resource._get_metric_counts() == (0, 0, 0)
    assert resource.min_response_time is None
    assert resource.max_response_time is None
    assert resource.avg_response_time is None
    assert resource.last_execution_time is None

    summary = resource.metrics_summary
    assert summary["total_executions"] == 0
    assert summary["failure_rate"] == 0.0


def test_prompt_metric_counts_and_timing_are_safe_when_detached():
    prompt = db.Prompt()
    assert prompt._get_metric_counts() == (0, 0, 0)
    assert prompt.min_response_time is None
    assert prompt.max_response_time is None
    assert prompt.avg_response_time is None
    assert prompt.last_execution_time is None

    summary = prompt.metrics_summary
    assert summary["total_executions"] == 0
    assert summary["failure_rate"] == 0.0


def test_server_metric_counts_and_timing_are_safe_when_detached():
    server = db.Server()
    assert server._get_metric_counts() == (0, 0, 0)
    assert server.min_response_time is None
    assert server.max_response_time is None
    assert server.avg_response_time is None
    assert server.last_execution_time is None

    summary = server.metrics_summary
    assert summary["total_executions"] == 0
    assert summary["failure_rate"] == 0.0


def test_a2a_agent_metrics_properties_loaded_and_unloaded():
    now = db.utc_now()
    agent = db.A2AAgent(name="Agent", slug="agent", endpoint_url="http://example.com")

    # Unloaded metrics: should avoid lazy loading and return safe defaults.
    assert agent.execution_count == 0
    assert agent.successful_executions == 0
    assert agent.failed_executions == 0
    assert agent.failure_rate == 0.0
    assert agent.avg_response_time is None
    assert agent.last_execution_time is None

    agent.metrics = [
        db.A2AAgentMetric(a2a_agent_id="a", response_time=1.0, is_success=True, timestamp=now),
        db.A2AAgentMetric(a2a_agent_id="a", response_time=3.0, is_success=False, timestamp=now + timedelta(seconds=1)),
    ]
    assert agent.execution_count == 2
    assert agent.successful_executions == 1
    assert agent.failed_executions == 1
    assert agent.failure_rate == 50.0
    assert agent.avg_response_time == 2.0
    assert agent.last_execution_time == now + timedelta(seconds=1)


# --- Hybrid expressions (class-level access) ---
def test_hybrid_property_expressions_compile():
    # Third-Party
    from sqlalchemy import select

    stmt = select(
        db.Tool.gateway_slug,
        db.Tool.execution_count,
        db.Resource.execution_count,
        db.Prompt.gateway_slug,
        db.Prompt.execution_count,
        db.Server.execution_count,
    )
    compiled = str(stmt)
    assert "SELECT" in compiled


# --- Gateway rename listeners: early return when name unchanged ---
def test_update_tool_names_on_gateway_update_no_name_change_returns(monkeypatch):
    class DummyHistory:
        def has_changes(self):
            return False

    connection = MagicMock()
    monkeypatch.setattr(db, "get_history", lambda *_a, **_k: DummyHistory())
    db.update_tool_names_on_gateway_update(None, connection, object())
    connection.execute.assert_not_called()


def test_update_prompt_names_on_gateway_update_no_name_change_returns(monkeypatch):
    class DummyHistory:
        def has_changes(self):
            return False

    connection = MagicMock()
    monkeypatch.setattr(db, "get_history", lambda *_a, **_k: DummyHistory())
    db.update_prompt_names_on_gateway_update(None, connection, object())
    connection.execute.assert_not_called()


# --- JSON schema validation: unsupported drafts produce warnings ---
def test_validate_tool_schema_logs_unsupported_draft(caplog):
    class Target:
        input_schema = {"$schema": "http://json-schema.org/draft-03/schema#", "type": "object"}

    with caplog.at_level(logging.WARNING):
        db.validate_tool_schema(None, None, Target())

    assert any("Unsupported JSON Schema draft" in record.message for record in caplog.records)


def test_validate_prompt_schema_logs_unsupported_draft(caplog):
    class Target:
        argument_schema = {"$schema": "http://json-schema.org/draft-03/schema#", "type": "object"}

    with caplog.at_level(logging.WARNING):
        db.validate_prompt_schema(None, None, Target())

    assert any("Unsupported JSON Schema draft" in record.message for record in caplog.records)


# --- MariaDB VARCHAR patching helper ---
def test_patch_string_columns_for_mariadb_sets_varchar_length():
    # Standard
    from types import SimpleNamespace

    # Third-Party
    from sqlalchemy import Column, MetaData, String, Table
    from sqlalchemy.sql.sqltypes import VARCHAR

    md = MetaData()
    tbl = Table("t", md, Column("c1", String()), Column("c2", String(10)))
    base = SimpleNamespace(metadata=md)
    engine_ = SimpleNamespace(dialect=SimpleNamespace(name="mariadb"))

    db.patch_string_columns_for_mariadb(base, engine_)

    assert isinstance(tbl.c.c1.type, VARCHAR)
    assert tbl.c.c1.type.length == 255
    assert tbl.c.c2.type.length == 10


def test_patch_string_columns_for_mariadb_non_mariadb_noop():
    # Standard
    from types import SimpleNamespace

    # Third-Party
    from sqlalchemy import Column, MetaData, String, Table

    md = MetaData()
    tbl = Table("t", md, Column("c1", String()))
    base = SimpleNamespace(metadata=md)
    engine_ = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    db.patch_string_columns_for_mariadb(base, engine_)
    assert isinstance(tbl.c.c1.type, String)
    assert tbl.c.c1.type.length is None


# --- EmailApiToken permissions helper ---
def test_email_api_token_get_effective_permissions_team_token():
    team = db.EmailTeam(name="Team", slug="team", created_by="user@example.com", is_personal=False)
    token = db.EmailApiToken(user_email="user@example.com", name="token", token_hash="hash", team_id="team-1", resource_scopes=["tools.read"])
    token.team = team

    assert token.get_effective_permissions() == ["tools.read"]


# --- Invitation/join request/pending approval expiration mismatch paths ---
def test_email_team_invitation_is_expired_handles_timezone_mismatch(monkeypatch):
    # expires_at naive, now aware
    expires_at = (db.utc_now() - timedelta(minutes=1)).replace(tzinfo=None)
    inv = db.EmailTeamInvitation(team_id="t", email="u@example.com", invited_by="admin@example.com", expires_at=expires_at, token="tok")
    assert inv.is_expired() is True

    # now naive, expires_at aware
    aware_expires = db.utc_now() + timedelta(minutes=1)
    inv2 = db.EmailTeamInvitation(team_id="t", email="u2@example.com", invited_by="admin@example.com", expires_at=aware_expires, token="tok2")
    monkeypatch.setattr(db, "utc_now", lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))  # naive now (UTC-based)
    assert inv2.is_expired() is False


def test_email_team_join_request_is_expired_handles_timezone_mismatch_now_naive(monkeypatch):
    expires_at = db.utc_now() + timedelta(minutes=1)
    join_request = db.EmailTeamJoinRequest(team_id="team-1", user_email="user@example.com", expires_at=expires_at)
    monkeypatch.setattr(db, "utc_now", lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))  # naive now (UTC-based)
    assert join_request.is_expired() is False


def test_pending_user_approval_is_expired_handles_timezone_mismatch_now_naive(monkeypatch):
    expires_at = db.utc_now() + timedelta(minutes=1)
    approval = db.PendingUserApproval(email="user@example.com", full_name="User", auth_provider="github", expires_at=expires_at, status="pending")
    monkeypatch.setattr(db, "utc_now", lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))  # naive now (UTC-based)
    assert approval.is_expired() is False


def test_sso_auth_session_is_expired_handles_timezone_mismatch_now_naive(monkeypatch):
    session = db.SSOAuthSession(provider_id="github", state="state2", redirect_uri="http://example.com")
    session.expires_at = db.utc_now() + timedelta(minutes=1)
    monkeypatch.setattr(db, "utc_now", lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))  # naive now (UTC-based)
    assert session.is_expired is False


def test_email_team_join_request_is_pending_true():
    join_request = db.EmailTeamJoinRequest(team_id="team-1", user_email="user@example.com", expires_at=db.utc_now() + timedelta(minutes=5), status="pending")
    assert join_request.is_pending() is True


# --- get_for_update missing branches ---
def test_get_for_update_returns_none_when_no_where_or_id():
    # Standard
    from types import SimpleNamespace

    db_session = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    assert db.get_for_update(db_session, db.Tool) is None


def test_get_for_update_postgresql_sets_lock_timeout_and_runs_query():
    # Standard
    from types import SimpleNamespace

    calls = []

    class Result:
        def scalar_one_or_none(self):
            return "row"

    class DummyDB:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, stmt):
            calls.append(stmt)
            return Result()

    db_session = DummyDB()
    result = db.get_for_update(db_session, db.Tool, entity_id="tool-1", lock_timeout_ms=50, nowait=True)

    assert result == "row"
    assert any("SET LOCAL lock_timeout" in str(stmt) for stmt in calls)


# --- Other slug listeners ---
def test_set_grpc_service_slug_sets_slug(monkeypatch):
    class Target:
        def __init__(self):
            self.name = "My Service"
            self.slug = ""

    monkeypatch.setattr(db, "slugify", lambda s: "my-service")
    target = Target()
    db.set_grpc_service_slug(None, None, target)
    assert target.slug == "my-service"


def test_set_llm_provider_slug_sets_slug(monkeypatch):
    class Target:
        def __init__(self):
            self.name = "My Provider"
            self.slug = ""

    monkeypatch.setattr(db, "slugify", lambda s: "my-provider")
    target = Target()
    db.set_llm_provider_slug(None, None, target)
    assert target.slug == "my-provider"


# --- Module-level config parsing and observability branches (requires reload) ---
def test_db_module_connect_args_postgresql_options_and_prepare_threshold(monkeypatch, caplog):
    # Standard
    import importlib

    # Third-Party
    import sqlalchemy

    original_url = db.settings.database_url
    original_prepare = db.settings.db_prepare_threshold
    original_obs = db.settings.observability_enabled

    try:
        monkeypatch.setattr(db.settings, "database_url", "postgresql+psycopg://user:pass@host:5432/db?options=-c%20search_path=mcp_gateway")
        monkeypatch.setattr(db.settings, "db_prepare_threshold", 123)
        monkeypatch.setattr(db.settings, "observability_enabled", False)

        real_create_engine = sqlalchemy.create_engine

        def safe_create_engine(*_a, **_k):
            # Use an in-memory SQLite engine so SQLAlchemy events can attach cleanly.
            return real_create_engine("sqlite+pysqlite:///:memory:")

        with monkeypatch.context() as m, caplog.at_level(logging.INFO):
            m.setattr(sqlalchemy, "create_engine", safe_create_engine)
            importlib.reload(db)

        assert db.backend == "postgresql"
        assert db.driver in ("psycopg", "default", "")
        assert db.connect_args["keepalives"] == 1
        assert db.connect_args["prepare_threshold"] == 123
        assert db.connect_args["options"] == "-c search_path=mcp_gateway"
        assert any("PostgreSQL connection options applied" in record.message for record in caplog.records)
        assert any("psycopg3 prepare_threshold set to 123" in record.message for record in caplog.records)
    finally:
        monkeypatch.setattr(db.settings, "database_url", original_url)
        monkeypatch.setattr(db.settings, "db_prepare_threshold", original_prepare)
        monkeypatch.setattr(db.settings, "observability_enabled", original_obs)
        importlib.reload(db)


def test_db_module_observability_instrumentation_success(monkeypatch, caplog):
    # Standard
    import importlib
    import sys
    import types

    # Third-Party
    import sqlalchemy

    original_url = db.settings.database_url
    original_obs = db.settings.observability_enabled

    called = {}

    def instrument_sqlalchemy(engine):
        called["engine"] = engine

    dummy_mod = types.ModuleType("mcpgateway.instrumentation")
    dummy_mod.instrument_sqlalchemy = instrument_sqlalchemy

    try:
        monkeypatch.setattr(db.settings, "database_url", "sqlite+pysqlite:///:memory:")
        monkeypatch.setattr(db.settings, "observability_enabled", True)
        monkeypatch.setitem(sys.modules, "mcpgateway.instrumentation", dummy_mod)

        real_create_engine = sqlalchemy.create_engine

        def safe_create_engine(*_a, **_k):
            return real_create_engine("sqlite+pysqlite:///:memory:")

        with monkeypatch.context() as m, caplog.at_level(logging.INFO):
            m.setattr(sqlalchemy, "create_engine", safe_create_engine)
            importlib.reload(db)

        assert called["engine"] is db.engine
        assert any("SQLAlchemy instrumentation enabled" in record.message for record in caplog.records)
    finally:
        monkeypatch.setattr(db.settings, "database_url", original_url)
        monkeypatch.setattr(db.settings, "observability_enabled", original_obs)
        importlib.reload(db)


def test_db_module_observability_instrumentation_importerror(monkeypatch, caplog):
    # Standard
    import builtins
    import importlib

    # Third-Party
    import sqlalchemy

    original_url = db.settings.database_url
    original_obs = db.settings.observability_enabled

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mcpgateway.instrumentation":
            raise ImportError("boom")
        return real_import(name, globals, locals, fromlist, level)

    try:
        monkeypatch.setattr(db.settings, "database_url", "sqlite+pysqlite:///:memory:")
        monkeypatch.setattr(db.settings, "observability_enabled", True)
        monkeypatch.setattr(builtins, "__import__", fake_import)

        real_create_engine = sqlalchemy.create_engine

        def safe_create_engine(*_a, **_k):
            return real_create_engine("sqlite+pysqlite:///:memory:")

        with monkeypatch.context() as m, caplog.at_level(logging.WARNING):
            m.setattr(sqlalchemy, "create_engine", safe_create_engine)
            importlib.reload(db)

        assert any("Failed to import SQLAlchemy instrumentation" in record.message for record in caplog.records)
    finally:
        monkeypatch.setattr(db.settings, "database_url", original_url)
        monkeypatch.setattr(db.settings, "observability_enabled", original_obs)
        importlib.reload(db)


# --- Additional coverage for remaining missing statements in mcpgateway/db.py ---
def test_set_sqlite_pragma_executes_expected_pragmas(monkeypatch):
    # Only defined when backend == "sqlite"
    assert db.backend == "sqlite"

    monkeypatch.setattr(db.settings, "db_sqlite_busy_timeout", 1234)

    executed = []

    class DummyCursor:
        def execute(self, sql):
            executed.append(sql)

        def close(self):
            executed.append("close")

    class DummyConn:
        def cursor(self):
            return DummyCursor()

    db.set_sqlite_pragma(DummyConn(), None)

    assert "PRAGMA journal_mode=WAL" in executed
    assert any("PRAGMA busy_timeout=1234" in s for s in executed)
    assert "PRAGMA synchronous=NORMAL" in executed
    assert "PRAGMA cache_size=-64000" in executed
    assert "PRAGMA foreign_keys=ON" in executed
    assert "close" in executed


def test_resilient_session_execute_rolls_back_on_connection_error(monkeypatch):
    class ProtocolViolation(Exception):
        pass

    def boom(_self, _statement, _params=None, **_kw):
        raise ProtocolViolation("connection timed out")

    monkeypatch.setattr(db.Session, "execute", boom)
    session = db.ResilientSession(bind=db.engine)
    rollback_spy = MagicMock()
    monkeypatch.setattr(session, "_safe_rollback", rollback_spy)

    with pytest.raises(ProtocolViolation):
        session.execute("SELECT 1")

    rollback_spy.assert_called_once()


def test_resilient_session_execute_does_not_rollback_for_non_connection_error(monkeypatch):
    class OtherError(Exception):
        pass

    def boom(_self, _statement, _params=None, **_kw):
        raise OtherError("not a connection error")

    monkeypatch.setattr(db.Session, "execute", boom)
    session = db.ResilientSession(bind=db.engine)
    rollback_spy = MagicMock()
    monkeypatch.setattr(session, "_safe_rollback", rollback_spy)

    with pytest.raises(OtherError):
        session.execute("SELECT 1")

    rollback_spy.assert_not_called()


def test_resilient_session_scalar_does_not_rollback_for_non_connection_error(monkeypatch):
    class OtherError(Exception):
        pass

    def boom(_self, _statement, _params=None, **_kw):
        raise OtherError("not a connection error")

    monkeypatch.setattr(db.Session, "scalar", boom)
    session = db.ResilientSession(bind=db.engine)
    rollback_spy = MagicMock()
    monkeypatch.setattr(session, "_safe_rollback", rollback_spy)

    with pytest.raises(OtherError):
        session.scalar("SELECT 1")

    rollback_spy.assert_not_called()


def test_resilient_session_scalars_does_not_rollback_for_non_connection_error(monkeypatch):
    class OtherError(Exception):
        pass

    def boom(_self, _statement, _params=None, **_kw):
        raise OtherError("not a connection error")

    monkeypatch.setattr(db.Session, "scalars", boom)
    session = db.ResilientSession(bind=db.engine)
    rollback_spy = MagicMock()
    monkeypatch.setattr(session, "_safe_rollback", rollback_spy)

    with pytest.raises(OtherError):
        session.scalars("SELECT 1")

    rollback_spy.assert_not_called()


def test_handle_pool_error_non_connection_error_noop():
    class Ctx:
        def __init__(self, original_exception):
            self.original_exception = original_exception
            self.is_disconnect = False

    ctx = Ctx(ValueError("query_wait_timeout"))
    db.handle_pool_error(ctx)
    assert ctx.is_disconnect is False


def test_refresh_slugs_on_startup_gateway_table_missing_returns(monkeypatch, caplog):
    # Third-Party
    from sqlalchemy.exc import OperationalError

    class DummySession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(db, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(db, "_refresh_gateway_slugs_batched", lambda *_a, **_k: (_ for _ in ()).throw(OperationalError("stmt", {}, Exception("orig"))))

    with caplog.at_level(logging.INFO):
        db.refresh_slugs_on_startup(batch_size=10)

    assert any("Gateway table not found" in record.message for record in caplog.records)


def test_email_user_get_personal_team_returns_none_when_missing():
    user = db.EmailUser(email="user@example.com", password_hash="hash")
    user.created_teams = []
    assert user.get_personal_team() is None


def test_email_auth_event_factory_methods():
    evt = db.EmailAuthEvent.create_login_attempt(user_email="user@example.com", success=True, ip_address="127.0.0.1")
    assert evt.event_type == "login"
    assert evt.success is True

    evt2 = db.EmailAuthEvent.create_registration_event(user_email="user@example.com", success=False)
    assert evt2.event_type == "registration"
    assert evt2.success is False

    evt3 = db.EmailAuthEvent.create_password_change_event(user_email="user@example.com", success=True)
    assert evt3.event_type == "password_change"


def test_pending_user_approval_approve_and_reject():
    approval = db.PendingUserApproval(email="user@example.com", full_name="User", auth_provider="github", expires_at=db.utc_now() + timedelta(minutes=5), status="pending")
    approval.approve(admin_email="admin@example.com", notes="ok")
    assert approval.status == "approved"
    assert approval.approved_by == "admin@example.com"
    assert approval.approved_at is not None
    assert approval.admin_notes == "ok"

    approval2 = db.PendingUserApproval(email="user2@example.com", full_name="User2", auth_provider="github", expires_at=db.utc_now() + timedelta(minutes=5), status="pending")
    approval2.reject(admin_email="admin@example.com", reason="nope", notes="details")
    assert approval2.status == "rejected"
    assert approval2.rejection_reason == "nope"
    assert approval2.admin_notes == "details"


def test_email_team_invitation_is_valid():
    inv = db.EmailTeamInvitation(team_id="t", email="u@example.com", invited_by="admin@example.com", expires_at=db.utc_now() + timedelta(minutes=5), token="tok", is_active=True)
    assert inv.is_valid() is True


def test_team_properties_on_tool_server_gateway():
    team = db.EmailTeam(name="Team", slug="team", created_by="user@example.com", is_personal=False)
    team.is_active = True

    tool = db.Tool()
    tool.email_team = team
    assert tool.team == "Team"

    server = db.Server()
    server.email_team = team
    assert server.team == "Team"

    gateway = db.Gateway(name="Gateway", slug="gw", url="http://example.com")
    gateway.email_team = team
    assert gateway.team == "Team"


def test_tool_name_and_gateway_slug_instance_and_expression(monkeypatch):
    monkeypatch.setattr(db.settings, "gateway_tool_name_separator", "__")
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    gateway = db.Gateway(name="Gateway Name", slug="gateway-name", url="http://example.com")
    tool = db.Tool()
    tool.gateway = gateway
    tool.gateway_id = "gw-1"
    tool.custom_name_slug = "My Tool"
    # Ensure stored value is unset so hybrid_property computes from gateway/custom slug.
    tool._computed_name = ""

    assert tool.gateway_slug == "gateway-name"
    assert tool.name == "gateway-name__my-tool"

    # Expression should resolve to stored column.
    # Third-Party
    from sqlalchemy import select

    stmt = select(db.Tool.name)
    assert "SELECT" in str(stmt)


def test_tool_name_computed_without_gateway_id_returns_custom_slug(monkeypatch):
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    tool = db.Tool()
    tool.custom_name_slug = "My Tool"
    tool._computed_name = ""  # force computed path
    tool.gateway_id = None

    assert tool.name == "my-tool"


def test_prompt_gateway_slug_instance_property():
    gateway = db.Gateway(name="Gateway Name", slug="gateway-name", url="http://example.com")
    prompt = db.Prompt()
    prompt.gateway = gateway
    assert prompt.gateway_slug == "gateway-name"


def test_a2a_agent_metrics_empty_list_paths():
    agent = db.A2AAgent(name="Agent", slug="agent", endpoint_url="http://example.com")
    agent.metrics = []  # loaded but empty
    assert agent.failure_rate == 0.0
    assert agent.avg_response_time is None
    assert agent.last_execution_time is None


def test_email_api_token_get_effective_permissions_non_team_token():
    token = db.EmailApiToken(user_email="user@example.com", name="token", token_hash="hash", resource_scopes=["tools.read"])
    assert token.get_effective_permissions() == ["tools.read"]


def test_get_for_update_dialect_detection_exception_path():
    # No bind attribute -> dialect detection falls back to empty string
    assert db.get_for_update(object(), db.Tool) is None


def test_get_for_update_where_and_options_paths():
    # Standard
    from types import SimpleNamespace

    # Third-Party
    from sqlalchemy.orm import joinedload

    executed = []

    class Result:
        def scalar_one_or_none(self):
            return "row"

    class DummyDB:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def get(self, _model, _entity_id):
            return "via-get"

        def execute(self, stmt):
            executed.append(stmt)
            return Result()

    db_session = DummyDB()

    # where-path + options => execute(select(...).options(...))
    loader_opt = joinedload(db.Tool.gateway)
    result = db.get_for_update(db_session, db.Tool, where=(db.Tool.id == "tool-1"), options=[loader_opt], skip_locked=True)
    assert result == "row"
    assert executed

    # entity_id path uses db.get when options is None and where is None.
    assert db.get_for_update(db_session, db.Tool, entity_id="tool-1") == "via-get"

    # options with entity_id forces execute path
    result2 = db.get_for_update(db_session, db.Tool, entity_id="tool-1", options=[loader_opt])
    assert result2 == "row"


def test_llm_provider_type_helpers():
    types_ = db.LLMProviderType.get_all_types()
    assert db.LLMProviderType.OPENAI in types_

    defaults = db.LLMProviderType.get_provider_defaults()
    assert "api_base" in defaults[db.LLMProviderType.OPENAI]


def test_slug_listeners_gateway_a2a_agent_email_team(monkeypatch):
    monkeypatch.setattr(db, "slugify", lambda s: s.lower().replace(" ", "-"))

    class Target:
        def __init__(self, name: str):
            self.name = name
            self.slug = ""

    gw = Target("Gateway Name")
    db.set_gateway_slug(None, None, gw)
    assert gw.slug == "gateway-name"

    agent = Target("Agent Name")
    db.set_a2a_agent_slug(None, None, agent)
    assert agent.slug == "agent-name"

    team = Target("Team Name")
    db.set_email_team_slug(None, None, team)
    assert team.slug == "team-name"
