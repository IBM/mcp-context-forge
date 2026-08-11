# -*- coding: utf-8 -*-
"""Reconciliation tests for Praxis rollout convergence and retention."""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, PraxisBundleGeneration, PraxisReplica, PraxisReplicaReport, PraxisRollout, PraxisTarget
from mcpgateway.services.praxis_bundle_reconciler import (
    PraxisBundleReconciler,
    ReportDisposition,
    RollbackEligibilityReason,
    SourceChange,
    classify_rollback_eligibility,
)
from mcpgateway.services.praxis_config_directives import PraxisActiveReport, PraxisCanaryPassedReport, PraxisFailedReport, PraxisPreparedReport, ReplicaFailureCategory
from tests.helpers.praxis_reconciler import FakeClock, add_generation, add_rollout


@pytest.fixture
def reconciler_store(tmp_path: Path) -> Iterator[tuple[sessionmaker[Session], FakeClock]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'reconciler.db'}", connect_args={"check_same_thread": False, "timeout": 10})
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    clock = FakeClock(datetime(2026, 8, 10, 12, tzinfo=timezone.utc))
    with factory() as db:
        db.add(PraxisTarget(id="target-a", name="Target A", created_by="admin@example.test"))
        db.add_all(PraxisReplica(id=replica_id, target_id="target-a", name=replica_id) for replica_id in ("replica-a", "replica-b"))
        add_generation(db, "target-a", "1" * 64, clock.now() - timedelta(minutes=5), b"a" * 12)
        add_generation(db, "target-a", "2" * 64, clock.now(), b"b" * 12)
        db.commit()
    yield factory, clock
    engine.dispose()


def test_each_noneligible_diff_and_unknown_diff_are_conservative() -> None:
    noneligible = set(SourceChange) - {SourceChange.ADDITIVE, SourceChange.DESCRIPTIVE}

    for change in noneligible:
        eligibility = classify_rollback_eligibility(frozenset({change}))
        assert not eligibility.eligible
        assert eligibility.reason.value == change.value

    assert classify_rollback_eligibility(frozenset({SourceChange.ADDITIVE})).eligible
    assert classify_rollback_eligibility(frozenset({SourceChange.DESCRIPTIVE})).eligible
    assert classify_rollback_eligibility(frozenset()).reason is RollbackEligibilityReason.UNKNOWN


def test_zero_cohort_blocks_activation_without_pointer_advance(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        db.query(PraxisReplica).update({PraxisReplica.enabled: False})
        rollout = add_rollout(db, "target-a", "candidate", "2" * 64, "c", clock.now())
        db.commit()

    result = PraxisBundleReconciler(factory, clock).reconcile_committed_change("target-a", rollout.rollout_id, frozenset({SourceChange.ADDITIVE}))

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        blocked = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "candidate"))
        assert result.status == "blocked_no_eligible_replicas"
        assert target is not None and target.desired_rollout_id is None
        assert blocked is not None and blocked.status == "blocked_no_eligible_replicas"


def test_stop_with_empty_cohort_is_desired_and_never_verified(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        db.query(PraxisReplica).update({PraxisReplica.enabled: False})
        stop = add_rollout(db, "target-a", "stop", None, "d", clock.now(), action="stop")
        db.commit()

    reconciler = PraxisBundleReconciler(factory, clock)
    reconciler.reconcile_committed_change("target-a", stop.rollout_id, frozenset({SourceChange.DISABLE}))
    reconciler.reconcile_target("target-a")

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        stored = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "stop"))
        assert target is not None and target.desired_rollout_id == "stop"
        assert stored is not None and stored.status == "desired"


def test_mixed_rollout_advances_only_after_every_member_reports_ordered_states(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        rollout = add_rollout(db, "target-a", "candidate", "2" * 64, "e", clock.now(), replicas=("replica-a", "replica-b"))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = rollout.rollout_id
        db.commit()
    reconciler = PraxisBundleReconciler(factory, clock)

    for replica_id in ("replica-a", "replica-b"):
        reconciler.accept_report("target-a", replica_id, PraxisPreparedReport(directive_id="e" * 64, sequence=1))
    reconciler.accept_report("target-a", "replica-a", PraxisCanaryPassedReport(directive_id="e" * 64, sequence=2))

    with factory() as db:
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "candidate"))
        assert rollout is not None and rollout.status == "prepared"

    reconciler.accept_report("target-a", "replica-b", PraxisCanaryPassedReport(directive_id="e" * 64, sequence=2))
    for replica_id in ("replica-a", "replica-b"):
        reconciler.accept_report("target-a", replica_id, PraxisActiveReport(directive_id="e" * 64, sequence=3))
    reconciler.reconcile_target("target-a")

    with factory() as db:
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "candidate"))
        assert rollout is not None and rollout.status == "verified" and rollout.rollback_eligible


