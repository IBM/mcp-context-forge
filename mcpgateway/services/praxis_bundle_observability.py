"""Redacted best-effort observability for Praxis bundle lifecycles."""

from dataclasses import dataclass
from enum import StrEnum, unique
import logging
from typing import assert_never, Final

from prometheus_client import Counter, Gauge, Histogram

from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.utils.correlation_id import get_or_generate_correlation_id


@unique
class PraxisTransition(StrEnum):
    """Closed lifecycle transitions safe for logs, audits, and metrics."""

    RENDER_REQUESTED = "render_requested"
    RENDER_SUCCEEDED = "render_succeeded"
    RENDER_FAILED = "render_failed"
    PUBLISHED_POINTER = "published_pointer"
    ARTIFACT_PULL = "artifact_pull"
    PREPARED = "prepared"
    CANARY_PASS = "canary_pass"
    CANARY_FAIL = "canary_fail"
    ACTIVATION = "activation"
    ROLLBACK = "rollback"
    STALE_GENERATION = "stale_generation"
    REJECTED_CREDENTIAL = "rejected_credential"
    DEPRECATION_GATE = "deprecation_gate"


@unique
class PraxisOutcome(StrEnum):
    """Bounded operation outcomes used by every Praxis sink."""

    REQUESTED = "requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STALE = "stale"


_KNOWN_SCHEMA: Final = "praxis-bundle/v1"
_KNOWN_RENDERER: Final = "1.0.0"
_KNOWN_STATES: Final = frozenset({"idle", "rendered", "desired", "prepared", "canary-passed", "active", "verified", "failed", "blocked_no_eligible_replicas"})
_SAFE_REASONS: Final = frozenset(
    {
        "artifact_corrupt",
        "config_validation",
        "conflicting_sequence",
        "credential_denied",
        "credential_material",
        "dangling_config_path",
        "dangling_reference",
        "desired_changed",
        "duplicate_plugin",
        "duplicate_route",
        "early_exit",
        "empty_route",
        "expired",
        "incompatible_output_model",
        "ineligible",
        "internal_error",
        "invalid_document",
        "listener",
        "missing_terminal_deny",
        "non_fail_security_plugin",
        "policy_canary",
        "publication_stale",
        "source_refused",
        "spawn",
        "timeout",
        "unknown_filter",
        "unsupported_capability",
    }
)

praxis_render_duration_seconds = Histogram(
    "praxis_render_duration_seconds",
    "Praxis render latency by bounded outcome and compatibility",
    ("outcome", "schema_version", "renderer_version"),
)
praxis_render_failures = Counter(
    "praxis_render_failures_total",
    "Praxis render failures by bounded compatibility",
    ("outcome", "schema_version", "renderer_version"),
)
praxis_desired_to_prepared_seconds = Histogram(
    "praxis_desired_to_prepared_seconds",
    "Praxis desired-to-prepared lag",
    ("state", "schema_version", "renderer_version"),
)
praxis_activation_failures = Counter("praxis_activation_failures_total", "Praxis activation failures", ("outcome",))
praxis_rollback_failures = Counter("praxis_rollback_failures_total", "Praxis rollback failures", ("outcome",))
praxis_stale_replicas = Gauge("praxis_stale_replicas", "Current stale Praxis replica count", ("state",))
praxis_generation_age_seconds = Gauge(
    "praxis_generation_age_seconds",
    "Current desired Praxis generation age",
    ("state", "schema_version", "renderer_version"),
)
praxis_convergence = Gauge("praxis_convergence", "Current Praxis convergence ratio", ("state", "schema_version", "renderer_version"))

_logger = get_structured_logger("praxis_bundle")
_audit = get_audit_trail_service()
_fallback_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PraxisLifecycleEvent:
    """Only lifecycle metadata approved for observability sinks."""

    transition: PraxisTransition
    outcome: PraxisOutcome
    target_id: str | None = None
    replica_id: str | None = None
    generation_id: str | None = None
    schema_version: str | None = None
    renderer_version: str | None = None
    reason: str | None = None
    duration_seconds: float | None = None
    lag_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class PraxisConvergenceSnapshot:
    """Bounded aggregate values exported by status and metrics."""

    state: str
    stale_replicas: int
    generation_age_seconds: float
    convergence_ratio: float
    schema_version: str | None = None
    renderer_version: str | None = None


def _version(value: str | None, known: str) -> str:
    return known if value == known else "unknown"


