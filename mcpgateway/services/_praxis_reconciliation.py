# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/_praxis_reconciliation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Typed policy contracts and transaction boundary for Praxis reconciliation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum, unique
from typing import assert_never, Final, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from mcpgateway.services.praxis_config_directives import PraxisActiveReport, PraxisCanaryPassedReport, PraxisFailedReport, PraxisPreparedReport, PraxisReplicaReport
from mcpgateway.services.praxis_bundle_observability import emit_praxis_event, PraxisLifecycleEvent

LKG_MAX_AGE: Final = timedelta(seconds=3600)
REPLICA_STALE_AFTER: Final = timedelta(seconds=180)


class Clock(Protocol):
    """Supply deterministic UTC time to reconciliation decisions."""

    def now(self) -> datetime:
        """Return the current instant."""


@unique
class SourceChange(StrEnum):
    """Closed source-diff classes used by the conservative rollback policy."""

    ADDITIVE = "additive"
    DESCRIPTIVE = "descriptive_metadata"
    REMOVAL = "removal"
    DISABLE = "disable"
    REASSIGNMENT = "reassignment"
    GATEWAY_ENDPOINT = "gateway_url_transport_header"
    PLUGIN_POLICY = "plugin_policy_auth_security_binding_config_mode_priority"
    AUTHORIZATION = "authorization_change"
    SECRET_CLASSIFICATION = "secret_classification_change"
    UNKNOWN = "unknown"


@unique
class RollbackEligibilityReason(StrEnum):
    """Deterministic persisted reason for an eligibility decision."""

    ADDITIVE = SourceChange.ADDITIVE
    DESCRIPTIVE = SourceChange.DESCRIPTIVE
    REMOVAL = SourceChange.REMOVAL
    DISABLE = SourceChange.DISABLE
    REASSIGNMENT = SourceChange.REASSIGNMENT
    GATEWAY_ENDPOINT = SourceChange.GATEWAY_ENDPOINT
    PLUGIN_POLICY = SourceChange.PLUGIN_POLICY
    AUTHORIZATION = SourceChange.AUTHORIZATION
    SECRET_CLASSIFICATION = SourceChange.SECRET_CLASSIFICATION
    UNKNOWN = SourceChange.UNKNOWN


@dataclass(frozen=True, slots=True)
class RollbackEligibility:
    """Conservative predecessor eligibility classification."""

    eligible: bool
    reason: RollbackEligibilityReason


def classify_rollback_eligibility(changes: frozenset[SourceChange]) -> RollbackEligibility:
    """Classify a predecessor, failing closed for mixed or unknown changes."""
    if not changes:
        return RollbackEligibility(False, RollbackEligibilityReason.UNKNOWN)
    if changes <= {SourceChange.ADDITIVE, SourceChange.DESCRIPTIVE}:
        reason = RollbackEligibilityReason.ADDITIVE if SourceChange.ADDITIVE in changes else RollbackEligibilityReason.DESCRIPTIVE
        return RollbackEligibility(True, reason)
    change = min((item for item in changes if item not in {SourceChange.ADDITIVE, SourceChange.DESCRIPTIVE}), key=lambda item: item.value)
    return RollbackEligibility(False, RollbackEligibilityReason(change.value))


@unique
class ReportDisposition(StrEnum):
    """Outcome classes for one submitted report."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    STALE = "stale"


@unique
class RolloutStatus(StrEnum):
    """Only rollout lifecycle values persisted by reconciliation."""

    RENDERED = "rendered"
    DESIRED = "desired"
    PREPARED = "prepared"
    CANARY_PASSED = "canary-passed"
    ACTIVE = "active"
    VERIFIED = "verified"
    FAILED = "failed"
    BLOCKED = "blocked_no_eligible_replicas"


LIVE_ROLLOUT_STATUSES: Final = frozenset(
    {
        RolloutStatus.RENDERED,
        RolloutStatus.DESIRED,
        RolloutStatus.PREPARED,
        RolloutStatus.CANARY_PASSED,
        RolloutStatus.ACTIVE,
    }
)
_REPORT_RANK: Final = {"pending": 0, "prepared": 1, "canary_passed": 2, "active": 3}


def aggregate_rollout_status(member_states: tuple[str, ...], current_status: RolloutStatus) -> RolloutStatus:
    """Map frozen-member progress to an allowed rollout lifecycle state."""
    state = min(member_states, key=_REPORT_RANK.__getitem__)
    if state == "pending":
        return current_status if current_status in {RolloutStatus.RENDERED, RolloutStatus.DESIRED} else RolloutStatus.DESIRED
    return {
        "prepared": RolloutStatus.PREPARED,
        "canary_passed": RolloutStatus.CANARY_PASSED,
        "active": RolloutStatus.ACTIVE,
    }[state]


def expected_report_state(state: str) -> str:
    """Return the only ordered successor accepted for a cohort member."""
    return {"pending": "prepared", "prepared": "canary_passed", "canary_passed": "active"}.get(state, "failed")


def normalized_utc(value: datetime) -> datetime:
    """Normalize SQLite-naive and PostgreSQL-aware timestamps to UTC."""
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def report_values(report: PraxisReplicaReport) -> tuple[str, str | None]:
    """Return persisted state and optional failure category for a typed report."""
    match report:
        case PraxisPreparedReport() | PraxisCanaryPassedReport() | PraxisActiveReport():
            return report.state.value, None
        case PraxisFailedReport(failure_category=category):
            return report.state.value, category.value
        case unreachable:
            assert_never(unreachable)


@dataclass(frozen=True, slots=True)
class ReportOutcome:
    """Accepted cursor state returned after report handling."""

    disposition: ReportDisposition
    rollout_id: str
    last_accepted: int
    next_sequence: int


@dataclass(frozen=True, slots=True)
class ReportCursor:
    """Cursor-sensitive desired response identity."""

    directive_id: str
    last_accepted: int
    next_sequence: int
    response_etag: str


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Persisted rollout state after one reconciliation action."""

    target_id: str
    rollout_id: str
    status: RolloutStatus


class WriteSession:
    """Own one backend-appropriate serialized reconciliation transaction."""

    def __init__(self, sessions: Callable[[], Session]) -> None:
        self._sessions = sessions
        self._db: Session | None = None

    def __enter__(self) -> Session:
        """Open the serialized transaction and return its session."""
        self._db = self._sessions()
        statement = "BEGIN IMMEDIATE" if self._db.get_bind().dialect.name == "sqlite" else "BEGIN"
        self._db.execute(text(statement))
        return self._db

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Commit on success, roll back on error, and close the session."""
        if self._db is None:
            return
        events = tuple(self._db.info.pop("praxis_observability_events", ()))
        if exc_type is None:
            self._db.commit()
        else:
            self._db.rollback()
        self._db.close()
        if exc_type is None:
            for event in events:
                if isinstance(event, PraxisLifecycleEvent):
                    emit_praxis_event(event)
