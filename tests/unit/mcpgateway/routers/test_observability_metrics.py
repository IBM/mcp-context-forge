# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_observability_metrics.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the /observability/metrics summary endpoints.

Uses an in-memory SQLite database with real ObservabilityTrace rows so the
bucketing and percentile math run as actual queries rather than mocked results.
"""

# Standard
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, ObservabilityTrace
from mcpgateway.middleware import rbac as rbac_module
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.routers import observability as observability_module
from mcpgateway.services.observability_service import _execution_timeseries_postgresql, _latency_percentiles_postgresql, ObservabilityService

BASE_TIME = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """datetime subclass pinning ``now()`` so BASE_TIME rows fall inside the look-back window."""

    @classmethod
    def now(cls, tz=None):
        """Return a fixed instant shortly after the newest fixture trace.

        Args:
            tz: Requested timezone, honoured if given.

        Returns:
            datetime: The frozen 'current' time.
        """
        frozen = BASE_TIME + timedelta(hours=2)
        return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)


@pytest.fixture
def db_session():
    """In-memory SQLite session shared across all connections within one test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def observability_on(monkeypatch: pytest.MonkeyPatch):
    """Enable observability; the config default is off."""
    monkeypatch.setattr(settings, "observability_enabled", True)


@pytest.fixture(autouse=True)
def no_plugin_manager(monkeypatch: pytest.MonkeyPatch):
    """Keep plugin hooks out of the permission path for these tests."""

    async def _no_plugin_manager():
        return None

    monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", _no_plugin_manager)


@pytest.fixture
def grant_permissions(monkeypatch: pytest.MonkeyPatch):
    """Return a helper that grants or denies specific permissions by name."""

    def _configure(denied=()):
        async def _check(self, **kwargs):  # type: ignore[no-self-use]
            return kwargs.get("permission") not in denied

        monkeypatch.setattr(rbac_module.PermissionService, "check_permission", _check)

    return _configure


def make_trace(db, *, offset_seconds=0, duration_ms=None, status="ok"):
    """Insert one ObservabilityTrace row and return it.

    Args:
        db: Database session.
        offset_seconds: Seconds added to BASE_TIME for this row's start time.
        duration_ms: Trace duration in milliseconds, or None.
        status: Trace status label.

    Returns:
        ObservabilityTrace: The persisted row.
    """
    row = ObservabilityTrace(
        name="GET /test",
        start_time=BASE_TIME + timedelta(seconds=offset_seconds),
        duration_ms=duration_ms,
        status=status,
    )
    db.add(row)
    db.commit()
    return row


async def call_timeseries(db, *, hours=24, interval_minutes=60):
    """Invoke the timeseries handler directly.

    Args:
        db: Database session.
        hours: Look-back window in hours.
        interval_minutes: Bucket width in minutes.

    Returns:
        TimeseriesResponse: The handler's response.
    """
    return await observability_module.get_metrics_timeseries(
        request=MagicMock(),
        hours=hours,
        interval_minutes=interval_minutes,
        user={"email": "admin@example.com", "db": db},
        db=db,
    )


async def call_percentiles(db, *, hours=24, interval_minutes=60):
    """Invoke the percentiles handler directly.

    Args:
        db: Database session.
        hours: Look-back window in hours.
        interval_minutes: Bucket width in minutes.

    Returns:
        PercentilesResponse: The handler's response.
    """
    return await observability_module.get_metrics_percentiles(
        request=MagicMock(),
        hours=hours,
        interval_minutes=interval_minutes,
        user={"email": "admin@example.com", "db": db},
        db=db,
    )


@pytest.mark.asyncio
async def test_timeseries_counts_executions_per_bucket(db_session, grant_permissions, monkeypatch):
    """Traces are counted into fixed-width buckets, sparse and time-ordered."""
    grant_permissions()
    monkeypatch.setattr(observability_module, "datetime", _FrozenDatetime)
    make_trace(db_session, offset_seconds=300)
    make_trace(db_session, offset_seconds=600)
    make_trace(db_session, offset_seconds=5400)

    response = await call_timeseries(db_session)

    assert response.buckets == ["2025-01-01T12:00:00+00:00", "2025-01-01T13:00:00+00:00"]
    assert response.values == [2, 1]


