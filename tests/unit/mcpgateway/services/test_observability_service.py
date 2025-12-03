# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from mcpgateway.services.observability_service import (
    ObservabilityService,
    parse_traceparent,
    generate_w3c_trace_id,
    generate_w3c_span_id,
    format_traceparent,
)


@pytest.fixture
def mock_db():
    # Mocked SQLAlchemy session-like object
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter_by.return_value = query
    query.options.return_value = query
    query.first.return_value = MagicMock()
    return db


@patch("mcpgateway.services.observability_service.ObservabilityTrace", MagicMock())
@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
@patch("mcpgateway.services.observability_service.ObservabilityEvent", MagicMock())
@patch("mcpgateway.services.observability_service.ObservabilityMetric", MagicMock())
@patch("mcpgateway.services.observability_service.joinedload", MagicMock(return_value=lambda x: x))
def test_get_trace_with_and_without_spans(mock_db):
    service = ObservabilityService()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter_by.return_value = mock_query
    mock_query.options.return_value = mock_query
    mock_query.first.return_value = MagicMock()
    assert service.get_trace(mock_db, "tid", include_spans=False) is not None
    assert service.get_trace(mock_db, "tid", include_spans=True) is not None


@patch("mcpgateway.services.observability_service.ObservabilityEvent", MagicMock())
def test_add_event_commits(mock_db):
    service = ObservabilityService()
    eid = service.add_event(mock_db, "span123", "evt", severity="info")
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()
    assert eid is not None


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_record_token_usage_missing_trace(mock_ctid, mock_db):
    # Test that record_token_usage returns early when no trace is active
    service = ObservabilityService()
    mock_ctid.get.return_value = None
    # Should return early without error when no trace is active
    service.record_token_usage(mock_db, input_tokens=5)
    # Verify no metric was recorded since there's no active trace
    mock_db.add.assert_not_called()


@patch("mcpgateway.services.observability_service.current_trace_id")
@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_record_token_usage_with_and_without_span(mock_ctid, mock_db):
    service = ObservabilityService()
    mock_ctid.get.return_value = "traceid"
    service.record_metric = MagicMock()
    span = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = span
    service.record_token_usage(mock_db, model="gpt-4-turbo", input_tokens=5, output_tokens=3)
    service.record_token_usage(mock_db, span_id="sid", model="claude-3-sonnet",
                               input_tokens=10, output_tokens=15, provider="anthropic")
    assert service.record_metric.call_count >= 2


