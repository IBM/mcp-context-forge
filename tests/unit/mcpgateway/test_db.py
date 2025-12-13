# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_db.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

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


def test_validate_tool_schema_invalid():
    class Target:
        input_schema = {"type": "invalid"}

    with pytest.raises(ValueError):
        db.validate_tool_schema(None, None, Target())


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


def test_validate_prompt_schema_invalid():
    class Target:
        argument_schema = {"type": "invalid"}

    with pytest.raises(ValueError):
        db.validate_prompt_schema(None, None, Target())


def test_validate_tool_schema_missing():
    class Target:
        pass

    db.validate_tool_schema(None, None, Target())  # Should not raise


def test_validate_tool_name_missing():
    class Target:
        pass

    db.validate_tool_name(None, None, Target())  # Should not raise


def test_validate_prompt_schema_missing():
    class Target:
        pass

    db.validate_prompt_schema(None, None, Target())  # Should not raise


# --- get_db generator ---
def test_get_db_yields_and_closes(monkeypatch):
    class DummySession:
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


def test_get_db_closes_on_exception(monkeypatch):
    class DummySession:
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
    from sqlalchemy import Column, String
    from sqlalchemy.dialects import sqlite
    col = Column("attributes", String)
    monkeypatch.setattr(db, "backend", "sqlite")
    expr = db.extract_json_field(col, '$."tool.name"')
    compiled = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    assert "json_extract" in compiled
    assert "$.\"tool.name\"" in compiled


def test_extract_json_field_postgresql(monkeypatch):
    from sqlalchemy import Column, String
    from sqlalchemy.dialects import postgresql
    col = Column("attributes", String)
    monkeypatch.setattr(db, "backend", "postgresql")
    expr = db.extract_json_field(col, '$."tool.name"')
    compiled = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "->>" in compiled
    assert "tool.name" in compiled
