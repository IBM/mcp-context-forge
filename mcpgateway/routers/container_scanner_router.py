#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/container_scanner_router.py

Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

FastAPI Router for Container Scanner Results API.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# First-Party
from mcpgateway.auth import get_current_user

container_scanner_router = APIRouter(
    prefix="/container-scanner",
    tags=["Container Scanner"],
    dependencies=[Depends(get_current_user)],
)


class SummaryResponse(BaseModel):
    """CVE severity counts for a single scan result."""

    critical_count: int
    high_count: int
    medium_count: int
    low_count: int


class VulnerabilityResponse(BaseModel):
    """API representation of a single CVE finding."""

    cve_id: str
    severity: str
    package_name: str
    installed_version: str
    fixed_version: Optional[str]
    description: Optional[str]


class ScanResultResponse(BaseModel):
    """API representation of one container scan result."""

    image_ref: str
    image_digest: Optional[str]
    scanners: str
    scan_time: str
    duration_ms: int
    blocked: bool
    reason: Optional[str]
    scan_error: Optional[str]
    summary: SummaryResponse
    vulnerability_count: int
    vulnerabilities: List[VulnerabilityResponse]


def _to_response(result: Any) -> ScanResultResponse:
    """Convert a ScanResult domain object to the API response model."""
    scan_time = result.scan_time
    if hasattr(scan_time, "isoformat"):
        scan_time_str = scan_time.isoformat()
    else:
        scan_time_str = str(scan_time)

    return ScanResultResponse(
        image_ref=result.image_ref,
        image_digest=result.image_digest,
        scanners=result.scanners,
        scan_time=scan_time_str,
        duration_ms=result.duration_ms,
        blocked=result.blocked,
        reason=result.reason,
        scan_error=result.scan_error,
        summary=SummaryResponse(
            critical_count=result.summary.critical_count,
            high_count=result.summary.high_count,
            medium_count=result.summary.medium_count,
            low_count=result.summary.low_count,
        ),
        vulnerability_count=len(result.vulnerabilities),
        vulnerabilities=[
            VulnerabilityResponse(
                cve_id=v.cve_id,
                severity=v.severity,
                package_name=v.package_name,
                installed_version=v.installed_version,
                fixed_version=v.fixed_version,
                description=v.description,
            )
            for v in result.vulnerabilities
        ],
    )


@container_scanner_router.get("/scans", response_model=List[ScanResultResponse])
async def list_scans(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[ScanResultResponse]:
    """Return all recent container scan results, most recent first."""
    # First-Party
    from plugins.container_scanner.storage.repository import container_scan_repo  # pylint: disable=import-outside-toplevel

    return [_to_response(r) for r in container_scan_repo.list_recent()]


@container_scanner_router.get("/scans/{image_ref:path}", response_model=ScanResultResponse)
async def get_scan(
    image_ref: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> ScanResultResponse:
    """Return the scan result for a specific image reference or digest."""
    # First-Party
    from plugins.container_scanner.storage.repository import container_scan_repo  # pylint: disable=import-outside-toplevel

    result = container_scan_repo.get(image_ref)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No scan result found for '{image_ref}'")
    return _to_response(result)


@container_scanner_router.get("/health")
async def health(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return liveness status and current result count."""
    # First-Party
    from plugins.container_scanner.storage.repository import container_scan_repo  # pylint: disable=import-outside-toplevel

    return {"status": "ok", "count": len(container_scan_repo)}