@pytest.mark.asyncio
async def test_percentiles_linear_interpolation_and_null_exclusion(db_session, grant_permissions, monkeypatch):
    """Percentiles interpolate like percentile_cont and skip rows without a duration."""
    grant_permissions()
    monkeypatch.setattr(observability_module, "datetime", _FrozenDatetime)
    make_trace(db_session, offset_seconds=60, duration_ms=100.0)
    make_trace(db_session, offset_seconds=120, duration_ms=200.0)
    make_trace(db_session, offset_seconds=180, duration_ms=None)

    response = await call_percentiles(db_session)

    assert response.buckets == ["2025-01-01T12:00:00+00:00"]
    assert response.p50 == [150.0]
    assert response.p95 == [195.0]
    assert response.p99 == [199.0]


@pytest.mark.asyncio
async def test_metrics_read_denied_returns_403(db_session, grant_permissions):
    """Both endpoints are gated by metrics:read."""
    grant_permissions(denied={"metrics:read"})

    with pytest.raises(HTTPException) as timeseries_error:
        await call_timeseries(db_session)
    assert timeseries_error.value.status_code == 403

    with pytest.raises(HTTPException) as percentiles_error:
        await call_percentiles(db_session)
    assert percentiles_error.value.status_code == 403


@pytest.mark.asyncio
async def test_observability_disabled_returns_empty_series(db_session, grant_permissions, monkeypatch):
    """Disabled observability yields empty series instead of an error, ignoring stale rows."""
    grant_permissions()
    monkeypatch.setattr(settings, "observability_enabled", False)
    make_trace(db_session, offset_seconds=300, duration_ms=100.0)

    timeseries = await call_timeseries(db_session)
    percentiles = await call_percentiles(db_session)

    assert (timeseries.buckets, timeseries.values) == ([], [])
    assert (percentiles.buckets, percentiles.p50, percentiles.p95, percentiles.p99) == ([], [], [], [])


def test_routes_registered_on_metrics_router():
    """The endpoints are served by the always-mounted metrics summary router, not the flag-gated observability router or the admin router."""
    paths = {route.path for route in observability_module.observability_metrics_router.routes}
    assert {"/observability/metrics/timeseries", "/observability/metrics/percentiles"} <= paths


def test_metrics_unauthenticated_returns_401():
    """No auth context -> 401 over HTTP, before any aggregation runs."""
    api = FastAPI()
    api.include_router(observability_module.observability_metrics_router)

    async def deny_auth():
        raise HTTPException(status_code=401, detail="Not authenticated")

    api.dependency_overrides[get_current_user_with_permissions] = deny_auth
    api.dependency_overrides[observability_module.get_db] = lambda: MagicMock(spec=Session)

    client = TestClient(api)
    assert client.get("/observability/metrics/timeseries").status_code == 401
    assert client.get("/observability/metrics/percentiles").status_code == 401


@pytest.mark.parametrize(
    "endpoint,params",
    [
        ("timeseries", {"hours": 0}),
        ("timeseries", {"hours": 169}),
        ("timeseries", {"interval_minutes": 4}),
        ("timeseries", {"interval_minutes": 1441}),
        ("percentiles", {"hours": 0}),
        ("percentiles", {"hours": 169}),
        ("percentiles", {"interval_minutes": 4}),
        ("percentiles", {"interval_minutes": 1441}),
    ],
)
def test_metrics_reject_out_of_range_query_params(endpoint, params):
    """Look-back and bucket width are bounded, so a caller cannot ask for an unbounded scan."""
    api = FastAPI()
    api.include_router(observability_module.observability_metrics_router)

    async def allow_auth():
        return {"email": "user@example.com", "db": MagicMock(spec=Session)}

    api.dependency_overrides[get_current_user_with_permissions] = allow_auth
    api.dependency_overrides[observability_module.get_db] = lambda: MagicMock(spec=Session)

    client = TestClient(api)
    assert client.get(f"/observability/metrics/{endpoint}", params=params).status_code == 422


def test_postgres_buckets_normalized_to_utc():
    """Postgres rows tagged with a session timezone serialize as UTC, matching the SQLite path."""
    est = timezone(timedelta(hours=-5))
    bucket = datetime(2025, 1, 1, 7, 0, 0, tzinfo=est)

    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [SimpleNamespace(bucket=bucket, total=2)]
    timeseries = _execution_timeseries_postgresql(db, BASE_TIME - timedelta(hours=24), 60)
    assert timeseries["buckets"] == ["2025-01-01T12:00:00+00:00"]
    assert timeseries["values"] == [2]

    db.execute.return_value.fetchall.return_value = [SimpleNamespace(bucket=bucket, p50=100.0, p95=190.0, p99=198.0)]
    percentiles = _latency_percentiles_postgresql(db, BASE_TIME - timedelta(hours=24), 60)
    assert percentiles["buckets"] == ["2025-01-01T12:00:00+00:00"]
    assert percentiles["p50"] == [100.0]


