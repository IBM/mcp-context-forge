# -*- coding: utf-8 -*-
"""Runtime deployment API router."""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.runtime_schemas import (
    RuntimeActionResponse,
    RuntimeApprovalDecisionRequest,
    RuntimeApprovalListResponse,
    RuntimeApprovalRead,
    RuntimeBackendListResponse,
    RuntimeDeployRequest,
    RuntimeDeployResponse,
    RuntimeGuardrailCompatibilityResponse,
    RuntimeGuardrailProfileCreate,
    RuntimeGuardrailProfileRead,
    RuntimeGuardrailProfileUpdate,
    RuntimeListResponse,
    RuntimeLogsResponse,
    RuntimeRead,
)
from mcpgateway.runtimes.base import RuntimeBackendError
from mcpgateway.services.runtime_service import RuntimeService

logger = logging.getLogger(__name__)
runtime_service = RuntimeService()


async def require_runtime_access(user=Depends(get_current_user_with_permissions)) -> None:
    """Enforce runtime API access policy.

    Runtime APIs are platform-admin-only by default for defense-in-depth.
    Operators can set ``RUNTIME_PLATFORM_ADMIN_ONLY=false`` to use the
    existing route-level RBAC permissions instead.

    Args:
        user: Authenticated user context.

    Raises:
        HTTPException: If runtime access is restricted to platform admins and
            the requester is not a platform admin.
    """
    if not settings.runtime_platform_admin_only:
        return

    if user.get("is_admin", False):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Runtime API is restricted to platform administrators",
    )


runtime_router = APIRouter(prefix="/runtimes", tags=["runtime"], dependencies=[Depends(require_runtime_access)])


def _raise_runtime_http_error(exc: RuntimeBackendError) -> None:
    """Map runtime service errors to HTTP responses.

    Args:
        exc: Runtime backend exception raised by the service layer.

    Raises:
        HTTPException: API-friendly error mapped from backend details.
    """
    message = str(exc)
    if "not found" in message.lower():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "disabled" in message.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


@runtime_router.get("/backends", response_model=RuntimeBackendListResponse)
@require_permission("servers.read")
async def list_runtime_backends(_user=Depends(get_current_user_with_permissions)) -> RuntimeBackendListResponse:
    """List enabled runtime backends and capability matrix.

    Returns:
        RuntimeBackendListResponse: Enabled runtime backends with capabilities.
    """
    return RuntimeBackendListResponse(backends=runtime_service.list_backend_capabilities())


