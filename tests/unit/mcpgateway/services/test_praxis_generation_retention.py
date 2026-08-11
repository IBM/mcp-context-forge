# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_praxis_generation_retention.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for Praxis protected-generation retention and terminal-history pruning.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from mcpgateway.db import Base, PraxisBundleGeneration, PraxisReplica, PraxisReplicaReport, PraxisRollout, PraxisRolloutReplica, PraxisTarget
from mcpgateway.services.praxis_config_directives import DirectiveAction
from mcpgateway.services.praxis_generation_retention import garbage_collect_generations, pending_blocked_rollout, rollback_reference_is_eligible
from tests.helpers.praxis_reconciler import FakeClock, TerminalHistorySpec, add_generation, add_rollout, add_terminal_history

NOW = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)


def _rollout(
    rollout_id: str,
    *,
    action: str = DirectiveAction.ACTIVATE.value,
    status: str = "rendered",
    fence: int = 0,
    created_at: datetime = NOW,
    generation_id: str | None = None,
    rollback_eligible: bool = False,
    eligibility_deadline: datetime | None = None,
) -> PraxisRollout:
    return PraxisRollout(
        target_id="target-a",
        rollout_id=rollout_id,
        generation_id=generation_id,
        directive_id=rollout_id.ljust(64, "0")[:64],
        policy_epoch=1,
        fence=fence,
        action=action,
        status=status,
        rollback_eligible=rollback_eligible,
        eligibility_deadline=eligibility_deadline if eligibility_deadline is not None else NOW + timedelta(hours=1),
        created_at=created_at,
    )


def test_pending_blocked_rollout_newer_than_desired_is_recoverable() -> None:
    desired = _rollout("desired", status="verified", fence=1, created_at=NOW - timedelta(minutes=5))
    blocked = _rollout("blocked", status="blocked_no_eligible_replicas", fence=2, created_at=NOW)
    target = PraxisTarget(id="target-a", name="Target A", created_by="admin@example.test", desired_rollout_id="desired")

    assert pending_blocked_rollout([desired, blocked], target) is blocked


def test_pending_blocked_rollout_older_than_desired_is_not_recoverable() -> None:
    desired = _rollout("desired", status="verified", fence=2, created_at=NOW)
    blocked = _rollout("blocked", status="blocked_no_eligible_replicas", fence=1, created_at=NOW - timedelta(minutes=5))
    target = PraxisTarget(id="target-a", name="Target A", created_by="admin@example.test", desired_rollout_id="desired")

    assert pending_blocked_rollout([desired, blocked], target) is None


def test_rollback_reference_requires_rollback_action() -> None:
    blocked = _rollout("blocked", action=DirectiveAction.ACTIVATE.value, eligibility_deadline=NOW - timedelta(hours=1))

    assert rollback_reference_is_eligible([], blocked, NOW) is True


def test_rollback_reference_expired_deadline_is_ineligible() -> None:
    blocked = _rollout("blocked", action=DirectiveAction.ROLLBACK.value, eligibility_deadline=NOW - timedelta(seconds=1))

    assert rollback_reference_is_eligible([], blocked, NOW) is False


def test_rollback_reference_requires_matching_verified_eligible_lkg() -> None:
    blocked = _rollout("blocked", action=DirectiveAction.ROLLBACK.value, generation_id="g" * 64)
    unrelated = _rollout("lkg-other", status="verified", generation_id="f" * 64, rollback_eligible=True)
    matching_expired = _rollout("lkg-expired", status="verified", generation_id="g" * 64, rollback_eligible=True, eligibility_deadline=NOW - timedelta(seconds=1))
    matching = _rollout("lkg", status="verified", generation_id="g" * 64, rollback_eligible=True)

    assert rollback_reference_is_eligible([unrelated, matching_expired], blocked, NOW) is False
    assert rollback_reference_is_eligible([unrelated, matching], blocked, NOW) is True


@pytest.fixture
def retention_store(tmp_path: Path) -> Iterator[tuple[sessionmaker[Session], FakeClock]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'retention.db'}", connect_args={"check_same_thread": False, "timeout": 10})
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    clock = FakeClock(NOW)
    with factory() as db:
        db.add(PraxisTarget(id="target-a", name="Target A", created_by="admin@example.test"))
        db.add(PraxisReplica(id="replica-a", target_id="target-a", name="replica-a"))
        db.commit()
    yield factory, clock
    engine.dispose()


def test_garbage_collect_returns_zero_when_everything_is_retained(retention_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = retention_store
    with factory() as db:
        add_terminal_history(db, TerminalHistorySpec(target_id="target-a", replica_id="replica-a", now=clock.now(), count=3))
        db.commit()

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        assert garbage_collect_generations(db, target, retained_generations=3, now=clock.now()) == 0
        db.commit()

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 3
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 3
        assert db.scalar(select(func.count()).select_from(PraxisReplicaReport)) == 3


def test_garbage_collect_prunes_terminal_history_with_references(retention_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = retention_store
    with factory() as db:
        add_terminal_history(db, TerminalHistorySpec(target_id="target-a", replica_id="replica-a", now=clock.now(), count=5))
        db.commit()

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        assert garbage_collect_generations(db, target, retained_generations=2, now=clock.now()) == 3
        db.commit()

    with factory() as db:
        # The two newest ordinary generations survive with their full history;
        # the three oldest are pruned with their reports, cohort rows, and rollouts.
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration)) == 2
        assert db.scalar(select(func.count()).select_from(PraxisRollout)) == 2
        assert db.scalar(select(func.count()).select_from(PraxisRolloutReplica)) == 2
        assert db.scalar(select(func.count()).select_from(PraxisReplicaReport)) == 2


def test_garbage_collect_drops_ineligible_blocked_recovery_reference(retention_store: tuple[sessionmaker[Session], FakeClock]) -> None:
    factory, clock = retention_store
    with factory() as db:
        add_generation(db, "target-a", "9" * 64, clock.now() - timedelta(days=10), b"c" * 12)
        add_rollout(db, "target-a", "blocked-rollback", "9" * 64, "z", clock.now() - timedelta(hours=2), action="rollback", status="blocked_no_eligible_replicas")
        add_terminal_history(db, TerminalHistorySpec(target_id="target-a", replica_id="replica-a", now=clock.now(), count=3))
        db.commit()

    with factory() as db:
        target = db.get(PraxisTarget, "target-a")
        assert target is not None
        # The expired blocked rollback is not a protected recovery reference, so
        # its generation joins the ordinary budget and is pruned with history.
        assert garbage_collect_generations(db, target, retained_generations=2, now=clock.now()) == 2
        db.commit()

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PraxisRollout).where(PraxisRollout.rollout_id == "blocked-rollback")) == 0
        assert db.scalar(select(func.count()).select_from(PraxisBundleGeneration).where(PraxisBundleGeneration.generation_id == "9" * 64)) == 0
