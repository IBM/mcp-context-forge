"""Transactional publication of immutable Praxis bundle generations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import time
import uuid

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from mcpgateway.db import PraxisBundleGeneration, PraxisReplica, PraxisRollout, PraxisRolloutReplica, PraxisTarget, utc_now
from mcpgateway.services.praxis_bundle_crypto import PraxisBundleCryptoService
from mcpgateway.services.praxis_bundle_renderer import render_praxis_bundle
from mcpgateway.services.praxis_bundle_validation import PraxisBundleRenderError
from mcpgateway.services.praxis_bundle_observability import emit_praxis_event, PraxisLifecycleEvent, PraxisOutcome, PraxisTransition
from mcpgateway.services.praxis_config_models import PraxisBundleArtifact, PraxisConfigSourceSnapshot, PraxisSourceError
from mcpgateway.services.praxis_config_directives import DirectiveAction, PraxisDirectiveIdentity, build_directive
from mcpgateway.services.praxis_generation_payload import build_generation, decrypt_generation, PraxisGenerationBuild, PraxisGenerationPayloadError
from mcpgateway.services._praxis_reconciliation import classify_rollback_eligibility, RolloutStatus, SourceChange
from mcpgateway.services.praxis_source_change import classify_source_changes, classify_source_refusal
from mcpgateway.services.praxis_config_source import PraxisConfigSourceService
from mcpgateway.services.praxis_target_epoch import PraxisTargetEpochService
from mcpgateway.services.praxis_e2e_controls import wait_after_revalidation


class PraxisPublicationStaleError(RuntimeError):
    """Publication lost its target fence or source identity."""


@dataclass(frozen=True, slots=True)
class PraxisPublicationCapture:
    """Target state reserved before expensive source rendering."""

    target_id: str
    enabled: bool
    fence: int
    source_epoch: int
    policy_epoch: int
    expected_rollout_id: str | None


@dataclass(frozen=True, slots=True)
class PraxisPublication:
    """Identity of one committed rollout issuance."""

    target_id: str
    generation_id: str | None
    source_fingerprint: str | None
    rollout_id: str
    directive_id: str
    cohort_replica_ids: tuple[str, ...]
    source_changes: frozenset[SourceChange]


@dataclass(frozen=True, slots=True)
class _PublicationCandidate:
    snapshot: PraxisConfigSourceSnapshot
    artifact: PraxisBundleArtifact
    source_changes: frozenset[SourceChange]


def _noop() -> None:
    return None


@dataclass(frozen=True, slots=True)
class PraxisPublicationHooks:
    """Deterministic phase hooks used to coordinate publication workers."""

    after_capture: Callable[[], None] = _noop
    after_render: Callable[[], None] = _noop
    after_revalidation: Callable[[], None] = _noop


class PraxisBundlePublicationService:
    """Render and issue a target generation under database fencing."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        source_service: PraxisConfigSourceService,
        crypto_service: PraxisBundleCryptoService,
        notifier: Callable[[PraxisPublication], None],
    ) -> None:
        """Bind persistence, source, crypto, and post-commit notification seams."""
        self._session_factory = session_factory
        self.source_service = source_service
        self._crypto_service = crypto_service
        self._notifier = notifier

    def publish(self, target_id: str, *, hooks: PraxisPublicationHooks | None = None) -> PraxisPublication:
        """Publish one fresh rollout or raise when the captured state is stale."""
        started_at = time.perf_counter()
        schema_version, renderer_version = "praxis-bundle/v1", "1.0.0"
        emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.RENDER_REQUESTED, PraxisOutcome.REQUESTED, target_id=target_id, schema_version=schema_version, renderer_version=renderer_version))
        active_hooks = hooks or PraxisPublicationHooks()
        try:
            capture = self._capture(target_id)
        except PraxisPublicationStaleError:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.RENDER_FAILED, PraxisOutcome.FAILED, target_id=target_id, schema_version=schema_version, renderer_version=renderer_version, reason="publication_stale", duration_seconds=time.perf_counter() - started_at))
            raise
        active_hooks.after_capture()
        try:
            snapshot = self.source_service.snapshot(target_id)
        except PraxisSourceError as error:
            self._revoke_predecessor(target_id, classify_source_refusal(error.code))
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.RENDER_FAILED, PraxisOutcome.FAILED, target_id=target_id, schema_version=schema_version, renderer_version=renderer_version, reason="source_refused", duration_seconds=time.perf_counter() - started_at))
            raise
        try:
            artifact = render_praxis_bundle(snapshot)
        except PraxisBundleRenderError as error:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.RENDER_FAILED, PraxisOutcome.FAILED, target_id=target_id, schema_version=schema_version, renderer_version=renderer_version, reason=error.code.value, duration_seconds=time.perf_counter() - started_at))
            raise
        schema_version, renderer_version = artifact.manifest.bundle_schema, artifact.manifest.renderer_version
        emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.RENDER_SUCCEEDED, PraxisOutcome.SUCCEEDED, target_id=target_id, generation_id=artifact.generation_id, schema_version=schema_version, renderer_version=renderer_version, duration_seconds=time.perf_counter() - started_at))
        previous = self._previous_snapshot(capture)
        changes = frozenset({SourceChange.UNKNOWN}) if previous is None else classify_source_changes(previous, snapshot)
        active_hooks.after_render()
        revalidated = self.source_service.snapshot(target_id)
        if revalidated.source_fingerprint != snapshot.source_fingerprint:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.STALE_GENERATION, PraxisOutcome.STALE, target_id=target_id, generation_id=artifact.generation_id, schema_version=schema_version, renderer_version=renderer_version, reason="publication_stale"))
            raise PraxisPublicationStaleError(target_id)
        active_hooks.after_revalidation()
        wait_after_revalidation(target_id)
        try:
            publication = self._persist(capture, _PublicationCandidate(snapshot, artifact, changes))
        except PraxisPublicationStaleError:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.STALE_GENERATION, PraxisOutcome.STALE, target_id=target_id, generation_id=artifact.generation_id, schema_version=schema_version, renderer_version=renderer_version, reason="publication_stale"))
            raise
        emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.PUBLISHED_POINTER, PraxisOutcome.SUCCEEDED, target_id=target_id, generation_id=artifact.generation_id, schema_version=schema_version, renderer_version=renderer_version))
        self._notifier(publication)
        return publication

    def disable(self, target_id: str) -> PraxisPublication:
        """Fence a target and atomically make a fresh stop rollout desired."""
        with self._session_factory() as db:
            self._begin_write(db)
            try:
                stop = PraxisTargetEpochService(db).disable_target(target_id)
                db.commit()
            finally:
                if db.in_transaction():
                    db.rollback()
        publication = PraxisPublication(stop.target_id, None, None, stop.rollout_id, stop.directive_id, stop.cohort_replica_ids, frozenset({SourceChange.DISABLE}))
        emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.PUBLISHED_POINTER, PraxisOutcome.SUCCEEDED, target_id=target_id))
        self._notifier(publication)
        return publication

    def _capture(self, target_id: str) -> PraxisPublicationCapture:
        with self._session_factory() as db:
            self._begin_write(db)
            query = select(PraxisTarget).where(PraxisTarget.id == target_id)
            if db.get_bind().dialect.name == "postgresql":
                query = query.with_for_update()
            target = db.scalar(query)
            if target is None or not target.enabled:
                db.rollback()
                raise PraxisPublicationStaleError(target_id)
            target.fence += 1
            capture = PraxisPublicationCapture(target.id, target.enabled, target.fence, target.source_epoch, target.policy_epoch, target.desired_rollout_id)
            db.commit()
            return capture

    def _persist(self, capture: PraxisPublicationCapture, candidate: _PublicationCandidate) -> PraxisPublication:
        artifact = candidate.artifact
        now = utc_now()
        with self._session_factory() as lookup:
            generation_exists = lookup.scalar(select(PraxisBundleGeneration.id).where(PraxisBundleGeneration.target_id == capture.target_id, PraxisBundleGeneration.generation_id == artifact.generation_id)) is not None
        generation_candidate = None if generation_exists else build_generation(
            PraxisGenerationBuild(capture.target_id, capture.source_epoch, capture.policy_epoch, capture.fence, now, candidate.snapshot, artifact), self._crypto_service
        )
        rollout_id = uuid.uuid4().hex
        deadline = now + timedelta(hours=1)
        directive = build_directive(
            PraxisDirectiveIdentity(
                target_id=capture.target_id,
                rollout_id=rollout_id,
                policy_epoch=capture.policy_epoch,
                action=DirectiveAction.ACTIVATE,
                generation_id=artifact.generation_id,
                eligibility_deadline=deadline,
            )
        )
        with self._session_factory() as db:
            db.info["praxis_publication"] = True
            try:
                self._begin_publication(db)
                generation = db.scalar(
                    select(PraxisBundleGeneration).where(
                        PraxisBundleGeneration.target_id == capture.target_id,
                        PraxisBundleGeneration.generation_id == artifact.generation_id,
                    )
                )
                if generation is None:
                    if generation_candidate is None:
                        raise PraxisPublicationStaleError(capture.target_id)
                    generation = generation_candidate
                    db.add(generation)
                    db.flush()
                replica_ids = tuple(
                    db.scalars(
                        select(PraxisReplica.id)
                        .where(PraxisReplica.target_id == capture.target_id, PraxisReplica.enabled.is_(True), PraxisReplica.revoked_at.is_(None))
                        .order_by(PraxisReplica.id)
                    ).all()
                )
                db.add(
                    PraxisRollout(
                        target_id=capture.target_id,
                        rollout_id=rollout_id,
                        generation_id=artifact.generation_id,
                        directive_id=directive.directive_id,
                        policy_epoch=capture.policy_epoch,
                        source_epoch=capture.source_epoch,
                        fence=capture.fence,
                        action=directive.action.value,
                        eligibility_deadline=deadline,
                    )
                )
                db.add_all(
                    PraxisRolloutReplica(
                        target_id=capture.target_id,
                        rollout_id=rollout_id,
                        replica_id=replica_id,
                        directive_id=directive.directive_id,
                        position=position,
                    )
                    for position, replica_id in enumerate(replica_ids)
                )
                db.flush()
                eligibility = classify_rollback_eligibility(candidate.source_changes)
                predecessor = db.scalar(
                    select(PraxisRollout)
                    .where(PraxisRollout.target_id == capture.target_id, PraxisRollout.status == RolloutStatus.VERIFIED.value, PraxisRollout.rollout_id != rollout_id)
                    .order_by(PraxisRollout.created_at.desc(), PraxisRollout.rollout_id.desc())
                )
                if predecessor is not None:
                    predecessor.rollback_eligible = eligibility.eligible
                    predecessor.eligibility_reason = eligibility.reason.value
                expected_pointer = PraxisTarget.desired_rollout_id.is_(None) if capture.expected_rollout_id is None else PraxisTarget.desired_rollout_id == capture.expected_rollout_id
                result = db.connection().execute(
                    update(PraxisTarget)
                    .where(
                        PraxisTarget.id == capture.target_id,
                        PraxisTarget.enabled.is_(capture.enabled),
                        PraxisTarget.fence == capture.fence,
                        PraxisTarget.source_epoch == capture.source_epoch,
                        PraxisTarget.policy_epoch == capture.policy_epoch,
                        expected_pointer,
                    )
                    .values(desired_rollout_id=rollout_id)
                )
                if result.rowcount != 1:
                    raise PraxisPublicationStaleError(capture.target_id)
                db.commit()
            finally:
                if db.in_transaction():
                    db.rollback()
        return PraxisPublication(capture.target_id, artifact.generation_id, artifact.manifest.source_fingerprint, rollout_id, directive.directive_id, replica_ids, candidate.source_changes)

    def _previous_snapshot(self, capture: PraxisPublicationCapture) -> PraxisConfigSourceSnapshot | None:
        if capture.expected_rollout_id is None:
            return None
        with self._session_factory() as db:
            rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.target_id == capture.target_id, PraxisRollout.rollout_id == capture.expected_rollout_id))
            if rollout is None or rollout.generation_id is None:
                return None
            generation = db.scalar(select(PraxisBundleGeneration).where(PraxisBundleGeneration.target_id == capture.target_id, PraxisBundleGeneration.generation_id == rollout.generation_id))
            if generation is None:
                return None
            db.expunge(generation)
        try:
            return decrypt_generation(generation, self._crypto_service).snapshot
        except PraxisGenerationPayloadError:
            return None

    def _revoke_predecessor(self, target_id: str, change: SourceChange) -> None:
        with self._session_factory() as db:
            self._begin_write(db)
            target_query = select(PraxisTarget).where(PraxisTarget.id == target_id)
            if db.get_bind().dialect.name == "postgresql":
                target_query = target_query.with_for_update()
            if db.scalar(target_query) is None:
                db.rollback()
                return
            predecessor = db.scalar(
                select(PraxisRollout).where(PraxisRollout.target_id == target_id, PraxisRollout.status == RolloutStatus.VERIFIED.value).order_by(PraxisRollout.created_at.desc(), PraxisRollout.rollout_id.desc())
            )
            if predecessor is not None:
                predecessor.rollback_eligible = False
                predecessor.eligibility_reason = change.value
            db.commit()

    @staticmethod
    def _begin_write(db: Session) -> None:
        statement = "BEGIN IMMEDIATE" if db.get_bind().dialect.name == "sqlite" else "BEGIN"
        db.execute(text(statement))

    @staticmethod
    def _begin_publication(db: Session) -> None:
        statement = "BEGIN IMMEDIATE" if db.get_bind().dialect.name == "sqlite" else "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ"
        db.execute(text(statement))


__all__ = ("PraxisBundlePublicationService", "PraxisPublication", "PraxisPublicationCapture", "PraxisPublicationHooks", "PraxisPublicationStaleError")
