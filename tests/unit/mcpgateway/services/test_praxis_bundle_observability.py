# -*- coding: utf-8 -*-
"""Redaction and bounded-cardinality contracts for Praxis observability."""

from dataclasses import replace
from datetime import datetime, timezone
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from mcpgateway.db import Base, PraxisBundleGeneration, PraxisReplica, PraxisTarget
from mcpgateway.services.praxis_bundle_observability import (
    PraxisLifecycleEvent,
    PraxisOutcome,
    PraxisTransition,
    emit_praxis_event,
    praxis_activation_failures,
    praxis_convergence,
    praxis_desired_to_prepared_seconds,
    praxis_generation_age_seconds,
    praxis_render_duration_seconds,
    praxis_render_failures,
    praxis_rollback_failures,
    praxis_stale_replicas,
)
from mcpgateway.services.praxis_target_service import PraxisTargetService
from tests.helpers.praxis_reconciler import add_generation, add_rollout

TOKEN_SENTINEL = "Bearer-TASK12-token-sentinel"
HEADER_SENTINEL = "X-Secret-TASK12-header-sentinel"
PLAINTEXT_SENTINEL = "TASK12-plaintext-tool-argument-sentinel"


def _serialized_calls(mock: MagicMock) -> str:
    return json.dumps(
        [
            {"args": call.args, "kwargs": call.kwargs}
            for call in mock.call_args_list
        ],
        default=str,
        sort_keys=True,
    )


def test_event_emits_only_redacted_structured_and_independent_audit_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    logger = MagicMock()
    audit = MagicMock()
    monkeypatch.setattr("mcpgateway.services.praxis_bundle_observability._logger", logger)
    monkeypatch.setattr("mcpgateway.services.praxis_bundle_observability._audit", audit)
    event = PraxisLifecycleEvent(
        transition=PraxisTransition.RENDER_FAILED,
        outcome=PraxisOutcome.FAILED,
        target_id="target-a",
        generation_id="a" * 64,
        schema_version="praxis-bundle/v1",
        renderer_version="1.0.0",
        reason=f"{TOKEN_SENTINEL} {HEADER_SENTINEL} {PLAINTEXT_SENTINEL}",
    )

    # When
    emit_praxis_event(event)

    # Then
    structured = logger.error.call_args.kwargs["custom_fields"]
    assert set(structured) == {"target", "generation", "schema_version", "renderer_version", "transition", "outcome", "reason"}
    assert structured["reason"] == "internal_error"
    audit_kwargs = audit.log_action.call_args.kwargs
    assert "db" not in audit_kwargs
    assert set(audit_kwargs["context"]) == {*structured, "correlation_id"}
    serialized = _serialized_calls(logger) + _serialized_calls(audit)
    assert TOKEN_SENTINEL not in serialized
    assert HEADER_SENTINEL not in serialized
    assert PLAINTEXT_SENTINEL not in serialized


def test_sink_failures_never_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    logger = MagicMock()
    audit = MagicMock()
    logger.info.side_effect = RuntimeError("logger unavailable")
    audit.log_action.side_effect = RuntimeError("audit unavailable")
    monkeypatch.setattr("mcpgateway.services.praxis_bundle_observability._logger", logger)
    monkeypatch.setattr("mcpgateway.services.praxis_bundle_observability._audit", audit)
    event = PraxisLifecycleEvent(transition=PraxisTransition.PUBLISHED_POINTER, outcome=PraxisOutcome.SUCCEEDED, target_id="target-a")

    # When / Then
    emit_praxis_event(event)


