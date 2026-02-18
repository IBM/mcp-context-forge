# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/compliance.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Compliance dashboard, framework reports, and evidence export endpoints.
"""

# flake8: noqa: DAR101, DAR201, DAR401

# Standard
import csv
from datetime import datetime, timezone
import io
import json
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.compliance_report_service import get_compliance_report_service, SUPPORTED_FRAMEWORKS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compliance", tags=["compliance"])

SUPPORTED_EXPORT_DATASETS = (
    "audit_logs",
    "access_control",
    "security_events",
    "compliance_summary",
    "encryption_status",
    "user_activity",
)


def _rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    """Serialize a list of dictionaries into CSV."""
    if not rows:
        return ""

    output = io.StringIO()
    fieldnames = sorted({key for row in rows for key in row.keys()})
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for row in rows:
        normalized_row: Dict[str, Any] = {}
        for key in fieldnames:
            value = row.get(key)
            if isinstance(value, datetime):
                normalized_row[key] = value.astimezone(timezone.utc).isoformat()
            elif isinstance(value, (dict, list)):
                normalized_row[key] = json.dumps(value, sort_keys=True)
            else:
                normalized_row[key] = value
        writer.writerow(normalized_row)

    return output.getvalue()


@router.get("/frameworks", response_model=List[str])
@require_permission("admin.security_audit")
async def get_frameworks(
    _user=Depends(get_current_user_with_permissions),
) -> List[str]:
    """Get supported compliance frameworks."""
    return get_compliance_report_service().normalize_frameworks(list(SUPPORTED_FRAMEWORKS))


@router.get("/dashboard", response_model=Dict[str, Any])
@require_permission("admin.security_audit")
async def get_compliance_dashboard(
    framework: Optional[List[str]] = Query(None, description="Framework filter (soc2, gdpr, hipaa, iso27001)"),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    trend_days: int = Query(14, ge=1, le=90),
    _user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get compliance dashboard summary and trend."""
    service = get_compliance_report_service()
    try:
        return service.build_dashboard(
            db=db,
            start_time=start_time,
            end_time=end_time,
            frameworks=framework,
            trend_days=trend_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to build compliance dashboard: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to build compliance dashboard") from exc


@router.get("/frameworks/{framework}", response_model=Dict[str, Any])
@require_permission("admin.security_audit")
async def get_framework_report(
    framework: str,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    _user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get a framework-specific compliance report."""
    service = get_compliance_report_service()
    try:
        return service.build_framework_report(
            framework=framework,
            db=db,
            start_time=start_time,
            end_time=end_time,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to build framework report: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to build framework report") from exc


@router.get("/user-activity/{user_identifier}", response_model=Dict[str, Any])
@require_permission("admin.security_audit")
async def get_user_activity_timeline(
    user_identifier: str,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(500, ge=1, le=50000),
    _user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get user activity timeline grouped by session."""
    service = get_compliance_report_service()
    try:
        return service.build_user_activity_timeline(
            user_identifier=user_identifier,
            db=db,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to build user activity timeline: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to build user activity timeline") from exc


@router.get("/evidence/export")
@require_permission("admin.security_audit")
async def export_evidence(
    dataset: str = Query(
        "audit_logs",
        description="Dataset to export (audit_logs, access_control, security_events, compliance_summary, encryption_status, user_activity)",
    ),
    format: str = Query("json", pattern="^(json|csv)$"),
    framework: Optional[List[str]] = Query(None, description="Frameworks used for compliance_summary dataset"),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(1000, ge=1, le=50000),
    user_identifier: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    success: Optional[bool] = Query(None, description="For audit_logs success filter; for security_events this maps to resolved"),
    severity: Optional[str] = Query(None),
    granted: Optional[bool] = Query(None),
    _user=Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
):
    """Export evidence datasets as JSON or CSV."""
    normalized_dataset = (dataset or "").strip().lower()
    if normalized_dataset not in SUPPORTED_EXPORT_DATASETS:
        raise HTTPException(
            status_code=400,
            detail=f"dataset must be one of: {', '.join(SUPPORTED_EXPORT_DATASETS)}",
        )

    service = get_compliance_report_service()
    try:
        rows = service.build_export_rows(
            dataset=normalized_dataset,
            db=db,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            user_identifier=user_identifier,
            action=action,
            resource_type=resource_type,
            success=success,
            severity=severity,
            granted=granted,
            frameworks=framework,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to export compliance evidence: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export compliance evidence") from exc

    if format == "json":
        return rows

    csv_payload = _rows_to_csv(rows)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{normalized_dataset}_{timestamp}.csv"
    return Response(
        content=csv_payload,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