@runtime_router.get("/guardrails", response_model=list[RuntimeGuardrailProfileRead])
@require_permission("servers.read")
async def list_guardrails(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> list[RuntimeGuardrailProfileRead]:
    """List built-in and custom runtime guardrail profiles.

    Args:
        db: Database session used for persisted custom profiles.

    Returns:
        list[RuntimeGuardrailProfileRead]: Built-in and custom guardrail profiles.
    """
    return await runtime_service.list_guardrail_profiles(db)


@runtime_router.get("/guardrails/{name}", response_model=RuntimeGuardrailProfileRead)
@require_permission("servers.read")
async def get_guardrail_profile(
    name: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeGuardrailProfileRead:
    """Get a guardrail profile by name.

    Args:
        name: Guardrail profile name.
        db: Database session used for persisted custom profiles.

    Returns:
        RuntimeGuardrailProfileRead: Guardrail profile details.

    Raises:
        RuntimeBackendError: If the guardrail profile does not exist.
    """
    try:
        return await runtime_service.get_guardrail_profile(name, db)
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.get("/guardrails/{name}/compatibility", response_model=RuntimeGuardrailCompatibilityResponse)
@require_permission("servers.read")
async def get_guardrail_profile_compatibility(
    name: str,
    backend: str = Query(...),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeGuardrailCompatibilityResponse:
    """Check profile compatibility with a backend.

    Args:
        name: Guardrail profile name.
        backend: Backend name to evaluate.
        db: Database session used for persisted custom profiles.

    Returns:
        RuntimeGuardrailCompatibilityResponse: Compatibility report and warnings.

    Raises:
        RuntimeBackendError: If profile lookup or compatibility evaluation fails.
    """
    try:
        return await runtime_service.guardrail_compatibility(name, backend, db)
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.post("/guardrails", response_model=RuntimeGuardrailProfileRead, status_code=status.HTTP_201_CREATED)
@require_permission("admin.system_config")
async def create_guardrail_profile(
    payload: RuntimeGuardrailProfileCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> RuntimeGuardrailProfileRead:
    """Create custom guardrail profile.

    Args:
        payload: Guardrail profile configuration.
        db: Database session for profile persistence.
        user: Authenticated user context.

    Returns:
        RuntimeGuardrailProfileRead: Newly created guardrail profile.

    Raises:
        RuntimeBackendError: If profile validation or persistence fails.
    """
    try:
        return await runtime_service.create_guardrail_profile(payload, db, created_by=user.get("email"))
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.put("/guardrails/{name}", response_model=RuntimeGuardrailProfileRead)
@require_permission("admin.system_config")
async def update_guardrail_profile(
    name: str,
    payload: RuntimeGuardrailProfileUpdate,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeGuardrailProfileRead:
    """Update custom guardrail profile.

    Args:
        name: Guardrail profile name.
        payload: Partial profile update payload.
        db: Database session for profile persistence.

    Returns:
        RuntimeGuardrailProfileRead: Updated guardrail profile.

    Raises:
        RuntimeBackendError: If the profile cannot be updated.
    """
    try:
        return await runtime_service.update_guardrail_profile(name, payload, db)
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.delete("/guardrails/{name}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("admin.system_config")
async def delete_guardrail_profile(
    name: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> None:
    """Delete custom guardrail profile.

    Args:
        name: Guardrail profile name.
        db: Database session for profile persistence.

    Raises:
        RuntimeBackendError: If the profile cannot be deleted.
    """
    try:
        await runtime_service.delete_guardrail_profile(name, db)
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.post("/deploy", response_model=RuntimeDeployResponse, status_code=status.HTTP_201_CREATED)
@require_permission("servers.create")
async def deploy_runtime(
    payload: RuntimeDeployRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> RuntimeDeployResponse:
    """Deploy a runtime from explicit source or catalog entry metadata.

    Args:
        payload: Deployment request payload.
        db: Database session used for runtime persistence.
        user: Authenticated user context.

    Returns:
        RuntimeDeployResponse: Deployment result with runtime metadata.

    Raises:
        RuntimeBackendError: If backend deployment cannot be completed.
    """
    try:
        runtime = await runtime_service.deploy(payload, db, requested_by=user.get("email"))
        message = "Deployment submitted"
        if runtime.approval_status == "pending":
            message = "Deployment pending approval"
        elif runtime.status in {"running", "connected"}:
            message = "Deployment started successfully"
        elif runtime.status == "error":
            message = "Deployment failed"
        return RuntimeDeployResponse(runtime=runtime, message=message)
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.get("", response_model=RuntimeListResponse)
@require_permission("servers.read")
async def list_runtimes(
    backend: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, alias="status", include_in_schema=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeListResponse:
    """List runtime deployments.

    Args:
        backend: Optional backend filter.
        status_filter: Optional runtime status filter (`status_filter` query param).
        status: Legacy runtime status filter (`status` query param).
        limit: Maximum number of items to return.
        offset: Pagination offset.
        db: Database session used for query execution.

    Returns:
        RuntimeListResponse: Paginated runtime deployment list.
    """
    effective_status = status_filter if status_filter is not None else status
    runtimes, total = await runtime_service.list_runtimes(db, backend=backend, status=effective_status, limit=limit, offset=offset)
    return RuntimeListResponse(runtimes=runtimes, total=total)


@runtime_router.get("/approvals", response_model=RuntimeApprovalListResponse)
@require_permission("admin.system_config")
async def list_runtime_approvals(
    status_filter: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, alias="status", include_in_schema=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeApprovalListResponse:
    """List runtime approval requests.

    Args:
        status_filter: Optional approval status filter (`status_filter` query param).
        status: Legacy approval status filter (`status` query param).
        limit: Maximum number of approvals to return.
        offset: Pagination offset.
        db: Database session used for query execution.

    Returns:
        RuntimeApprovalListResponse: Paginated runtime approval list.
    """
    effective_status = status_filter if status_filter is not None else status or "pending"
    approvals, total = await runtime_service.list_approvals(db, status=effective_status, limit=limit, offset=offset)
    return RuntimeApprovalListResponse(approvals=approvals, total=total)


@runtime_router.get("/approvals/{approval_id}", response_model=RuntimeApprovalRead)
@require_permission("admin.system_config")
async def get_runtime_approval(
    approval_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeApprovalRead:
    """Get details for a runtime approval request.

    Args:
        approval_id: Runtime approval identifier.
        db: Database session used for lookup.

    Returns:
        RuntimeApprovalRead: Approval metadata and decision state.

    Raises:
        RuntimeBackendError: If the approval cannot be found.
    """
    try:
        return await runtime_service.get_approval(approval_id, db)
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.post("/approvals/{approval_id}/approve", response_model=RuntimeDeployResponse)
@require_permission("admin.system_config")
async def approve_runtime_request(
    approval_id: str,
    payload: RuntimeApprovalDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> RuntimeDeployResponse:
    """Approve a pending runtime deployment request.

    Args:
        approval_id: Runtime approval identifier.
        payload: Approval reason payload.
        db: Database session used for persistence.
        user: Authenticated reviewer context.

    Returns:
        RuntimeDeployResponse: Updated runtime deployment state.

    Raises:
        RuntimeBackendError: If approval cannot be applied.
    """
    try:
        runtime = await runtime_service.approve(approval_id, db, reviewer=user.get("email"), reason=payload.reason)
        return RuntimeDeployResponse(runtime=runtime, message=f"Approved deployment {runtime.id}")
    except RuntimeBackendError as exc:
        if "expired" in str(exc).lower():
            db.commit()
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.post("/approvals/{approval_id}/reject", response_model=RuntimeDeployResponse)
@require_permission("admin.system_config")
async def reject_runtime_request(
    approval_id: str,
    payload: RuntimeApprovalDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_with_permissions),
) -> RuntimeDeployResponse:
    """Reject a pending runtime deployment request.

    Args:
        approval_id: Runtime approval identifier.
        payload: Rejection reason payload.
        db: Database session used for persistence.
        user: Authenticated reviewer context.

    Returns:
        RuntimeDeployResponse: Updated runtime deployment state.

    Raises:
        RuntimeBackendError: If rejection cannot be applied.
    """
    try:
        runtime = await runtime_service.reject(approval_id, db, reviewer=user.get("email"), reason=payload.reason)
        return RuntimeDeployResponse(runtime=runtime, message=f"Rejected deployment {runtime.id}")
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.get("/{runtime_id}", response_model=RuntimeRead)
@require_permission("servers.read")
async def get_runtime(
    runtime_id: str,
    refresh_status: bool = Query(default=False),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeRead:
    """Get runtime details, optionally refreshing backend status.

    Args:
        runtime_id: Runtime deployment identifier.
        refresh_status: Whether to refresh backend status before returning.
        db: Database session used for lookup and updates.

    Returns:
        RuntimeRead: Runtime deployment details.

    Raises:
        RuntimeBackendError: If runtime retrieval or refresh fails.
    """
    try:
        if refresh_status:
            return await runtime_service.refresh_runtime_status(runtime_id, db)
        return await runtime_service.get_runtime(runtime_id, db)
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.post("/{runtime_id}/start", response_model=RuntimeActionResponse)
@require_permission("servers.update")
async def start_runtime(
    runtime_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeActionResponse:
    """Start a runtime deployment.

    Args:
        runtime_id: Runtime deployment identifier.
        db: Database session used for persistence.

    Returns:
        RuntimeActionResponse: Runtime action result.

    Raises:
        RuntimeBackendError: If runtime start fails.
    """
    try:
        runtime = await runtime_service.start_runtime(runtime_id, db)
        return RuntimeActionResponse(runtime_id=runtime.id, status=runtime.status, message=f"Runtime {runtime.id} started")
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.post("/{runtime_id}/stop", response_model=RuntimeActionResponse)
@require_permission("servers.update")
async def stop_runtime(
    runtime_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeActionResponse:
    """Stop a runtime deployment.

    Args:
        runtime_id: Runtime deployment identifier.
        db: Database session used for persistence.

    Returns:
        RuntimeActionResponse: Runtime action result.

    Raises:
        RuntimeBackendError: If runtime stop fails.
    """
    try:
        runtime = await runtime_service.stop_runtime(runtime_id, db)
        return RuntimeActionResponse(runtime_id=runtime.id, status=runtime.status, message=f"Runtime {runtime.id} stopped")
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.delete("/{runtime_id}", response_model=RuntimeActionResponse)
@require_permission("servers.delete")
async def delete_runtime(
    runtime_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeActionResponse:
    """Delete a runtime deployment.

    Args:
        runtime_id: Runtime deployment identifier.
        db: Database session used for persistence.

    Returns:
        RuntimeActionResponse: Runtime action result.

    Raises:
        RuntimeBackendError: If runtime deletion fails.
    """
    try:
        runtime = await runtime_service.delete_runtime(runtime_id, db)
        return RuntimeActionResponse(runtime_id=runtime.id, status=runtime.status, message=f"Runtime {runtime.id} deleted")
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover


@runtime_router.get("/{runtime_id}/logs", response_model=RuntimeLogsResponse)
@require_permission("servers.read")
async def runtime_logs(
    runtime_id: str,
    tail: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user_with_permissions),
) -> RuntimeLogsResponse:
    """Read runtime logs from the backend.

    Args:
        runtime_id: Runtime deployment identifier.
        tail: Number of trailing log lines to fetch.
        db: Database session used for runtime lookup.

    Returns:
        RuntimeLogsResponse: Runtime log payload.

    Raises:
        RuntimeBackendError: If runtime lookup or log retrieval fails.
    """
    try:
        runtime = await runtime_service.get_runtime(runtime_id, db)
        logs = await runtime_service.logs(runtime_id, db, tail=tail)
        return RuntimeLogsResponse(runtime_id=runtime.id, backend=runtime.backend, logs=logs)
    except RuntimeBackendError as exc:
        _raise_runtime_http_error(exc)
        raise  # pragma: no cover
