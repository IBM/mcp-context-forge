# mcpgateway/routers/orchestrate_router.py
"""Orchestrate router to support gateway-authoritative orchestration actions.

Endpoints:
- POST /orchestrate/cancel -> Request cancellation for a run/requestId
- GET  /orchestrate/{request_id} -> Get status for a registered run

Security: endpoints require RBAC permission `admin.system_config` by default.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from mcpgateway.middleware.rbac import require_permission, get_current_user_with_permissions
from mcpgateway.services.orchestration_service import orchestration_service
import mcpgateway.main as main_module

router = APIRouter(prefix="/orchestrate", tags=["Orchestrate"])


class CancelRequest(BaseModel):
    requestId: str
    reason: Optional[str] = None


class CancelResponse(BaseModel):
    status: str  # "cancelled" | "queued"
    requestId: str
    reason: Optional[str] = None


@router.post("/cancel", response_model=CancelResponse)
@require_permission("admin.system_config")
async def cancel_run(payload: CancelRequest, _user=Depends(get_current_user_with_permissions)) -> CancelResponse:
    request_id = payload.requestId
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
            except Exception:
                # Per-session errors are non-fatal for cancellation (best-effort)
                continue
    except Exception:
        # Continue silently if we cannot enumerate sessions
        pass

    return CancelResponse(status=("cancelled" if local_cancelled else "queued"), requestId=request_id, reason=reason)


@router.get("/status/{request_id}")
@require_permission("admin.system_config")
async def get_status(request_id: str, _user=Depends(get_current_user_with_permissions)):
    status_obj = await orchestration_service.get_status(request_id)
    if status_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return status_obj
