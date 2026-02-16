# -*- coding: utf-8 -*-
"""Policy Decision API - Authenticated endpoints.

Location: mcpgateway/routers/policy_decisions_api.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Provides REST API for querying policy decisions.
Addresses reviewer feedback #4 - adds authentication.
"""

# Standard
from datetime import datetime
import logging
from typing import List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.policy_decision_service import policy_decision_service
from mcpgateway.utils.verify_credentials import require_admin_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/policy-decisions",
    tags=["Policy Decisions"],
    dependencies=[Depends(require_admin_auth)],
)

# Separate unauthenticated router for health endpoint
health_router = APIRouter(
    prefix="/api/policy-decisions",
    tags=["Policy Decisions"],
)


class PolicyDecisionResponse(BaseModel):
    """Response model for policy decision."""

    id: str
    timestamp: str
    request_id: Optional[str] = None
    gateway_node: Optional[str] = None
    subject: Optional[dict] = None
    action: str
    resource: Optional[dict] = None
    decision: str
    reason: Optional[str] = None
    matching_policies: List[dict] = []
    duration_ms: Optional[float] = None
    metadata: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


class QueryRequest(BaseModel):
    """Request model for querying decisions."""

    subject_email: Optional[str] = None
    subject_id: Optional[str] = None
    resource_id: Optional[str] = None
    resource_type: Optional[str] = None
    action: Optional[str] = None
    decision: Optional[str] = Field(None, pattern="^(allow|deny|not_applicable)$")
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    severity: Optional[str] = Field(None, pattern="^(info|warning|critical)$")
    min_risk_score: Optional[int] = Field(None, ge=0, le=100)
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    sort_by: str = Field("timestamp", pattern="^(timestamp|action|decision|severity|risk_score)$")
    sort_order: str = Field("desc", pattern="^(asc|desc)$")


class StatisticsResponse(BaseModel):
    """Response model for statistics."""

    total_decisions: int
    allowed: int
    denied: int
    avg_duration_ms: float
    time_range: dict


def _to_response(d) -> PolicyDecisionResponse:
    """Convert a PolicyDecision ORM object to a response model."""
    return PolicyDecisionResponse(
        id=str(d.id),
        timestamp=d.timestamp.isoformat() if d.timestamp else "",
        request_id=d.request_id,
        gateway_node=d.gateway_node,
        subject=({"type": d.subject_type, "id": d.subject_id, "email": d.subject_email, "roles": d.subject_roles or [], "teams": d.subject_teams or []} if d.subject_id else None),
        action=d.action,
        resource=({"type": d.resource_type, "id": d.resource_id, "server": d.resource_server} if d.resource_id else None),
        decision=d.decision,
        reason=d.reason,
        matching_policies=d.matching_policies or [],
        duration_ms=d.duration_ms,
        metadata={"severity": d.severity, "risk_score": d.risk_score, "anomaly_detected": d.anomaly_detected},
    )


@router.get(
    "/decisions",
    response_model=List[PolicyDecisionResponse],
    summary="Query policy decisions",
    description="Query policy decision audit logs with various filters. Requires admin authentication.",
)
def query_decisions(
    subject_email: Optional[str] = Query(None, description="Filter by subject email"),
    subject_id: Optional[str] = Query(None, description="Filter by subject ID"),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    action: Optional[str] = Query(None, description="Filter by action"),
    decision: Optional[str] = Query(None, description="Filter by decision (allow/deny)"),
    start_time: Optional[datetime] = Query(None, description="Start of time range"),
    end_time: Optional[datetime] = Query(None, description="End of time range"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    min_risk_score: Optional[int] = Query(None, ge=0, le=100, description="Minimum risk score"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    sort_by: str = Query("timestamp", pattern="^(timestamp|action|decision|severity|risk_score)$", description="Column to sort by"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order (asc/desc)"),
):
    """Query policy decisions. Requires admin authentication."""
    try:
        decisions = policy_decision_service.query_decisions(
            subject_email=subject_email,
            subject_id=subject_id,
            resource_id=resource_id,
            resource_type=resource_type,
            action=action,
            decision=decision,
            start_time=start_time,
            end_time=end_time,
            severity=severity,
            min_risk_score=min_risk_score,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return [_to_response(d) for d in decisions]
    except Exception as e:
        logger.error(f"Failed to query decisions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to query decisions")


@router.post(
    "/decisions/query",
    response_model=List[PolicyDecisionResponse],
    summary="Query policy decisions (POST)",
    description="Query using POST for complex queries. Requires admin authentication.",
)
def query_decisions_post(query: QueryRequest):
    """Query decisions using POST method for complex queries."""
    try:
        decisions = policy_decision_service.query_decisions(**query.model_dump(exclude_unset=True))
        return [_to_response(d) for d in decisions]
    except Exception as e:
        logger.error(f"Failed to query decisions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to query decisions")


@router.get(
    "/statistics",
    response_model=StatisticsResponse,
    summary="Get policy decision statistics",
    description="Get aggregate statistics about policy decisions. Requires admin authentication.",
)
def get_statistics(
    start_time: Optional[datetime] = Query(None, description="Start of time range"),
    end_time: Optional[datetime] = Query(None, description="End of time range"),
):
    """Get statistics about policy decisions."""
    try:
        stats = policy_decision_service.get_statistics(start_time=start_time, end_time=end_time)
        return StatisticsResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get statistics")


@health_router.get(
    "/health",
    summary="Health check",
    description="Check if policy decision logging is healthy",
)
def health_check():
    """Health check endpoint (no auth required for monitoring)."""
    return {
        "status": "healthy",
        "service": "policy-decision-logging",
        "enabled": settings.policy_audit_enabled,
    }