def test_partial_prepared_cohort_keeps_desired_rollout_status(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        rollout = add_rollout(db, "target-a", "partial", "2" * 64, "a", clock.now(), status="desired", replicas=("replica-a", "replica-b"))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = rollout.rollout_id
        db.commit()

    PraxisBundleReconciler(factory, clock).accept_report("target-a", "replica-a", PraxisPreparedReport(directive_id="a" * 64, sequence=1))

    with factory() as db:
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "partial"))
        assert rollout is not None and rollout.status == "desired"


def test_equal_timestamp_verified_predecessor_is_selected_deterministically(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        predecessor = add_rollout(db, "target-a", "a-verified", "1" * 64, "b", clock.now(), status="verified")
        candidate = add_rollout(db, "target-a", "z-candidate", "2" * 64, "c", clock.now(), status="verified", replicas=("replica-a",))
        db.commit()

    PraxisBundleReconciler(factory, clock).reconcile_committed_change("target-a", candidate.rollout_id, frozenset({SourceChange.ADDITIVE}))

    with factory() as db:
        predecessor = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == predecessor.rollout_id))
        candidate = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == candidate.rollout_id))
        assert predecessor is not None and predecessor.rollback_eligible and predecessor.eligibility_reason == "additive"
        assert candidate is not None and candidate.rollback_eligible


def test_zero_cohort_retry_does_not_advance_pointer(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        source = add_rollout(db, "target-a", "source", "2" * 64, "d", clock.now(), status="desired", replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = source.rollout_id
        db.query(PraxisReplica).update({PraxisReplica.enabled: False})
        db.commit()

    result = PraxisBundleReconciler(factory, clock).retry("target-a", source.rollout_id)

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        retry = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == result.rollout_id))
        assert target is not None and target.desired_rollout_id == source.rollout_id
        assert retry is not None and retry.status == "blocked_no_eligible_replicas" and retry.cohort == []


def test_zero_cohort_rollback_falls_back_to_desired_stop(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        predecessor = add_rollout(db, "target-a", "verified", "1" * 64, "7", clock.now() - timedelta(minutes=1), status="verified")
        predecessor.rollback_eligible = True
        candidate = add_rollout(db, "target-a", "candidate", "2" * 64, "8", clock.now(), status="desired", replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = candidate.rollout_id
        db.query(PraxisReplica).update({PraxisReplica.enabled: False})
        db.commit()

    PraxisBundleReconciler(factory, clock).accept_report("target-a", "replica-a", PraxisFailedReport(directive_id="8" * 64, sequence=1, failure_category=ReplicaFailureCategory.TIMEOUT))

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        predecessor = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "verified"))
        issued = db.scalars(select(PraxisRollout).where(PraxisRollout.rollout_id.not_in(("verified", "candidate"))).order_by(PraxisRollout.fence)).all()
        assert len(issued) == 2
        rollback, stop = issued
        assert rollback.action == "rollback" and rollback.status == "blocked_no_eligible_replicas" and rollback.cohort == []
        assert stop.action == "stop" and stop.status == "desired" and stop.cohort == []
        assert rollback.fence < stop.fence
        assert target is not None and target.desired_rollout_id == stop.rollout_id
        assert predecessor is not None and predecessor.rollback_eligible


def test_conflicting_sequence_fails_current_rollout(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        rollout = add_rollout(db, "target-a", "candidate", "2" * 64, "f", clock.now(), replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = rollout.rollout_id
        db.commit()
    reconciler = PraxisBundleReconciler(factory, clock)
    reconciler.accept_report("target-a", "replica-a", PraxisPreparedReport(directive_id="f" * 64, sequence=1))

    outcome = reconciler.accept_report("target-a", "replica-a", PraxisFailedReport(directive_id="f" * 64, sequence=1, failure_category=ReplicaFailureCategory.TIMEOUT))

    with factory() as db:
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "candidate"))
        assert outcome.disposition is ReportDisposition.CONFLICT
        assert rollout is not None and rollout.status == "failed" and rollout.failure_category == "conflicting_sequence"
        assert db.scalar(select(func.count()).select_from(PraxisReplicaReport)) == 1


