"""Transactional protected-generation classification and terminal-history pruning."""

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.db import PraxisBundleGeneration, PraxisReplicaReport, PraxisRollout, PraxisRolloutReplica, PraxisTarget
from mcpgateway.services._praxis_reconciliation import LIVE_ROLLOUT_STATUSES, RolloutStatus
from mcpgateway.services.praxis_config_directives import DirectiveAction


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def pending_blocked_rollout(rollouts: Sequence[PraxisRollout], target: PraxisTarget) -> PraxisRollout | None:
    """Return the newest blocked issuance that is newer than current desired state."""
    blocked = max(
        (rollout for rollout in rollouts if rollout.status == RolloutStatus.BLOCKED.value and rollout.action != DirectiveAction.STOP.value),
        key=lambda rollout: (rollout.fence, rollout.policy_epoch, _as_utc(rollout.created_at), rollout.rollout_id),
        default=None,
    )
    if blocked is None or target.desired_rollout_id is None:
        return blocked
    desired = next(rollout for rollout in rollouts if rollout.rollout_id == target.desired_rollout_id)
    blocked_order = blocked.fence, blocked.policy_epoch, _as_utc(blocked.created_at), blocked.rollout_id
    desired_order = desired.fence, desired.policy_epoch, _as_utc(desired.created_at), desired.rollout_id
    return blocked if blocked_order > desired_order else None


def rollback_reference_is_eligible(rollouts: Sequence[PraxisRollout], blocked: PraxisRollout, now: datetime) -> bool:
    """Require an unexpired blocked directive and matching verified eligible LKG."""
    if blocked.action != DirectiveAction.ROLLBACK.value:
        return True
    return _as_utc(blocked.eligibility_deadline) > now and any(
        rollout.status == RolloutStatus.VERIFIED.value
        and rollout.generation_id == blocked.generation_id
        and rollout.rollback_eligible
        and _as_utc(rollout.eligibility_deadline) > now
        for rollout in rollouts
    )


def garbage_collect_generations(db: Session, target: PraxisTarget, retained_generations: int, now: datetime) -> int:
    """Retain protected generations plus the newest ordinary generation budget."""
    generations = db.scalars(
        select(PraxisBundleGeneration)
        .where(PraxisBundleGeneration.target_id == target.id)
        .order_by(PraxisBundleGeneration.created_at.desc(), PraxisBundleGeneration.generation_id.desc())
    ).all()
    rollouts = db.scalars(select(PraxisRollout).where(PraxisRollout.target_id == target.id)).all()
    recoverable_blocked = pending_blocked_rollout(rollouts, target)
    if recoverable_blocked is not None and not rollback_reference_is_eligible(rollouts, recoverable_blocked, now):
        recoverable_blocked = None
    protected_rollouts = {
        rollout.rollout_id
        for rollout in rollouts
        if rollout.rollout_id == target.desired_rollout_id
        or RolloutStatus(rollout.status) in LIVE_ROLLOUT_STATUSES
        or (rollout.status == RolloutStatus.VERIFIED.value and rollout.rollback_eligible and _as_utc(rollout.eligibility_deadline) > now)
        or rollout is recoverable_blocked
    }
    protected_generations = {
        rollout.generation_id
        for rollout in rollouts
        if rollout.rollout_id in protected_rollouts and rollout.generation_id is not None
    }
    ordinary = [generation for generation in generations if generation.generation_id not in protected_generations]
    removable = ordinary[retained_generations:]
    if not removable:
        return 0
    generation_ids = {generation.generation_id for generation in removable}
    rollout_ids = [
        rollout.rollout_id
        for rollout in rollouts
        if rollout.generation_id in generation_ids and rollout.rollout_id not in protected_rollouts
    ]
    if rollout_ids:
        db.query(PraxisReplicaReport).filter(PraxisReplicaReport.target_id == target.id, PraxisReplicaReport.rollout_id.in_(rollout_ids)).delete(synchronize_session=False)
        db.query(PraxisRolloutReplica).filter(PraxisRolloutReplica.target_id == target.id, PraxisRolloutReplica.rollout_id.in_(rollout_ids)).delete(synchronize_session=False)
        db.query(PraxisRollout).filter(PraxisRollout.target_id == target.id, PraxisRollout.rollout_id.in_(rollout_ids)).delete(synchronize_session=False)
        db.flush()
    remaining_references = select(PraxisRollout.generation_id).where(PraxisRollout.target_id == target.id, PraxisRollout.generation_id.is_not(None))
    return db.query(PraxisBundleGeneration).filter(PraxisBundleGeneration.id.in_([generation.id for generation in removable]), PraxisBundleGeneration.generation_id.not_in(remaining_references)).delete(synchronize_session=False)
