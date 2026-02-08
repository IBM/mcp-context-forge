"""
FastAPI REST API for audit log queries.

Provides HTTP endpoints for querying and analyzing audit decisions.
Aligned with IBM MCP Context Forge requirements.
"""

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import json

from mcp_audit_models import (
    AuditDecisionRecord,
    AuditQueryFilter,
    AuditStatistics,
    DecisionResult,
    SubjectDetails,
    ResourceDetails,
    ContextDetails,
    PolicyMatchDetails
)
from mcp_audit_database import AuditDatabasePool


# Pydantic models for API

class SubjectDetailsResponse(BaseModel):
    """Subject details in API response."""
    type: str
    id: str
    email: Optional[str] = None
    roles: List[str] = []
    teams: List[str] = []
    clearance_level: Optional[int] = None


class ResourceDetailsResponse(BaseModel):
    """Resource details in API response."""
    type: str
    id: str
    server: Optional[str] = None
    classification: Optional[int] = None
    owner: Optional[str] = None


class PolicyMatchResponse(BaseModel):
    """Policy match in API response."""
    id: str
    name: str
    engine: str
    result: str
    explanation: str


class DecisionRecordResponse(BaseModel):
    """Decision record in API response."""
    id: str
    timestamp: str
    request_id: Optional[str] = None
    gateway_node: Optional[str] = None
    subject: Optional[SubjectDetailsResponse] = None
    action: str
    resource: Optional[ResourceDetailsResponse] = None
    decision: str
    reason: str
    matching_policies: List[PolicyMatchResponse] = []
    duration_ms: float


class QueryDecisionsRequest(BaseModel):
    """Request body for querying decisions."""
    start_time: Optional[str] = Field(None, description="ISO 8601 timestamp")
    end_time: Optional[str] = Field(None, description="ISO 8601 timestamp")
    subject_email: Optional[str] = None
    subject_id: Optional[str] = None
    resource_id: Optional[str] = None
    resource_type: Optional[str] = None
    decision: Optional[str] = Field(None, description="allow, deny, or indeterminate")
    action: Optional[str] = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class StatisticsResponse(BaseModel):
    """Statistics response."""
    total_decisions: int
    allowed: int
    denied: int
    errors: int
    unique_subjects: int
    unique_resources: int
    avg_duration_ms: float
    time_range: dict


# Create FastAPI app
app = FastAPI(
    title="MCP Audit API",
    description="REST API for querying policy decision audit logs",
    version="1.0.0"
)


# Dependency to get database pool
_db_pool: Optional[AuditDatabasePool] = None


def get_db_pool() -> AuditDatabasePool:
    """Get database pool instance."""
    if _db_pool is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return _db_pool


def set_db_pool(pool: AuditDatabasePool) -> None:
    """Set database pool instance."""
    global _db_pool
    _db_pool = pool


# API Endpoints