@pytest.mark.parametrize(("elapsed", "expected_action"), [(0, "rollback"), (3600, "stop")])
def test_cohort_failure_uses_only_unexpired_eligible_predecessor(reconciler_store: tuple[sessionmaker[Session], FakeClock], elapsed: int, expected_action: str) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        predecessor = add_rollout(db, "target-a", "verified", "1" * 64, "1", clock.now(), status="verified", replicas=("replica-a",))
        predecessor.rollback_eligible = True
        predecessor.eligibility_reason = "additive"
        candidate = add_rollout(db, "target-a", "candidate", "2" * 64, "2", clock.now(), status="desired", replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = candidate.rollout_id
        db.commit()
    clock.advance(elapsed)

    PraxisBundleReconciler(factory, clock).accept_report(
        "target-a", "replica-a", PraxisFailedReport(directive_id="2" * 64, sequence=1, failure_category=ReplicaFailureCategory.POLICY_CANARY)
    )

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        fallback = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == target.desired_rollout_id)) if target is not None else None
        assert fallback is not None and fallback.action == expected_action
        assert fallback.generation_id == ("1" * 64 if expected_action == "rollback" else None)
        assert fallback.rollout_id not in {"verified", "candidate"}


def test_failed_noneligible_stops_and_revokes_predecessor_lkg(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        predecessor = add_rollout(db, "target-a", "verified", "1" * 64, "3", clock.now() - timedelta(minutes=2), status="verified", replicas=("replica-a",))
        predecessor.rollback_eligible = False
        predecessor.eligibility_reason = "removal"
        candidate = add_rollout(db, "target-a", "candidate", "2" * 64, "4", clock.now(), status="desired", replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = candidate.rollout_id
        db.commit()

    PraxisBundleReconciler(factory, clock).accept_report(
        "target-a", "replica-a", PraxisFailedReport(directive_id="4" * 64, sequence=1, failure_category=ReplicaFailureCategory.TIMEOUT)
    )

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        predecessor = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "verified"))
        stop = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == target.desired_rollout_id)) if target is not None else None
        assert predecessor is not None and not predecessor.rollback_eligible
        assert stop is not None and stop.action == "stop" and stop.generation_id is None


def test_expired_affirmation_excludes_stale_replica_and_lkg(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        replica = db.get(PraxisReplica, "replica-a")
        assert replica is not None
        replica.last_heartbeat_at = clock.now()
        verified = add_rollout(db, "target-a", "verified", "1" * 64, "5", clock.now(), status="verified", replicas=("replica-a",))
        verified.rollback_eligible = True
        verified.eligibility_deadline = clock.now() + timedelta(hours=1)
        db.commit()
    clock.advance(3600)

    PraxisBundleReconciler(factory, clock).reconcile_target("target-a")

    with factory() as db:
        replica = db.get(PraxisReplica, "replica-a")
        verified = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "verified"))
        assert replica is not None and replica.last_heartbeat_at is not None
        assert verified is not None and not verified.rollback_eligible and verified.eligibility_reason == "expired_lkg"


def test_gc_race_keeps_referenced_and_ten_newest_ordinary_generations(reconciler_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = reconciler_store
    with factory() as db:
        for index in range(3, 16):
            add_generation(db, "target-a", f"{index:064x}", clock.now() - timedelta(days=index), index.to_bytes(12, "big"))
        protected = add_rollout(db, "target-a", "protected", f"{15:064x}", "6", clock.now(), status="verified")
        protected.rollback_eligible = True
        db.commit()

    removed = PraxisBundleReconciler(factory, clock, retained_generations=10).garbage_collect("target-a")

    with factory() as db:
        remaining = set(db.scalars(select(PraxisBundleGeneration.generation_id).where(PraxisBundleGeneration.target_id == "target-a")).all())
        assert removed == 4
        assert f"{15:064x}" in remaining
        assert len(remaining) == 11
