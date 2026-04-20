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
    ensure_timezone_aware,
)
from sqlalchemy.exc import SQLAlchemyError


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


@pytest.fixture
def mock_session_factory():
    """Mock SessionLocal for observability independent sessions."""
    with patch('mcpgateway.services.observability_service.SessionLocal') as mock_factory:
        mock_session = MagicMock()
        mock_factory.return_value = mock_session
        # Setup common mock behaviors
        mock_session.commit.return_value = None
        mock_session.rollback.return_value = None
        mock_session.close.return_value = None
        # Return a MagicMock for query chains so tests can set attributes
        mock_session.query.return_value.filter_by.return_value.first.return_value = MagicMock()
        mock_session.query.return_value.filter_by.return_value.options.return_value = MagicMock()
        yield mock_factory, mock_session


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


def test_get_trace_with_spans_executes_options_chain(mock_db):
    service = ObservabilityService()

    class _Joinedload:
        def joinedload(self, *_args, **_kwargs):
            return self

    with (
        patch("mcpgateway.services.observability_service.ObservabilityTrace", MagicMock()),
        patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock()),
        patch("mcpgateway.services.observability_service.joinedload", lambda *_args, **_kwargs: _Joinedload()),
    ):
        assert service.get_trace_with_spans(mock_db, "tid") is not None


