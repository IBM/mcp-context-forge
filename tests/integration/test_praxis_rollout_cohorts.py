# -*- coding: utf-8 -*-
"""Cross-database cohort and cursor integration tests for Praxis reconciliation."""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, PraxisBundleGeneration, PraxisReplica, PraxisReplicaReport, PraxisRollout, PraxisRolloutReplica, PraxisTarget
from mcpgateway.services.praxis_bundle_reconciler import PraxisBundleReconciler, ReportDisposition, RolloutStatus, SourceChange
from mcpgateway.services.praxis_config_directives import PraxisPreparedReport
from tests.helpers.praxis_reconciler import FakeClock, TerminalHistorySpec, add_generation, add_rollout, add_terminal_history


DATABASE_PARAMS = [pytest.param("sqlite", id="sqlite")]
if postgres_url := os.getenv("MCPGATEWAY_TEST_POSTGRES_URL"):
    DATABASE_PARAMS.append(pytest.param(postgres_url, id="postgresql"))


@pytest.fixture(params=DATABASE_PARAMS)
def engine(request: pytest.FixtureRequest) -> Iterator[Engine]:
    path: Path | None = None
    if request.param == "sqlite":
        descriptor, file_name = tempfile.mkstemp(prefix="praxis-cohort-", suffix=".db")
        os.close(descriptor)
        path = Path(file_name)
        database_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10})
        event.listen(database_engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    else:
        database_engine = create_engine(request.param)
    if path is None:
        Base.metadata.drop_all(database_engine)
    Base.metadata.create_all(database_engine)
    yield database_engine
    if path is None:
        Base.metadata.drop_all(database_engine)
    database_engine.dispose()
    if path is not None:
        path.unlink(missing_ok=True)


@pytest.fixture
def cohort_store(engine: Engine) -> tuple[sessionmaker[Session], FakeClock]:
    factory = sessionmaker(engine, expire_on_commit=False)
    clock = FakeClock(datetime(2026, 8, 10, 12, tzinfo=timezone.utc))
    with factory() as db:
        db.add(PraxisTarget(id="target-a", name="Target A", created_by="admin@example.test"))
        db.add(PraxisReplica(id="replica-a", target_id="target-a", name="Replica A"))
        add_generation(db, "target-a", "1" * 64, clock.now() - timedelta(minutes=1), b"a" * 12)
        db.commit()
    return factory, clock


def test_same_generation_new_cohort_freezes_current_fleet(cohort_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = cohort_store
    with factory() as db:
        first = add_rollout(db, "target-a", "first", "1" * 64, "a", clock.now(), replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = first.rollout_id
        db.commit()
    with factory() as db:
        db.add(PraxisReplica(id="replica-b", target_id="target-a", name="Replica B"))
        db.commit()

    retry = PraxisBundleReconciler(factory, clock).retry("target-a", "first")

    with factory() as db:
        old_members = tuple(db.scalars(select(PraxisRolloutReplica.replica_id).where(PraxisRolloutReplica.rollout_id == "first").order_by(PraxisRolloutReplica.position)).all())
        new_members = tuple(db.scalars(select(PraxisRolloutReplica.replica_id).where(PraxisRolloutReplica.rollout_id == retry.rollout_id).order_by(PraxisRolloutReplica.position)).all())
        assert old_members == ("replica-a",)
        assert new_members == ("replica-a", "replica-b")


@pytest.mark.parametrize(
    ("current_status", "member_states", "expected"),
    [
        ("rendered", ("pending", "pending"), "rendered"),
        ("desired", ("pending", "prepared"), "desired"),
        ("desired", ("pending", "canary_passed"), "desired"),
        ("desired", ("pending", "active"), "desired"),
        ("desired", ("prepared", "prepared"), "prepared"),
        ("prepared", ("prepared", "canary_passed"), "prepared"),
        ("prepared", ("prepared", "active"), "prepared"),
        ("prepared", ("canary_passed", "canary_passed"), "canary-passed"),
        ("canary-passed", ("canary_passed", "active"), "canary-passed"),
        ("canary-passed", ("active", "active"), "active"),
    ],
)
def test_cohort_aggregation_maps_only_to_allowed_rollout_states(current_status: str, member_states: tuple[str, ...], expected: str) -> None:
    members = [PraxisRolloutReplica(state=state) for state in member_states]
    assert PraxisBundleReconciler._aggregate_status(members, current_status) == expected
    assert {status.value for status in RolloutStatus} == {"rendered", "desired", "prepared", "canary-passed", "active", "verified", "failed", "blocked_no_eligible_replicas"}


def test_etag_cursor_changes_without_changing_directive(cohort_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = cohort_store
    with factory() as db:
        rollout = add_rollout(db, "target-a", "rollout", "1" * 64, "b", clock.now(), status="desired", replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = rollout.rollout_id
        db.commit()
    reconciler = PraxisBundleReconciler(factory, clock)
    before = reconciler.report_cursor("target-a", "replica-a")

    reconciler.accept_report("target-a", "replica-a", PraxisPreparedReport(directive_id="b" * 64, sequence=1))
    after = reconciler.report_cursor("target-a", "replica-a")

    assert before.directive_id == after.directive_id == "b" * 64
    assert before.response_etag != after.response_etag
    assert (before.last_accepted, before.next_sequence) == (0, 1)
    assert (after.last_accepted, after.next_sequence) == (1, 2)


def test_duplicate_report_is_idempotent(cohort_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = cohort_store
    with factory() as db:
        rollout = add_rollout(db, "target-a", "rollout", "1" * 64, "f", clock.now(), status="desired", replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = rollout.rollout_id
        db.commit()
    reconciler = PraxisBundleReconciler(factory, clock)
    report = PraxisPreparedReport(directive_id="f" * 64, sequence=1)
    reconciler.accept_report("target-a", "replica-a", report)

    duplicate = reconciler.accept_report("target-a", "replica-a", report)

    assert duplicate.disposition is ReportDisposition.DUPLICATE
    assert (duplicate.last_accepted, duplicate.next_sequence) == (1, 2)


def test_stale_report_never_mutates_current_cursor_or_pointer(cohort_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = cohort_store
    with factory() as db:
        old = add_rollout(db, "target-a", "old", "1" * 64, "7", clock.now() - timedelta(minutes=1), status="desired", replicas=("replica-a",))
        current = add_rollout(db, "target-a", "current", "1" * 64, "8", clock.now(), status="desired", replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = current.rollout_id
        db.commit()

    stale = PraxisBundleReconciler(factory, clock).accept_report("target-a", "replica-a", PraxisPreparedReport(directive_id=old.directive_id, sequence=1))

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        old_member = db.scalar(select(PraxisRolloutReplica).where(PraxisRolloutReplica.rollout_id == old.rollout_id))
        current_member = db.scalar(select(PraxisRolloutReplica).where(PraxisRolloutReplica.rollout_id == current.rollout_id))
        assert stale.disposition is ReportDisposition.STALE
        assert target is not None and target.desired_rollout_id == current.rollout_id
        assert old_member is not None and old_member.last_report_sequence == 0 and old_member.state == "pending"
        assert current_member is not None and current_member.last_report_sequence == 0 and current_member.state == "pending"


def test_eligibility_304_refreshes_only_current_replica_heartbeat(cohort_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = cohort_store
    with factory() as db:
        rollout = add_rollout(db, "target-a", "rollout", "1" * 64, "c", clock.now(), status="desired", replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = rollout.rollout_id
        db.commit()
    reconciler = PraxisBundleReconciler(factory, clock)
    before = reconciler.report_cursor("target-a", "replica-a")
    deadline = rollout.eligibility_deadline
    clock.advance(60)

    refreshed = reconciler.affirm_current_directive("target-a", "replica-a", "c" * 64)
    after = reconciler.report_cursor("target-a", "replica-a")

    with factory() as db:
        replica = db.get(PraxisReplica, "replica-a")
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "rollout"))
        assert refreshed
        assert replica is not None and replica.last_heartbeat_at is not None
        assert replica.last_heartbeat_at.replace(tzinfo=timezone.utc) == clock.now()
        assert rollout is not None and rollout.eligibility_deadline.replace(tzinfo=timezone.utc) == deadline
        assert before == after


@pytest.mark.parametrize(
    ("action", "change", "elapsed", "expected_action"),
    [
        ("activate", SourceChange.ADDITIVE, 0, "activate"),
        ("retry", SourceChange.ADDITIVE, 0, "retry"),
        ("rollback", SourceChange.ADDITIVE, 0, "rollback"),
        ("rollback", SourceChange.ADDITIVE, 3600, "stop"),
        ("rollback", SourceChange.REMOVAL, 0, "stop"),
    ],
)
def test_blocked_rollout_reconciliation_issues_only_safe_current_cohort(
    cohort_store: tuple[sessionmaker[Session], FakeClock], action: str, change: SourceChange, elapsed: int, expected_action: str
) -> None:
    factory, clock = cohort_store
    with factory() as db:
        replica = db.get(PraxisReplica, "replica-a")
        assert replica is not None
        replica.enabled = False
        if action == "rollback":
            predecessor = add_rollout(db, "target-a", "verified", "1" * 64, "8", clock.now(), status="verified")
            predecessor.rollback_eligible = True
        blocked = add_rollout(db, "target-a", "blocked", "1" * 64, "9", clock.now(), action=action)
        db.commit()
    reconciler = PraxisBundleReconciler(factory, clock)
    reconciler.reconcile_committed_change("target-a", blocked.rollout_id, frozenset({change}))
    original_deadline = blocked.eligibility_deadline
    with factory() as db:
        replica = db.get(PraxisReplica, "replica-a")
        assert replica is not None
        replica.enabled = True
        db.commit()
    clock.advance(elapsed)

    recovered = reconciler.reconcile_target("target-a")

    with factory() as db:
        original = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "blocked"))
        fresh = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == recovered.rollout_id)) if recovered is not None else None
        target = db.get(PraxisTarget, "target-a")
        assert original is not None and original.status == "blocked_no_eligible_replicas" and original.cohort == []
        assert original.eligibility_deadline.replace(tzinfo=timezone.utc) == original_deadline
        assert fresh is not None and fresh.rollout_id != original.rollout_id and fresh.directive_id != original.directive_id
        assert fresh.action == expected_action
        assert tuple(member.replica_id for member in fresh.cohort) == ("replica-a",)
        assert target is not None and target.desired_rollout_id == fresh.rollout_id


def test_additive_failure_rolls_back(cohort_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = cohort_store
    with factory() as db:
        verified = add_rollout(db, "target-a", "verified", "1" * 64, "d", clock.now() - timedelta(minutes=1), status="verified", replicas=("replica-a",))
        candidate = add_rollout(db, "target-a", "candidate", "1" * 64, "e", clock.now(), replicas=("replica-a",))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = verified.rollout_id
        db.commit()
    reconciler = PraxisBundleReconciler(factory, clock)
    reconciler.reconcile_committed_change("target-a", candidate.rollout_id, frozenset({SourceChange.ADDITIVE}))

    from mcpgateway.services.praxis_config_directives import PraxisFailedReport, ReplicaFailureCategory

    reconciler.accept_report("target-a", "replica-a", PraxisFailedReport(directive_id="e" * 64, sequence=1, failure_category=ReplicaFailureCategory.TIMEOUT))

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        rollback = db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == target.desired_rollout_id)) if target is not None else None
        assert rollback is not None and rollback.action == "rollback" and rollback.generation_id == verified.generation_id


def test_gc_retires_terminal_history_to_ten_ordinary_generations(cohort_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = cohort_store
    with factory() as db:
        lkg = add_rollout(db, "target-a", "lkg", "1" * 64, "a", clock.now(), status="verified")
        lkg.rollback_eligible = True
        add_generation(db, "target-a", "f" * 64, clock.now() - timedelta(days=30), b"z" * 12)
        live = add_rollout(db, "target-a", "live", "f" * 64, "b", clock.now(), status="active", replicas=("replica-a",))
        current = add_rollout(db, "target-a", "current", "1" * 64, "c", clock.now(), status="desired", replicas=("replica-a",))
        current.cohort[0].state = "prepared"
        current.cohort[0].last_report_sequence = 1
        db.add(PraxisReplicaReport(target_id="target-a", rollout_id=current.rollout_id, replica_id="replica-a", directive_id=current.directive_id, sequence=1, state="prepared"))
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        target.desired_rollout_id = current.rollout_id
        ordinary_ids = add_terminal_history(db, TerminalHistorySpec("target-a", "replica-a", clock.now()))
        db.commit()

    removed = PraxisBundleReconciler(factory, clock).garbage_collect("target-a")

    with factory() as db:
        generations = set(db.scalars(select(PraxisBundleGeneration.generation_id).where(PraxisBundleGeneration.target_id == "target-a")).all())
        retained_ordinary = generations.intersection(ordinary_ids)
        assert removed == 5 and len(retained_ordinary) == 10
        assert {"1" * 64, "f" * 64} <= generations
        assert db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == lkg.rollout_id)) is not None
        assert db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == live.rollout_id)) is not None
        assert db.scalar(select(PraxisRolloutReplica).where(PraxisRolloutReplica.rollout_id == current.rollout_id)) is not None
        assert db.scalar(select(PraxisReplicaReport).where(PraxisReplicaReport.rollout_id == current.rollout_id)) is not None
        assert len(db.scalars(select(PraxisRollout).where(PraxisRollout.rollout_id.like("history-%"))).all()) == 10
        assert db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "history-14")) is None
        assert db.scalar(select(PraxisRollout).where(PraxisRollout.rollout_id == "history-13")) is None
