"""Strict contracts for legacy consumer telemetry and removal readiness."""

from datetime import datetime
from enum import StrEnum, unique

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@unique
class LegacyConsumerPath(StrEnum):
    """Closed set of compatibility paths covered by the gate."""

    REDIS_PUBLISHER = "redis_publisher"
    CONTROL_PLANE_GRPC = "control_plane_grpc"
    DIRECT_REDIS = "direct_redis"


@unique
class LegacyObservabilityClass(StrEnum):
    """Whether ContextForge can observe authenticated use of a path."""

    SERVER_OBSERVABLE = "server_observable"
    UNOBSERVABLE = "unobservable"


@unique
class LegacyRetentionState(StrEnum):
    """Persisted lifecycle of a telemetry record."""

    ACTIVE = "active"
    RETAINED = "retained"
    EXPIRED = "expired"


@unique
class RemovalBlockerCode(StrEnum):
    """Stable machine-readable reasons that prevent later removal."""

    EMPTY_REGISTRY = "empty_registry"
    PREINSTRUMENTATION = "preinstrumentation"
    MISSING_COVERAGE = "missing_coverage"
    MISSING_ATTESTATION = "missing_attestation"
    COVERAGE_WINDOW = "coverage_window"
    ACTIVE_CONSUMER = "active_consumer"
    UNKNOWN_VERSION = "unknown_version"
    UNOBSERVABLE_CONSUMER = "unobservable_consumer"
    PRIVATE_STATE = "private_state"
    SHADOW_MISMATCH = "shadow_mismatch"
    FAILED_E2E = "failed_e2e"
    INCOMPATIBLE_LAUNCHER = "incompatible_launcher"


class InventoryConsumer(_StrictModel):
    """One platform-admin inventory declaration."""

    identity: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)
    path: LegacyConsumerPath
    active: bool


class InventoryAttestation(_StrictModel):
    """Complete inventory and release-evidence attestation."""

    consumers: tuple[InventoryConsumer, ...] = Field(max_length=4096)
    private_state_present: bool
    shadow_diff_count: int = Field(ge=0)
    task20_e2e_passed: bool
    launcher_fleet_compatible: bool


class LegacyHeartbeat(_StrictModel):
    """Authenticated heartbeat with no caller-controlled identity."""

    version: str = Field(min_length=1, max_length=64)
    path: LegacyConsumerPath


class LegacyConsumerView(_StrictModel):
    """Redacted persisted consumer inventory row."""

    identity: str
    version: str
    path: LegacyConsumerPath
    observability_class: LegacyObservabilityClass
    first_seen_at: datetime
    last_seen_at: datetime
    active: bool
    observed: bool
    attested: bool
    retention_state: LegacyRetentionState
    expires_at: datetime | None
    retain_until: datetime | None


class InventoryStatus(_StrictModel):
    """Current coverage and attestation state."""

    coverage_started_at: datetime | None
    inventory_attested_at: datetime | None
    inventory_attested_by: str | None
    consumers: tuple[LegacyConsumerView, ...]


class AttestationReceipt(_StrictModel):
    """Redacted acknowledgement of one persisted attestation."""

    actor: str
    attested_at: datetime
    consumer_count: int


class HeartbeatReceipt(_StrictModel):
    """Redacted acknowledgement of one authenticated heartbeat."""

    identity: str
    observed_at: datetime
    expires_at: datetime


class RemovalReadinessReport(_StrictModel):
    """Read-only later-release decision with stable blockers."""

    ready: bool
    blockers: tuple[RemovalBlockerCode, ...]
    coverage_started_at: datetime | None
    inventory_attested_at: datetime | None
    qualifying_window_started_at: datetime | None
    evaluated_at: datetime
    consumer_count: int


def observability_for(path: LegacyConsumerPath) -> LegacyObservabilityClass:
    """Classify direct Redis readers as explicitly unobservable."""
    if path is LegacyConsumerPath.DIRECT_REDIS:
        return LegacyObservabilityClass.UNOBSERVABLE
    return LegacyObservabilityClass.SERVER_OBSERVABLE


__all__ = (
    "AttestationReceipt",
    "HeartbeatReceipt",
    "InventoryAttestation",
    "InventoryConsumer",
    "InventoryStatus",
    "LegacyConsumerPath",
    "LegacyConsumerView",
    "LegacyHeartbeat",
    "LegacyObservabilityClass",
    "LegacyRetentionState",
    "RemovalBlockerCode",
    "RemovalReadinessReport",
    "observability_for",
)
