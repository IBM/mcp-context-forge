# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/runtime_admin_router.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Runtime-mode admin router.

Exposes ``GET`` / ``PATCH /admin/runtime/mcp-mode`` and
``GET`` / ``PATCH /admin/runtime/a2a-mode`` for flipping the public ``/mcp``
ingress and the registered-A2A invocation path between ``shadow`` (Python) and
``edge`` (Rust) at runtime. Boot env vars (``RUST_MCP_MODE`` /
``RUST_A2A_MODE``) still pick the initial mode; overrides are in-memory only.

Each endpoint requires the ``admin.system_config`` permission (the same
permission used by sibling admin routers such as ``llm_admin_router`` and
``observability``). Successful flips emit a ``runtime_config`` audit event via
``SecurityLogger.log_data_access`` and, when Redis is available, propagate to
all pods via the ``RuntimeStateCoordinator``.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# First-Party
from mcpgateway import version as version_module
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db, require_permission
from mcpgateway.runtime_state import (
    get_runtime_state,
    get_runtime_state_coordinator,
    MoveCompatibility,
    OverrideMode,
    PublishStatus,
    RuntimeKind,
    RuntimeStateError,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.security_logger import get_security_logger

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

runtime_admin_router = APIRouter()

# Headers commonly added by reverse proxies. When any are present we know the
# gateway is fronted by an L7 proxy that won't follow runtime flips by itself
# (see issue #4278), and we emit a one-line WARN so operators don't expect the
# override to change public traffic on that hop.
_REVERSE_PROXY_HEADER_NAMES: frozenset[str] = frozenset({"x-forwarded-for", "forwarded", "x-forwarded-host", "x-forwarded-proto"})


def _move_compat_to_409_detail(runtime: RuntimeKind, mode: OverrideMode, boot_mode: str, compat: MoveCompatibility) -> str:
    """Translate a ``MoveCompatibility`` rejection into an operator-actionable 409 detail.

    Args:
        runtime: Runtime kind being changed.
        mode: Requested target mode.
        boot_mode: Boot-time mode label, included for operator context.
        compat: The ``MoveCompatibility`` rejection reason.

    Returns:
        Detail string naming the exact env var or flag to flip, suitable for
        an HTTPException 409 response body.
    """
    runtime_label = runtime.value.upper()
    if compat == MoveCompatibility.NO_DISPATCHER:
        # Note: boot='full' is intentionally NOT recommended here — it returns
        # BOOT_FULL_STRANDS for the same reason (no dispatcher mounted). Only
        # 'shadow' and 'edge' boot deployments mount the dispatcher that
        # observes overrides.
        return (
            f"{runtime_label} runtime cannot accept overrides when boot_mode={boot_mode!r}. "
            "The Rust sidecar is not enabled for this runtime, so there is no mechanism to honor an override. "
            f"Boot with RUST_{runtime.value.upper()}_MODE='shadow' or 'edge' to enable overrides."
        )
    if compat == MoveCompatibility.BOOT_FULL_STRANDS:
        return (
            f"{runtime_label} runtime cannot accept overrides when boot_mode={boot_mode!r}. "
            "Full-boot mounts a plain Rust proxy with no dispatcher, so an override could not be honored. "
            "Boot with RUST_MCP_MODE='edge' to enable overrides without giving up the Rust ingress."
        )
    if compat == MoveCompatibility.EDGE_NEEDS_SAFETY_FLAG:
        flag = "experimental_rust_mcp_session_auth_reuse_enabled" if runtime == RuntimeKind.MCP else "experimental_rust_a2a_runtime_delegate_enabled"
        return (
            f"{runtime_label} runtime cannot be flipped to 'edge' when boot_mode={boot_mode!r}. "
            f"The edge override requires the {flag} safety flag, which only boot_mode='edge' deployments set. "
            f"Boot with RUST_{runtime.value.upper()}_MODE='edge' to enable edge overrides. "
            "(mode='shadow' is always accepted as an escape hatch to clear a stale override.)"
        )
    # OK shouldn't reach here; defensive default for any future MoveCompatibility variant.
    return f"{runtime_label} runtime cannot accept this override on boot_mode={boot_mode!r} (reason={compat.value})."  # pragma: no cover


class RuntimeModeUpdate(BaseModel):
    """Request body for ``PATCH /admin/runtime/{runtime}-mode``."""

    mode: OverrideMode = Field(description="Target override mode. Only shadow and edge are supported at runtime.")


@dataclass(frozen=True)
class ApplyModeResult:
    """Outcome of an admin-initiated mode change.

    Returned by ``_apply_mode_change`` and consumed by the PATCH handlers to
    populate ``publish_status`` and ``audit_persisted`` on the response.
    """

    publish_status: PublishStatus
    audit_persisted: bool


def _build_state_payload(runtime: RuntimeKind, *, boot_mode: str, mounted: Optional[str] = None, invoke_mode: Optional[str] = None) -> Dict[str, Any]:
    """Build the response payload describing the current override state for ``runtime``.

    Args:
        runtime: Runtime kind (``RuntimeKind.MCP`` or ``RuntimeKind.A2A``).
        boot_mode: Boot-time mode label derived from settings.
        mounted: For MCP, the active transport mount label (``"rust"`` or ``"python"``).
        invoke_mode: For A2A, the active invocation runtime label (``"rust"`` or ``"python"``).

    Returns:
        Response body for the GET / PATCH endpoints.
    """
    state = get_runtime_state()
    override = state.override_mode(runtime)
    last_change = state.last_change(runtime)
    payload: Dict[str, Any] = {
        "runtime": runtime.value,
        "boot_mode": boot_mode,
        "effective_mode": (override or boot_mode),
        "override_active": override is not None,
        "override_version": state.version(runtime),
        "cluster_propagation": state.cluster_propagation.value,
        "boot_reconcile_status": state.boot_reconcile_status(runtime).value,
        "pod_id": state.pod_id,
        "supported_override_modes": sorted(m.value for m in OverrideMode),
    }
    if mounted is not None:
        payload["mounted"] = mounted
    if invoke_mode is not None:
        payload["invoke_mode"] = invoke_mode
    if last_change is not None:
        payload["last_change"] = {
            "version": last_change.version,
            "mode": last_change.mode.value,
            "initiator_user": last_change.initiator_user,
            "initiator_pod": last_change.initiator_pod,
            "timestamp": last_change.timestamp,
        }
    return payload


async def _apply_mode_change(
    *,
    runtime: RuntimeKind,
    new_mode: OverrideMode,
    user: Dict[str, Any],
    db: Session,
    boot_mode: str,
    resource_label: str,
    request: Optional[Any] = None,
) -> ApplyModeResult:
    """Validate and apply a runtime-mode override, emit audit event, and publish.

    Args:
        runtime: Runtime kind being changed.
        new_mode: Requested override mode (already validated by Pydantic).
        user: Authenticated user context from ``get_current_user_with_permissions``.
        db: Request-scoped DB session for the audit write.
        boot_mode: Boot-time mode label, used for the 409 check and audit context.
        resource_label: Audit ``resource_id`` (e.g. ``"mcp_mode"``).
        request: Optional FastAPI Request used for reverse-proxy detection.

    Returns:
        An ``ApplyModeResult`` with ``publish_status`` (``PublishStatus``) and
        ``audit_persisted`` (bool).

    Raises:
        HTTPException: 409 when boot mode does not support flips, 503 when a
            Redis-backed version cannot be allocated (would risk a silent
            collision with a concurrent PATCH on a peer pod).
    """
    # Single source of truth for "can this deployment honor the override?":
    # the same helper the coordinator uses for hint reconciliation. Returning
    # the structured ``MoveCompatibility`` reason lets us produce a 409 detail
    # that names the exact env var the operator needs to flip.
    compat = version_module.deployment_allows_override_mode(runtime, new_mode)
    if compat != MoveCompatibility.OK:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_move_compat_to_409_detail(runtime, new_mode, boot_mode, compat),
        )

    if request is not None:
        _warn_if_behind_reverse_proxy(request, runtime=runtime)

    state = get_runtime_state()
    coordinator = get_runtime_state_coordinator()
    previous_override = state.override_mode(runtime)

    try:
        next_version = await coordinator.next_version(runtime, state.version(runtime))
    except RuntimeStateError as exc:
        # Refusing to allocate a colliding version is preferable to silently
        # losing one of two concurrent flips at peer dedup time.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot safely allocate a runtime-mode version: {exc}",
        ) from exc

    change = await state.apply_local(runtime, new_mode, initiator_user=user.get("email"), version=next_version)
    if change is None:
        # A concurrent newer change won the race on this pod. Surface this as
        # a soft success — current state already reflects an authorized flip
        # — but record the intent in the audit trail so postmortems can see
        # the superseded request.
        winning_version = state.version(runtime)
        winning_override = state.override_mode(runtime)
        winning_mode = winning_override.value if winning_override is not None else boot_mode
        audit_persisted = _write_audit_event(
            user=user,
            db=db,
            runtime=runtime,
            resource_label=resource_label,
            success=False,
            old_values={"mode": (previous_override.value if previous_override is not None else boot_mode), "override_active": previous_override is not None},
            new_values={"mode": new_mode.value, "override_active": True, "version": next_version, "applied": False},
            additional_context={
                "runtime": runtime.value,
                "boot_mode": boot_mode,
                "initiator_pod": state.pod_id,
                "outcome": "superseded",
                "attempted_version": next_version,
                "superseded_by_version": winning_version,
                "superseded_by_mode": winning_mode,
            },
        )
        return ApplyModeResult(publish_status=PublishStatus.SUPERSEDED, audit_persisted=audit_persisted)

    audit_persisted = _write_audit_event(
        user=user,
        db=db,
        runtime=runtime,
        resource_label=resource_label,
        success=True,
        old_values={"mode": (previous_override.value if previous_override is not None else boot_mode), "override_active": previous_override is not None},
        new_values={"mode": new_mode.value, "override_active": True, "version": change.version},
        additional_context={
            "runtime": runtime.value,
            "boot_mode": boot_mode,
            "initiator_pod": change.initiator_pod,
            "outcome": "applied",
        },
    )

    publish_ok = await coordinator.publish(change)
    if publish_ok:
        publish_status = PublishStatus.PROPAGATED if coordinator.cluster_propagation_enabled else PublishStatus.LOCAL_ONLY
    else:
        publish_status = PublishStatus.FAILED
    logger.info(
        "Runtime override applied: runtime=%s new=%s previous=%s version=%d initiator=%s publish=%s audit=%s",
        runtime.value,
        new_mode.value,
        previous_override,
        change.version,
        user.get("email"),
        publish_status.value,
        audit_persisted,
    )
    return ApplyModeResult(publish_status=publish_status, audit_persisted=audit_persisted)


