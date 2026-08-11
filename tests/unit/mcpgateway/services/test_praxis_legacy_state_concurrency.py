"""Cross-session concurrency regressions for legacy telemetry state."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier, Event, Lock, get_ident

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, PraxisLegacyTelemetryState
from mcpgateway.services import praxis_config_runtime
from mcpgateway.services.praxis_legacy_models import InventoryAttestation
from mcpgateway.services.praxis_legacy_telemetry import PraxisLegacyTelemetryService

DATABASE_PARAMS = [pytest.param("sqlite", id="sqlite")]
if postgres_url := os.getenv("MCPGATEWAY_TEST_POSTGRES_URL"):
    DATABASE_PARAMS.append(pytest.param(postgres_url, id="postgresql"))


class _FixedClock:
    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


@pytest.fixture(params=DATABASE_PARAMS)
def concurrent_store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'legacy-state.db'}", connect_args={"check_same_thread": False, "timeout": 10})
    else:
        engine = create_engine(request.param)
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine, sessionmaker(engine, expire_on_commit=False)
    if request.param != "sqlite":
        Base.metadata.drop_all(engine)
    engine.dispose()


def _synchronize_initial_state_reads(engine: Engine, barrier: Barrier) -> None:
    seen_threads: set[int] = set()
    guard = Lock()
    initialization_started = Event()

    def before_cursor_execute(_connection, _cursor, statement: str, _parameters, _context, _executemany: bool) -> None:
        normalized = statement.lstrip().upper()
        if "praxis_legacy_telemetry_state" not in statement:
            return
        if normalized.startswith("INSERT"):
            initialization_started.set()
            return
        if not normalized.startswith("SELECT") or initialization_started.is_set():
            return
        thread_id = get_ident()
        with guard:
            first_read = thread_id not in seen_threads
            seen_threads.add(thread_id)
        if first_read:
            barrier.wait()

    event.listen(engine, "before_cursor_execute", before_cursor_execute)


def test_runtime_startup_converges_on_one_authoritative_coverage_timestamp(
    concurrent_store: tuple[Engine, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory = concurrent_store
    instant = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    _synchronize_initial_state_reads(engine, Barrier(2))
    monkeypatch.setattr(praxis_config_runtime, "SessionLocal", factory)
    monkeypatch.setattr(praxis_config_runtime, "_SystemClock", lambda: _FixedClock(instant))

    def start() -> datetime | SQLAlchemyError:
        try:
            return praxis_config_runtime.start_praxis_legacy_coverage()
        except SQLAlchemyError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: start(), range(2)))

    assert outcomes == (instant, instant)
    with factory() as db:
        states = db.scalars(select(PraxisLegacyTelemetryState)).all()
        assert len(states) == 1
        coverage_started_at = states[0].coverage_started_at
        assert coverage_started_at is not None
        assert coverage_started_at.replace(tzinfo=timezone.utc) == instant
        assert states[0].cas_epoch == 1


def test_concurrent_attestation_creation_serializes_and_increments_cas(
    concurrent_store: tuple[Engine, sessionmaker[Session]],
) -> None:
    engine, factory = concurrent_store
    instant = datetime(2026, 8, 11, 13, tzinfo=timezone.utc)
    _synchronize_initial_state_reads(engine, Barrier(2))
    payload = InventoryAttestation(
        consumers=(),
        private_state_present=False,
        shadow_diff_count=0,
        task20_e2e_passed=True,
        launcher_fleet_compatible=True,
    )

    def attest(actor: str) -> str | SQLAlchemyError:
        try:
            with factory() as db:
                return PraxisLegacyTelemetryService(db, _FixedClock(instant)).attest(actor, payload).actor
        except SQLAlchemyError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(attest, ("admin-a@example.com", "admin-b@example.com")))

    assert set(outcomes) == {"admin-a@example.com", "admin-b@example.com"}
    with factory() as db:
        state = db.scalar(select(PraxisLegacyTelemetryState))
        assert state is not None
        assert db.scalar(select(func.count()).select_from(PraxisLegacyTelemetryState)) == 1
        assert state.inventory_attested_by in outcomes
        assert state.inventory_attestation_hash is not None
        assert state.cas_epoch == 2
