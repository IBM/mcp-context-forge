# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/compliance_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Compliance Report Generator Router.

This module exposes REST endpoints for generating and retrieving compliance
reports for FedRAMP Moderate, FedRAMP High, HIPAA, and SOC2 Type II.

Examples:
    >>> from mcpgateway.routers.compliance_router import router
    >>> from fastapi import APIRouter
    >>> isinstance(router, APIRouter)
    True
"""

# Standard
import logging
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import SessionLocal
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_admin_permission
from mcpgateway.services.compliance_service import ComplianceFramework, get_compliance_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance", tags=["Compliance"])


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    """Get database session for dependency injection.

    Yields:
        Session: SQLAlchemy database session

    Raises:
        Exception: Re-raises any exception after rollback.

    Examples:
        >>> gen = get_db()
        >>> db = next(gen)
        >>> hasattr(db, 'close')
        True
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()
            except Exception:
                pass  # nosec B110 - Best effort cleanup on connection failure
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class GenerateReportRequest(BaseModel):
    """Request body for compliance report generation.

    Attributes:
        framework: Compliance framework to assess
        period_start: UTC start of assessment period
        period_end: UTC end of assessment period
    """

    framework: ComplianceFramework
    period_start: datetime
    period_end: datetime


class ControlEvidenceResponse(BaseModel):
    """Response schema for a single control evidence entry."""

    control_id: str
    status: str
    evidence: str
    findings: List[str]
    recommendations: List[str]

    model_config = {"from_attributes": True}


class ComplianceReportResponse(BaseModel):
    """Response schema for a compliance report."""

    id: str
    framework: str
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    controls: List[ControlEvidenceResponse]
    summary: Dict[str, Any]

    model_config = {"from_attributes": True}


class FrameworkInfo(BaseModel):
    """Information about a supported compliance framework."""

    id: str
    name: str
    description: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/frameworks", response_model=List[FrameworkInfo])
@require_admin_permission()
async def list_frameworks(user=Depends(get_current_user_with_permissions)) -> List[FrameworkInfo]:
    """List all supported compliance frameworks.

    Args:
        user: Authenticated admin user context.

    Returns:
        List of FrameworkInfo objects.
    """
    return [
        FrameworkInfo(id=ComplianceFramework.FEDRAMP_MODERATE.value, name="FedRAMP Moderate", description="NIST SP 800-53 controls at the Moderate impact level required by FedRAMP."),
        FrameworkInfo(id=ComplianceFramework.FEDRAMP_HIGH.value, name="FedRAMP High", description="NIST SP 800-53 controls at the High impact level required by FedRAMP."),
        FrameworkInfo(id=ComplianceFramework.HIPAA.value, name="HIPAA", description="Health Insurance Portability and Accountability Act Security Rule technical safeguards."),
        FrameworkInfo(id=ComplianceFramework.SOC2_TYPE2.value, name="SOC 2 Type II", description="AICPA Trust Services Criteria for a SOC 2 Type II examination."),
    ]


@router.post("/reports", response_model=ComplianceReportResponse, status_code=status.HTTP_201_CREATED)
@require_admin_permission()
async def generate_report(body: GenerateReportRequest, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> ComplianceReportResponse:
    """Generate a new compliance report.

    Args:
        body: Framework and assessment period.
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        ComplianceReportResponse: The generated report.

    Raises:
        HTTPException: 400 if period_start is after period_end.
    """
    if body.period_start >= body.period_end:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="period_start must be before period_end")

    service = get_compliance_service()
    report = service.generate_report(db=db, framework=body.framework, period_start=body.period_start, period_end=body.period_end)

    controls_out = [
        ControlEvidenceResponse(
            control_id=c.control_id,
            status=c.status.value,
            evidence=c.evidence,
            findings=c.findings,
            recommendations=c.recommendations,
        )
        for c in report.controls
    ]

    return ComplianceReportResponse(
        id=report.id,
        framework=report.framework.value,
        period_start=report.period_start,
        period_end=report.period_end,
        generated_at=report.generated_at,
        controls=controls_out,
        summary=report.summary,
    )


@router.get("/reports", response_model=List[ComplianceReportResponse])
@require_admin_permission()
async def list_reports(user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> List[ComplianceReportResponse]:
    """List all stored compliance reports.

    Args:
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        List of ComplianceReportResponse objects.
    """
    service = get_compliance_service()
    reports = service.list_reports(db=db)

    result = []
    for report in reports:
        controls_out = [
            ControlEvidenceResponse(
                control_id=c.control_id,
                status=c.status.value,
                evidence=c.evidence,
                findings=c.findings,
                recommendations=c.recommendations,
            )
            for c in report.controls
        ]
        result.append(
            ComplianceReportResponse(
                id=report.id,
                framework=report.framework.value,
                period_start=report.period_start,
                period_end=report.period_end,
                generated_at=report.generated_at,
                controls=controls_out,
                summary=report.summary,
            )
        )
    return result


@router.get("/reports/{report_id}", response_model=ComplianceReportResponse)
@require_admin_permission()
async def get_report(report_id: str, user=Depends(get_current_user_with_permissions), db: Session = Depends(get_db)) -> ComplianceReportResponse:
    """Get a specific compliance report by ID.

    Args:
        report_id: Report UUID.
        user: Authenticated admin user context.
        db: Database session.

    Returns:
        ComplianceReportResponse: The requested report.

    Raises:
        HTTPException: 404 if report not found.
    """
    service = get_compliance_service()
    report = service.get_report(db=db, report_id=report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Compliance report {report_id} not found")

    controls_out = [
        ControlEvidenceResponse(
            control_id=c.control_id,
            status=c.status.value,
            evidence=c.evidence,
            findings=c.findings,
            recommendations=c.recommendations,
        )
        for c in report.controls
    ]

    return ComplianceReportResponse(
        id=report.id,
        framework=report.framework.value,
        period_start=report.period_start,
        period_end=report.period_end,
        generated_at=report.generated_at,
        controls=controls_out,
        summary=report.summary,
    )


@router.get("/reports/{report_id}/export")
@require_admin_permission()
async def export_report(
    report_id: str,
    user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    format: Optional[str] = Query(default="json", description="Export format: json or csv"),
):
    """Export a compliance report in JSON or CSV format.

    Args:
        report_id: Report UUID.
        user: Authenticated admin user context.
        db: Database session.
        format: Export format ('json' or 'csv').

    Returns:
        Dict with content_type and data fields.

    Raises:
        HTTPException: 404 if report not found.
        HTTPException: 400 if format is unsupported.
    """
    service = get_compliance_service()
    report = service.get_report(db=db, report_id=report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Compliance report {report_id} not found")

    fmt = (format or "json").lower()
    if fmt == "json":
        return {"content_type": "application/json", "data": service.export_json(report)}
    if fmt == "csv":
        return {"content_type": "text/csv", "data": service.export_csv(report)}

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported export format '{fmt}'. Use 'json' or 'csv'.")