def _warn_if_behind_reverse_proxy(request: Any, *, runtime: RuntimeKind) -> None:
    """Emit a one-line WARNING when reverse-proxy headers are present on a PATCH.

    A reverse proxy fronting the gateway is configured at deploy time and does
    not follow the runtime override (see issue #4278). The local override still
    takes effect on this pod, but public ingress traffic that lands at the
    proxy will continue to follow whatever upstream the proxy was configured
    with. Surfacing this on every PATCH gives operators a chance to notice
    before they assume the flip is end-to-end.

    Args:
        request: FastAPI request whose headers we inspect.
        runtime: Runtime kind being changed.
    """
    headers = getattr(request, "headers", None)
    if headers is None:
        return
    detected = sorted(name for name in _REVERSE_PROXY_HEADER_NAMES if name in headers)
    if not detected:
        return
    logger.warning(
        "Runtime-mode PATCH for %s arrived through a reverse proxy (headers: %s). The local override is applied, but "
        "the proxy is configured at deploy time and will not follow the override unless explicitly reconfigured. "
        "See https://github.com/IBM/mcp-context-forge/issues/4278 for the proxy-side mechanism follow-up.",
        runtime.value,
        detected,
    )


def _write_audit_event(
    *,
    user: Dict[str, Any],
    db: Session,
    runtime: RuntimeKind,
    resource_label: str,
    success: bool,
    old_values: Dict[str, Any],
    new_values: Dict[str, Any],
    additional_context: Dict[str, Any],
) -> bool:
    """Write a runtime_config audit trail entry; report whether the write persisted.

    Audit-write failures must NOT roll back a runtime-mode change. Operators
    rely on this endpoint as an incident-rollback lever, and a failed audit
    write (DB outage, sink unreachable, misconfigured logger) is strictly
    less harmful than a failed flip. Catch broadly, log at ERROR with full
    context so the audit gap is visible, and let the caller surface
    ``audit_persisted: False`` in the response.

    Args:
        user: Authenticated user context.
        db: Request-scoped DB session.
        runtime: Runtime kind being changed.
        resource_label: Audit ``resource_id`` (e.g. ``"mcp_mode"``).
        success: ``True`` for an applied change, ``False`` for a superseded one.
        old_values: Snapshot of state before the attempted change.
        new_values: Snapshot of the requested change (and ``applied`` flag for the superseded path).
        additional_context: Free-form context dict surfaced in the audit row.

    Returns:
        ``True`` when the audit write succeeded, ``False`` when it failed.
    """
    try:
        get_security_logger().log_data_access(
            action="update",
            resource_type="runtime_config",
            resource_id=resource_label,
            resource_name=f"{runtime.value}_runtime_mode",
            user_id=user.get("email") or "unknown",
            user_email=user.get("email"),
            team_id=None,
            client_ip=user.get("ip_address"),
            user_agent=user.get("user_agent"),
            success=success,
            old_values=old_values,
            new_values=new_values,
            additional_context=additional_context,
            db=db,
        )
        return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "Runtime-mode audit trail failed to persist for %s outcome=%s (override action still proceeded): %s",
            runtime.value,
            additional_context.get("outcome", "unknown"),
            exc,
        )
        return False