@pytest.fixture
def non_utc_host_timezone():
    """Force a non-UTC host timezone so naive-datetime handling is observable."""
    # Standard
    import os
    import time

    original = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


def test_postgres_buckets_with_naive_timestamps_labeled_utc(non_utc_host_timezone):
    """A naive bucket is labeled UTC rather than shifted by the host's local offset.

    Guards the ensure_timezone_aware() call: a bare .astimezone() would read a
    naive value as host-local time, so on this fixture's America/New_York host
    the bucket would serialize as 17:00Z instead of 12:00Z.
    """
    naive_bucket = datetime(2025, 1, 1, 12, 0, 0)

    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [SimpleNamespace(bucket=naive_bucket, total=2)]
    timeseries = _execution_timeseries_postgresql(db, BASE_TIME - timedelta(hours=24), 60)
    assert timeseries["buckets"] == ["2025-01-01T12:00:00+00:00"]

    db.execute.return_value.fetchall.return_value = [SimpleNamespace(bucket=naive_bucket, p50=100.0, p95=190.0, p99=198.0)]
    percentiles = _latency_percentiles_postgresql(db, BASE_TIME - timedelta(hours=24), 60)
    assert percentiles["buckets"] == ["2025-01-01T12:00:00+00:00"]
    assert percentiles["p95"] == [190.0]
    assert percentiles["p99"] == [198.0]


@pytest.mark.parametrize("handler", (call_timeseries, call_percentiles))
@pytest.mark.asyncio
async def test_metrics_permission_check_is_global_only(db_session, monkeypatch, handler):
    """Team-scoped roles can never satisfy metrics:read on these endpoints.

    The aggregation queries have no team/tenant filter, so the isolation guarantee
    must live in the decorator (global_only=True) rather than depending on which
    roles happen to be granted the permission. Without it, check_any_team=True
    would let a team-scoped grant pass RBAC and return platform-wide data.
    """
    captured = {}

    async def _check(self, **kwargs):  # type: ignore[no-self-use]
        captured.update(kwargs)
        return True

    monkeypatch.setattr(rbac_module.PermissionService, "check_permission", _check)

    await handler(db_session)

    assert captured["permission"] == "metrics:read"
    assert captured["team_id"] is None
    assert captured["check_any_team"] is False
    assert captured["allow_admin_bypass"] is False


@pytest.mark.parametrize(
    "service_method,expected_keys",
    [
        ("get_execution_timeseries", ("buckets", "values")),
        ("get_latency_percentiles", ("buckets", "p50", "p95", "p99")),
    ],
)
def test_service_dispatches_to_postgresql_path_when_empty(service_method, expected_keys):
    """The public dispatch methods route to the PostgreSQL helpers on that dialect.

    A mocked postgresql dialect with no rows also exercises the helpers' own
    empty-results branch, which the SQLite-backed handler tests never reach
    since observability-disabled short-circuits before either helper runs.
    """
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "postgresql"
    db.execute.return_value.fetchall.return_value = []

    result = getattr(ObservabilityService(), service_method)(db, BASE_TIME - timedelta(hours=24), 60)

    assert result["buckets"] == []
    for key in expected_keys[1:]:
        assert result[key] == []
    db.execute.assert_called_once()


@pytest.mark.parametrize("handler,service_method", [(call_timeseries, "get_execution_timeseries"), (call_percentiles, "get_latency_percentiles")])
@pytest.mark.asyncio
async def test_metrics_endpoint_returns_500_on_service_error(db_session, grant_permissions, monkeypatch, handler, service_method):
    """A service-layer failure surfaces as a 500, not an unhandled exception."""
    grant_permissions()

    def _raise(self, *args, **kwargs):
        raise RuntimeError("aggregation query failed")

    monkeypatch.setattr(ObservabilityService, service_method, _raise)

    with pytest.raises(HTTPException) as exc_info:
        await handler(db_session)
    assert exc_info.value.status_code == 500
