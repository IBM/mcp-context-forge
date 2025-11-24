# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/log_search.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Log Search API Router.

This module provides REST API endpoints for searching and analyzing structured logs,
security events, audit trails, and performance metrics.
"""

# Standard
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, desc, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func as sa_func

# First-Party
from mcpgateway.db import (
    AuditTrail,
    PerformanceMetric,
    SecurityEvent,
    StructuredLogEntry,
    get_db,
)
from mcpgateway.middleware.rbac import require_permission, get_current_user_with_permissions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])


# Request/Response Models
class LogSearchRequest(BaseModel):
    """Log search request parameters."""
    search_text: Optional[str] = Field(None, description="Text search query")
    level: Optional[List[str]] = Field(None, description="Log levels to filter")
    component: Optional[List[str]] = Field(None, description="Components to filter")
    category: Optional[List[str]] = Field(None, description="Categories to filter")
    correlation_id: Optional[str] = Field(None, description="Correlation ID to filter")
    user_id: Optional[str] = Field(None, description="User ID to filter")
    start_time: Optional[datetime] = Field(None, description="Start timestamp")
    end_time: Optional[datetime] = Field(None, description="End timestamp")
    min_duration_ms: Optional[float] = Field(None, description="Minimum duration")
    max_duration_ms: Optional[float] = Field(None, description="Maximum duration")
    has_error: Optional[bool] = Field(None, description="Filter for errors")
    limit: int = Field(100, ge=1, le=1000, description="Maximum results")
    offset: int = Field(0, ge=0, description="Result offset")
    sort_by: str = Field("timestamp", description="Field to sort by")
    sort_order: str = Field("desc", description="Sort order (asc/desc)")


class LogEntry(BaseModel):
    """Log entry response model."""
    id: str
    timestamp: datetime
    level: str
    component: str
    message: str
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    duration_ms: Optional[float] = None
    operation_type: Optional[str] = None
    request_path: Optional[str] = None
    request_method: Optional[str] = None
    is_security_event: bool = False
    error_details: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True


class LogSearchResponse(BaseModel):
    """Log search response."""
    total: int
    results: List[LogEntry]


class CorrelationTraceRequest(BaseModel):
    """Correlation trace request."""
    correlation_id: str


class CorrelationTraceResponse(BaseModel):
    """Correlation trace response with all related logs."""
    correlation_id: str
    total_duration_ms: Optional[float]
    log_count: int
    error_count: int
    logs: List[LogEntry]
    security_events: List[Dict[str, Any]]
    audit_trails: List[Dict[str, Any]]
    performance_metrics: Optional[Dict[str, Any]]


class SecurityEventResponse(BaseModel):
    """Security event response model."""
    id: str
    timestamp: datetime
    event_type: str
    severity: str
    category: str
    user_id: Optional[str]
    client_ip: str
    description: str
    threat_score: float
    action_taken: Optional[str]
    resolved: bool
    
    class Config:
        from_attributes = True


class AuditTrailResponse(BaseModel):
    """Audit trail response model."""
    id: str
    timestamp: datetime
    action: str
    resource_type: str
    resource_id: Optional[str]
    user_id: str
    success: bool
    requires_review: bool
    data_classification: Optional[str]
    
    class Config:
        from_attributes = True


class PerformanceMetricResponse(BaseModel):
    """Performance metric response model."""
    id: str
    timestamp: datetime
    component: str
    operation_type: str
    window_start: datetime
    window_end: datetime
    request_count: int
    error_count: int
    error_rate: float
    avg_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    p50_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float
    
    class Config:
        from_attributes = True


# API Endpoints
@router.post("/search", response_model=LogSearchResponse)
@require_permission("logs:read")
async def search_logs(
    request: LogSearchRequest,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db)
) -> LogSearchResponse:
    """Search structured logs with filters and pagination.
    
    Args:
        request: Search parameters
        db: Database session
        _: Permission check dependency
        
    Returns:
        Search results with pagination
    """
    try:
        # Build base query
        stmt = select(StructuredLogEntry)
        
        # Apply filters
        conditions = []
        
        if request.search_text:
            conditions.append(
                or_(
                    StructuredLogEntry.message.ilike(f"%{request.search_text}%"),
                    StructuredLogEntry.component.ilike(f"%{request.search_text}%")
                )
            )
        
        if request.level:
            conditions.append(StructuredLogEntry.level.in_(request.level))
        
        if request.component:
            conditions.append(StructuredLogEntry.component.in_(request.component))
        
        # Note: category field doesn't exist in StructuredLogEntry
        # if request.category:
        #     conditions.append(StructuredLogEntry.category.in_(request.category))
        
        if request.correlation_id:
            conditions.append(StructuredLogEntry.correlation_id == request.correlation_id)
        
        if request.user_id:
            conditions.append(StructuredLogEntry.user_id == request.user_id)
        
        if request.start_time:
            conditions.append(StructuredLogEntry.timestamp >= request.start_time)
        
        if request.end_time:
            conditions.append(StructuredLogEntry.timestamp <= request.end_time)
        
        if request.min_duration_ms is not None:
            conditions.append(StructuredLogEntry.duration_ms >= request.min_duration_ms)
        
        if request.max_duration_ms is not None:
            conditions.append(StructuredLogEntry.duration_ms <= request.max_duration_ms)
        
        if request.has_error is not None:
            if request.has_error:
                conditions.append(StructuredLogEntry.error_details.isnot(None))
            else:
                conditions.append(StructuredLogEntry.error_details.is_(None))
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        # Get total count
        count_stmt = select(sa_func.count()).select_from(stmt.subquery())
        total = db.execute(count_stmt).scalar() or 0
        
        # Apply sorting
        sort_column = getattr(StructuredLogEntry, request.sort_by, StructuredLogEntry.timestamp)
        if request.sort_order == "desc":
            stmt = stmt.order_by(desc(sort_column))
        else:
            stmt = stmt.order_by(sort_column)
        
        # Apply pagination
        stmt = stmt.limit(request.limit).offset(request.offset)
        
        # Execute query
        results = db.execute(stmt).scalars().all()
        
        # Convert to response models
        log_entries = [
            LogEntry(
                id=str(log.id),
                timestamp=log.timestamp,
                level=log.level,
                component=log.component,
                message=log.message,
                correlation_id=log.correlation_id,
                user_id=log.user_id,
                user_email=log.user_email,
                duration_ms=log.duration_ms,
                operation_type=log.operation_type,
                request_path=log.request_path,
                request_method=log.request_method,
                is_security_event=log.is_security_event,
                error_details=log.error_details,
            )
            for log in results
        ]
        
        return LogSearchResponse(
            total=total,
            results=log_entries
        )
    
    except Exception as e:
        logger.error(f"Log search failed: {e}")
        raise HTTPException(status_code=500, detail="Log search failed")


@router.get("/trace/{correlation_id}", response_model=CorrelationTraceResponse)
@require_permission("logs:read")
async def trace_correlation_id(
    correlation_id: str,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db)
) -> CorrelationTraceResponse:
    """Get all logs and events for a correlation ID.
    
    Args:
        correlation_id: Correlation ID to trace
        db: Database session
        _: Permission check dependency
        
    Returns:
        Complete trace of all related logs and events
    """
    try:
        # Get structured logs
        log_stmt = select(StructuredLogEntry).where(
            StructuredLogEntry.correlation_id == correlation_id
        ).order_by(StructuredLogEntry.timestamp)
        
        logs = db.execute(log_stmt).scalars().all()
        
        # Get security events
        security_stmt = select(SecurityEvent).where(
            SecurityEvent.correlation_id == correlation_id
        ).order_by(SecurityEvent.timestamp)
        
        security_events = db.execute(security_stmt).scalars().all()
        
        # Get audit trails
        audit_stmt = select(AuditTrail).where(
            AuditTrail.correlation_id == correlation_id
        ).order_by(AuditTrail.timestamp)
        
        audit_trails = db.execute(audit_stmt).scalars().all()
        
        # Calculate metrics
        durations = [log.duration_ms for log in logs if log.duration_ms is not None]
        total_duration = sum(durations) if durations else None
        error_count = sum(1 for log in logs if log.error_details)
        
        # Get performance metrics (if any aggregations exist)
        perf_metrics = None
        if logs:
            component = logs[0].component
            operation = logs[0].operation_type
            if component and operation:
                perf_stmt = select(PerformanceMetric).where(
                    and_(
                        PerformanceMetric.component == component,
                        PerformanceMetric.operation_type == operation
                    )
                ).order_by(desc(PerformanceMetric.window_start)).limit(1)
                
                perf = db.execute(perf_stmt).scalar_one_or_none()
                if perf:
                    perf_metrics = {
                        "avg_duration_ms": perf.avg_duration_ms,
                        "p95_duration_ms": perf.p95_duration_ms,
                        "p99_duration_ms": perf.p99_duration_ms,
                        "error_rate": perf.error_rate,
                    }
        
        return CorrelationTraceResponse(
            correlation_id=correlation_id,
            total_duration_ms=total_duration,
            log_count=len(logs),
            error_count=error_count,
            logs=[
                LogEntry(
                    id=str(log.id),
                    timestamp=log.timestamp,
                    level=log.level,
                    component=log.component,
                    message=log.message,
                    correlation_id=log.correlation_id,
                    user_id=log.user_id,
                    user_email=log.user_email,
                    duration_ms=log.duration_ms,
                    operation_type=log.operation_type,
                    request_path=log.request_path,
                    request_method=log.request_method,
                    is_security_event=log.is_security_event,
                    error_details=log.error_details,
                )
                for log in logs
            ],
            security_events=[
                {
                    "id": str(event.id),
                    "timestamp": event.timestamp.isoformat(),
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "description": event.description,
                    "threat_score": event.threat_score,
                }
                for event in security_events
            ],
            audit_trails=[
                {
                    "id": str(audit.id),
                    "timestamp": audit.timestamp.isoformat(),
                    "action": audit.action,
                    "resource_type": audit.resource_type,
                    "resource_id": audit.resource_id,
                    "success": audit.success,
                }
                for audit in audit_trails
            ],
            performance_metrics=perf_metrics,
        )
    
    except Exception as e:
        logger.error(f"Correlation trace failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Correlation trace failed: {str(e)}")


@router.get("/security-events", response_model=List[SecurityEventResponse])
@require_permission("security:read")
async def get_security_events(
    severity: Optional[List[str]] = Query(None),
    event_type: Optional[List[str]] = Query(None),
    resolved: Optional[bool] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db)
) -> List[SecurityEventResponse]:
    """Get security events with filters.
    
    Args:
        severity: Filter by severity levels
        event_type: Filter by event types
        resolved: Filter by resolution status
        start_time: Start timestamp
        end_time: End timestamp
        limit: Maximum results
        offset: Result offset
        db: Database session
        _: Permission check dependency
        
    Returns:
        List of security events
    """
    try:
        stmt = select(SecurityEvent)
        
        conditions = []
        if severity:
            conditions.append(SecurityEvent.severity.in_(severity))
        if event_type:
            conditions.append(SecurityEvent.event_type.in_(event_type))
        if resolved is not None:
            conditions.append(SecurityEvent.resolved == resolved)
        if start_time:
            conditions.append(SecurityEvent.timestamp >= start_time)
        if end_time:
            conditions.append(SecurityEvent.timestamp <= end_time)
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        stmt = stmt.order_by(desc(SecurityEvent.timestamp)).limit(limit).offset(offset)
        
        events = db.execute(stmt).scalars().all()
        
        return [
            SecurityEventResponse(
                id=str(event.id),
                timestamp=event.timestamp,
                event_type=event.event_type,
                severity=event.severity,
                category=event.category,
                user_id=event.user_id,
                client_ip=event.client_ip,
                description=event.description,
                threat_score=event.threat_score,
                action_taken=event.action_taken,
                resolved=event.resolved,
            )
            for event in events
        ]
    
    except Exception as e:
        logger.error(f"Security events query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Security events query failed: {str(e)}")


@router.get("/audit-trails", response_model=List[AuditTrailResponse])
@require_permission("audit:read")
async def get_audit_trails(
    action: Optional[List[str]] = Query(None),
    resource_type: Optional[List[str]] = Query(None),
    user_id: Optional[str] = Query(None),
    requires_review: Optional[bool] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db)
) -> List[AuditTrailResponse]:
    """Get audit trails with filters.
    
    Args:
        action: Filter by actions
        resource_type: Filter by resource types
        user_id: Filter by user ID
        requires_review: Filter by review requirement
        start_time: Start timestamp
        end_time: End timestamp
        limit: Maximum results
        offset: Result offset
        db: Database session
        _: Permission check dependency
        
    Returns:
        List of audit trail entries
    """
    try:
        stmt = select(AuditTrail)
        
        conditions = []
        if action:
            conditions.append(AuditTrail.action.in_(action))
        if resource_type:
            conditions.append(AuditTrail.resource_type.in_(resource_type))
        if user_id:
            conditions.append(AuditTrail.user_id == user_id)
        if requires_review is not None:
            conditions.append(AuditTrail.requires_review == requires_review)
        if start_time:
            conditions.append(AuditTrail.timestamp >= start_time)
        if end_time:
            conditions.append(AuditTrail.timestamp <= end_time)
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        stmt = stmt.order_by(desc(AuditTrail.timestamp)).limit(limit).offset(offset)
        
        trails = db.execute(stmt).scalars().all()
        
        return [
            AuditTrailResponse(
                id=str(trail.id),
                timestamp=trail.timestamp,
                action=trail.action,
                resource_type=trail.resource_type,
                resource_id=trail.resource_id,
                user_id=trail.user_id,
                success=trail.success,
                requires_review=trail.requires_review,
                data_classification=trail.data_classification,
            )
            for trail in trails
        ]
    
    except Exception as e:
        logger.error(f"Audit trails query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Audit trails query failed: {str(e)}")


@router.get("/performance-metrics", response_model=List[PerformanceMetricResponse])
@require_permission("metrics:read")
async def get_performance_metrics(
    component: Optional[str] = Query(None),
    operation: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=1000),
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db)
) -> List[PerformanceMetricResponse]:
    """Get performance metrics.
    
    Args:
        component: Filter by component
        operation: Filter by operation
        hours: Hours of history
        db: Database session
        _: Permission check dependency
        
    Returns:
        List of performance metrics
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        stmt = select(PerformanceMetric).where(
            PerformanceMetric.window_start >= since
        )
        
        if component:
            stmt = stmt.where(PerformanceMetric.component == component)
        if operation:
            stmt = stmt.where(PerformanceMetric.operation_type == operation)
        
        stmt = stmt.order_by(desc(PerformanceMetric.window_start))
        
        metrics = db.execute(stmt).scalars().all()
        
        return [
            PerformanceMetricResponse(
                id=str(metric.id),
                timestamp=metric.timestamp,
                component=metric.component,
                operation_type=metric.operation_type,
                window_start=metric.window_start,
                window_end=metric.window_end,
                request_count=metric.request_count,
                error_count=metric.error_count,
                error_rate=metric.error_rate,
                avg_duration_ms=metric.avg_duration_ms,
                min_duration_ms=metric.min_duration_ms,
                max_duration_ms=metric.max_duration_ms,
                p50_duration_ms=metric.p50_duration_ms,
                p95_duration_ms=metric.p95_duration_ms,
                p99_duration_ms=metric.p99_duration_ms,
            )
            for metric in metrics
        ]
    
    except Exception as e:
        logger.error(f"Performance metrics query failed: {e}")
        raise HTTPException(status_code=500, detail="Performance metrics query failed")
