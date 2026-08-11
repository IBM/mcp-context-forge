"""Target-bound desired, artifact, and report operations for Praxis replicas."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from typing import Annotated, Final, assert_never

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from mcpgateway.db import Permissions, PraxisBundleGeneration, PraxisRollout, PraxisRolloutReplica, PraxisTarget, SessionLocal
from mcpgateway.middleware.praxis_endpoint_scoping import PraxisReplicaRequestIdentity, require_praxis_replica
from mcpgateway.services._praxis_reconciliation import ReportDisposition
from mcpgateway.services.praxis_bundle_crypto import PraxisBundleCryptoService
from mcpgateway.services.praxis_bundle_reconciler import LKG_MAX_AGE, PraxisBundleReconciler
from mcpgateway.services.praxis_config_api_models import DesiredResponse, ReportResponse
from mcpgateway.services.praxis_config_directives import DirectiveAction, PraxisDirectiveIdentity, PraxisReplicaReport, build_directive
from mcpgateway.services.praxis_config_runtime import get_praxis_crypto_service, get_praxis_reconciler
from mcpgateway.services.praxis_generation_payload import decrypt_generation, PraxisGenerationPayloadError
from mcpgateway.services.praxis_bundle_observability import emit_praxis_event, PraxisLifecycleEvent, PraxisOutcome, PraxisTransition

DESIRED_CHANGED: Final = "praxis_desired_changed"
router = APIRouter(prefix="/praxis/v1", tags=["Praxis Configuration"])
ArtifactIdentity = Annotated[PraxisReplicaRequestIdentity, Depends(require_praxis_replica(Permissions.PRAXIS_ARTIFACTS_READ))]
ReportIdentity = Annotated[PraxisReplicaRequestIdentity, Depends(require_praxis_replica(Permissions.PRAXIS_REPORTS_WRITE))]


class PraxisDesiredChangedError(Exception):
    """The stable directive changed while a machine request was in flight."""


class PraxisDesiredUnavailableError(Exception):
    """No current desired directive exists for this frozen replica cohort."""


class PraxisArtifactCorruptError(Exception):
    """The authorized encrypted artifact failed authenticated validation."""


class PraxisReportConflictError(Exception):
    """A report replay or sequence conflicts with immutable report history."""


@dataclass(frozen=True, slots=True)
class _CurrentDesired:
    target_id: str
    replica_id: str
    rollout_id: str
    directive_id: str
    generation_id: str | None
    policy_epoch: int
    action: str
    status: str
    eligibility_deadline: datetime
    rollback_eligible: bool
    eligibility_reason: str | None
    last_report_sequence: int
    cohort_replica_ids: tuple[str, ...]


def artifact_response_headers(content_hash: str) -> dict[str, str]:
    """Return noncacheable headers bound to verified plaintext content."""
    return {"Cache-Control": "private, no-store", "ETag": f'"{content_hash}"'}


def report_response_headers(response_etag: str) -> dict[str, str]:
    """Return noncacheable headers bound to the accepted report cursor."""
    return {"Cache-Control": "private, no-store", "ETag": quoted_etag(response_etag)}


def quoted_etag(value: str) -> str:
    """Render one strong HTTP entity tag."""
    return f'"{value}"'


class PraxisMachineApiService:
    """Read machine state through fresh sessions and delegate mutations to Task 9."""

    def __init__(self, sessions: Callable[[], Session], crypto: PraxisBundleCryptoService, reconciler: PraxisBundleReconciler) -> None:
        """Bind fresh read sessions, authenticated crypto, and reconciliation."""
        self._sessions = sessions
        self._crypto = crypto
        self._reconciler = reconciler

    def desired(self, target_id: str, replica_id: str, if_none_match: str | None) -> tuple[DesiredResponse, bool]:
        """Return current desired state and whether its response ETag matched."""
        current = self._current(target_id, replica_id)
        try:
            cursor = self._reconciler.report_cursor(target_id, replica_id)
        except KeyError:
            raise PraxisDesiredChangedError from None
        observed_at = self._reconciler.affirm_current_directive(target_id, replica_id, current.directive_id)
        if observed_at is None:
            raise PraxisDesiredChangedError
        eligible = current.action == DirectiveAction.STOP.value or self._utc(current.eligibility_deadline) > observed_at
        if not eligible:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.STALE_GENERATION, PraxisOutcome.STALE, target_id=target_id, replica_id=replica_id, generation_id=current.generation_id, reason="expired"))
        response = DesiredResponse(
            directive_id=current.directive_id,
            response_etag=cursor.response_etag,
            action=current.action,
            rollout_id=current.rollout_id,
            generation_id=current.generation_id,
            policy_epoch=current.policy_epoch,
            status=current.status,
            eligible=eligible,
            eligibility_reason=current.eligibility_reason,
            eligibility_deadline=current.eligibility_deadline,
            freshness_deadline=observed_at + LKG_MAX_AGE,
            cohort_replica_ids=current.cohort_replica_ids,
            last_report_sequence=cursor.last_accepted,
            next_report_sequence=cursor.next_sequence,
        )
        return response, if_none_match in {cursor.response_etag, quoted_etag(cursor.response_etag)}

    def artifact(self, target_id: str, replica_id: str, directive_id: str | None) -> tuple[bytes, str]:
        """Authorize, fully authenticate, and materialize the current archive."""
        current = self._current(target_id, replica_id)
        if directive_id is None or not hmac.compare_digest(directive_id, current.directive_id) or current.generation_id is None:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.STALE_GENERATION, PraxisOutcome.STALE, target_id=target_id, replica_id=replica_id, generation_id=current.generation_id, reason="desired_changed"))
            raise PraxisDesiredChangedError
        if current.action == DirectiveAction.ROLLBACK.value and (not current.rollback_eligible or self._utc(current.eligibility_deadline) <= self._reconciler.now()):
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.STALE_GENERATION, PraxisOutcome.STALE, target_id=target_id, replica_id=replica_id, generation_id=current.generation_id, reason="expired"))
            raise PraxisDesiredChangedError
        generation = self._generation(current)
        try:
            archive = decrypt_generation(generation, self._crypto).archive
        except PraxisGenerationPayloadError:
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.ARTIFACT_PULL, PraxisOutcome.FAILED, target_id=target_id, replica_id=replica_id, generation_id=current.generation_id, schema_version=generation.bundle_schema, renderer_version=generation.renderer_version, reason="artifact_corrupt"))
            raise PraxisArtifactCorruptError from None
        if not hmac.compare_digest(hashlib.sha256(archive).hexdigest(), generation.content_hash):
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.ARTIFACT_PULL, PraxisOutcome.FAILED, target_id=target_id, replica_id=replica_id, generation_id=current.generation_id, schema_version=generation.bundle_schema, renderer_version=generation.renderer_version, reason="artifact_corrupt"))
            raise PraxisArtifactCorruptError
        after = self._current(target_id, replica_id)
        if (after.rollout_id, after.directive_id, after.generation_id) != (current.rollout_id, current.directive_id, current.generation_id):
            emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.STALE_GENERATION, PraxisOutcome.STALE, target_id=target_id, replica_id=replica_id, generation_id=current.generation_id, schema_version=generation.bundle_schema, renderer_version=generation.renderer_version, reason="desired_changed"))
            raise PraxisDesiredChangedError
        emit_praxis_event(PraxisLifecycleEvent(PraxisTransition.ARTIFACT_PULL, PraxisOutcome.SUCCEEDED, target_id=target_id, replica_id=replica_id, generation_id=current.generation_id, schema_version=generation.bundle_schema, renderer_version=generation.renderer_version))
        return archive, generation.content_hash

    def report(self, target_id: str, replica_id: str, if_match: str | None, report: PraxisReplicaReport) -> ReportResponse:
        """Accept one current monotonic report and return its server cursor."""
        if if_match is None or not hmac.compare_digest(if_match, report.directive_id):
            raise PraxisDesiredChangedError
        outcome = self._reconciler.accept_report(target_id, replica_id, report)
        match outcome.disposition:
            case ReportDisposition.STALE:
                raise PraxisDesiredChangedError
            case ReportDisposition.CONFLICT:
                raise PraxisReportConflictError
            case ReportDisposition.ACCEPTED | ReportDisposition.DUPLICATE:
                cursor = self._reconciler.report_cursor(target_id, replica_id)
                return ReportResponse(
                    disposition=outcome.disposition.value,
                    directive_id=cursor.directive_id,
                    response_etag=cursor.response_etag,
                    last_report_sequence=cursor.last_accepted,
                    next_report_sequence=cursor.next_sequence,
                )
            case unreachable:
                assert_never(unreachable)

    def _current(self, target_id: str, replica_id: str) -> _CurrentDesired:
        with self._sessions() as db:
            target = db.get(PraxisTarget, target_id)
            if target is None or target.desired_rollout_id is None:
                raise PraxisDesiredUnavailableError
            rollout = db.scalar(select(PraxisRollout).where(PraxisRollout.target_id == target_id, PraxisRollout.rollout_id == target.desired_rollout_id))
            member = db.scalar(select(PraxisRolloutReplica).where(PraxisRolloutReplica.target_id == target_id, PraxisRolloutReplica.rollout_id == target.desired_rollout_id, PraxisRolloutReplica.replica_id == replica_id))
            if rollout is None or member is None or member.directive_id != rollout.directive_id:
                raise PraxisDesiredUnavailableError
            identity = PraxisDirectiveIdentity(target_id=target_id, rollout_id=rollout.rollout_id, policy_epoch=rollout.policy_epoch, action=DirectiveAction(rollout.action), generation_id=rollout.generation_id, eligibility_deadline=self._utc(rollout.eligibility_deadline))
            if build_directive(identity).directive_id != rollout.directive_id:
                raise PraxisDesiredUnavailableError
            cohort = tuple(db.scalars(select(PraxisRolloutReplica.replica_id).where(PraxisRolloutReplica.target_id == target_id, PraxisRolloutReplica.rollout_id == rollout.rollout_id).order_by(PraxisRolloutReplica.position)).all())
            return _CurrentDesired(target_id, replica_id, rollout.rollout_id, rollout.directive_id, rollout.generation_id, rollout.policy_epoch, rollout.action, rollout.status, rollout.eligibility_deadline, rollout.rollback_eligible, rollout.eligibility_reason, member.last_report_sequence, cohort)

    def _generation(self, current: _CurrentDesired) -> PraxisBundleGeneration:
        with self._sessions() as db:
            generation = db.scalar(select(PraxisBundleGeneration).where(PraxisBundleGeneration.target_id == current.target_id, PraxisBundleGeneration.generation_id == current.generation_id))
            if generation is None:
                raise PraxisDesiredUnavailableError
            db.expunge(generation)
            return generation

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def get_machine_service(reconciler: Annotated[PraxisBundleReconciler, Depends(get_praxis_reconciler)]) -> PraxisMachineApiService:
    """Build the machine API service with fresh database sessions."""
    return PraxisMachineApiService(SessionLocal, get_praxis_crypto_service(), reconciler)


@router.get("/desired", response_model=DesiredResponse)
async def desired(identity: ArtifactIdentity, if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None, service: PraxisMachineApiService = Depends(get_machine_service)) -> DesiredResponse | Response:
    """Return current desired state for the authenticated replica."""
    try:
        payload, unchanged = service.desired(identity.target_id, identity.replica_id, if_none_match)
        headers = {"ETag": quoted_etag(payload.response_etag), "Cache-Control": "private, no-store"}
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers) if unchanged else Response(content=payload.model_dump_json(), media_type="application/json", headers=headers)
    except (PraxisDesiredChangedError, PraxisDesiredUnavailableError):
        raise HTTPException(status.HTTP_409_CONFLICT, DESIRED_CHANGED) from None


@router.get("/artifact")
async def artifact(identity: ArtifactIdentity, if_match: Annotated[str | None, Header(alias="If-Match")] = None, service: PraxisMachineApiService = Depends(get_machine_service)) -> StreamingResponse:
    """Return one fully authenticated current canonical archive."""
    try:
        content, content_hash = service.artifact(identity.target_id, identity.replica_id, if_match)
        return StreamingResponse(iter((content,)), media_type="application/vnd.contextforge.praxis-bundle", headers=artifact_response_headers(content_hash))
    except (PraxisDesiredChangedError, PraxisDesiredUnavailableError):
        raise HTTPException(status.HTTP_409_CONFLICT, DESIRED_CHANGED) from None
    except PraxisArtifactCorruptError:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "praxis_artifact_corrupt") from None


@router.post("/reports", response_model=ReportResponse)
async def submit_report(report: PraxisReplicaReport, response: Response, identity: ReportIdentity, if_match: Annotated[str | None, Header(alias="If-Match")] = None, service: PraxisMachineApiService = Depends(get_machine_service)) -> ReportResponse:
    """Accept one monotonic report from the authenticated replica."""
    try:
        payload = service.report(identity.target_id, identity.replica_id, if_match, report)
        response.headers.update(report_response_headers(payload.response_etag))
        return payload
    except (PraxisDesiredChangedError, PraxisDesiredUnavailableError):
        raise HTTPException(status.HTTP_409_CONFLICT, DESIRED_CHANGED) from None
    except PraxisReportConflictError:
        raise HTTPException(status.HTTP_409_CONFLICT, "praxis_report_conflict") from None


__all__ = (
    "DESIRED_CHANGED",
    "PraxisArtifactCorruptError",
    "PraxisDesiredChangedError",
    "PraxisDesiredUnavailableError",
    "PraxisMachineApiService",
    "PraxisReportConflictError",
    "artifact_response_headers",
    "get_machine_service",
    "quoted_etag",
    "report_response_headers",
    "router",
)