@runtime_admin_router.get("/mcp-mode")
@require_permission("admin.system_config")
async def get_mcp_mode(
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Return the current MCP runtime mode and override state.

    Args:
        user: Authenticated user context (must have ``admin.system_config``).

    Returns:
        State payload describing boot mode, effective mode, override state, and propagation status.
    """
    del user  # consumed by the @require_permission decorator
    return _build_state_payload(
        RuntimeKind.MCP,
        boot_mode=version_module.boot_mcp_runtime_mode(),
        mounted=version_module.current_mcp_transport_mount(),
    )


@runtime_admin_router.patch("/mcp-mode")
@require_permission("admin.system_config")
async def patch_mcp_mode(
    body: RuntimeModeUpdate,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Flip the public ``/mcp`` ingress between ``shadow`` and ``edge``.

    Args:
        body: Request body containing the target mode.
        request: FastAPI request (used for reverse-proxy header detection).
        user: Authenticated user context (must have ``admin.system_config``).
        db: Request-scoped DB session for the audit write.

    Returns:
        Updated state payload after the flip is applied locally and published.
    """
    boot_mode = version_module.boot_mcp_runtime_mode()
    result = await _apply_mode_change(
        runtime=RuntimeKind.MCP,
        new_mode=body.mode,
        user=user,
        db=db,
        boot_mode=boot_mode,
        resource_label="mcp_mode",
        request=request,
    )
    payload = _build_state_payload(
        RuntimeKind.MCP,
        boot_mode=boot_mode,
        mounted=version_module.current_mcp_transport_mount(),
    )
    payload["publish_status"] = result.publish_status.value
    payload["audit_persisted"] = result.audit_persisted
    return payload


@runtime_admin_router.get("/a2a-mode")
@require_permission("admin.system_config")
async def get_a2a_mode(
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
) -> Dict[str, Any]:
    """Return the current A2A runtime mode and override state.

    Args:
        user: Authenticated user context (must have ``admin.system_config``).

    Returns:
        State payload describing boot mode, effective mode, override state, and propagation status.
    """
    del user
    return _build_state_payload(
        RuntimeKind.A2A,
        boot_mode=version_module.boot_a2a_runtime_mode(),
        invoke_mode="rust" if version_module.should_delegate_a2a_to_rust() else "python",
    )


@runtime_admin_router.patch("/a2a-mode")
@require_permission("admin.system_config")
async def patch_a2a_mode(
    body: RuntimeModeUpdate,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Flip the registered-A2A invocation path between Python and the Rust runtime.

    Args:
        body: Request body containing the target mode.
        request: FastAPI request (used for reverse-proxy header detection).
        user: Authenticated user context (must have ``admin.system_config``).
        db: Request-scoped DB session for the audit write.

    Returns:
        Updated state payload after the flip is applied locally and published.
    """
    boot_mode = version_module.boot_a2a_runtime_mode()
    result = await _apply_mode_change(
        runtime=RuntimeKind.A2A,
        new_mode=body.mode,
        user=user,
        db=db,
        boot_mode=boot_mode,
        resource_label="a2a_mode",
        request=request,
    )
    payload = _build_state_payload(
        RuntimeKind.A2A,
        boot_mode=boot_mode,
        invoke_mode="rust" if version_module.should_delegate_a2a_to_rust() else "python",
    )
    payload["publish_status"] = result.publish_status.value
    payload["audit_persisted"] = result.audit_persisted
    return payload