@patch("mcpgateway.services.observability_service.ObservabilityMetric", MagicMock())
def test_record_transport_activity_message_count_zero(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity(mock_db, "sse", "connect", message_count=0, bytes_sent=123)
    service.record_metric.assert_called()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_tool_invocation_exception_flow(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "traceid"
        service.add_event = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with pytest.raises(ValueError):
            with service.trace_tool_invocation(mock_db, "toolX", {"api_key": "secret"}) as (span_id, result):
                raise ValueError("tool failed")
        service.add_event.assert_called()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_a2a_request_exception_flow(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "traceid"
        service.add_event = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with pytest.raises(RuntimeError):
            with service.trace_a2a_request(mock_db, "agent-007", "SpyAgent", "query", {"auth_token": "abc"}) as (span_id, result):
                raise RuntimeError("A2A failed")
        service.add_event.assert_called()


def test_estimate_token_cost_models_all():
    service = ObservabilityService()
    models = ["gpt-4", "gpt-3.5-turbo", "claude-3-sonnet", "claude-3.5-haiku", "gpt-4o-mini", "default"]
    for m in models:
        cost = service._estimate_token_cost(m, 10_000, 5_000)
        assert cost >= 0


def test_parse_traceparent_edge_invalid_version(caplog):
    bad = "01-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    assert parse_traceparent(bad) is None
    assert "Unsupported traceparent version" in caplog.text


def test_parse_traceparent_zero_ids(caplog):
    bad_trace_id = "00-" + "0" * 32 + "-b7ad6b7169203331-01"
    bad_parent_id = "00-0af7651916cd43dd8448eb211c80319c-" + "0" * 16 + "-01"
    assert parse_traceparent(bad_trace_id) is None
    assert parse_traceparent(bad_parent_id) is None
    # Both should be rejected due to zero IDs
    assert "Invalid traceparent" in caplog.text or "zero" in caplog.text.lower()


def test_parse_traceparent_valid_but_zero_ids(caplog):
    header = "00-" + "0"*32 + "-0000000000000000-01"
    output = parse_traceparent(header)
    assert output is None
    assert "Invalid traceparent" in caplog.text or "zero" in caplog.text


def test_parse_traceparent_malformed_formats(caplog):
    assert parse_traceparent("wrong-format") is None
    assert parse_traceparent("xx-" + "abc"*16 + "-1234567890123456-00") is None
    assert "Invalid traceparent" in caplog.text or "Unsupported" in caplog.text


def test_format_traceparent_unsampled_branch():
    val = format_traceparent("a"*32, "b"*16, sampled=False)
    assert val.endswith("-00")


def test_start_trace_with_parent_and_resources(mock_db):
    service = ObservabilityService()
    tid = service.start_trace(mock_db, "GET /endpoint", parent_span_id="parent123",
                              http_method="GET", http_url="/endpoint",
                              attributes={"a": 1}, resource_attributes={"service": "gateway"})
    assert isinstance(tid, str)
    mock_db.add.assert_called()


def test_end_trace_missing_trace_warns(mock_db, caplog):
    service = ObservabilityService()
    mock_db.query.return_value.filter_by.return_value.first.return_value = None
    service.end_trace(mock_db, "missing")
    assert "not found" in caplog.text


def test_end_trace_merges_attributes(mock_db):
    service = ObservabilityService()
    trace = MagicMock()
    trace.start_time = datetime.now(timezone.utc)
    trace.attributes = {"x": 1}
    mock_db.query.return_value.filter_by.return_value.first.return_value = trace
    service.end_trace(mock_db, "tid", status="ok", attributes={"y": 2}, http_status_code=200)
    mock_db.commit.assert_called()


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_trace_tool_invocation_success(mock_ctid, mock_db):
    service = ObservabilityService()
    mock_ctid.get.return_value = "tid"
    mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
    with service.trace_tool_invocation(mock_db, "toolY", {"arg": "val"}) as (span_id, result):
        result["ok"] = True
    mock_db.commit.assert_called()


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_trace_span_exception(mock_ctid, mock_db):
    service = ObservabilityService()
    mock_ctid.get.return_value = "tid"
    mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError):
        with service.trace_span(mock_db, "traceid", "demo-span"):
            raise RuntimeError("boom")


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_record_token_usage_computed_cost(mock_ctid, mock_db):
    service = ObservabilityService()
    mock_ctid.get.return_value = "tid"
    service.record_metric = MagicMock()
    # missing total_tokens and cost
    service.record_token_usage(mock_db, model="gpt-4o-mini", input_tokens=10, output_tokens=5, provider="openai")
    service.record_metric.assert_called()


def test_trace_a2a_request_success(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "tid"
        mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_a2a_request(mock_db, "agentX", "Name", "query", {"x": "y"}) as (span_id, result):
            result["response_time_ms"] = 20
        mock_db.commit.assert_called()


def test_record_transport_activity_full_branches(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity(mock_db, "http", "send",
                                      message_count=1, bytes_sent=100, bytes_received=50, connection_id="conn1")
    assert service.record_metric.call_count >= 3


def test_record_metric_exists(mock_db):
    service = ObservabilityService()
    metric_func = getattr(service, "record_metric", None)
    if metric_func:
        metric_func(db=mock_db, name="metric.test", value=1.0, metric_type="counter",
                    unit="test", trace_id="tid", attributes={"a": "b"})
        mock_db.add.assert_called()


def test_record_token_usage_all_paths(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "traceid"
        service.record_metric = MagicMock()
        service.record_token_usage(mock_db, model="gpt-4o-mini", input_tokens=10, output_tokens=10)
        service.record_token_usage(mock_db, model="unknown-model", input_tokens=0, output_tokens=0, total_tokens=None)
        service.record_metric.assert_called()


def test_estimate_token_cost_default_fallback():
    service = ObservabilityService()
    cost = service._estimate_token_cost("some-weird-model", 1000, 500)
    assert cost >= 0


def test_trace_a2a_request_success_path(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "tid"
        mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_a2a_request(mock_db, "agent-1", "AgentName", "ping", {"data": "v"}) as (span_id, result):
            result["ok"] = True
        mock_db.commit.assert_called()


def test_record_transport_activity_all_metrics(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity(mock_db, "ws", "send",
                                      message_count=3, bytes_sent=100, bytes_received=200, connection_id="c123")
    assert service.record_metric.call_count >= 3


def test_parse_traceparent_invalid_strings(caplog):
    assert parse_traceparent("invalid-header") is None
    assert parse_traceparent("00-" + "0"*32 + "-abcd"*4 + "-01") is None
    bad = "01-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    assert parse_traceparent(bad) is None
    assert "Invalid" in caplog.text or "Unsupported" in caplog.text


def test_start_trace_with_resource_and_parent(mock_db):
    service = ObservabilityService()
    tid = service.start_trace(mock_db, "GET /test", parent_span_id="p123",
                              attributes={"foo": "bar"},
                              resource_attributes={"service": "gateway"})
    mock_db.add.assert_called()
    assert isinstance(tid, str)


def test_end_trace_multiple_flows(mock_db, caplog):
    service = ObservabilityService()
    # no trace found
    mock_db.query.return_value.filter_by.return_value.first.return_value = None
    service.end_trace(mock_db, "missing-trace")
    assert "not found" in caplog.text
    # valid trace merge attributes
    trace = MagicMock()
    trace.start_time = datetime.now(timezone.utc)
    trace.attributes = {"x": 1}
    mock_db.query.return_value.filter_by.return_value.first.return_value = trace
    service.end_trace(mock_db, "tid", attributes={"y": 2})
    mock_db.commit.assert_called()


def test_trace_span_exception_path(mock_db):
    service = ObservabilityService()
    mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError):
        with service.trace_span(mock_db, "traceid", "failing"):
            raise RuntimeError("forced error")


def test_trace_tool_invocation_with_status_result(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as ct:
        ct.get.return_value = "traceid"
        mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_tool_invocation(mock_db, "toolname", {"a": "b"}) as (sid, result):
            result["status"] = "ok"
        mock_db.commit.assert_called()


def test_record_token_usage_autocalc(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as ct:
        ct.get.return_value = "traceid"
        service.record_metric = MagicMock()
        service.record_token_usage(mock_db, model="gpt-4o", input_tokens=10, output_tokens=15)
        service.record_metric.assert_called()


def test_trace_a2a_request_with_response_result(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as ct:
        ct.get.return_value = "traceid"
        mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_a2a_request(mock_db, "agent-123", "Agent", "query", {"input": "v"}) as (sid, result):
            result["response"] = "ok"
        mock_db.commit.assert_called()


def test_record_transport_activity_full(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity(mock_db, "http", "send",
                                      message_count=1, bytes_sent=50, bytes_received=25,
                                      connection_id="cid")
    assert service.record_metric.call_count >= 3


def test_parse_traceparent_zero_trace_parent(caplog):
    header = "00-" + "0"*32 + "-0000000000000000-01"
    result = parse_traceparent(header)
    assert result is None
    assert "Invalid traceparent" in caplog.text or "zero" in caplog.text


def test_generate_trace_and_span_ids_lengths():
    t_id = generate_w3c_trace_id()
    s_id = generate_w3c_span_id()
    assert 32 <= len(t_id) <= 48
    assert len(s_id) == 16


def test_start_trace_parent_id_included(mock_db):
    service = ObservabilityService()
    trace_id = service.start_trace(mock_db, "GET /resource",
                                   parent_span_id="p123",
                                   attributes={"foo": "bar"})
    mock_db.add.assert_called()
    # parent_span_id gets merged in attributes
    assert "parent_span_id" in (mock_db.add.call_args[0][0].attributes or {})
    assert isinstance(trace_id, str)


def test_end_trace_merges_additional_attributes(mock_db):
    service = ObservabilityService()
    trace = MagicMock()
    trace.start_time = datetime.now(timezone.utc)
    trace.attributes = {"a": 1}
    mock_db.query.return_value.filter_by.return_value.first.return_value = trace
    service.end_trace(mock_db, "tid", attributes={"b": 2})
    assert "b" in trace.attributes
    mock_db.commit.assert_called()


def test_end_span_no_span_found_logs_warning(mock_db, caplog):
    service = ObservabilityService()
    mock_db.query.return_value.filter_by.return_value.first.return_value = None
    service.end_span(mock_db, "missing")
    # The service should log a warning when span is not found
    assert "not found" in caplog.text.lower() or mock_db.commit.call_count == 0


def test_trace_span_exception_triggers_event(mock_db):
    service = ObservabilityService()
    service.add_event = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        with service.trace_span(mock_db, "traceid", "operation"):
            raise ValueError("boom")
    service.add_event.assert_called_once()


def test_trace_tool_invocation_normal_exit(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as cvar:
        cvar.get.return_value = "tid"
        mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_tool_invocation(mock_db, "tool_normal", {"a": "b"}) as (sid, result):
            result["success"] = True
        assert mock_db.commit.call_count >= 2


def test_record_token_usage_auto_cost_and_total(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as cvar:
        cvar.get.return_value = "tid"
        service.record_metric = MagicMock()
        service.record_token_usage(mock_db, model="gpt-4o-mini",
                                   input_tokens=10, output_tokens=5,
                                   total_tokens=None, estimated_cost_usd=None)
        service.record_metric.assert_called()


def test_trace_a2a_request_successful_path(mock_db):
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as cvar:
        cvar.get.return_value = "tid"
        mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_a2a_request(mock_db, "agent007", "Spy", "run", {"key": "val"}) as (sid, result):
            result["done"] = "ok"
        mock_db.commit.assert_called()


def test_record_transport_activity_all_metrics_and_error(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity(mock_db, "http", "send",
                                      message_count=2,
                                      bytes_sent=128,
                                      bytes_received=64,
                                      connection_id="cid1",
                                      error="fail")
    # should record message, send, receive, error metrics
    assert service.record_metric.call_count >= 3


def test_query_traces_invalid_limit_and_order_raises(mock_db):
    service = ObservabilityService()
    with pytest.raises(ValueError):
        service.query_traces(mock_db, limit=0)
    with pytest.raises(ValueError):
        service.query_traces(mock_db, order_by="unknown_field")
