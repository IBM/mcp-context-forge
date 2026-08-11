"""Persistence and report-only policy for legacy Praxis consumers."""

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Protocol

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from mcpgateway.db import PraxisLegacyConsumer, PraxisLegacyTelemetryState
from mcpgateway.services.praxis_legacy_models import (
    AttestationReceipt,
    HeartbeatReceipt,
    InventoryAttestation,
    InventoryStatus,
    LegacyConsumerPath,
    LegacyConsumerView,
    LegacyHeartbeat,
    LegacyObservabilityClass,
    LegacyRetentionState,
    RemovalBlockerCode,
    RemovalReadinessReport,
    observability_for,
)
from mcpgateway.services.praxis_legacy_observability import emit_legacy_event, emit_removal_blockers

_HEARTBEAT_TTL = timedelta(days=1)
_RETENTION = timedelta(days=90)
_COVERAGE_WINDOW = timedelta(days=30)


class Clock(Protocol):
    """Injectable source of timezone-aware instants."""

    def now(self) -> datetime:
        """Return the current timezone-aware instant."""
        ...


class LegacyTelemetryError(RuntimeError):
    """Sanitized legacy telemetry boundary failure."""


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _consumer_id(identity: str, path: LegacyConsumerPath) -> str:
    return hashlib.sha256(f"{path.value}\0{identity}".encode()).hexdigest()[:36]


