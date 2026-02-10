# -*- coding: utf-8 -*-
"""Tests for log search router helpers."""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.routers import log_search
from mcpgateway.middleware import rbac as rbac_module
import mcpgateway.plugins.framework as plugin_framework


@pytest.fixture(autouse=True)
def allow_permissions(monkeypatch: pytest.MonkeyPatch):
    async def _ok(self, **_kwargs):  # type: ignore[no-self-use]
        return True

    monkeypatch.setattr(rbac_module.PermissionService, "check_permission", _ok)
    monkeypatch.setattr(plugin_framework, "get_plugin_manager", lambda: None)


def test_align_to_window_rounds_down():
    ts = datetime(2024, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
    aligned = log_search._align_to_window(ts, 15)
    assert aligned.minute == 30
    assert aligned.second == 0


def test_deduplicate_metrics_keeps_latest():
    now = datetime.now(timezone.utc)
    older = SimpleNamespace(component="c", operation_type="op", window_start=now, timestamp=now - timedelta(seconds=5))
    newer = SimpleNamespace(component="c", operation_type="op", window_start=now, timestamp=now)

    deduped = log_search._deduplicate_metrics([older, newer])

    assert len(deduped) == 1
    assert deduped[0] is newer


def test_deduplicate_metrics_empty_returns_empty():
    assert log_search._deduplicate_metrics([]) == []


def test_deduplicate_metrics_keeps_existing_when_newer_first():
    now = datetime.now(timezone.utc)
    newer = SimpleNamespace(component="c", operation_type="op", window_start=now, timestamp=now)
    older = SimpleNamespace(component="c", operation_type="op", window_start=now, timestamp=now - timedelta(seconds=5))

    deduped = log_search._deduplicate_metrics([newer, older])

    assert len(deduped) == 1
    assert deduped[0] is newer


def test_expand_component_filters_adds_alias():
    result = log_search._expand_component_filters(["gateway"])
    assert "gateway" in result
    assert "http_gateway" in result


def test_expand_component_filters_no_alias():
    assert log_search._expand_component_filters(["other"]) == ["other"]


def test_aggregate_custom_windows_batch_success():
    aggregator = MagicMock()
    db = MagicMock()

    sample_exec = MagicMock()
    sample_exec.first.return_value = None
    max_exec = MagicMock()
    max_exec.scalar.return_value = None
    earliest_exec = MagicMock()
    earliest_exec.scalar.return_value = datetime.now(timezone.utc) - timedelta(minutes=30)

    db.execute.side_effect = [sample_exec, max_exec, earliest_exec]

    log_search._aggregate_custom_windows(aggregator, window_minutes=60, db=db)

    assert aggregator.aggregate_all_components_batch.called


def test_aggregate_custom_windows_batch_fallback():
    aggregator = MagicMock()
    aggregator.aggregate_all_components_batch.side_effect = Exception("fail")
    db = MagicMock()

    sample_exec = MagicMock()
    sample_exec.first.return_value = None
    max_exec = MagicMock()
    max_exec.scalar.return_value = None
    earliest_exec = MagicMock()
    earliest_exec.scalar.return_value = datetime.now(timezone.utc) - timedelta(minutes=30)

    db.execute.side_effect = [sample_exec, max_exec, earliest_exec]

    log_search._aggregate_custom_windows(aggregator, window_minutes=60, db=db)

    assert aggregator.aggregate_all_components.called
    assert db.rollback.called


def test_aggregate_custom_windows_rebuilds_when_sample_misaligned():
    """Cover needs_rebuild path (delete + commit) when sample windows are misaligned."""
    aggregator = MagicMock()
    db = MagicMock()

    sample_exec = MagicMock()
    sample_start = datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc)  # not aligned to 60m boundary
    sample_end = sample_start + timedelta(minutes=60)
    sample_exec.first.return_value = (sample_start, sample_end)

    delete_exec = MagicMock()
    earliest_exec = MagicMock()
    earliest_exec.scalar.return_value = datetime.now(timezone.utc) - timedelta(minutes=30)

    db.execute.side_effect = [sample_exec, delete_exec, earliest_exec]

    log_search._aggregate_custom_windows(aggregator, window_minutes=60, db=db)

    assert db.commit.called


