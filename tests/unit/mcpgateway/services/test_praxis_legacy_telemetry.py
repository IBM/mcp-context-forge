"""Deterministic policy and persistence tests for legacy telemetry."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import threading
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, PraxisLegacyConsumer
from mcpgateway.config import settings
from mcpgateway.services.praxis_legacy_models import (
    InventoryAttestation,
    InventoryConsumer,
    LegacyConsumerPath,
    LegacyHeartbeat,
    RemovalBlockerCode,
)
from mcpgateway.services.praxis_legacy_telemetry import LegacyTelemetryError, PraxisLegacyTelemetryService
from mcpgateway.services.praxis_legacy_observability import emit_legacy_event, legacy_events


class FakeClock:
    __slots__ = ("current",)

    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


@pytest.fixture
def telemetry() -> Generator[tuple[Session, FakeClock, PraxisLegacyTelemetryService], None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        yield db, clock, PraxisLegacyTelemetryService(db, clock)
    engine.dispose()


def _attestation(**changes: bool | int | tuple[InventoryConsumer, ...]) -> InventoryAttestation:
    values = {
        "consumers": (),
        "private_state_present": False,
        "shadow_diff_count": 0,
        "task20_e2e_passed": True,
        "launcher_fleet_compatible": True,
    }
    values.update(changes)
    return InventoryAttestation.model_validate(values)


def _ready(telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService]) -> PraxisLegacyTelemetryService:
    _, clock, service = telemetry
    service.start_coverage()
    service.attest("admin@example.com", _attestation())
    clock.advance(timedelta(days=30))
    return service


def test_later_of_coverage_and_attestation_30_days(telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService]) -> None:
    _, clock, service = telemetry
    service.start_coverage()
    clock.advance(timedelta(days=10))
    service.attest("admin@example.com", _attestation())
    clock.advance(timedelta(days=29, hours=23, minutes=59, seconds=59))
    assert RemovalBlockerCode.COVERAGE_WINDOW in service.removal_report().blockers
    clock.advance(timedelta(seconds=1))
    assert service.removal_report().ready


@pytest.mark.parametrize(
    ("name", "setup", "blocker"),
    [
        ("empty_registry", lambda service: None, RemovalBlockerCode.EMPTY_REGISTRY),
        ("missing_attestation", lambda service: service.start_coverage(), RemovalBlockerCode.MISSING_ATTESTATION),
        ("private_state", lambda service: service.attest("admin@example.com", _attestation(private_state_present=True)), RemovalBlockerCode.PRIVATE_STATE),
        ("shadow_mismatch", lambda service: service.attest("admin@example.com", _attestation(shadow_diff_count=1)), RemovalBlockerCode.SHADOW_MISMATCH),
        ("failed_e2e", lambda service: service.attest("admin@example.com", _attestation(task20_e2e_passed=False)), RemovalBlockerCode.FAILED_E2E),
        ("incompatible_launcher", lambda service: service.attest("admin@example.com", _attestation(launcher_fleet_compatible=False)), RemovalBlockerCode.INCOMPATIBLE_LAUNCHER),
    ],
)
def test_readiness_failure_codes(
    telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService],
    name: str,
    setup,
    blocker: RemovalBlockerCode,
) -> None:
    del name
    _, _, service = telemetry
    setup(service)
    assert blocker in service.removal_report().blockers


@pytest.mark.parametrize(
    ("name", "consumer", "blocker"),
    [
        ("active_consumer", InventoryConsumer(identity="client-a", version="1.2.0", path=LegacyConsumerPath.CONTROL_PLANE_GRPC, active=True), RemovalBlockerCode.ACTIVE_CONSUMER),
        ("unknown_version", InventoryConsumer(identity="client-a", version="unknown", path=LegacyConsumerPath.CONTROL_PLANE_GRPC, active=False), RemovalBlockerCode.UNKNOWN_VERSION),
        ("unobservable", InventoryConsumer(identity="redis-reader", version="1.2.0", path=LegacyConsumerPath.DIRECT_REDIS, active=False), RemovalBlockerCode.UNOBSERVABLE_CONSUMER),
    ],
)
def test_consumer_failure_codes(
    telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService],
    name: str,
    consumer: InventoryConsumer,
    blocker: RemovalBlockerCode,
) -> None:
    del name
    _, _, service = telemetry
    service.start_coverage()
    service.attest("admin@example.com", _attestation(consumers=(consumer,)))
    assert blocker in service.removal_report().blockers


def test_preinstrumentation_and_stale_heartbeat_block(telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService]) -> None:
    _, clock, service = telemetry
    service.heartbeat("client@example.com", LegacyHeartbeat(version="1.2.0", path=LegacyConsumerPath.CONTROL_PLANE_GRPC))
    clock.advance(timedelta(days=2))
    service.start_coverage()
    service.attest("admin@example.com", _attestation())
    report = service.removal_report()
    assert RemovalBlockerCode.PREINSTRUMENTATION in report.blockers
    assert RemovalBlockerCode.ACTIVE_CONSUMER not in report.blockers


def test_direct_redis_cannot_forge_observable_heartbeat(telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService]) -> None:
    _, _, service = telemetry
    with pytest.raises(LegacyTelemetryError, match="unobservable_consumer"):
        service.heartbeat("client@example.com", LegacyHeartbeat(version="1.2.0", path=LegacyConsumerPath.DIRECT_REDIS))


def test_heartbeat_identity_is_authenticated_actor_and_upserts(telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService]) -> None:
    db, clock, service = telemetry
    payload = LegacyHeartbeat(version="1.2.0", path=LegacyConsumerPath.CONTROL_PLANE_GRPC)
    service.heartbeat("authenticated@example.com", payload)
    clock.advance(timedelta(minutes=5))
    service.heartbeat("authenticated@example.com", payload)
    rows = db.scalars(select(PraxisLegacyConsumer)).all()
    assert len(rows) == 1
    assert rows[0].declared_identity == "authenticated@example.com"
    assert rows[0].authenticated_identity == "authenticated@example.com"


def test_removal_report_is_read_only(telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService]) -> None:
    db, _, service = telemetry
    _ready(telemetry)
    before = db.scalar(select(func.count()).select_from(PraxisLegacyConsumer))
    first = service.removal_report()
    second = service.removal_report()
    after = db.scalar(select(func.count()).select_from(PraxisLegacyConsumer))
    assert first == second
    assert before == after


def test_removal_report_cannot_delete_legacy_code_rows_or_redis_state(telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService]) -> None:
    from mcpgateway.services import dataplane_publisher

    db, _, service = telemetry
    service.heartbeat("client@example.com", LegacyHeartbeat(version="1.2.0", path=LegacyConsumerPath.CONTROL_PLANE_GRPC))
    publisher_path = Path(dataplane_publisher.__file__)
    source_before = publisher_path.read_bytes()
    rows_before = db.scalar(select(func.count()).select_from(PraxisLegacyConsumer))
    with patch.object(dataplane_publisher, "get_redis_client", new_callable=AsyncMock) as redis_client:
        service.removal_report()
    assert publisher_path.read_bytes() == source_before
    assert db.scalar(select(func.count()).select_from(PraxisLegacyConsumer)) == rows_before
    redis_client.assert_not_awaited()


def test_retention_expiration_never_deletes_consumer(telemetry: tuple[Session, FakeClock, PraxisLegacyTelemetryService]) -> None:
    db, clock, service = telemetry
    service.start_coverage()
    service.attest(
        "admin@example.com",
        _attestation(consumers=(InventoryConsumer(identity="old-client", version="1.2.0", path=LegacyConsumerPath.CONTROL_PLANE_GRPC, active=False),)),
    )
    clock.advance(timedelta(days=91))
    status = service.inventory()
    assert status.consumers[0].retention_state.value == "expired"
    assert db.scalar(select(func.count()).select_from(PraxisLegacyConsumer)) == 1


def test_persistence_survives_new_session(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'telemetry.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with factory() as db:
        service = PraxisLegacyTelemetryService(db, clock)
        service.start_coverage()
        service.attest("admin@example.com", _attestation())
        service.heartbeat("client@example.com", LegacyHeartbeat(version="1.2.0", path=LegacyConsumerPath.CONTROL_PLANE_GRPC))
    with factory() as db:
        status = PraxisLegacyTelemetryService(db, clock).inventory()
        assert status.coverage_started_at == clock.current
        assert status.inventory_attested_by == "admin@example.com"
        assert status.consumers[0].identity == "client@example.com"
    engine.dispose()


def test_concurrent_heartbeats_upsert_one_consumer(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def send() -> None:
        try:
            barrier.wait()
            with factory() as db:
                PraxisLegacyTelemetryService(db, clock).heartbeat(
                    "client@example.com",
                    LegacyHeartbeat(version="1.2.0", path=LegacyConsumerPath.CONTROL_PLANE_GRPC),
                )
        except (SQLAlchemyError, LegacyTelemetryError, threading.BrokenBarrierError) as error:
            failures.append(error)

    workers = [threading.Thread(target=send) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    with factory() as db:
        assert failures == []
        assert db.scalar(select(func.count()).select_from(PraxisLegacyConsumer)) == 1
    engine.dispose()


def test_legacy_compatibility_scaffolding_defaults_off() -> None:
    assert settings.dataplane_publisher is False
    assert settings.mcpgateway_grpc_enabled is False


def test_deprecation_signal_has_bounded_redacted_labels(caplog: pytest.LogCaptureFixture) -> None:
    before = legacy_events.labels(path="control_plane_grpc", outcome="heartbeat")._value.get()
    with caplog.at_level(logging.WARNING):
        emit_legacy_event(LegacyConsumerPath.CONTROL_PLANE_GRPC, "heartbeat")
    after = legacy_events.labels(path="control_plane_grpc", outcome="heartbeat")._value.get()
    assert after == before + 1
    assert "control_plane_grpc" in caplog.text
    assert "token-sentinel" not in caplog.text
