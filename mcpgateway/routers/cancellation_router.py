# -*- coding: utf-8 -*-
# mcpgateway/routers/cancellation_router.py
"""Location: ./mcpgateway/routers/cancellation_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Cancellation router to support gateway-authoritative cancellation actions.

Endpoints:
- POST /cancellation/cancel -> Request cancellation for a run/requestId
- GET  /cancellation/status/{request_id} -> Get status for a registered run

Security: endpoints require RBAC permission `admin.system_config` by default.
"""
# Standard
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

# First-Party
import mcpgateway.main as main_module
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.cancellation_service import cancellation_service
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

router = APIRouter(prefix="/cancellation", tags=["Cancellation"])


class CancelRequest(BaseModel):
    """
    Request model for cancelling a run/requestId.

    Attributes:
        request_id: The ID of the request to cancel.
        reason: Optional reason for cancellation.
    """

    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(..., alias="requestId")
    reason: Optional[str] = None


class CancelResponse(BaseModel):
    """
    Response model for cancellation requests.

    Attributes:
        status: Status of the cancellation request ("cancelled" or "queued").
        request_id: The ID of the request that was cancelled.
        reason: Optional reason for cancellation.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str  # "cancelled" | "queued"
    request_id: str = Field(..., alias="requestId")
    reason: Optional[str] = None


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
    local_cancelled = await cancellation_service.cancel_run(request_id, reason=reason)

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
    if not await cancellation_service.is_registered(request_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    status_obj = await cancellation_service.get_status(request_id)
    if status_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    # Filter out non-serializable fields (cancel_callback is a function reference)
    return {k: v for k, v in status_obj.items() if k != "cancel_callback"}