def test_metric_labels_are_bounded_and_exclude_event_identifiers() -> None:
    # Given / When
    metric_label_names = {
        praxis_render_duration_seconds._name: set(praxis_render_duration_seconds._labelnames),
        praxis_render_failures._name: set(praxis_render_failures._labelnames),
        praxis_desired_to_prepared_seconds._name: set(praxis_desired_to_prepared_seconds._labelnames),
        praxis_activation_failures._name: set(praxis_activation_failures._labelnames),
        praxis_rollback_failures._name: set(praxis_rollback_failures._labelnames),
        praxis_stale_replicas._name: set(praxis_stale_replicas._labelnames),
        praxis_generation_age_seconds._name: set(praxis_generation_age_seconds._labelnames),
        praxis_convergence._name: set(praxis_convergence._labelnames),
    }

    # Then
    allowed = {"outcome", "state", "schema_version", "renderer_version"}
    assert all(labels <= allowed for labels in metric_label_names.values())
    assert all(labels.isdisjoint({"target", "replica", "generation", "token", "correlation_id", "reason"}) for labels in metric_label_names.values())


def test_metric_versions_and_reasons_are_collapsed_to_closed_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    metric = MagicMock()
    monkeypatch.setattr("mcpgateway.services.praxis_bundle_observability.praxis_render_duration_seconds", metric)
    event = PraxisLifecycleEvent(
        transition=PraxisTransition.RENDER_SUCCEEDED,
        outcome=PraxisOutcome.SUCCEEDED,
        target_id="target-a",
        schema_version=TOKEN_SENTINEL,
        renderer_version=HEADER_SENTINEL,
        duration_seconds=0.25,
    )

    # When
    emit_praxis_event(event)

    # Then
    assert metric.labels.call_args.kwargs == {"outcome": "succeeded", "schema_version": "unknown", "renderer_version": "unknown"}
    metric.labels.return_value.observe.assert_called_once_with(0.25)
    assert TOKEN_SENTINEL not in _serialized_calls(metric)
    assert HEADER_SENTINEL not in _serialized_calls(metric)


def test_all_required_transitions_are_closed_enum_members() -> None:
    # Given / When
    transitions = {transition.value for transition in PraxisTransition}

    # Then
    assert transitions == {
        "render_requested",
        "render_succeeded",
        "render_failed",
        "published_pointer",
        "artifact_pull",
        "prepared",
        "canary_pass",
        "canary_fail",
        "activation",
        "rollback",
        "stale_generation",
        "rejected_credential",
        "deprecation_gate",
    }


def test_dataclass_replacement_cannot_retain_unbounded_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    logger = MagicMock()
    monkeypatch.setattr("mcpgateway.services.praxis_bundle_observability._logger", logger)
    original = PraxisLifecycleEvent(transition=PraxisTransition.CANARY_FAIL, outcome=PraxisOutcome.FAILED, reason="policy_canary")

    # When
    emit_praxis_event(replace(original, reason=PLAINTEXT_SENTINEL))

    # Then
    assert logger.error.call_args.kwargs["custom_fields"]["reason"] == "internal_error"


def test_convergence_status_excludes_artifact_and_credential_surfaces() -> None:
    # Given
    now = datetime.now(timezone.utc)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(PraxisTarget(id="target-a", name="Target A", created_by="admin@example.test"))
        db.add(PraxisReplica(id="replica-a", target_id="target-a", name="Replica A", last_heartbeat_at=now))
        db.flush()
        add_generation(db, "target-a", "a" * 64, now, b"a" * 12)
        generation = next(item for item in db.new if isinstance(item, PraxisBundleGeneration))
        generation.ciphertext = TOKEN_SENTINEL.encode()
        generation.source_ciphertext = HEADER_SENTINEL.encode()
        generation.key_id = PLAINTEXT_SENTINEL
        rollout = add_rollout(db, "target-a", "rollout-a", "a" * 64, "d", now, status="active", replicas=("replica-a",))
        rollout.cohort[0].state = "active"
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = rollout.rollout_id
        db.commit()

        # When
        payload = PraxisTargetService(db, MagicMock()).status("target-a").model_dump_json()

        # Then
        assert '"state":"active"' in payload
        assert '"convergence_ratio":1.0' in payload
        assert all(sentinel not in payload for sentinel in (TOKEN_SENTINEL, HEADER_SENTINEL, PLAINTEXT_SENTINEL))
        assert all(field not in payload for field in ("ciphertext", "token", "url", "headers", "tool_arguments"))
    engine.dispose()