def test_aggregate_custom_windows_rebuilds_when_duration_mismatch():
    """Cover needs_rebuild when stored window duration does not match requested duration."""
    aggregator = MagicMock()
    db = MagicMock()

    sample_exec = MagicMock()
    sample_start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)  # aligned
    sample_end = sample_start + timedelta(minutes=30)  # duration mismatch for 60m
    sample_exec.first.return_value = (sample_start, sample_end)

    delete_exec = MagicMock()
    earliest_exec = MagicMock()
    earliest_exec.scalar.return_value = datetime.now(timezone.utc) - timedelta(minutes=30)

    db.execute.side_effect = [sample_exec, delete_exec, earliest_exec]

    log_search._aggregate_custom_windows(aggregator, window_minutes=60, db=db)

    assert db.commit.called


def test_aggregate_custom_windows_sample_row_with_nulls_skips_rebuild_check():
    """Cover sample_row present but missing start/end values."""
    aggregator = MagicMock()
    db = MagicMock()

    sample_exec = MagicMock()
    sample_exec.first.return_value = (None, datetime(2025, 1, 1, tzinfo=timezone.utc))
    max_exec = MagicMock()
    max_exec.scalar.return_value = None
    earliest_exec = MagicMock()
    earliest_exec.scalar.return_value = None

    db.execute.side_effect = [sample_exec, max_exec, earliest_exec]

    log_search._aggregate_custom_windows(aggregator, window_minutes=60, db=db)


def test_aggregate_custom_windows_returns_when_no_earliest_log():
    """Cover early return when there are no structured log timestamps."""
    aggregator = MagicMock()
    db = MagicMock()

    sample_exec = MagicMock()
    sample_exec.first.return_value = None
    max_exec = MagicMock()
    max_exec.scalar.return_value = None
    earliest_exec = MagicMock()
    earliest_exec.scalar.return_value = None

    db.execute.side_effect = [sample_exec, max_exec, earliest_exec]

    log_search._aggregate_custom_windows(aggregator, window_minutes=60, db=db)

    assert not aggregator.aggregate_all_components_batch.called


def test_aggregate_custom_windows_adds_timezone_to_naive_earliest_log():
    """Cover tzinfo normalization for earliest_log timestamps."""
    aggregator = MagicMock()
    db = MagicMock()

    sample_exec = MagicMock()
    sample_exec.first.return_value = None
    max_exec = MagicMock()
    max_exec.scalar.return_value = None
    earliest_exec = MagicMock()
    earliest_exec.scalar.return_value = datetime.now() - timedelta(minutes=30)  # naive

    db.execute.side_effect = [sample_exec, max_exec, earliest_exec]

    log_search._aggregate_custom_windows(aggregator, window_minutes=60, db=db)

    assert aggregator.aggregate_all_components_batch.called


def test_aggregate_custom_windows_truncates_window_starts(monkeypatch: pytest.MonkeyPatch):
    """Cover max_windows truncation warning."""
    aggregator = MagicMock()
    db = MagicMock()

    sample_exec = MagicMock()
    sample_exec.first.return_value = None
    max_exec = MagicMock()
    max_exec.scalar.return_value = None
    earliest_exec = MagicMock()
    earliest_exec.scalar.return_value = datetime.now(timezone.utc) - timedelta(minutes=10001)

    db.execute.side_effect = [sample_exec, max_exec, earliest_exec]

    warn = MagicMock()
    monkeypatch.setattr(log_search.logger, "warning", warn)

    log_search._aggregate_custom_windows(aggregator, window_minutes=1, db=db)

    assert warn.called
    assert len(aggregator.aggregate_all_components_batch.call_args.kwargs["window_starts"]) == 10000


def test_aggregate_custom_windows_no_windows_exits_early():
    """Cover branch where computed window list is empty (e.g., max_existing is in the future)."""
    aggregator = MagicMock()
    db = MagicMock()

    sample_exec = MagicMock()
    sample_exec.first.return_value = None
    max_exec = MagicMock()
    max_exec.scalar.return_value = datetime.now(timezone.utc) + timedelta(days=1)

    db.execute.side_effect = [sample_exec, max_exec]

    log_search._aggregate_custom_windows(aggregator, window_minutes=60, db=db)

    assert not aggregator.aggregate_all_components_batch.called