@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "name": "MCP Audit API",
        "version": "1.0.0",
        "endpoints": {
            "query_decisions": "/audit/decisions",
            "get_statistics": "/audit/statistics",
            "export_csv": "/audit/export/csv",
            "health": "/health"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/audit/decisions", response_model=List[DecisionRecordResponse])
async def query_decisions(
    start_time: Optional[str] = Query(None, description="Start time (ISO 8601)"),
    end_time: Optional[str] = Query(None, description="End time (ISO 8601)"),
    subject_email: Optional[str] = Query(None, description="Filter by subject email"),
    subject_id: Optional[str] = Query(None, description="Filter by subject ID"),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    decision: Optional[str] = Query(None, description="Filter by decision (allow/deny)"),
    action: Optional[str] = Query(None, description="Filter by action"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db_pool: AuditDatabasePool = Depends(get_db_pool)
):
    """
    Query audit decision records.
    
    Example:
    ```
    GET /audit/decisions?
        subject_email=user@example.com&
        decision=deny&
        start_time=2024-01-01T00:00:00Z&
        limit=50
    ```
    """
    
    # Build filter
    filter = AuditQueryFilter(
        start_time=datetime.fromisoformat(start_time.replace('Z', '+00:00')) if start_time else None,
        end_time=datetime.fromisoformat(end_time.replace('Z', '+00:00')) if end_time else None,
        subject_email=subject_email,
        subject_id=subject_id,
        resource_id=resource_id,
        resource_type=resource_type,
        decision=DecisionResult(decision) if decision else None,
        action=action,
        limit=limit,
        offset=offset
    )
    
    # Query database
    records = await db_pool.query_decisions(filter)
    
    # Convert to response format
    response = []
    for record in records:
        response.append(DecisionRecordResponse(
            id=record.id,
            timestamp=record.timestamp.isoformat(),
            request_id=record.request_id,
            gateway_node=record.gateway_node,
            subject=SubjectDetailsResponse(**record.subject.to_dict()) if record.subject else None,
            action=record.action,
            resource=ResourceDetailsResponse(**record.resource.to_dict()) if record.resource else None,
            decision=record.decision.value,
            reason=record.reason,
            matching_policies=[
                PolicyMatchResponse(
                    id=p.id,
                    name=p.name,
                    engine=p.engine,
                    result=p.result,
                    explanation=p.explanation
                )
                for p in record.matching_policies
            ],
            duration_ms=record.duration_ms
        ))
    
    return response


@app.post("/audit/decisions/query", response_model=List[DecisionRecordResponse])
async def query_decisions_post(
    request: QueryDecisionsRequest,
    db_pool: AuditDatabasePool = Depends(get_db_pool)
):
    """
    Query decisions using POST (for complex queries).
    
    Example:
    ```json
    {
        "subject_email": "user@example.com",
        "decision": "deny",
        "start_time": "2024-01-01T00:00:00Z",
        "end_time": "2024-01-31T23:59:59Z",
        "limit": 100
    }
    ```
    """
    
    # Build filter from request
    filter = AuditQueryFilter(
        start_time=datetime.fromisoformat(request.start_time.replace('Z', '+00:00')) if request.start_time else None,
        end_time=datetime.fromisoformat(request.end_time.replace('Z', '+00:00')) if request.end_time else None,
        subject_email=request.subject_email,
        subject_id=request.subject_id,
        resource_id=request.resource_id,
        resource_type=request.resource_type,
        decision=DecisionResult(request.decision) if request.decision else None,
        action=request.action,
        limit=request.limit,
        offset=request.offset
    )
    
    records = await db_pool.query_decisions(filter)
    
    # Convert to response
    return [
        DecisionRecordResponse(
            id=r.id,
            timestamp=r.timestamp.isoformat(),
            request_id=r.request_id,
            gateway_node=r.gateway_node,
            subject=SubjectDetailsResponse(**r.subject.to_dict()) if r.subject else None,
            action=r.action,
            resource=ResourceDetailsResponse(**r.resource.to_dict()) if r.resource else None,
            decision=r.decision.value,
            reason=r.reason,
            matching_policies=[
                PolicyMatchResponse(id=p.id, name=p.name, engine=p.engine, result=p.result, explanation=p.explanation)
                for p in r.matching_policies
            ],
            duration_ms=r.duration_ms
        )
        for r in records
    ]


@app.get("/audit/statistics", response_model=StatisticsResponse)
async def get_statistics(
    start_time: Optional[str] = Query(None, description="Start time (ISO 8601)"),
    end_time: Optional[str] = Query(None, description="End time (ISO 8601)"),
    db_pool: AuditDatabasePool = Depends(get_db_pool)
):
    """
    Get audit statistics for a time range.
    
    Example:
    ```
    GET /audit/statistics?start_time=2024-01-01T00:00:00Z&end_time=2024-01-31T23:59:59Z
    ```
    """
    
    start = datetime.fromisoformat(start_time.replace('Z', '+00:00')) if start_time else None
    end = datetime.fromisoformat(end_time.replace('Z', '+00:00')) if end_time else None
    
    stats = await db_pool.get_statistics(start, end)
    
    return StatisticsResponse(
        total_decisions=stats.total_decisions,
        allowed=stats.allowed,
        denied=stats.denied,
        errors=stats.errors,
        unique_subjects=stats.unique_subjects,
        unique_resources=stats.unique_resources,
        avg_duration_ms=stats.avg_duration_ms,
        time_range={
            'start': stats.time_range_start.isoformat() if stats.time_range_start else None,
            'end': stats.time_range_end.isoformat() if stats.time_range_end else None
        }
    )


@app.get("/audit/export/csv")
async def export_csv(
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    subject_email: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    limit: int = Query(10000, le=100000),
    db_pool: AuditDatabasePool = Depends(get_db_pool)
):
    """
    Export audit records as CSV.
    
    Example:
    ```
    GET /audit/export/csv?start_time=2024-01-01T00:00:00Z&limit=1000
    ```
    """
    
    # Build filter
    filter = AuditQueryFilter(
        start_time=datetime.fromisoformat(start_time.replace('Z', '+00:00')) if start_time else None,
        end_time=datetime.fromisoformat(end_time.replace('Z', '+00:00')) if end_time else None,
        subject_email=subject_email,
        decision=DecisionResult(decision) if decision else None,
        limit=limit
    )
    
    records = await db_pool.query_decisions(filter)
    
    # Generate CSV
    def generate_csv():
        # Header
        yield "id,timestamp,subject_email,action,resource_id,decision,reason,duration_ms\n"
        
        # Rows
        for record in records:
            subject_email = record.subject.email if record.subject else ""
            resource_id = record.resource.id if record.resource else ""
            
            yield (
                f'"{record.id}",'
                f'"{record.timestamp.isoformat()}",'
                f'"{subject_email}",'
                f'"{record.action}",'
                f'"{resource_id}",'
                f'"{record.decision.value}",'
                f'"{record.reason}",'
                f'{record.duration_ms}\n'
            )
    
    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_decisions.csv"}
    )


@app.get("/audit/export/json")
async def export_json(
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    limit: int = Query(10000, le=100000),
    db_pool: AuditDatabasePool = Depends(get_db_pool)
):
    """
    Export audit records as JSON Lines (one JSON object per line).
    
    Example:
    ```
    GET /audit/export/json?start_time=2024-01-01T00:00:00Z
    ```
    """
    
    filter = AuditQueryFilter(
        start_time=datetime.fromisoformat(start_time.replace('Z', '+00:00')) if start_time else None,
        end_time=datetime.fromisoformat(end_time.replace('Z', '+00:00')) if end_time else None,
        limit=limit
    )
    
    records = await db_pool.query_decisions(filter)
    
    def generate_jsonl():
        for record in records:
            yield record.to_json() + '\n'
    
    return StreamingResponse(
        generate_jsonl(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=audit_decisions.jsonl"}
    )


# Error handlers

@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"error": "Bad Request", "detail": str(exc)}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "detail": str(exc)}
    )