@patch("mcpgateway.services.observability_service.ObservabilityEvent", MagicMock())
def test_add_event_commits(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    eid = service.add_event("span123", "evt", severity="info")
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once()
    assert eid is not None


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_record_token_usage_missing_trace(mock_ctid, mock_db):
    # Test that record_token_usage returns early when no trace is active
    service = ObservabilityService()
    mock_ctid.get.return_value = None
    # Should return early without error when no trace is active
    service.record_token_usage(input_tokens=5)
    # Verify no metric was recorded since there's no active trace
    mock_db.add.assert_not_called()


@patch("mcpgateway.services.observability_service.current_trace_id")
@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_record_token_usage_with_and_without_span(mock_ctid, mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    mock_ctid.get.return_value = "traceid"
    service.record_metric = MagicMock()
    span = MagicMock()
    mock_session.query.return_value.filter_by.return_value.first.return_value = span
    service.record_token_usage(model="gpt-4-turbo", input_tokens=5, output_tokens=3)
    service.record_token_usage(span_id="sid", model="claude-3-sonnet",
                               input_tokens=10, output_tokens=15, provider="anthropic")
    assert service.record_metric.call_count >= 2


@patch("mcpgateway.services.observability_service.ObservabilityMetric", MagicMock())
def test_record_transport_activity_message_count_zero(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity("sse", "connect", message_count=0, bytes_sent=123)
    service.record_metric.assert_called()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_tool_invocation_exception_flow(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "traceid"
        service.add_event = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with pytest.raises(ValueError):
            with service.trace_tool_invocation("toolX", {"api_key": "secret"}) as (span_id, result):
                raise ValueError("tool failed")
        service.add_event.assert_called()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_a2a_request_exception_flow(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "traceid"
        service.add_event = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with pytest.raises(RuntimeError):
            with service.trace_a2a_request("agent-007", "SpyAgent", "query", {"auth_token": "abc"}) as (span_id, result):
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


def test_start_trace_with_parent_and_resources(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    tid = service.start_trace("GET /endpoint", parent_span_id="parent123",
                              http_method="GET", http_url="/endpoint",
                              attributes={"a": 1}, resource_attributes={"service": "gateway"})
    assert isinstance(tid, str)
    # Session add handled internally


def test_start_trace_with_explicit_trace_id_and_no_parent(mock_session_factory):
    """Cover branches where trace_id is provided and parent_span_id is not set."""
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    tid = service.start_trace(
        "GET /explicit",
        trace_id="trace-explicit",
        parent_span_id=None,
        attributes={"a": 1},
    )
    assert tid == "trace-explicit"
    trace_obj = mock_session.add.call_args[0][0]
    assert trace_obj.trace_id == "trace-explicit"
    assert "parent_span_id" not in (trace_obj.attributes or {})


def test_end_trace_missing_trace_warns(mock_session_factory, caplog):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    mock_session.query.return_value.filter_by.return_value.first.return_value = None
    service.end_trace("missing")
    assert "not found" in caplog.text


def test_end_trace_merges_attributes(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    trace = MagicMock()
    trace.start_time = datetime.now(timezone.utc)
    trace.attributes = {"x": 1}
    mock_session.query.return_value.filter_by.return_value.first.return_value = trace
    service.end_trace("tid", status="ok", attributes={"y": 2}, http_status_code=200)
    mock_session.commit.assert_called()


def test_end_trace_without_attributes_does_not_merge(mock_session_factory):
    """Cover end_trace branch where no attributes are provided."""
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    trace = MagicMock()
    trace.start_time = datetime.now(timezone.utc)
    trace.attributes = {"x": 1}
    mock_session.query.return_value.filter_by.return_value.first.return_value = trace
    service.end_trace("tid", status="ok", http_status_code=200)
    assert trace.attributes == {"x": 1}
    mock_session.commit.assert_called()


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_trace_tool_invocation_success(mock_ctid, mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    mock_ctid.get.return_value = "tid"
    mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
    with service.trace_tool_invocation("toolY", {"arg": "val"}) as (span_id, result):
        result["ok"] = True
    mock_session.commit.assert_called()


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_trace_span_exception(mock_ctid, mock_db):
    service = ObservabilityService()
    mock_ctid.get.return_value = "tid"
    mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError):
        with service.trace_span("traceid", "demo-span"):
            raise RuntimeError("boom")


def test_trace_span_success_calls_end_span_ok(mock_session_factory):
    """Cover trace_span success path (observability_service.py:486)."""
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    service.start_span = MagicMock(return_value="span123")
    service.end_span = MagicMock()

    with service.trace_span("traceid", "ok-span") as span_id:
        assert span_id == "span123"

    # end_span called with span_id, status, commit=False, and obs_db session
    assert service.end_span.call_count == 1
    call_args = service.end_span.call_args
    assert call_args[0][0] == "span123"  # span_id
    assert call_args[1]["status"] == "ok"
    assert call_args[1]["commit"] == False
    assert call_args[1]["obs_db"] == mock_session


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_record_token_usage_computed_cost(mock_ctid, mock_db):
    service = ObservabilityService()
    mock_ctid.get.return_value = "tid"
    service.record_metric = MagicMock()
    # missing total_tokens and cost
    service.record_token_usage(model="gpt-4o-mini", input_tokens=10, output_tokens=5, provider="openai")
    service.record_metric.assert_called()


def test_record_token_usage_explicit_trace_id_total_and_cost_skip_autocalc(mock_session_factory):
    """Cover record_token_usage branches skipping trace lookup, total token calc, cost estimate, and missing span."""
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    service.record_metric = MagicMock()

    # span_id provided but span not found -> branch to metrics recording
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    service.record_token_usage(
        span_id="sid",
        trace_id="traceid",
        model="gpt-4",
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        estimated_cost_usd=0.01,
    )
    assert service.record_metric.called


def test_trace_a2a_request_success(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "tid"
        mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_a2a_request("agentX", "Name", "query", {"x": "y"}) as (span_id, result):
            result["response_time_ms"] = 20
        mock_session.commit.assert_called()


def test_trace_a2a_request_no_request_data_skips_sanitization(mock_session_factory):
    """Cover request_data falsy branch in trace_a2a_request (observability_service.py:837->841)."""
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "tid"
        service.start_span = MagicMock(return_value="span123")
        service.end_span = MagicMock()

        with service.trace_a2a_request("agent-1", "AgentName", "ping", request_data=None) as (sid, result):
            result["ok"] = True

        attrs = service.start_span.call_args.kwargs["attributes"]
        assert attrs["a2a.request_data"] == {}


def test_record_transport_activity_full_branches(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity("http", "send",
                                      message_count=1, bytes_sent=100, bytes_received=50, connection_id="conn1")
    assert service.record_metric.call_count >= 3


def test_record_transport_activity_bytes_sent_zero_skips_metric(mock_db):
    """Cover bytes_sent falsy branch in record_transport_activity (observability_service.py:939->955)."""
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity("sse", "receive", message_count=1, bytes_sent=0, bytes_received=5)

    # Ensure we didn't emit bytes_sent metric
    metric_names = [call.kwargs["name"] for call in service.record_metric.mock_calls if "name" in call.kwargs]
    assert not any(name.endswith(".bytes_sent") for name in metric_names)

def test_record_metric_exists(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    metric_func = getattr(service, "record_metric", None)
    if metric_func:
        metric_func(name="metric.test", value=1.0, metric_type="counter",
                    unit="test", trace_id="tid", attributes={"a": "b"})
        # Session add handled internally


def test_record_token_usage_all_paths(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "traceid"
        service.record_metric = MagicMock()
        service.record_token_usage(model="gpt-4o-mini", input_tokens=10, output_tokens=10)
        service.record_token_usage(model="unknown-model", input_tokens=0, output_tokens=0, total_tokens=None)
        service.record_metric.assert_called()


def test_estimate_token_cost_default_fallback():
    service = ObservabilityService()
    cost = service._estimate_token_cost("some-weird-model", 1000, 500)
    assert cost >= 0


def test_trace_a2a_request_success_path(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_ctid:
        mock_ctid.get.return_value = "tid"
        mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_a2a_request("agent-1", "AgentName", "ping", {"data": "v"}) as (span_id, result):
            result["ok"] = True
        mock_session.commit.assert_called()


def test_parse_traceparent_valid():
    header = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    trace_id, parent_id, flags = parse_traceparent(header)
    assert trace_id == "0af7651916cd43dd8448eb211c80319c"
    assert parent_id == "b7ad6b7169203331"
    assert flags == "01"


def test_ensure_timezone_aware_sets_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    aware = ensure_timezone_aware(naive)
    assert aware.tzinfo is not None
    assert aware.tzinfo == timezone.utc


def test_safe_commit_failure_rolls_back():
    service = ObservabilityService()
    mock_db = MagicMock()
    mock_db.commit.side_effect = SQLAlchemyError("commit failed")
    mock_db.rollback.side_effect = SQLAlchemyError("rollback failed")

    assert service._safe_commit(mock_db, "test") is False


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_trace_tool_invocation_no_trace(mock_ctid, mock_db):
    service = ObservabilityService()
    mock_ctid.get.return_value = None
    with service.trace_tool_invocation("tool", {"password": "secret"}) as (span_id, result):
        result["ok"] = True
    assert span_id is None


@patch("mcpgateway.services.observability_service.current_trace_id")
def test_trace_a2a_request_no_trace(mock_ctid, mock_db):
    service = ObservabilityService()
    mock_ctid.get.return_value = None
    with service.trace_a2a_request("agent", "Name", "query", {"token": "x"}) as (span_id, result):
        result["ok"] = True
    assert span_id is None


def test_add_event_commit_failure_returns_zero(mock_db):
    service = ObservabilityService()
    with patch.object(service, "_safe_commit", return_value=False):
        event_id = service.add_event("span", "evt")
    assert event_id == 0


def test_record_metric_commit_failure_returns_zero(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch.object(service, "_safe_commit", return_value=False):
        metric_id = service.record_metric(name="m", value=1.0, metric_type="counter", trace_id="tid")
    assert metric_id == 0


def test_query_traces_applies_filters(mock_db):
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["trace"]
    mock_db.query.return_value = query

    with patch("mcpgateway.services.observability_service.ObservabilityTrace") as mock_trace:
        mock_trace.attributes.__getitem__.return_value.astext = MagicMock()
        class _Comparable:
            def __ge__(self, _other):
                return MagicMock()

            def __le__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

            def __gt__(self, _other):
                return MagicMock()

        mock_trace.start_time = _Comparable()
        mock_trace.duration_ms = _Comparable()

        with patch("mcpgateway.services.observability_service.desc", lambda _col: MagicMock()):
            results = service.query_traces(
                mock_db,
                start_time=datetime.now(timezone.utc),
                end_time=datetime.now(timezone.utc),
                min_duration_ms=1.0,
                max_duration_ms=10.0,
                status="error",
                status_in=["ok", "error"],
                status_not_in=["ok"],
                http_status_code=500,
                http_status_code_in=[400, 500],
                http_method="GET",
                http_method_in=["GET", "POST"],
                user_email="user@example.com",
                user_email_in=["user@example.com", "other@example.com"],
                attribute_filters={"http.route": "/"},
                attribute_filters_or={"component": "api"},
                attribute_search="foo%",
                name_contains="api",
                order_by="duration_desc",
                limit=5,
                offset=2,
            )

    assert results == ["trace"]
    assert query.filter.called
    assert query.order_by.called
    query.limit.assert_called_with(5)
    query.offset.assert_called_with(2)


def test_query_traces_default_order_and_no_filters(mock_db):
    """Cover query_traces false-branch filters and default ordering (start_time_desc)."""
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["trace"]
    mock_db.query.return_value = query

    with patch("mcpgateway.services.observability_service.ObservabilityTrace") as mock_trace, patch("mcpgateway.services.observability_service.desc", lambda _col: MagicMock()):
        mock_trace.start_time = MagicMock()
        mock_trace.duration_ms = MagicMock()
        assert service.query_traces(mock_db) == ["trace"]


def test_query_traces_order_by_start_time_asc(mock_db):
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["trace"]
    mock_db.query.return_value = query

    with patch("mcpgateway.services.observability_service.ObservabilityTrace") as mock_trace:
        mock_trace.start_time = MagicMock()
        mock_trace.duration_ms = MagicMock()
        assert service.query_traces(mock_db, order_by="start_time_asc") == ["trace"]


def test_query_traces_order_by_duration_asc(mock_db):
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["trace"]
    mock_db.query.return_value = query

    with patch("mcpgateway.services.observability_service.ObservabilityTrace") as mock_trace:
        mock_trace.start_time = MagicMock()
        mock_trace.duration_ms = MagicMock()
        assert service.query_traces(mock_db, order_by="duration_asc") == ["trace"]


def test_query_traces_attribute_filters_or_truthy_empty_mapping(mock_db):
    """Cover inner or_conditions empty branch (observability_service.py:1202->1206)."""
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["trace"]
    mock_db.query.return_value = query

    class _TruthyEmptyMapping(dict):
        def __bool__(self):
            return True

        def items(self):
            return []

    with patch("mcpgateway.services.observability_service.ObservabilityTrace") as mock_trace, patch("mcpgateway.services.observability_service.desc", lambda _col: MagicMock()):
        mock_trace.start_time = MagicMock()
        mock_trace.duration_ms = MagicMock()
        assert service.query_traces(mock_db, attribute_filters_or=_TruthyEmptyMapping()) == ["trace"]


def test_query_traces_invalid_limit_and_order(mock_db):
    service = ObservabilityService()
    mock_db.query.return_value = MagicMock()

    with pytest.raises(ValueError):
        service.query_traces(mock_db, limit=0)

    with pytest.raises(ValueError):
        service.query_traces(mock_db, order_by="bad_order")


def test_record_transport_activity_all_metrics(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity("ws", "send",
                                      message_count=3, bytes_sent=100, bytes_received=200, connection_id="c123")
    assert service.record_metric.call_count >= 3


def test_parse_traceparent_invalid_strings(caplog):
    assert parse_traceparent("invalid-header") is None
    assert parse_traceparent("00-" + "0"*32 + "-abcd"*4 + "-01") is None
    bad = "01-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    assert parse_traceparent(bad) is None
    assert "Invalid" in caplog.text or "Unsupported" in caplog.text


def test_start_trace_with_resource_and_parent(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    tid = service.start_trace("GET /test", parent_span_id="p123",
                              attributes={"foo": "bar"},
                              resource_attributes={"service": "gateway"})
    # Session add handled internally
    assert isinstance(tid, str)


def test_end_trace_multiple_flows(mock_session_factory, caplog):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    # no trace found
    mock_session.query.return_value.filter_by.return_value.first.return_value = None
    service.end_trace("missing-trace")
    assert "not found" in caplog.text
    # valid trace merge attributes
    trace = MagicMock()
    trace.start_time = datetime.now(timezone.utc)
    trace.attributes = {"x": 1}
    mock_session.query.return_value.filter_by.return_value.first.return_value = trace
    service.end_trace("tid", attributes={"y": 2})
    mock_session.commit.assert_called()


def test_trace_span_exception_path(mock_db):
    service = ObservabilityService()
    mock_db.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError):
        with service.trace_span("traceid", "failing"):
            raise RuntimeError("forced error")


def test_trace_tool_invocation_with_status_result(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as ct:
        ct.get.return_value = "traceid"
        mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_tool_invocation("toolname", {"a": "b"}) as (sid, result):
            result["status"] = "ok"
        mock_session.commit.assert_called()


def test_record_token_usage_autocalc(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as ct:
        ct.get.return_value = "traceid"
        service.record_metric = MagicMock()
        service.record_token_usage(model="gpt-4o", input_tokens=10, output_tokens=15)
        service.record_metric.assert_called()


def test_trace_a2a_request_with_response_result(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as ct:
        ct.get.return_value = "traceid"
        mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_a2a_request("agent-123", "Agent", "query", {"input": "v"}) as (sid, result):
            result["response"] = "ok"
        mock_session.commit.assert_called()


def test_record_transport_activity_full(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity("http", "send",
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


def test_start_trace_parent_id_included(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    trace_id = service.start_trace("GET /resource",
                                   parent_span_id="p123",
                                   attributes={"foo": "bar"})
    # Session add handled internally
    # parent_span_id gets merged in attributes
    assert "parent_span_id" in (mock_session.add.call_args[0][0].attributes or {})
    assert isinstance(trace_id, str)


def test_end_trace_merges_additional_attributes(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    trace = MagicMock()
    trace.start_time = datetime.now(timezone.utc)
    trace.attributes = {"a": 1}
    mock_session.query.return_value.filter_by.return_value.first.return_value = trace
    service.end_trace("tid", attributes={"b": 2})
    assert "b" in trace.attributes
    mock_session.commit.assert_called()


def test_end_span_no_span_found_logs_warning(mock_session_factory, caplog):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    mock_session.query.return_value.filter_by.return_value.first.return_value = None
    service.end_span("missing")
    # The service should log a warning when span is not found
    assert "not found" in caplog.text.lower() or mock_session.commit.call_count == 0


def test_trace_span_exception_triggers_event(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    service.add_event = MagicMock()
    mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        with service.trace_span(mock_session, "traceid", "operation"):
            raise ValueError("boom")
    service.add_event.assert_called_once()


def test_trace_tool_invocation_normal_exit(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as cvar:
        cvar.get.return_value = "tid"
        mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_tool_invocation("tool_normal", {"a": "b"}) as (sid, result):
            result["success"] = True
        # Context manager commits once at the end (single session, single commit)
        mock_session.commit.assert_called_once()


def test_query_spans_applies_filters(mock_db):
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["span"]
    mock_db.query.return_value = query

    with patch("mcpgateway.services.observability_service.ObservabilitySpan") as mock_span:
        mock_span.attributes.__getitem__.return_value.astext = MagicMock()
        class _Comparable:
            def __ge__(self, _other):
                return MagicMock()

            def __le__(self, _other):
                return MagicMock()

            def __lt__(self, _other):
                return MagicMock()

            def __gt__(self, _other):
                return MagicMock()

        mock_span.start_time = _Comparable()
        mock_span.duration_ms = _Comparable()

        with patch("mcpgateway.services.observability_service.desc", lambda _col: MagicMock()):
            results = service.query_spans(
                mock_db,
                trace_id="tid",
                trace_id_in=["tid"],
                resource_type="tool",
                resource_type_in=["tool", "resource"],
                resource_name="name",
                resource_name_in=["name"],
                name_contains="invoke",
                kind="client",
                kind_in=["client", "server"],
                status="ok",
                status_in=["ok"],
                status_not_in=["error"],
                start_time=datetime.now(timezone.utc),
                end_time=datetime.now(timezone.utc),
                min_duration_ms=1.0,
                max_duration_ms=10.0,
                attribute_filters={"k": "v"},
                attribute_search="foo%",
                order_by="duration_desc",
                limit=5,
                offset=2,
            )

    assert results == ["span"]
    assert query.filter.called
    assert query.order_by.called
    query.limit.assert_called_with(5)
    query.offset.assert_called_with(2)


def test_query_spans_default_order_and_no_filters(mock_db):
    """Cover query_spans false-branch filters and default ordering (start_time_desc)."""
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["span"]
    mock_db.query.return_value = query

    with patch("mcpgateway.services.observability_service.ObservabilitySpan") as mock_span, patch("mcpgateway.services.observability_service.desc", lambda _col: MagicMock()):
        mock_span.start_time = MagicMock()
        mock_span.duration_ms = MagicMock()
        assert service.query_spans(mock_db) == ["span"]


def test_query_spans_order_by_start_time_asc(mock_db):
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["span"]
    mock_db.query.return_value = query

    with patch("mcpgateway.services.observability_service.ObservabilitySpan") as mock_span:
        mock_span.start_time = MagicMock()
        mock_span.duration_ms = MagicMock()
        assert service.query_spans(mock_db, order_by="start_time_asc") == ["span"]


def test_query_spans_order_by_duration_asc(mock_db):
    service = ObservabilityService()
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = ["span"]
    mock_db.query.return_value = query

    with patch("mcpgateway.services.observability_service.ObservabilitySpan") as mock_span:
        mock_span.start_time = MagicMock()
        mock_span.duration_ms = MagicMock()
        assert service.query_spans(mock_db, order_by="duration_asc") == ["span"]


def test_query_spans_invalid_limit_and_order(mock_db):
    service = ObservabilityService()
    mock_db.query.return_value = MagicMock()

    with pytest.raises(ValueError):
        service.query_spans(mock_db, limit=0)

    with pytest.raises(ValueError):
        service.query_spans(mock_db, order_by="bad_order")


def test_start_and_end_span_without_commit(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    span_id = service.start_span("traceid", "operation", commit=False)
    mock_session.commit.assert_not_called()

    span = MagicMock()
    span.start_time = datetime.now(timezone.utc)
    span.attributes = {"x": 1}
    mock_session.query.return_value.filter_by.return_value.first.return_value = span

    service.end_span(span_id, attributes={"y": 2}, commit=False)
    mock_session.commit.assert_not_called()
    assert span.attributes["y"] == 2


def test_delete_old_traces_commit_failure_returns_zero(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    mock_session.query.return_value.filter.return_value.delete.return_value = 3

    with patch.object(service, "_safe_commit", return_value=False):
        deleted = service.delete_old_traces(datetime.now(timezone.utc))

    assert deleted == 0


def test_delete_old_traces_success(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    mock_session.query.return_value.filter.return_value.delete.return_value = 2
    with patch.object(service, "_safe_commit", return_value=True):
        deleted = service.delete_old_traces(datetime.now(timezone.utc))
    assert deleted == 2


def test_record_token_usage_auto_cost_and_total(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as cvar:
        cvar.get.return_value = "tid"
        service.record_metric = MagicMock()
        service.record_token_usage(model="gpt-4o-mini",
                                   input_tokens=10, output_tokens=5,
                                   total_tokens=None, estimated_cost_usd=None)
        service.record_metric.assert_called()


def test_trace_a2a_request_successful_path(mock_session_factory):
    mock_factory, mock_session = mock_session_factory
    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as cvar:
        cvar.get.return_value = "tid"
        mock_session.query.return_value.filter_by.return_value.first.return_value.start_time = datetime.now(timezone.utc)
        with service.trace_a2a_request("agent007", "Spy", "run", {"key": "val"}) as (sid, result):
            result["done"] = "ok"
        mock_session.commit.assert_called()


def test_record_transport_activity_all_metrics_and_error(mock_db):
    service = ObservabilityService()
    service.record_metric = MagicMock()
    service.record_transport_activity("http", "send",
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


# =============================================================================
# Coverage tests for exception handling in session close operations
# =============================================================================


@patch("mcpgateway.services.observability_service.ObservabilityTrace", MagicMock())
def test_start_trace_session_close_failure(mock_session_factory):
    """Test that start_trace handles session close failures gracefully."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    service = ObservabilityService()
    trace_id = service.start_trace("test_trace")

    # Verify trace was created despite close failure
    assert trace_id is not None
    mock_session.close.assert_called_once()


@patch("mcpgateway.services.observability_service.ObservabilityTrace", MagicMock())
def test_end_trace_session_close_failure(mock_session_factory):
    """Test that end_trace handles session close failures gracefully."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    trace = MagicMock()
    trace.start_time = datetime.now(timezone.utc)
    trace.attributes = {}
    mock_session.query.return_value.filter_by.return_value.first.return_value = trace

    service = ObservabilityService()
    service.end_trace("trace123", status="ok")

    # Verify close was attempted
    mock_session.close.assert_called_once()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_start_span_session_close_failure(mock_session_factory):
    """Test that start_span handles session close failures gracefully."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    service = ObservabilityService()
    span_id = service.start_span(trace_id="trace123", name="test_span")

    # Verify span was created despite close failure
    assert span_id is not None
    mock_session.close.assert_called_once()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_start_span_with_commit_true(mock_session_factory):
    """Test start_span with commit=True explicitly calls _safe_commit."""
    mock_factory, mock_session = mock_session_factory

    service = ObservabilityService()
    with patch.object(service, "_safe_commit") as mock_safe_commit:
        span_id = service.start_span(
            trace_id="trace123",
            name="test_span",
            commit=True
        )

        # Verify _safe_commit was called
        mock_safe_commit.assert_called_once_with(mock_session, "start_span")
        assert span_id is not None




@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_start_span_with_plugin_context_custom_attributes(mock_session_factory):
    """Test start_span merges custom attributes from plugin context."""
    mock_factory, mock_session = mock_session_factory

    # Create mock context with custom attributes
    mock_context = MagicMock()
    mock_context.global_context.state = {
        "custom_span_attributes": {"custom_key": "custom_value", "another_key": 123}
    }

    service = ObservabilityService()
    span_id = service.start_span(
        trace_id="trace123",
        name="test_span",
        attributes={"original_key": "original_value"},
        context=mock_context
    )

    assert span_id is not None
    mock_session.close.assert_called_once()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_start_span_with_plugin_context_remove_attributes(mock_session_factory):
    """Test start_span removes attributes specified by plugin context."""
    mock_factory, mock_session = mock_session_factory

    # Create mock context with attributes to remove
    mock_context = MagicMock()
    mock_context.global_context.state = {
        "remove_span_attributes": ["sensitive_key", "another_key"]
    }

    service = ObservabilityService()
    span_id = service.start_span(
        trace_id="trace123",
        name="test_span",
        attributes={"sensitive_key": "secret", "keep_key": "value"},
        context=mock_context
    )

    assert span_id is not None
    mock_session.close.assert_called_once()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_end_span_session_close_failure(mock_session_factory):
    """Test that end_span handles session close failures gracefully."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    span = MagicMock()
    span.start_time = datetime.now(timezone.utc)
    span.attributes = {}
    mock_session.query.return_value.filter_by.return_value.first.return_value = span

    service = ObservabilityService()
    service.end_span("span123", status="ok")

    # Verify close was attempted
    mock_session.close.assert_called_once()


def test_add_event_session_close_failure(mock_session_factory):
    """Test that add_event handles session close failures gracefully."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    # Mock ObservabilityEvent to return an object with id=123 after refresh
    mock_event = MagicMock()
    mock_event.id = 123
    with patch("mcpgateway.services.observability_service.ObservabilityEvent", return_value=mock_event):
        # Patch _safe_commit to return True
        service = ObservabilityService()
        with patch.object(service, '_safe_commit', return_value=True):
            event_id = service.add_event("span123", "test_event", severity="info")

    # Verify event was created (returns non-zero if successful)
    assert event_id == 123
    mock_session.close.assert_called_once()


def test_record_metric_session_close_failure(mock_session_factory):
    """Test that record_metric handles session close failures gracefully."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    # Mock ObservabilityMetric to return an object with id=456 after refresh
    mock_metric = MagicMock()
    mock_metric.id = 456
    with patch("mcpgateway.services.observability_service.ObservabilityMetric", return_value=mock_metric):
        # Patch _safe_commit to return True
        service = ObservabilityService()
        with patch.object(service, '_safe_commit', return_value=True):
            metric_id = service.record_metric(
                name="test.metric",
                value=1.0,
                metric_type="counter"
            )

    # Verify metric was created
    assert metric_id == 456
    mock_session.close.assert_called_once()


def test_delete_old_traces_session_close_failure(mock_session_factory):
    """Test that delete_old_traces handles session close failures gracefully."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")
    mock_session.query.return_value.filter.return_value.delete.return_value = 5

    service = ObservabilityService()
    with patch.object(service, "_safe_commit", return_value=True):
        deleted = service.delete_old_traces(datetime.now(timezone.utc))

        # Verify deletion succeeded
        assert deleted == 5
        mock_session.close.assert_called_once()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_span_context_manager_session_close_failure(mock_session_factory):
    """Test that trace_span context manager handles session close failures."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    span = MagicMock()
    span.start_time = datetime.now(timezone.utc)
    span.attributes = {}
    mock_session.query.return_value.filter_by.return_value.first.return_value = span

    service = ObservabilityService()
    with service.trace_span("trace123", "test_span") as span_id:
        assert span_id is not None

    # Verify close was attempted
    mock_session.close.assert_called()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_tool_invocation_context_manager_session_close_failure(mock_session_factory):
    """Test that trace_tool_invocation handles session close failures."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    span = MagicMock()
    span.start_time = datetime.now(timezone.utc)
    span.attributes = {}
    mock_session.query.return_value.filter_by.return_value.first.return_value = span

    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_trace:
        mock_trace.get.return_value = "trace123"
        with service.trace_tool_invocation("test_tool", {"arg": "value"}) as (span_id, result):
            assert span_id is not None
            result["status"] = "success"

    # Verify close was attempted
    mock_session.close.assert_called()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_a2a_request_context_manager_session_close_failure(mock_session_factory):
    """Test that trace_a2a_request handles session close failures."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    span = MagicMock()
    span.start_time = datetime.now(timezone.utc)
    span.attributes = {}
    mock_session.query.return_value.filter_by.return_value.first.return_value = span

    service = ObservabilityService()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_trace:
        mock_trace.get.return_value = "trace123"
        with service.trace_a2a_request("agent123", "TestAgent", "query", {"data": "test"}) as (span_id, result):
            assert span_id is not None
            result["response"] = "success"

    # Verify close was attempted
    mock_session.close.assert_called()


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_tool_invocation_error_path_end_span_failure(mock_session_factory):
    """Test that trace_tool_invocation handles end_span failure during error path."""
    mock_factory, mock_session = mock_session_factory

    service = ObservabilityService()

    # Make end_span raise during error path by making the query fail
    call_count = [0]
    original_query = mock_session.query

    def failing_query_on_second_call(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] > 1:
            raise Exception("end_span query failed")
        return original_query(*args, **kwargs)

    mock_session.query = failing_query_on_second_call

    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_trace:
        mock_trace.get.return_value = "trace123"
        with pytest.raises(RuntimeError, match="tool error"):
            with service.trace_tool_invocation("test_tool", {"arg": "value"}) as (span_id, result):
                raise RuntimeError("tool error")


@patch("mcpgateway.services.observability_service.ObservabilitySpan", MagicMock())
def test_trace_a2a_request_error_path_end_span_failure(mock_session_factory):
    """Test that trace_a2a_request handles end_span failure during error path."""
    mock_factory, mock_session = mock_session_factory

    service = ObservabilityService()

    # Make end_span raise during error path by making the query fail
    call_count = [0]
    original_query = mock_session.query

    def failing_query_on_second_call(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] > 1:
            raise Exception("end_span query failed")
        return original_query(*args, **kwargs)

    mock_session.query = failing_query_on_second_call

    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_trace:
        mock_trace.get.return_value = "trace123"
        with pytest.raises(RuntimeError, match="a2a error"):
            with service.trace_a2a_request("agent123", "TestAgent", "query") as (span_id, result):
                raise RuntimeError("a2a error")


def test_record_token_usage_session_close_failure(mock_session_factory):
    """Test that record_token_usage handles session close failures gracefully."""
    mock_factory, mock_session = mock_session_factory
    mock_session.close.side_effect = Exception("close failed")

    span = MagicMock()
    span.attributes = {}
    mock_session.query.return_value.filter_by.return_value.first.return_value = span

    service = ObservabilityService()
    service.record_metric = MagicMock()
    with patch("mcpgateway.services.observability_service.current_trace_id") as mock_trace:
        mock_trace.get.return_value = "trace123"
        with patch.object(service, "_safe_commit", return_value=True):
            service.record_token_usage(
                span_id="span123",
                model="test-model",
                input_tokens=10,
                output_tokens=5,
            )

    # Verify close was attempted despite failure
    mock_session.close.assert_called()
