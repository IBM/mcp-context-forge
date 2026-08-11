"""Privileged controls and target-bound machine APIs for Praxis configuration."""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from mcpgateway.auth_context import get_user_email
from mcpgateway.db import get_db, Permissions, PraxisReplica, utc_now
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.praxis_feature_gates import require_praxis_artifact_delivery
from mcpgateway.services.praxis_bundle_reconciler import PraxisBundleReconciler
from mcpgateway.services.praxis_bundle_service import PraxisBundlePublicationService, PraxisPublicationStaleError
from mcpgateway.services.praxis_config_api_models import (
    AssignmentReplace,
    AssignmentView,
    CredentialCreate,
    CredentialView,
    ReplicaCreate,
    ReplicaView,
    TargetCreate,
    TargetStatus,
    TargetUpdate,
    TargetView,
)
from mcpgateway.services.praxis_config_models import PraxisSourceError
from mcpgateway.services.praxis_config_runtime import get_praxis_publication_service, get_praxis_reconciler, get_praxis_source_service
from mcpgateway.services.praxis_replica_identity import PraxisCredentialConflictError, PraxisCredentialLimitError, PraxisReplicaIdentityService, PraxisReplicaNotAvailableError
from mcpgateway.services.praxis_target_service import PraxisTargetConflictError, PraxisTargetNotFoundError, PraxisTargetService

router = APIRouter(prefix="/praxis", tags=["Praxis Configuration"])


def get_target_service(db: Annotated[Session, Depends(get_db)]) -> PraxisTargetService:
    return PraxisTargetService(db, get_praxis_source_service())


def _actor(user: dict) -> str:
    return get_user_email(user)


def _target_error(error: Exception) -> HTTPException:
    if isinstance(error, PraxisTargetNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "praxis_target_not_found")
    if isinstance(error, PraxisSourceError):
        return HTTPException(status.HTTP_409_CONFLICT, error.code.value)
    return HTTPException(status.HTTP_409_CONFLICT, "praxis_target_conflict")


@router.post("/targets", response_model=TargetView, status_code=status.HTTP_201_CREATED)
@require_permission(Permissions.PRAXIS_MANAGE)
async def create_target(payload: TargetCreate, user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> TargetView:
    try:
        return service.create(payload, _actor(user))
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "praxis_target_conflict") from None