class PraxisLegacyTelemetryService:
    """Own persisted inventory, authenticated heartbeats, and removal reports."""

    def __init__(self, db: Session, clock: Clock) -> None:
        """Bind request-scoped persistence and an explicit clock."""
        self._db = db
        self._clock = clock

    def _state(self) -> PraxisLegacyTelemetryState | None:
        return self._db.get(PraxisLegacyTelemetryState, 1)

    def _initialize_state(self, now: datetime) -> None:
        values = {
            "id": 1,
            "private_state_present": False,
            "shadow_diff_count": 0,
            "task20_e2e_passed": False,
            "launcher_fleet_compatible": False,
            "cas_epoch": 0,
            "updated_at": now,
        }
        if self._db.get_bind().dialect.name == "postgresql":
            statement = postgresql_insert(PraxisLegacyTelemetryState).values(**values).on_conflict_do_nothing(index_elements=["id"])
        else:
            statement = sqlite_insert(PraxisLegacyTelemetryState).values(**values).on_conflict_do_nothing(index_elements=["id"])
        self._db.execute(statement)
        self._db.commit()

    def _locked_state(self) -> PraxisLegacyTelemetryState:
        if self._db.get_bind().dialect.name == "sqlite":
            self._db.execute(text("BEGIN IMMEDIATE"))
        query = select(PraxisLegacyTelemetryState).where(PraxisLegacyTelemetryState.id == 1)
        if self._db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update()
        state = self._db.scalar(query)
        assert state is not None
        return state

    def start_coverage(self) -> datetime:
        """Persist the first authoritative instrumentation instant exactly once."""
        now = self._clock.now()
        self._initialize_state(now)
        self._db.execute(
            update(PraxisLegacyTelemetryState)
            .where(PraxisLegacyTelemetryState.id == 1, PraxisLegacyTelemetryState.coverage_started_at.is_(None))
            .values(coverage_started_at=now, cas_epoch=PraxisLegacyTelemetryState.cas_epoch + 1, updated_at=now)
        )
        self._db.commit()
        coverage_started_at = self._db.scalar(select(PraxisLegacyTelemetryState.coverage_started_at).where(PraxisLegacyTelemetryState.id == 1))
        assert coverage_started_at is not None
        return _utc(coverage_started_at)

    def attest(self, actor: str, payload: InventoryAttestation) -> AttestationReceipt:
        """Persist one complete platform-admin inventory attestation."""
        now = self._clock.now()
        self._initialize_state(now)
        state = self._locked_state()
        for row in self._db.scalars(select(PraxisLegacyConsumer).where(PraxisLegacyConsumer.attested.is_(True))):
            row.attested = False
            if not row.observed:
                row.active = False
                row.revoked_at = now
                row.retention_state = LegacyRetentionState.RETAINED.value
                row.retain_until = now + _RETENTION
        for item in payload.consumers:
            row = self._db.get(PraxisLegacyConsumer, _consumer_id(item.identity, item.path))
            if row is None:
                row = PraxisLegacyConsumer(
                    id=_consumer_id(item.identity, item.path),
                    declared_identity=item.identity,
                    declared_version=item.version,
                    consumer_path=item.path.value,
                    observability_class=observability_for(item.path).value,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                self._db.add(row)
            row.declared_version = item.version
            row.attested = True
            row.active = item.active or bool(row.observed)
            row.revoked_at = None if row.active else now
            row.retention_state = LegacyRetentionState.ACTIVE.value if row.active else LegacyRetentionState.RETAINED.value
            row.retain_until = now + _RETENTION
        state.inventory_attested_at = now
        state.inventory_attested_by = actor
        state.inventory_attestation_hash = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        state.private_state_present = payload.private_state_present
        state.shadow_diff_count = payload.shadow_diff_count
        state.task20_e2e_passed = payload.task20_e2e_passed
        state.launcher_fleet_compatible = payload.launcher_fleet_compatible
        state.cas_epoch += 1
        self._db.commit()
        return AttestationReceipt(actor=actor, attested_at=now, consumer_count=len(payload.consumers))

    def heartbeat(self, actor: str, payload: LegacyHeartbeat) -> HeartbeatReceipt:
        """Upsert one authenticated server-observable consumer heartbeat."""
        if observability_for(payload.path) is LegacyObservabilityClass.UNOBSERVABLE:
            raise LegacyTelemetryError(RemovalBlockerCode.UNOBSERVABLE_CONSUMER.value)
        now = self._clock.now()
        expires_at = now + _HEARTBEAT_TTL
        values = {
            "id": _consumer_id(actor, payload.path),
            "declared_identity": actor,
            "declared_version": payload.version,
            "consumer_path": payload.path.value,
            "observability_class": LegacyObservabilityClass.SERVER_OBSERVABLE.value,
            "authenticated_identity": actor,
            "observed": True,
            "attested": False,
            "first_seen_at": now,
            "last_seen_at": now,
            "active": True,
            "revoked_at": None,
            "expires_at": expires_at,
            "retain_until": now + _RETENTION,
            "retention_state": LegacyRetentionState.ACTIVE.value,
        }
        updates = {key: value for key, value in values.items() if key not in {"id", "declared_identity", "consumer_path", "attested", "first_seen_at"}}
        if self._db.get_bind().dialect.name == "postgresql":
            statement = postgresql_insert(PraxisLegacyConsumer).values(**values).on_conflict_do_update(
                constraint="uq_praxis_legacy_consumers_identity_path",
                set_=updates,
            )
        else:
            statement = sqlite_insert(PraxisLegacyConsumer).values(**values).on_conflict_do_update(
                index_elements=["declared_identity", "consumer_path"],
                set_=updates,
            )
        self._db.execute(statement)
        self._db.commit()
        emit_legacy_event(payload.path, "heartbeat")
        return HeartbeatReceipt(identity=actor, observed_at=now, expires_at=expires_at)

    def _effective_retention(self, row: PraxisLegacyConsumer, now: datetime) -> LegacyRetentionState:
        if row.retain_until is not None and _utc(row.retain_until) <= now:
            return LegacyRetentionState.EXPIRED
        if row.observed and row.expires_at is not None and _utc(row.expires_at) <= now:
            return LegacyRetentionState.RETAINED
        return LegacyRetentionState.ACTIVE if row.active else LegacyRetentionState.RETAINED

    def inventory(self) -> InventoryStatus:
        """Return redacted inventory without changing persistence."""
        now = self._clock.now()
        state = self._state()
        rows = self._db.scalars(select(PraxisLegacyConsumer).order_by(PraxisLegacyConsumer.declared_identity, PraxisLegacyConsumer.consumer_path)).all()
        consumers = tuple(
            LegacyConsumerView(
                identity=row.declared_identity,
                version=row.declared_version,
                path=LegacyConsumerPath(row.consumer_path),
                observability_class=LegacyObservabilityClass(row.observability_class),
                first_seen_at=_utc(row.first_seen_at),
                last_seen_at=_utc(row.last_seen_at),
                active=self._effective_retention(row, now) is LegacyRetentionState.ACTIVE,
                observed=row.observed,
                attested=row.attested,
                retention_state=self._effective_retention(row, now),
                expires_at=None if row.expires_at is None else _utc(row.expires_at),
                retain_until=None if row.retain_until is None else _utc(row.retain_until),
            )
            for row in rows
        )
        return InventoryStatus(
            coverage_started_at=None if state is None or state.coverage_started_at is None else _utc(state.coverage_started_at),
            inventory_attested_at=None if state is None or state.inventory_attested_at is None else _utc(state.inventory_attested_at),
            inventory_attested_by=None if state is None else state.inventory_attested_by,
            consumers=consumers,
        )

    def removal_report(self) -> RemovalReadinessReport:
        """Compute the report without deleting or mutating compatibility state."""
        now = self._clock.now()
        state = self._state()
        rows = self._db.scalars(select(PraxisLegacyConsumer)).all()
        blockers: set[RemovalBlockerCode] = set()
        coverage = None if state is None or state.coverage_started_at is None else _utc(state.coverage_started_at)
        attested = None if state is None or state.inventory_attested_at is None else _utc(state.inventory_attested_at)
        if coverage is None:
            blockers.add(RemovalBlockerCode.MISSING_COVERAGE)
        if attested is None:
            blockers.add(RemovalBlockerCode.MISSING_ATTESTATION)
        window_start = max(coverage, attested) if coverage is not None and attested is not None else None
        if window_start is not None and now - window_start < _COVERAGE_WINDOW:
            blockers.add(RemovalBlockerCode.COVERAGE_WINDOW)
        relevant = [row for row in rows if self._effective_retention(row, now) is not LegacyRetentionState.EXPIRED]
        if not rows and blockers:
            blockers.add(RemovalBlockerCode.EMPTY_REGISTRY)
        if coverage is not None and any(row.observed and _utc(row.last_seen_at) < coverage for row in relevant):
            blockers.add(RemovalBlockerCode.PREINSTRUMENTATION)
        if any(self._effective_retention(row, now) is LegacyRetentionState.ACTIVE for row in relevant):
            blockers.add(RemovalBlockerCode.ACTIVE_CONSUMER)
        if any(row.declared_version.strip().lower() in {"unknown", "unversioned"} for row in relevant):
            blockers.add(RemovalBlockerCode.UNKNOWN_VERSION)
        if any(row.observability_class == LegacyObservabilityClass.UNOBSERVABLE.value for row in relevant):
            blockers.add(RemovalBlockerCode.UNOBSERVABLE_CONSUMER)
        if state is not None:
            if state.private_state_present:
                blockers.add(RemovalBlockerCode.PRIVATE_STATE)
            if state.shadow_diff_count:
                blockers.add(RemovalBlockerCode.SHADOW_MISMATCH)
            if not state.task20_e2e_passed:
                blockers.add(RemovalBlockerCode.FAILED_E2E)
            if not state.launcher_fleet_compatible:
                blockers.add(RemovalBlockerCode.INCOMPATIBLE_LAUNCHER)
        ordered = tuple(sorted(blockers, key=lambda item: item.value))
        emit_removal_blockers(ordered)
        return RemovalReadinessReport(
            ready=not ordered,
            blockers=ordered,
            coverage_started_at=coverage,
            inventory_attested_at=attested,
            qualifying_window_started_at=window_start,
            evaluated_at=now,
            consumer_count=len(rows),
        )


__all__ = ("Clock", "LegacyTelemetryError", "PraxisLegacyTelemetryService")
