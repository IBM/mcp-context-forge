# mcpgateway/routers/orchestrate_router.py
"""Location: ./mcpgateway/routers/orchestrate_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Orchestrate router to support gateway-authoritative orchestration actions.

Endpoints:
- POST /orchestrate/cancel -> Request cancellation for a run/requestId
- GET  /orchestrate/{request_id} -> Get status for a registered run

Security: endpoints require RBAC permission `admin.system_config` by default.
"""
# Standard
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

# First-Party
import mcpgateway.main as main_module
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.orchestration_service import orchestration_service

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

router = APIRouter(prefix="/orchestrate", tags=["Orchestrate"])


class CancelRequest(BaseModel):
    """
    Request model for cancelling a run/requestId.
    :param request_id: The ID of the request to cancel.
    :param reason: Optional reason for cancellation.
    """

    request_id: str = Field(..., alias="requestId")
    reason: Optional[str] = None

    class Config:
        """
        Configuration to allow population by field name.
        """

        allow_population_by_field_name = True


class CancelResponse(BaseModel):
    """
    Response model for cancellation requests.
    :param status: Status of the cancellation request ("cancelled" or "queued").
    :param request_id: The ID of the request that was cancelled.
    :param reason: Optional reason for cancellation.
    """

    status: str  # "cancelled" | "queued"
    request_id: str = Field(..., alias="requestId")
    reason: Optional[str] = None

    class Config:
        """
        Configuration to allow population by field name.
        """

        allow_population_by_field_name = True


@router.post("/cancel", response_model=CancelResponse)
@require_permission("admin.system_config")
async def cancel_run(payload: CancelRequest, _user=Depends(get_current_user_with_permissions)) -> CancelResponse:
    """
    Cancel a run by its request ID.

    Args:
        payload: The cancellation request payload.
        _user: The current user (dependency injection).

    Returns:
        CancelResponse: The cancellation response indicating whether the run was cancelled or queued.
    """
    request_id = payload.request_id
    reason = payload.reason

    # Try local cancellation first
    local_cancelled = await orchestration_service.cancel_run(request_id, reason=reason)

    # Build MCP-style notification to broadcast to sessions (servers/peers)
    notification = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": request_id, "reason": reason}}

    # Broadcast best-effort to all sessions
    try:
        session_ids = await main_module.session_registry.get_all_session_ids()
        for sid in session_ids:
            try:
                await main_module.session_registry.broadcast(sid, notification)
            except Exception as e:
                # Per-session errors are non-fatal for cancellation (best-effort)
                logger.warning(f"Failed to broadcast cancellation notification to session {sid}: {e}")
    except Exception as e:
        # Continue silently if we cannot enumerate sessions
        logger.warning(f"Failed to enumerate sessions for cancellation notification: {e}")

    return CancelResponse(status=("cancelled" if local_cancelled else "queued"), request_id=request_id, reason=reason)


@router.get("/status/{request_id}")
@require_permission("admin.system_config")
async def get_status(request_id: str, _user=Depends(get_current_user_with_permissions)):
    """
    Get the status of a run by its request ID.

    Args:
        request_id: The ID of the request to get the status for.
        _user: The current user (dependency injection).

    Returns:
        dict: The status dictionary for the run (e.g. keys: 'name', 'registered_at', 'cancelled').

    Raises:
        HTTPException: If the run is not found.
    """
    if not orchestration_service.is_registered(request_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    status_obj = await orchestration_service.get_status(request_id)
    if status_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return status_obj
