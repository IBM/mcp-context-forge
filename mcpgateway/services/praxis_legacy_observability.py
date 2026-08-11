"""Bounded-cardinality redacted signals for legacy compatibility paths."""

import logging

from prometheus_client import Counter

from mcpgateway.services.praxis_legacy_models import LegacyConsumerPath, RemovalBlockerCode

_logger = logging.getLogger(__name__)
legacy_events = Counter(
    "praxis_legacy_compatibility_events_total",
    "Legacy compatibility events by bounded path and outcome",
    ("path", "outcome"),
)
legacy_removal_blockers = Counter(
    "praxis_legacy_removal_blockers_total",
    "Legacy removal report blockers by stable reason",
    ("reason",),
)


def emit_legacy_event(path: LegacyConsumerPath, outcome: str) -> None:
    """Emit one event without consumer identity, payload, or secret labels."""
    bounded_outcome = outcome if outcome in {"enabled", "heartbeat", "published", "failed", "stopped"} else "unknown"
    legacy_events.labels(path=path.value, outcome=bounded_outcome).inc()
    _logger.warning("Deprecated Praxis compatibility path observed path=%s outcome=%s", path.value, bounded_outcome)


def emit_removal_blockers(blockers: tuple[RemovalBlockerCode, ...]) -> None:
    """Emit stable blocker reasons without inventory contents."""
    for blocker in blockers:
        legacy_removal_blockers.labels(reason=blocker.value).inc()
    _logger.info("Praxis legacy removal readiness evaluated ready=%s blocker_count=%d", not blockers, len(blockers))


__all__ = ("emit_legacy_event", "emit_removal_blockers", "legacy_events", "legacy_removal_blockers")