@pytest.mark.asyncio
async def test_search_logs_builds_response():
    log_entry = SimpleNamespace(
        id="log-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        level="INFO",
        component="gateway",
        message="hello",
        correlation_id="corr-1",
        user_id="user-1",
        user_email="user@example.com",
        duration_ms=12.5,
        operation_type="op",
        request_path="/path",
        request_method="GET",
        is_security_event=False,
        error_details=None,
    )

    count_result = MagicMock()
    count_result.scalar.return_value = 1
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [log_entry]

    db = MagicMock()
    db.execute.side_effect = [count_result, rows_result]

    request = log_search.LogSearchRequest(
        search_text="hello",
        level=["INFO"],
        component=["gateway"],
        correlation_id="corr-1",
        user_id="user-1",
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
        min_duration_ms=1.0,
        max_duration_ms=20.0,
        has_error=False,
        limit=10,
        offset=0,
        sort_by="timestamp",
        sort_order="desc",
    )

    response = await log_search.search_logs(request, user={"email": "user@example.com"}, db=db)
    assert response.total == 1
    assert response.results[0].id == "log-1"
    assert response.results[0].message == "hello"


@pytest.mark.asyncio
async def test_search_logs_has_error_true_and_sort_asc():
    log_entry = SimpleNamespace(
        id="log-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        level="INFO",
        component="gateway",
        message="hello",
        correlation_id="corr-1",
        user_id="user-1",
        user_email="user@example.com",
        duration_ms=12.5,
        operation_type="op",
        request_path="/path",
        request_method="GET",
        is_security_event=False,
        error_details={"msg": "boom"},
    )

    count_result = MagicMock()
    count_result.scalar.return_value = 1
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [log_entry]

    db = MagicMock()
    db.execute.side_effect = [count_result, rows_result]

    request = log_search.LogSearchRequest(has_error=True, sort_order="asc", limit=10, offset=0)

    response = await log_search.search_logs(request, user={"email": "user@example.com"}, db=db)
    assert response.total == 1
    assert response.results[0].error_details["msg"] == "boom"


@pytest.mark.asyncio
async def test_search_logs_error_path():
    db = MagicMock()
    db.execute.side_effect = Exception("boom")
    request = log_search.LogSearchRequest()

    with pytest.raises(HTTPException):
        await log_search.search_logs(request, user={"email": "user@example.com"}, db=db)


@pytest.mark.asyncio
async def test_trace_correlation_id_includes_metrics():
    log_entry = SimpleNamespace(
        id="log-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        level="INFO",
        component="gateway",
        message="hello",
        correlation_id="corr-1",
        user_id="user-1",
        user_email="user@example.com",
        duration_ms=12.5,
        operation_type="op",
        request_path="/path",
        request_method="GET",
        is_security_event=False,
        error_details=None,
    )
    security_event = SimpleNamespace(
        id="sec-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        event_type="login",
        severity="high",
        description="bad",
        threat_score=9.5,
    )
    audit_trail = SimpleNamespace(
        id="audit-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        action="update",
        resource_type="tool",
        resource_id="tool-1",
        success=True,
    )
    perf_metric = SimpleNamespace(avg_duration_ms=10.0, p95_duration_ms=20.0, p99_duration_ms=30.0, error_rate=0.1)

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [log_entry]
    security_result = MagicMock()
    security_result.scalars.return_value.all.return_value = [security_event]
    audit_result = MagicMock()
    audit_result.scalars.return_value.all.return_value = [audit_trail]
    perf_result = MagicMock()
    perf_result.scalar_one_or_none.return_value = perf_metric

    db = MagicMock()
    db.execute.side_effect = [logs_result, security_result, audit_result, perf_result]

    response = await log_search.trace_correlation_id("corr-1", user={"email": "user@example.com"}, db=db)
    assert response.correlation_id == "corr-1"
    assert response.log_count == 1
    assert response.error_count == 0
    assert response.performance_metrics["avg_duration_ms"] == 10.0
    assert response.security_events[0]["event_type"] == "login"
    assert response.audit_trails[0]["action"] == "update"


@pytest.mark.asyncio
async def test_trace_correlation_id_no_logs_has_no_perf_metrics():
    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = []
    security_result = MagicMock()
    security_result.scalars.return_value.all.return_value = []
    audit_result = MagicMock()
    audit_result.scalars.return_value.all.return_value = []

    db = MagicMock()
    db.execute.side_effect = [logs_result, security_result, audit_result]

    response = await log_search.trace_correlation_id("corr-1", user={"email": "user@example.com"}, db=db)
    assert response.log_count == 0
    assert response.performance_metrics is None


@pytest.mark.asyncio
async def test_trace_correlation_id_missing_component_or_operation_skips_perf_query():
    log_entry = SimpleNamespace(
        id="log-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        level="INFO",
        component="",
        message="hello",
        correlation_id="corr-1",
        user_id="user-1",
        user_email="user@example.com",
        duration_ms=None,
        operation_type="op",
        request_path="/path",
        request_method="GET",
        is_security_event=False,
        error_details=None,
    )

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [log_entry]
    security_result = MagicMock()
    security_result.scalars.return_value.all.return_value = []
    audit_result = MagicMock()
    audit_result.scalars.return_value.all.return_value = []

    db = MagicMock()
    db.execute.side_effect = [logs_result, security_result, audit_result]

    response = await log_search.trace_correlation_id("corr-1", user={"email": "user@example.com"}, db=db)
    assert response.performance_metrics is None


