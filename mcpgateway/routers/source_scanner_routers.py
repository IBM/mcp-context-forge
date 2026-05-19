# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/source_scanner_routers.py

Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn
Source Code Security Scanner Router for ContextForge AI Gateway.

Provides API endpoints for viewing security scanner results and serving
HTMX partial templates for the Admin UI scanner dashboard tab.

Data flows through the existing plugin pipeline:
    BanditRunner / SemgrepRunner → Normalizer → Report → this router → UI
"""

# Standard
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

# First-Party
from mcpgateway.middleware.rbac import get_current_user_with_permissions as get_current_user

# Scanner plugin imports
from plugins.source_scanner.models import Finding
from plugins.source_scanner.report import Report

LOGGER = logging.getLogger(__name__)

source_scanner_router = APIRouter(prefix="/admin/scanner", tags=["Source Scanner"])


# ---------------------------------------------------------------------------
# In-memory cache of the latest scan data
# ---------------------------------------------------------------------------
_latest_report: Dict[str, Any] = {}


def _resolve_root_path(request: Request) -> str:
    """Resolve root path for URL generation."""
    return getattr(request.app.state, "root_path", "") or request.scope.get("root_path", "")


def _report_to_dict(report: Report, source: str = "scan") -> Dict[str, Any]:
    """Convert a Report into a JSON-serializable dict for the dashboard.

    Args:
        report: Report instance with findings.
        source: Label for how the data was generated.

    Returns:
        Dict with summary, ordered breakdown, and full findings list.
    """
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "summary": report.summary(),
        "ordered": report.ordered(),
        "findings": [f.model_dump() for f in report.findings],
    }


# ---------------------------------------------------------------------------
# API: Upload a pre-generated scan report (JSON)
# ---------------------------------------------------------------------------
@source_scanner_router.post("/upload", response_class=JSONResponse)
async def upload_scan_report(
    request: Request,
    user=Depends(get_current_user),
) -> JSONResponse:
    """Accept a raw scanner JSON report and normalize it into Finding objects.

    The request body should contain a 'findings' list of Finding-compatible
    dicts, OR a raw Bandit/Semgrep JSON output which will be passed through
    as-is if it already has the correct shape.

    Args:
        request: FastAPI request object.
        user: Authenticated user.

    Returns:
        JSONResponse with the normalized report data.
    """
    global _latest_report  # noqa: PLW0603
    body = await request.json()

    # Accept either {findings: [...]} or raw scanner output with {results: [...]}
    raw_findings = body.get("findings", [])

    if not raw_findings and "results" in body:
        # Likely raw Bandit JSON — map to Finding shape
        for r in body["results"]:
            severity_map = {"HIGH": "ERROR", "MEDIUM": "WARNING", "LOW": "INFO"}
            raw_findings.append(
                {
                    "scanner": "bandit",
                    "severity": severity_map.get(r.get("issue_severity", "LOW"), "INFO"),
                    "rule_id": r.get("test_id", "unknown"),
                    "message": r.get("issue_text", ""),
                    "file_path": r.get("filename"),
                    "line": r.get("line_number"),
                    "column": r.get("col_offset"),
                    "code_snippet": (r.get("code", "") or "").strip() or None,
                    "help_url": r.get("more_info"),
                }
            )

    if not raw_findings:
        raise HTTPException(status_code=400, detail='Invalid report: no "findings" or "results" found.')

    # Parse into Finding objects
    findings: List[Finding] = []
    for f in raw_findings:
        try:
            findings.append(Finding(**f))
        except Exception as e:
            LOGGER.warning("Skipping invalid finding: %s", e)

    # Build report
    report = Report(findings)
    _latest_report = _report_to_dict(report, source="uploaded")

    LOGGER.info(
        "User %s uploaded scanner report with %d findings",
        getattr(user, "email", "unknown"),
        len(findings),
    )
    return JSONResponse(content=_latest_report)


# ---------------------------------------------------------------------------
# API: Accept scan results from the plugin pipeline
# ---------------------------------------------------------------------------
@source_scanner_router.post("/ingest", response_class=JSONResponse)
async def ingest_scan_result(
    request: Request,
    user=Depends(get_current_user),
) -> JSONResponse:
    """Accept a ScanResult dict (from SourceScannerPlugin.scan()) and cache it.

    This endpoint is called after a scan completes through the plugin pipeline.
    The body should be the output of ScanResult.model_dump().

    Args:
        request: FastAPI request object.
        user: Authenticated user.

    Returns:
        JSONResponse with the processed report data.
    """
    global _latest_report  # noqa: PLW0603
    body = await request.json()

    raw_findings = body.get("findings", [])
    findings = []
    for f in raw_findings:
        try:
            findings.append(Finding(**f))
        except Exception as e:
            LOGGER.warning("Skipping invalid finding: %s", e)

    report = Report(findings)
    result = _report_to_dict(report, source=body.get("repo_url", "scan"))
    # Carry over extra metadata from ScanResult
    result["repo_url"] = body.get("repo_url")
    result["ref"] = body.get("ref")
    result["commit_sha"] = body.get("commit_sha")
    result["languages"] = body.get("languages", [])
    result["blocked"] = body.get("blocked", False)
    result["block_reason"] = body.get("block_reason")
    _latest_report = result

    LOGGER.info(
        "User %s ingested scan result with %d findings",
        getattr(user, "email", "unknown"),
        len(findings),
    )
    return JSONResponse(content=_latest_report)


# ---------------------------------------------------------------------------
# API: Get latest scan results
# ---------------------------------------------------------------------------
@source_scanner_router.get("/results", response_class=JSONResponse)
async def get_scan_results(
    _request: Request,
    _user=Depends(get_current_user),
) -> JSONResponse:
    """Return the latest cached scan results.

    Args:
        request: FastAPI request object.
        user: Authenticated user.

    Returns:
        JSONResponse with the latest report data, or 404 if none available.
    """
    if not _latest_report:
        raise HTTPException(status_code=404, detail="No scan results available. Run a scan or upload a report first.")
    return JSONResponse(content=_latest_report)


# ---------------------------------------------------------------------------
# HTMX: Scanner dashboard partial (loaded by admin.html tab)
# ---------------------------------------------------------------------------
@source_scanner_router.get("/partial", response_class=HTMLResponse)
async def scanner_partial_html(
    request: Request,
    _user=Depends(get_current_user),
) -> HTMLResponse:
    """Return the scanner dashboard HTML partial for HTMX injection.

    This is the entry-point called when the user clicks the Security Scanner
    tab in the Admin UI sidebar.

    Args:
        request: FastAPI request object.
        user: Authenticated user.

    Returns:
        HTMLResponse rendered from scanner_partial.html.
    """
    root_path = _resolve_root_path(request)
    return request.app.state.templates.TemplateResponse(
        request,
        "scanner_partial.html",
        {
            "request": request,
            "root_path": root_path,
            "has_results": bool(_latest_report),
            "scan_data_json": json.dumps(_latest_report) if _latest_report else "null",
        },
    )
