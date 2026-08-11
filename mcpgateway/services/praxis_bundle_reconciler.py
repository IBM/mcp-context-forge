"""Database-authoritative Praxis rollout reconciliation and retention."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.db import PraxisBundleGeneration, PraxisReplica, PraxisReplicaReport as StoredReport, PraxisRollout, PraxisRolloutReplica, PraxisTarget
from mcpgateway.services._praxis_reconciliation import (
    Clock,
    ReconcileResult,
    ReportCursor,
    ReportDisposition,
    ReportOutcome,
    REPLICA_STALE_AFTER,
    RollbackEligibility,
    RollbackEligibilityReason,
    RolloutStatus,
    LKG_MAX_AGE,
    SourceChange,
    WriteSession,
    aggregate_rollout_status,
    classify_rollback_eligibility,
    expected_report_state,
    normalized_utc,
    report_values,
)
from mcpgateway.services.praxis_config_directives import (
    DirectiveAction,
    PraxisDirectiveIdentity,
    PraxisReplicaReport,
    build_directive,
    compute_response_etag,
)
from mcpgateway.services.praxis_generation_retention import garbage_collect_generations, pending_blocked_rollout, rollback_reference_is_eligible
from mcpgateway.services.praxis_bundle_observability import emit_praxis_event, PraxisLifecycleEvent, PraxisOutcome, PraxisTransition


class PraxisBundleReconciler:
    """Serialize desired issuance, cohort reports, LKG decisions, and GC in SQL."""

    def __init__(self, session_factory: Callable[[], Session], clock: Clock, *, retained_generations: int = 10) -> None:
        """Bind database sessions, deterministic time, and ordinary retention."""
        self._sessions = session_factory
        self._clock = clock
        self._retained_generations = retained_generations

    def reconcile_committed_change(self, target_id: str, rollout_id: str, changes: frozenset[SourceChange]) -> ReconcileResult:
        """Classify the predecessor and make one rendered rollout desired when safe."""
        with WriteSession(self._sessions) as db:
            target = self._target(db, target_id)
            rollout = self._rollout(db, target_id, rollout_id)
            predecessor = self._verified_predecessor(db, target_id, rollout)
            eligibility = classify_rollback_eligibility(changes)
            rollout.rollback_eligible = predecessor is not None and eligibility.eligible
            rollout.eligibility_reason = eligibility.reason.value if predecessor is not None else "no_verified_predecessor"
            if predecessor is not None:
                predecessor.rollback_eligible = eligibility.eligible
                predecessor.eligibility_reason = eligibility.reason.value
            cohort_size = len(rollout.cohort)
            if rollout.action != DirectiveAction.STOP.value and cohort_size == 0:
                rollout.status = RolloutStatus.BLOCKED.value
                if target.desired_rollout_id == rollout.rollout_id:
                    target.desired_rollout_id = predecessor.rollout_id if predecessor is not None else None
            else:
                rollout.status = RolloutStatus.DESIRED.value
                target.desired_rollout_id = rollout.rollout_id
            return ReconcileResult(target_id, rollout_id, RolloutStatus(rollout.status))

    def retry(self, target_id: str, rollout_id: str) -> ReconcileResult:
        """Issue a fresh retry with the current eligible fleet."""
        with WriteSession(self._sessions) as db:
            target = self._target(db, target_id)
            source = self._rollout(db, target_id, rollout_id)
            if source.generation_id is None:
                raise KeyError(rollout_id)
            issued = self._issue(db, target, DirectiveAction.RETRY, source.generation_id)
            return ReconcileResult(target_id, issued.rollout_id, RolloutStatus(issued.status))

    def rollback_current(self, target_id: str) -> ReconcileResult:
        """Issue a fresh rollback only from the current eligible verified predecessor."""
        try:
            with WriteSession(self._sessions) as db:
                target = self._target(db, target_id)
                if target.desired_rollout_id is None:
                    raise KeyError(target_id)
                current = self._rollout(db, target_id, target.desired_rollout_id)
                predecessor = self._verified_predecessor(db, target_id, current)
                if predecessor is None or not predecessor.rollback_eligible or normalized_utc(predecessor.eligibility_deadline) <= self._now():
                    raise KeyError(target_id)
                issued = self._issue(db, target, DirectiveAction.ROLLBACK, predecessor.generation_id)
                issued.rollback_eligible = True
                issued.eligibility_reason = predecessor.eligibility_reason
                result = ReconcileResult(target_id, issued.rollout_id, RolloutStatus(issued.status))
        except KeyError:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.ROLLBACK, PraxisOutcome.FAILED, target_id=target_id, reason="ineligible"))
            raise
        return result

    def accept_report(self, target_id: str, replica_id: str, report: PraxisReplicaReport) -> ReportOutcome:
        """Accept one monotonic report or classify its idempotent/stale outcome."""
        with WriteSession(self._sessions) as db:
            target = self._target(db, target_id)
            member = db.scalar(select(PraxisRolloutReplica).where(PraxisRolloutReplica.target_id == target_id, PraxisRolloutReplica.replica_id == replica_id, PraxisRolloutReplica.directive_id == report.directive_id))
            if member is None or target.desired_rollout_id != member.rollout_id:
                self._defer(db, PraxisLifecycleEvent(PraxisTransition.STALE_GENERATION, PraxisOutcome.STALE, target_id=target_id, replica_id=replica_id, reason="desired_changed"))
                return ReportOutcome(ReportDisposition.STALE, member.rollout_id if member is not None else "", member.last_report_sequence if member is not None else 0, (member.last_report_sequence + 1) if member is not None else 1)
            rollout = self._rollout(db, target_id, member.rollout_id)
            existing = db.scalar(select(StoredReport).where(StoredReport.target_id == target_id, StoredReport.replica_id == replica_id, StoredReport.directive_id == report.directive_id, StoredReport.sequence == report.sequence))
            state, failure = report_values(report)
            if existing is not None:
                if (existing.state, existing.failure_category) == (state, failure):
                    return ReportOutcome(ReportDisposition.DUPLICATE, rollout.rollout_id, member.last_report_sequence, member.last_report_sequence + 1)
                self._fail(db, target, rollout, member, "conflicting_sequence")
                self._defer(db, self._report_event(db, rollout, PraxisLifecycleEvent(PraxisTransition.ACTIVATION, PraxisOutcome.FAILED, replica_id=replica_id, reason="conflicting_sequence")))
                return ReportOutcome(ReportDisposition.CONFLICT, rollout.rollout_id, member.last_report_sequence, member.last_report_sequence + 1)
            expected_state = expected_report_state(member.state)
            if report.sequence != member.last_report_sequence + 1 or state not in {"failed", expected_state}:
                self._fail(db, target, rollout, member, "conflicting_sequence")
                self._defer(db, self._report_event(db, rollout, PraxisLifecycleEvent(PraxisTransition.ACTIVATION, PraxisOutcome.FAILED, replica_id=replica_id, reason="conflicting_sequence")))
                return ReportOutcome(ReportDisposition.CONFLICT, rollout.rollout_id, member.last_report_sequence, member.last_report_sequence + 1)
            db.add(StoredReport(target_id=target_id, rollout_id=rollout.rollout_id, replica_id=replica_id, directive_id=report.directive_id, sequence=report.sequence, state=state, failure_category=failure, received_at=self._now()))
            member.state, member.last_report_sequence, member.state_updated_at = state, report.sequence, self._now()
            replica = db.get(PraxisReplica, replica_id)
            if replica is not None:
                replica.last_heartbeat_at = self._now()
            if state == "failed":
                self._fail(db, target, rollout, member, failure or "timeout")
                transition = PraxisTransition.CANARY_FAIL if failure == "policy_canary" else PraxisTransition.ACTIVATION
                self._defer(db, self._report_event(db, rollout, PraxisLifecycleEvent(transition, PraxisOutcome.FAILED, replica_id=replica_id, reason=failure or "timeout")))
            else:
                rollout.status = self._aggregate_status(rollout.cohort, rollout.status).value
                transition = {"prepared": PraxisTransition.PREPARED, "canary_passed": PraxisTransition.CANARY_PASS, "active": PraxisTransition.ACTIVATION}[state]
                self._defer(db, self._report_event(db, rollout, PraxisLifecycleEvent(transition, PraxisOutcome.SUCCEEDED, replica_id=replica_id)))
            return ReportOutcome(ReportDisposition.ACCEPTED, rollout.rollout_id, member.last_report_sequence, member.last_report_sequence + 1)

    def reconcile_target(self, target_id: str) -> ReconcileResult | None:
        """Advance a converged active rollout and expire stale LKG eligibility."""
        with WriteSession(self._sessions) as db:
            target = self._target(db, target_id)
            expired = db.scalars(select(PraxisRollout).where(PraxisRollout.target_id == target_id, PraxisRollout.status == RolloutStatus.VERIFIED.value, PraxisRollout.rollback_eligible.is_(True), PraxisRollout.eligibility_deadline <= self._now())).all()
            for rollout in expired:
                rollout.rollback_eligible, rollout.eligibility_reason = False, "expired_lkg"
            rollouts = db.scalars(select(PraxisRollout).where(PraxisRollout.target_id == target_id)).all()
            blocked = pending_blocked_rollout(rollouts, target)
            if blocked is not None and not rollback_reference_is_eligible(rollouts, blocked, self._now()):
                stopped = self._issue(db, target, DirectiveAction.STOP, None)
                return ReconcileResult(target_id, stopped.rollout_id, RolloutStatus(stopped.status))
            if blocked is not None and self._eligible_replicas(db, target_id):
                issued = self._issue(db, target, DirectiveAction(blocked.action), blocked.generation_id)
                issued.rollback_eligible = blocked.rollback_eligible
                issued.eligibility_reason = blocked.eligibility_reason
                return ReconcileResult(target_id, issued.rollout_id, RolloutStatus(issued.status))
            if target.desired_rollout_id is None:
                return None
            desired = self._rollout(db, target_id, target.desired_rollout_id)
            if desired.action != DirectiveAction.STOP.value and desired.cohort and all(member.state == "active" for member in desired.cohort):
                desired.status, desired.rollback_eligible, desired.eligibility_reason = RolloutStatus.VERIFIED.value, True, "verified"
            return ReconcileResult(target_id, desired.rollout_id, RolloutStatus(desired.status))

    def affirm_current_directive(self, target_id: str, replica_id: str, directive_id: str) -> datetime | None:
        """Record authenticated desired/304 freshness only for the current frozen member."""
        with WriteSession(self._sessions) as db:
            target = self._target(db, target_id)
            member = db.scalar(select(PraxisRolloutReplica).where(PraxisRolloutReplica.target_id == target_id, PraxisRolloutReplica.replica_id == replica_id, PraxisRolloutReplica.directive_id == directive_id))
            if member is None or target.desired_rollout_id != member.rollout_id:
                return None
            replica = db.get(PraxisReplica, replica_id)
            if replica is None:
                return None
            observed_at = self._now()
            replica.last_heartbeat_at = observed_at
            return observed_at

    def report_cursor(self, target_id: str, replica_id: str) -> ReportCursor:
        """Return the current member's cursor-sensitive response identity."""
        with self._sessions() as db:
            target = self._target(db, target_id)
            member = db.scalar(select(PraxisRolloutReplica).where(PraxisRolloutReplica.target_id == target_id, PraxisRolloutReplica.rollout_id == target.desired_rollout_id, PraxisRolloutReplica.replica_id == replica_id))
            if member is None:
                raise KeyError(replica_id)
            next_sequence = member.last_report_sequence + 1
            return ReportCursor(member.directive_id, member.last_report_sequence, next_sequence, compute_response_etag(member.directive_id, member.last_report_sequence, next_sequence))

    def fallback_scan(self) -> tuple[ReconcileResult, ...]:
        """Run the callable reconciliation path intended for a 60-second lifecycle loop."""
        with self._sessions() as db:
            target_ids = tuple(db.scalars(select(PraxisTarget.id).order_by(PraxisTarget.id)).all())
        results = tuple(result for target_id in target_ids if (result := self.reconcile_target(target_id)) is not None)
        for target_id in target_ids:
            self.garbage_collect(target_id)
        return results

    def garbage_collect(self, target_id: str) -> int:
        """Delete only unreferenced generations beyond the newest retained ordinary set."""
        with WriteSession(self._sessions) as db:
            target = self._target(db, target_id)
            return garbage_collect_generations(db, target, self._retained_generations, self._now())

    def _issue(self, db: Session, target: PraxisTarget, action: DirectiveAction, generation_id: str | None) -> PraxisRollout:
        target.policy_epoch += 1
        target.fence += 1
        rollout_id, deadline = uuid.uuid4().hex, self._now() + LKG_MAX_AGE
        directive = build_directive(PraxisDirectiveIdentity(target_id=target.id, rollout_id=rollout_id, policy_epoch=target.policy_epoch, action=action, generation_id=generation_id, eligibility_deadline=deadline))
        replica_ids = self._eligible_replicas(db, target.id)
        status = RolloutStatus.DESIRED if replica_ids or action is DirectiveAction.STOP else RolloutStatus.BLOCKED
        rollout = PraxisRollout(target_id=target.id, rollout_id=rollout_id, generation_id=generation_id, directive_id=directive.directive_id, policy_epoch=target.policy_epoch, source_epoch=target.source_epoch, fence=target.fence, action=action.value, eligibility_deadline=deadline, status=status.value)
        db.add(rollout)
        db.flush()
        db.add_all(PraxisRolloutReplica(target_id=target.id, rollout_id=rollout_id, replica_id=replica_id, directive_id=directive.directive_id, position=position) for position, replica_id in enumerate(replica_ids))
        if status is RolloutStatus.DESIRED:
            target.desired_rollout_id = rollout_id
        if action is DirectiveAction.ROLLBACK:
            outcome = PraxisOutcome.SUCCEEDED if status is RolloutStatus.DESIRED else PraxisOutcome.FAILED
            reason = None if outcome is PraxisOutcome.SUCCEEDED else "ineligible"
            self._defer(db, self._report_event(db, rollout, PraxisLifecycleEvent(PraxisTransition.ROLLBACK, outcome, reason=reason)))
        db.flush()
        return rollout

    def _report_event(
        self,
        db: Session,
        rollout: PraxisRollout,
        event: PraxisLifecycleEvent,
    ) -> PraxisLifecycleEvent:
        generation = None if rollout.generation_id is None else db.scalar(select(PraxisBundleGeneration).where(PraxisBundleGeneration.target_id == rollout.target_id, PraxisBundleGeneration.generation_id == rollout.generation_id))
        lag = (self._now() - normalized_utc(rollout.created_at)).total_seconds() if event.transition is PraxisTransition.PREPARED else None
        return replace(
            event,
            target_id=rollout.target_id,
            generation_id=rollout.generation_id,
            schema_version=generation.bundle_schema if generation is not None else None,
            renderer_version=generation.renderer_version if generation is not None else None,
            lag_seconds=max(lag, 0.0) if lag is not None else None,
        )

    @staticmethod
    def _defer(db: Session, event: PraxisLifecycleEvent) -> None:
        db.info.setdefault("praxis_observability_events", []).append(event)

    def _fail(self, db: Session, target: PraxisTarget, rollout: PraxisRollout, member: PraxisRolloutReplica, category: str) -> None:
        member.state, rollout.status, rollout.failure_category = "failed", RolloutStatus.FAILED.value, category
        predecessor = self._verified_predecessor(db, target.id, rollout)
        if predecessor is not None and predecessor.rollback_eligible and normalized_utc(predecessor.eligibility_deadline) > self._now():
            rollback = self._issue(db, target, DirectiveAction.ROLLBACK, predecessor.generation_id)
            rollback.rollback_eligible = True
            rollback.eligibility_reason = predecessor.eligibility_reason
            if rollback.status == RolloutStatus.BLOCKED.value:
                self._issue(db, target, DirectiveAction.STOP, None)
            return
        if predecessor is not None:
            predecessor.rollback_eligible = False
            if normalized_utc(predecessor.eligibility_deadline) <= self._now():
                predecessor.eligibility_reason = "expired_lkg"
            elif rollout.eligibility_reason is not None:
                predecessor.eligibility_reason = rollout.eligibility_reason
            else:
                predecessor.eligibility_reason = "candidate_noneligible"
        self._issue(db, target, DirectiveAction.STOP, None)

    def _eligible_replicas(self, db: Session, target_id: str) -> tuple[str, ...]:
        cutoff = self._now() - REPLICA_STALE_AFTER
        return tuple(db.scalars(select(PraxisReplica.id).where(PraxisReplica.target_id == target_id, PraxisReplica.enabled.is_(True), PraxisReplica.revoked_at.is_(None), (PraxisReplica.last_heartbeat_at.is_(None) | (PraxisReplica.last_heartbeat_at >= cutoff))).order_by(PraxisReplica.id)).all())

    @staticmethod
    def _aggregate_status(cohort: list[PraxisRolloutReplica], current_status: str) -> RolloutStatus:
        return aggregate_rollout_status(tuple(member.state for member in cohort), RolloutStatus(current_status))

    @staticmethod
    def _rollout(db: Session, target_id: str, rollout_id: str) -> PraxisRollout:
        rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.target_id == target_id, PraxisRollout.rollout_id == rollout_id))
        if rollout is None:
            raise KeyError(rollout_id)
        return rollout

    @staticmethod
    def _verified_predecessor(db: Session, target_id: str, rollout: PraxisRollout) -> PraxisRollout | None:
        return db.scalar(
            select(PraxisRollout)
            .where(PraxisRollout.target_id == target_id, PraxisRollout.status == RolloutStatus.VERIFIED.value, PraxisRollout.rollout_id != rollout.rollout_id)
            .order_by(PraxisRollout.created_at.desc(), PraxisRollout.rollout_id.desc())
        )

    @staticmethod
    def _target(db: Session, target_id: str) -> PraxisTarget:
        query = select(PraxisTarget).where(PraxisTarget.id == target_id)
        if db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update()
        target = db.scalar(query)
        if target is None:
            raise KeyError(target_id)
        return target

    def _now(self) -> datetime:
        return normalized_utc(self._clock.now())

    now = _now


__all__ = ("Clock", "PraxisBundleReconciler", "ReconcileResult", "ReportCursor", "ReportDisposition", "ReportOutcome", "RollbackEligibility", "RollbackEligibilityReason", "RolloutStatus", "SourceChange", "classify_rollback_eligibility")
