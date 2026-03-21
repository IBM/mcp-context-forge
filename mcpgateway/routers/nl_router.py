# -*- coding: utf-8 -*-
"""Natural language execution API endpoints."""

# Standard
from collections import defaultdict
import time
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.nl_execution_service import NLExecutionService

logger = LoggingService().get_logger(__name__)

router = APIRouter(prefix="/api/v1/nl", tags=["Natural Language"])
service = NLExecutionService()

_rate_limit_storage: Dict[str, List[float]] = defaultdict(list)


class NLExecuteRequest(BaseModel):
    query: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1)
    include_follow_ups: Optional[bool] = None
    dry_run: bool = False


class NLExecuteResponse(BaseModel):
    session_id: str
    type: str
    response: str
    tool_used: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    pending_tool: Optional[str] = None
    partial_params: Optional[Dict[str, Any]] = None
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)
    follow_ups: List[Dict[str, str]] = Field(default_factory=list)
    intent: Optional[Dict[str, Any]] = None


class NLParseRequest(BaseModel):
    query: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1)


class NLParseResponse(BaseModel):
    session_id: str
    intent: Dict[str, Any]
    matches: List[Dict[str, Any]]
    slot_filling: Optional[Dict[str, Any]] = None


class NLConfirmRequest(BaseModel):
    session_id: str
    confirm: bool = True
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1)


class NLContextResponse(BaseModel):
    session_id: str
    messages: List[Dict[str, Any]]
    extracted_entities: Dict[str, Any]
    pending_execution: Optional[Dict[str, Any]] = None
    clarification_rounds: int


class NLFeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    query: Optional[str] = None
    tool_used: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None


def _ensure_enabled(model_override: Optional[str] = None) -> None:
    if not settings.nl_execution_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Natural language execution is disabled")
    if not (model_override or settings.nl_execution_model):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="NL execution model is not configured")


def _enforce_rate_limit(request: Request, limit: Optional[int] = None) -> None:
    limit = limit or settings.nl_execution_rate_limit
    if limit <= 0:
        return
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    minute_ago = now - 60
    _rate_limit_storage[client_ip] = [ts for ts in _rate_limit_storage[client_ip] if ts > minute_ago]
    if len(_rate_limit_storage[client_ip]) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Maximum {limit} requests per minute.",
        )
    _rate_limit_storage[client_ip].append(now)


@router.post("/execute", response_model=NLExecuteResponse)
@require_permission("tools.execute")
async def execute_nl(
    payload: NLExecuteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> NLExecuteResponse:
    _ensure_enabled(payload.model)
    _enforce_rate_limit(request)

    result = await service.execute(
        query=payload.query,
        db=db,
        user_ctx=current_user_ctx,
        request_headers=dict(request.headers),
        session_id=payload.session_id,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        include_follow_ups=payload.include_follow_ups,
        dry_run=payload.dry_run,
    )
    return NLExecuteResponse(**result)


@router.post("/parse", response_model=NLParseResponse)
@require_permission("tools.read")
async def parse_nl(
    payload: NLParseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> NLParseResponse:
    _ensure_enabled(payload.model)
    _enforce_rate_limit(request, limit=settings.nl_execution_rate_limit)

    result = await service.parse(
        query=payload.query,
        db=db,
        user_ctx=current_user_ctx,
        session_id=payload.session_id,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    return NLParseResponse(**result)


@router.post("/confirm", response_model=NLExecuteResponse)
@require_permission("tools.execute")
async def confirm_nl(
    payload: NLConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> NLExecuteResponse:
    _ensure_enabled(payload.model)

    result = await service.confirm(
        session_id=payload.session_id,
        db=db,
        user_ctx=current_user_ctx,
        request_headers=dict(request.headers),
        confirm=payload.confirm,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    return NLExecuteResponse(**result)


@router.get("/context/{session_id}", response_model=NLContextResponse)
@require_permission("tools.read")
async def get_context(
    session_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user_with_permissions),
) -> NLContextResponse:
    _ensure_enabled()
    context = await service.get_context(session_id)
    return NLContextResponse(**context)


@router.delete("/context/{session_id}")
@require_permission("tools.read")
async def clear_context(
    session_id: str,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user_with_permissions),
) -> Dict[str, str]:
    _ensure_enabled()
    await service.clear_context(session_id)
    return {"status": "cleared"}


@router.post("/feedback")
@require_permission("tools.read")
async def submit_feedback(
    payload: NLFeedbackRequest,
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user_with_permissions),
) -> Dict[str, str]:
    _ensure_enabled()
    await service.submit_feedback(payload.session_id, payload.model_dump())
    return {"status": "received"}