@pytest.mark.asyncio
async def test_trace_correlation_id_no_perf_metric_found():
    log_entry = SimpleNamespace(
        id="log-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        level="INFO",
        component="gateway",
        message="hello",
        correlation_id="corr-1",
        user_id="user-1",
        user_email="user@example.com",
        duration_ms=12.5,
        operation_type="op",
        request_path="/path",
        request_method="GET",
        is_security_event=False,
        error_details=None,
    )

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [log_entry]
    security_result = MagicMock()
    security_result.scalars.return_value.all.return_value = []
    audit_result = MagicMock()
    audit_result.scalars.return_value.all.return_value = []
    perf_result = MagicMock()
    perf_result.scalar_one_or_none.return_value = None

    db = MagicMock()
    db.execute.side_effect = [logs_result, security_result, audit_result, perf_result]

    response = await log_search.trace_correlation_id("corr-1", user={"email": "user@example.com"}, db=db)
    assert response.performance_metrics is None


@pytest.mark.asyncio
async def test_trace_correlation_id_error_path():
    db = MagicMock()
    db.execute.side_effect = Exception("boom")

    with pytest.raises(HTTPException) as exc_info:
        await log_search.trace_correlation_id("corr-1", user={"email": "user@example.com"}, db=db)

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_get_security_events_filters():
    event = SimpleNamespace(
        id="sec-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        event_type="login",
        severity="high",
        category="auth",
        user_id="user-1",
        client_ip="127.0.0.1",
        description="bad",
        threat_score=9.5,
        action_taken=None,
        resolved=False,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [event]
    db = MagicMock()
    db.execute.return_value = result

    response = await log_search.get_security_events(
        severity=["high"],
        event_type=["login"],
        resolved=False,
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
        limit=10,
        offset=0,
        user={"email": "user@example.com"},
        db=db,
    )
    assert response[0].event_type == "login"
    assert response[0].severity == "high"


@pytest.mark.asyncio
async def test_get_security_events_no_filters():
    event = SimpleNamespace(
        id="sec-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        event_type="login",
        severity="high",
        category="auth",
        user_id="user-1",
        client_ip="127.0.0.1",
        description="bad",
        threat_score=9.5,
        action_taken=None,
        resolved=False,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [event]
    db = MagicMock()
    db.execute.return_value = result

    response = await log_search.get_security_events(
        severity=None,
        event_type=None,
        resolved=None,
        start_time=None,
        end_time=None,
        limit=10,
        offset=0,
        user={"email": "user@example.com"},
        db=db,
    )
    assert response[0].id == "sec-1"


@pytest.mark.asyncio
async def test_get_security_events_error_path():
    db = MagicMock()
    db.execute.side_effect = Exception("boom")

    with pytest.raises(HTTPException) as exc_info:
        await log_search.get_security_events(
            severity=None,
            event_type=None,
            resolved=None,
            start_time=None,
            end_time=None,
            limit=10,
            offset=0,
            user={"email": "user@example.com"},
            db=db,
        )

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_get_audit_trails_filters():
    trail = SimpleNamespace(
        id="audit-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        correlation_id="corr-1",
        action="update",
        resource_type="tool",
        resource_id="tool-1",
        resource_name="Tool",
        user_id="user-1",
        user_email="user@example.com",
        success=True,
        requires_review=False,
        data_classification=None,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [trail]
    db = MagicMock()
    db.execute.return_value = result

    response = await log_search.get_audit_trails(
        action=["update"],
        resource_type=["tool"],
        user_id="user-1",
        requires_review=False,
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
        limit=10,
        offset=0,
        user={"email": "user@example.com"},
        db=db,
    )
    assert response[0].action == "update"
    assert response[0].resource_type == "tool"


@pytest.mark.asyncio
async def test_get_audit_trails_no_filters():
    trail = SimpleNamespace(
        id="audit-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        correlation_id="corr-1",
        action="update",
        resource_type="tool",
        resource_id="tool-1",
        resource_name="Tool",
        user_id="user-1",
        user_email="user@example.com",
        success=True,
        requires_review=False,
        data_classification=None,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [trail]
    db = MagicMock()
    db.execute.return_value = result

    response = await log_search.get_audit_trails(
        action=None,
        resource_type=None,
        user_id=None,
        requires_review=None,
        start_time=None,
        end_time=None,
        limit=10,
        offset=0,
        user={"email": "user@example.com"},
        db=db,
    )
    assert response[0].id == "audit-1"


@pytest.mark.asyncio
async def test_get_audit_trails_error_path():
    db = MagicMock()
    db.execute.side_effect = Exception("boom")

    with pytest.raises(HTTPException) as exc_info:
        await log_search.get_audit_trails(
            action=None,
            resource_type=None,
            user_id=None,
            requires_review=None,
            start_time=None,
            end_time=None,
            limit=10,
            offset=0,
            user={"email": "user@example.com"},
            db=db,
        )

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_get_performance_metrics_with_backfill(monkeypatch):
    metric = SimpleNamespace(
        id="perf-1",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        component="gateway",
        operation_type="op",
        window_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        request_count=10,
        error_count=1,
        error_rate=0.1,
        avg_duration_ms=10.0,
        min_duration_ms=1.0,
        max_duration_ms=20.0,
        p50_duration_ms=8.0,
        p95_duration_ms=18.0,
        p99_duration_ms=19.0,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [metric]
    db = MagicMock()
    db.execute.return_value = result

    aggregator = MagicMock()
    monkeypatch.setattr(log_search, "get_log_aggregator", lambda: aggregator)
    monkeypatch.setattr(log_search.settings, "metrics_aggregation_enabled", True)

    response = await log_search.get_performance_metrics(
        component=None,
        operation=None,
        hours=1.0,
        aggregation="5m",
        user={"email": "user@example.com"},
        db=db,
    )
    assert response[0].id == "perf-1"
    assert aggregator.backfill.called


@pytest.mark.asyncio
async def test_get_performance_metrics_custom_window(monkeypatch):
    metric = SimpleNamespace(
        id="perf-2",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        component="gateway",
        operation_type="op",
        window_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        request_count=10,
        error_count=1,
        error_rate=0.1,
        avg_duration_ms=10.0,
        min_duration_ms=1.0,
        max_duration_ms=20.0,
        p50_duration_ms=8.0,
        p95_duration_ms=18.0,
        p99_duration_ms=19.0,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [metric]
    db = MagicMock()
    db.execute.return_value = result

    monkeypatch.setattr(log_search, "_aggregate_custom_windows", MagicMock())
    monkeypatch.setattr(log_search, "get_log_aggregator", lambda: MagicMock())
    monkeypatch.setattr(log_search.settings, "metrics_aggregation_enabled", True)

    response = await log_search.get_performance_metrics(
        component="gateway",
        operation="op",
        hours=1.0,
        aggregation="24h",
        user={"email": "user@example.com"},
        db=db,
    )
    assert response[0].id == "perf-2"
    assert log_search._aggregate_custom_windows.called


@pytest.mark.asyncio
async def test_get_performance_metrics_no_aggregation_enabled(monkeypatch):
    metric = SimpleNamespace(
        id="perf-3",
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        component="gateway",
        operation_type="op",
        window_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        request_count=10,
        error_count=1,
        error_rate=0.1,
        avg_duration_ms=10.0,
        min_duration_ms=1.0,
        max_duration_ms=20.0,
        p50_duration_ms=8.0,
        p95_duration_ms=18.0,
        p99_duration_ms=19.0,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [metric]
    db = MagicMock()
    db.execute.return_value = result

    monkeypatch.setattr(log_search.settings, "metrics_aggregation_enabled", False)
    get_agg = MagicMock()
    monkeypatch.setattr(log_search, "get_log_aggregator", get_agg)

    response = await log_search.get_performance_metrics(
        component=None,
        operation=None,
        hours=1.0,
        aggregation="5m",
        user={"email": "user@example.com"},
        db=db,
    )

    assert response[0].id == "perf-3"
    assert not get_agg.called


@pytest.mark.asyncio
async def test_get_performance_metrics_error_path(monkeypatch):
    db = MagicMock()
    db.execute.side_effect = Exception("boom")

    monkeypatch.setattr(log_search.settings, "metrics_aggregation_enabled", False)

    with pytest.raises(HTTPException) as exc_info:
        await log_search.get_performance_metrics(
            component=None,
            operation=None,
            hours=1.0,
            aggregation="5m",
            user={"email": "user@example.com"},
            db=db,
        )

    assert exc_info.value.status_code == 500