@router.get("/targets", response_model=tuple[TargetView, ...])
@require_permission(Permissions.PRAXIS_MANAGE)
async def list_targets(_user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> tuple[TargetView, ...]:
    return service.list()


@router.get("/targets/{target_id}", response_model=TargetView)
@require_permission(Permissions.PRAXIS_MANAGE)
async def get_target(target_id: str, _user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> TargetView:
    try:
        return service.view(service.get(target_id))
    except PraxisTargetNotFoundError as error:
        raise _target_error(error) from None


@router.patch("/targets/{target_id}", response_model=TargetView)
@require_permission(Permissions.PRAXIS_MANAGE)
async def update_target(target_id: str, payload: TargetUpdate, user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> TargetView:
    try:
        return service.update(target_id, payload, _actor(user))
    except (PraxisTargetNotFoundError, IntegrityError) as error:
        raise _target_error(error) from None


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission(Permissions.PRAXIS_MANAGE)
async def delete_target(target_id: str, _user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> Response:
    try:
        service.delete(target_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except (PraxisTargetNotFoundError, PraxisTargetConflictError) as error:
        raise _target_error(error) from None


@router.put("/targets/{target_id}/assignments", response_model=AssignmentView)
@require_permission(Permissions.PRAXIS_MANAGE)
async def replace_assignments(target_id: str, payload: AssignmentReplace, user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> AssignmentView:
    try:
        return service.replace_assignments(target_id, payload.server_ids, _actor(user), reassign=payload.reassign)
    except (PraxisTargetNotFoundError, PraxisTargetConflictError, PraxisSourceError, IntegrityError) as error:
        raise _target_error(error) from None


@router.post("/targets/{target_id}/replicas", response_model=ReplicaView, status_code=status.HTTP_201_CREATED)
@require_permission(Permissions.PRAXIS_MANAGE)
async def create_replica(target_id: str, payload: ReplicaCreate, _user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> ReplicaView:
    try:
        return service.create_replica(target_id, payload.name)
    except (PraxisTargetNotFoundError, PraxisTargetConflictError, IntegrityError) as error:
        raise _target_error(error) from None


@router.delete("/targets/{target_id}/replicas/{replica_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission(Permissions.PRAXIS_MANAGE)
async def remove_replica(target_id: str, replica_id: str, _user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> Response:
    try:
        service.remove_replica(target_id, replica_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except PraxisTargetNotFoundError as error:
        raise _target_error(error) from None


@router.post("/targets/{target_id}/render", dependencies=[Depends(require_praxis_artifact_delivery)])
@require_permission(Permissions.PRAXIS_MANAGE)
async def render_target(target_id: str, _user: dict = Depends(get_current_user_with_permissions), publisher: PraxisBundlePublicationService = Depends(get_praxis_publication_service), reconciler: PraxisBundleReconciler = Depends(get_praxis_reconciler)) -> dict[str, str | None]:
    try:
        if os.getenv("PRAXIS_E2E_CONTROLS_ENABLED") == "true":
            publication = await run_in_threadpool(publisher.publish, target_id)
        else:
            publication = publisher.publish(target_id)
        result = reconciler.reconcile_committed_change(target_id, publication.rollout_id, publication.source_changes)
        return {"generation_id": publication.generation_id, "rollout_id": publication.rollout_id, "directive_id": publication.directive_id, "status": result.status.value}
    except (PraxisPublicationStaleError, PraxisSourceError) as error:
        detail = error.code.value if isinstance(error, PraxisSourceError) else "praxis_publication_stale"
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from None


@router.get("/targets/{target_id}/status", response_model=TargetStatus)
@require_permission(Permissions.PRAXIS_MANAGE)
async def target_status(target_id: str, _user: dict = Depends(get_current_user_with_permissions), service: PraxisTargetService = Depends(get_target_service)) -> TargetStatus:
    try:
        return service.status(target_id)
    except PraxisTargetNotFoundError as error:
        raise _target_error(error) from None


@router.post("/targets/{target_id}/replicas/{replica_id}/credentials", response_model=CredentialView, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_praxis_artifact_delivery)])
@require_permission(Permissions.PRAXIS_MANAGE)
async def issue_credential(target_id: str, replica_id: str, payload: CredentialCreate, _user: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> CredentialView:
    replica = db.get(PraxisReplica, replica_id)
    if replica is None or replica.target_id != target_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "praxis_replica_not_found")
    try:
        issued = PraxisReplicaIdentityService(db).issue_credential(replica_id, expires_at=payload.expires_at(utc_now()))
        return CredentialView(jti=issued.jti, token=issued.raw_token, target_id=issued.target_id, replica_id=issued.replica_id, credential_epoch=issued.credential_epoch, expires_at=issued.expires_at)
    except (PraxisCredentialConflictError, PraxisCredentialLimitError, PraxisReplicaNotAvailableError):
        raise HTTPException(status.HTTP_409_CONFLICT, "praxis_credential_conflict") from None


@router.delete("/targets/{target_id}/replicas/{replica_id}/credentials/{jti}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission(Permissions.PRAXIS_MANAGE)
async def revoke_credential(target_id: str, replica_id: str, jti: str, _user: dict = Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> Response:
    replica = db.get(PraxisReplica, replica_id)
    if replica is None or replica.target_id != target_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "praxis_replica_not_found")
    if not PraxisReplicaIdentityService(db).revoke_credential(replica_id, jti):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "praxis_credential_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/targets/{target_id}/disable", dependencies=[Depends(require_praxis_artifact_delivery)])
@require_permission(Permissions.PRAXIS_MANAGE)
async def disable_target(target_id: str, _user: dict = Depends(get_current_user_with_permissions), publisher: PraxisBundlePublicationService = Depends(get_praxis_publication_service)) -> dict[str, str]:
    try:
        publication = publisher.disable(target_id)
        return {"rollout_id": publication.rollout_id, "directive_id": publication.directive_id, "action": "stop"}
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "praxis_target_not_found") from None


@router.post("/targets/{target_id}/rollback", dependencies=[Depends(require_praxis_artifact_delivery)])
@require_permission(Permissions.PRAXIS_MANAGE)
async def rollback_target(target_id: str, _user: dict = Depends(get_current_user_with_permissions), reconciler: PraxisBundleReconciler = Depends(get_praxis_reconciler)) -> dict[str, str]:
    try:
        result = reconciler.rollback_current(target_id)
        return {"rollout_id": result.rollout_id, "status": result.status.value}
    except KeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "praxis_rollback_ineligible") from None


@router.post("/targets/{target_id}/rollouts/{rollout_id}/retry", dependencies=[Depends(require_praxis_artifact_delivery)])
@require_permission(Permissions.PRAXIS_MANAGE)
async def retry_rollout(target_id: str, rollout_id: str, _user: dict = Depends(get_current_user_with_permissions), reconciler: PraxisBundleReconciler = Depends(get_praxis_reconciler)) -> dict[str, str]:
    """Issue a fresh retry directive for an existing rendered generation."""
    try:
        result = reconciler.retry(target_id, rollout_id)
        return {"rollout_id": result.rollout_id, "status": result.status.value}
    except KeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "praxis_retry_ineligible") from None


__all__ = ("router",)