def _fields(event: PraxisLifecycleEvent) -> dict[str, str]:
    fields = {
        "target": event.target_id,
        "replica": event.replica_id,
        "generation": event.generation_id,
        "schema_version": _version(event.schema_version, _KNOWN_SCHEMA) if event.schema_version is not None else None,
        "renderer_version": _version(event.renderer_version, _KNOWN_RENDERER) if event.renderer_version is not None else None,
        "transition": event.transition.value,
        "outcome": event.outcome.value,
        "reason": None if event.reason is None else event.reason if event.reason in _SAFE_REASONS else "internal_error",
    }
    return {key: value for key, value in fields.items() if value is not None}


def _record_event_metrics(event: PraxisLifecycleEvent) -> None:
    schema = _version(event.schema_version, _KNOWN_SCHEMA)
    renderer = _version(event.renderer_version, _KNOWN_RENDERER)
    match event.transition:
        case PraxisTransition.RENDER_SUCCEEDED | PraxisTransition.RENDER_FAILED:
            if event.duration_seconds is not None:
                praxis_render_duration_seconds.labels(outcome=event.outcome.value, schema_version=schema, renderer_version=renderer).observe(event.duration_seconds)
            if event.transition is PraxisTransition.RENDER_FAILED:
                praxis_render_failures.labels(outcome=event.outcome.value, schema_version=schema, renderer_version=renderer).inc()
        case PraxisTransition.PREPARED:
            if event.lag_seconds is not None:
                praxis_desired_to_prepared_seconds.labels(state="prepared", schema_version=schema, renderer_version=renderer).observe(event.lag_seconds)
        case PraxisTransition.ACTIVATION:
            if event.outcome is PraxisOutcome.FAILED:
                praxis_activation_failures.labels(outcome="failed").inc()
        case PraxisTransition.ROLLBACK:
            if event.outcome is PraxisOutcome.FAILED:
                praxis_rollback_failures.labels(outcome="failed").inc()
        case (
            PraxisTransition.RENDER_REQUESTED
            | PraxisTransition.PUBLISHED_POINTER
            | PraxisTransition.ARTIFACT_PULL
            | PraxisTransition.CANARY_PASS
            | PraxisTransition.CANARY_FAIL
            | PraxisTransition.STALE_GENERATION
            | PraxisTransition.REJECTED_CREDENTIAL
            | PraxisTransition.DEPRECATION_GATE
        ):
            return
        case unreachable:
            assert_never(unreachable)


def _report_sink_failure(_error: Exception) -> None:
    _fallback_logger.warning("Praxis observability sink failed")


def emit_praxis_event(event: PraxisLifecycleEvent) -> None:
    """Emit each sink independently so telemetry can never change primary work."""
    fields = _fields(event)
    try:
        _record_event_metrics(event)
    except Exception as error:
        _report_sink_failure(error)
    try:
        method = _logger.error if event.outcome is PraxisOutcome.FAILED else _logger.info
        method("praxis.lifecycle", custom_fields=fields)
    except Exception as error:
        _report_sink_failure(error)
    try:
        correlation_id = get_or_generate_correlation_id()
        _audit.log_action(
            action=event.transition.value,
            resource_type="praxis_bundle",
            resource_id=event.target_id or "unresolved",
            user_id=event.replica_id or "system",
            success=event.outcome not in {PraxisOutcome.FAILED, PraxisOutcome.REJECTED, PraxisOutcome.STALE},
            error_message=fields.get("reason"),
            context={"correlation_id": correlation_id, **fields},
        )
    except Exception as error:
        _report_sink_failure(error)


def record_praxis_convergence(snapshot: PraxisConvergenceSnapshot) -> None:
    """Publish aggregate convergence without identifier-bearing labels."""
    schema = _version(snapshot.schema_version, _KNOWN_SCHEMA)
    renderer = _version(snapshot.renderer_version, _KNOWN_RENDERER)
    state = snapshot.state if snapshot.state in _KNOWN_STATES else "unknown"
    try:
        praxis_stale_replicas.labels(state=state).set(snapshot.stale_replicas)
        praxis_generation_age_seconds.labels(state=state, schema_version=schema, renderer_version=renderer).set(snapshot.generation_age_seconds)
        praxis_convergence.labels(state=state, schema_version=schema, renderer_version=renderer).set(snapshot.convergence_ratio)
    except Exception as error:
        _report_sink_failure(error)


__all__ = (
    "PraxisConvergenceSnapshot",
    "PraxisLifecycleEvent",
    "PraxisOutcome",
    "PraxisTransition",
    "emit_praxis_event",
    "record_praxis_convergence",
)
