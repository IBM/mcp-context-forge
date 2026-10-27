# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_observability_session_lifecycle.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify observability persistence and pool usage with real SQLite sessions.
"""

# Standard
import asyncio
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from typing import Any

# Third-Party
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway import db
from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware
from mcpgateway.services import observability_service
from mcpgateway.services.observability_service import ObservabilityService


Database = tuple[Engine, sessionmaker[Session], dict[str, int]]


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Database, None, None]:
    """Provide isolated persistence with foreign keys and a two-connection pool."""
    engine = create_engine(f"sqlite:///{tmp_path / 'observability.db'}", pool_size=2, max_overflow=0, pool_timeout=5, connect_args={"timeout": 5})

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: Any, _record: Any) -> None:
        """Enforce parent visibility for independent child writers."""
        connection.execute("PRAGMA foreign_keys=ON")

    tables = [db.Base.metadata.tables[model.__tablename__] for model in (db.ObservabilityTrace, db.ObservabilitySpan, db.ObservabilityEvent, db.ObservabilityMetric)]
    db.Base.metadata.create_all(engine, tables=tables)
    counts = {"sessions": 0, "closed": 0, "checkouts": 0, "active": 0, "peak": 0}
    lock = Lock()

    class CountedSession(Session):
        """Count real session creation and closure."""

        def __init__(self, **kwargs: Any) -> None:
            """Record session creation."""
            super().__init__(**kwargs)
            with lock:
                counts["sessions"] += 1

        def close(self) -> None:
            """Release resources and record closure."""
            super().close()
            with lock:
                counts["closed"] += 1

    @event.listens_for(engine, "checkout")
    def checkout(_connection: Any, _record: Any, _proxy: Any) -> None:
        """Count actual checked-out connections."""
        with lock:
            counts["checkouts"] += 1
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])

    @event.listens_for(engine, "checkin")
    def checkin(_connection: Any, _record: Any) -> None:
        """Record connection release."""
        with lock:
            counts["active"] -= 1

    factory = sessionmaker[Session](bind=engine, class_=CountedSession, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(observability_service, "SessionLocal", factory)
    yield engine, factory, counts
    engine.dispose()


@pytest.mark.parametrize("fail", [False, True])
def test_pending_lifecycle_persists(database: Database, fail: bool) -> None:
    """Complete pending records with autoflush disabled on success and error."""
    engine, factory, _counts = database
    service = ObservabilityService()
    with factory() as session:
        trace_id = service.start_trace("pending", commit=False, obs_db=session)
        span_id = service.start_span(trace_id, "pending", commit=False, obs_db=session)
        status = "error" if fail else "ok"
        service.end_span(span_id, status=status, commit=False, obs_db=session)
        if fail:
            service.add_event(span_id, "exception", message="failure", obs_db=session)
        service.end_trace(trace_id, status=status, obs_db=session)
    with Session(engine) as reader:
        trace = reader.get(db.ObservabilityTrace, trace_id)
        span = reader.get(db.ObservabilitySpan, span_id)
        assert trace is not None
        assert span is not None
        assert trace.status == span.status == status
        assert trace.end_time is not None
        assert span.end_time is not None
        assert reader.scalar(select(func.count()).select_from(db.ObservabilityEvent)) == int(fail)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_middleware_independent_child_writers(database: Database, fail: bool) -> None:
    """Persist parent records before independent child spans and metrics."""
    engine, _factory, counts = database
    service = ObservabilityService()
    middleware = ObservabilityMiddleware(None, enabled=True, service=service)
    request = Request({"type": "http", "method": "GET", "path": "/rpc", "headers": [], "query_string": b""})

    async def handler(request: Request) -> Response:
        """Write child data through independent transactions."""
        assert counts["active"] == 0
        with Session(engine) as reader:
            assert reader.get(db.ObservabilityTrace, request.state.trace_id) is not None
            assert reader.get(db.ObservabilitySpan, request.state.span_id) is not None
        child_id = service.start_span(request.state.trace_id, "child", parent_span_id=request.state.span_id)
        service.end_span(child_id)
        service.record_metric("test.child", 1, trace_id=request.state.trace_id)
        if fail:
            raise RuntimeError("handler failure")
        return Response("OK")

    if fail:
        with pytest.raises(RuntimeError, match="handler failure"):
            await middleware.dispatch(request, handler)
    else:
        assert (await middleware.dispatch(request, handler)).status_code == 200
    assert counts["active"] == 0
    assert counts["sessions"] == counts["closed"] == 4
    with Session(engine) as reader:
        trace = reader.get(db.ObservabilityTrace, request.state.trace_id)
        span = reader.get(db.ObservabilitySpan, request.state.span_id)
        assert trace is not None
        assert span is not None
        assert trace.status == span.status == ("error" if fail else "ok")
        assert trace.end_time is not None
        assert span.end_time is not None
        assert reader.scalar(select(func.count()).select_from(db.ObservabilitySpan)) == 2
        assert reader.scalar(select(func.count()).select_from(db.ObservabilityMetric)) == 1
        assert reader.scalar(select(func.count()).select_from(db.ObservabilityEvent)) == int(fail)


@pytest.mark.parametrize("reuse", [False, True], ids=["independent-baseline", "reused"])
@pytest.mark.parametrize("fail", [False, True], ids=["success", "error"])
def test_concurrent_lifecycle_pool_counts(database: Database, reuse: bool, fail: bool) -> None:
    """Measure independent and reused lifecycles with eight requests and two connections."""
    engine, _factory, counts = database

    def assert_connections_released() -> None:
        """Verify all handlers overlap without reserved connections."""
        assert counts["active"] == 0

    barrier = Barrier(8, action=assert_connections_released)

    def run_request(_index: int) -> None:
        """Run one lifecycle while all request handlers overlap."""
        service = ObservabilityService()
        request = Request({"type": "http", "method": "GET", "path": "/rpc", "headers": [], "query_string": b""})

        async def handler(_request: Request) -> Response:
            """Hold concurrent requests without retaining database connections."""
            barrier.wait(timeout=10)
            await asyncio.sleep(0.01)
            if fail:
                raise RuntimeError("handler failure")
            return Response("OK")

        async def dispatch() -> Response:
            """Compare middleware reuse against the original independent-session lifecycle."""
            if reuse:
                return await ObservabilityMiddleware(None, enabled=True, service=service).dispatch(request, handler)
            trace_id = service.start_trace("baseline")
            span_id = service.start_span(trace_id, "http.request")
            try:
                response = await handler(request)
            except RuntimeError:
                service.end_span(span_id, status="error")
                service.add_event(span_id, "exception", message="handler failure")
                service.end_trace(trace_id, status="error", http_status_code=500)
                raise
            service.end_span(span_id)
            service.end_trace(trace_id, http_status_code=200)
            return response

        if fail:
            with pytest.raises(RuntimeError, match="handler failure"):
                asyncio.run(dispatch())
        else:
            assert asyncio.run(dispatch()).status_code == 200

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(run_request, range(8)))
    expected_sessions = 8 if reuse else 8 * (5 if fail else 4)
    assert counts["sessions"] == counts["closed"] == expected_sessions
    expected_checkouts = 8 * ((4 if fail else 3) if reuse else (6 if fail else 4))
    assert counts["checkouts"] == expected_checkouts
    assert counts["active"] == 0
    assert counts["peak"] <= 2
    print(f"reuse={reuse} fail={fail} requests=8 counts={counts}")
    with Session(engine) as reader:
        status = "error" if fail else "ok"
        assert reader.scalar(select(func.count()).select_from(db.ObservabilityTrace).where(db.ObservabilityTrace.status == status)) == 8
        assert reader.scalar(select(func.count()).select_from(db.ObservabilitySpan).where(db.ObservabilitySpan.status == status)) == 8
        assert reader.scalar(select(func.count()).select_from(db.ObservabilityEvent)) == 8 * int(fail)


@pytest.mark.asyncio
async def test_session_creation_failure_preserves_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Continue serving requests when observability session allocation fails."""

    def unavailable() -> Session:
        """Simulate unavailable observability persistence."""
        raise RuntimeError("session unavailable")

    monkeypatch.setattr(db, "SessionLocal", unavailable)
    middleware = ObservabilityMiddleware(None, enabled=True)
    request = Request({"type": "http", "method": "GET", "path": "/rpc", "headers": [], "query_string": b""})

    async def handler(_request: Request) -> Response:
        """Return the application response without tracing."""
        return Response("OK")

    assert (await middleware.dispatch(request, handler)).status_code == 200
