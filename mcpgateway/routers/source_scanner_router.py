#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/source_scanner_router.py

Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Arnav

FastAPI Router for Source Scanner Results API.
"""

# Future
from __future__ import annotations

# Standard
from typing import Annotated, Any, Dict, List, Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.db import get_db
from mcpgateway.services.logging_service import LoggingService
from plugins.source_scanner.storage.repository import ScanRepository

REPOSITORY_AVAILABLE = True


logger = LoggingService().get_logger(__name__)

source_scanner_router = APIRouter(
    prefix="/source-scanner",
    tags=["Source Scanner"],
    dependencies=[Depends(get_current_user)],
)


class FindingResponse(BaseModel):
    """Single finding response."""

    id: int
    scanner: str
    severity: str
    rule_id: str
    message: str
    file_path: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    code_snippet: Optional[str] = None
    help_url: Optional[str] = None

    class Config:
        from_attributes = True


class ScanSummaryResponse(BaseModel):
    """Scan summary statistics."""

    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0


class ScanResponse(BaseModel):
    """Scan record response."""

    id: int
    repo_url: str
    ref: Optional[str] = None
    commit_sha: Optional[str] = None
    languages: Optional[str] = None
    blocked: bool = False
    block_reason: Optional[str] = None
    summary: ScanSummaryResponse
    created_at: str

    class Config:
        from_attributes = True


class ScanWithFindingsResponse(ScanResponse):
    """Scan response with findings."""

    findings: Annotated[list[FindingResponse], Field(default_factory=list)]


@source_scanner_router.get("/scans/{scan_id}", response_model=ScanWithFindingsResponse)
async def get_scan(
    scan_id: int,
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Retrieve a scan record with all associated findings."""
    if not REPOSITORY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Repository not available")

    repository = ScanRepository(db)
    scan = repository.get_scan_by_id(scan_id)

    if not scan:
        logger.warning(f"Scan {scan_id} not found")
        raise HTTPException(status_code=404, detail=f"Scan {scan_id} not found")

    findings_response = [
        FindingResponse(
            id=f.id,
            scanner=f.scanner,
            severity=f.severity,
            rule_id=f.rule_id,
            message=f.message,
            file_path=f.file_path,
            line=f.line,
            column=f.column,
            code_snippet=f.code_snippet,
            help_url=f.help_url,
        )
        for f in scan.findings
    ]

    return ScanWithFindingsResponse(
        id=scan.id,
        repo_url=scan.repo_url,
        ref=scan.ref,
        commit_sha=scan.commit_sha,
        languages=scan.languages,
        blocked=scan.blocked,
        block_reason=scan.block_reason,
        summary=ScanSummaryResponse(
            error_count=int(scan.error_count),
            warning_count=int(scan.warning_count),
            info_count=int(scan.info_count),
        ),
        created_at=scan.created_at.isoformat(),
        findings=findings_response,
    )


@source_scanner_router.get("/scans/{scan_id}/findings", response_model=List[FindingResponse])
async def get_scan_findings(
    scan_id: int,
    severity: Optional[str] = Query(None, description="Filter by severity (ERROR|WARNING|INFO)"),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Retrieve findings for a scan with optional severity filtering."""
    if not REPOSITORY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Repository not available")

    if severity and severity not in ("ERROR", "WARNING", "INFO"):
        raise HTTPException(status_code=400, detail="Invalid severity")

    repository = ScanRepository(db)
    scan = repository.get_scan_by_id(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id} not found")

    findings = repository.get_findings_by_severity(scan_id, severity) if severity else repository.get_findings_for_scan(scan_id)

    return [
        FindingResponse(
            id=f.id,
            scanner=f.scanner,
            severity=f.severity,
            rule_id=f.rule_id,
            message=f.message,
            file_path=f.file_path,
            line=f.line,
            column=f.column,
            code_snippet=f.code_snippet,
            help_url=f.help_url,
        )
        for f in findings
    ]


@source_scanner_router.get("/latest/{repo_url:path}", response_model=ScanWithFindingsResponse)
async def get_latest_scan(
    repo_url: str,
    commit_sha: str = Query(..., description="Commit SHA to lookup"),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Retrieve the latest scan for a repository and commit SHA."""
    if not REPOSITORY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Repository not available")

    repository = ScanRepository(db)
    scan = repository.get_latest_scan_for_commit(repo_url, commit_sha)

    if not scan:
        logger.info(f"No scan found for repo={repo_url}, commit={commit_sha}")
        raise HTTPException(status_code=404, detail=f"No scan found for commit {commit_sha} in {repo_url}")

    findings_response = [
        FindingResponse(
            id=f.id,
            scanner=f.scanner,
            severity=f.severity,
            rule_id=f.rule_id,
            message=f.message,
            file_path=f.file_path,
            line=f.line,
            column=f.column,
            code_snippet=f.code_snippet,
            help_url=f.help_url,
        )
        for f in scan.findings
    ]

    return ScanWithFindingsResponse(
        id=scan.id,
        repo_url=scan.repo_url,
        ref=scan.ref,
        commit_sha=scan.commit_sha,
        languages=scan.languages,
        blocked=scan.blocked,
        block_reason=scan.block_reason,
        summary=ScanSummaryResponse(
            error_count=int(scan.error_count),
            warning_count=int(scan.warning_count),
            info_count=int(scan.info_count),
        ),
        created_at=scan.created_at.isoformat(),
        findings=findings_response,
    )


@source_scanner_router.get("/repos/{repo_url:path}/scans", response_model=List[ScanResponse])
async def list_repo_scans(
    repo_url: str,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Retrieve paginated list of scans for a repository."""
    if not REPOSITORY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Repository not available")

    repository = ScanRepository(db)
    scans = repository.get_scans_for_repo(repo_url, limit=limit, offset=offset)

    return [
        ScanResponse(
            id=scan.id,
            repo_url=scan.repo_url,
            ref=scan.ref,
            commit_sha=scan.commit_sha,
            languages=scan.languages,
            blocked=scan.blocked,
            block_reason=scan.block_reason,
            summary=ScanSummaryResponse(
                error_count=int(scan.error_count),
                warning_count=int(scan.warning_count),
                info_count=int(scan.info_count),
            ),
            created_at=scan.created_at.isoformat(),
        )
        for scan in scans
    ]


@source_scanner_router.get("/health")
async def health_check(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Verify Source Scanner API is operational."""
    return {"status": "ok", "repository_available": REPOSITORY_AVAILABLE}
