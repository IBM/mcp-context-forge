#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API routes for Policy Testing and Simulation Sandbox.
Location: ./mcpgateway/routes/sandbox.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: "Hugh Hennelly"

This module provides REST API endpoints for testing policy drafts before
deployment. It exposes the SandboxService functionality via HTTP endpoints.

Related to Issue #2226: Policy testing and simulation sandbox
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user

# Local
from ..db import get_db
from ..schemas import (
    BatchSimulateRequest,
    BatchSimulationResult,
    RegressionReport,
    RegressionTestRequest,
    TestSuite,
)
from ..services.sandbox_service import get_sandbox_service, SandboxService

logger = logging.getLogger(__name__)

# Create router with prefix and tags
router = APIRouter(
    prefix="/sandbox",
    tags=["Policy Sandbox"],
    responses={
        404: {"description": "Policy draft or test suite not found"},
        500: {"description": "Internal server error during simulation"},
    },
)


# ---------------------------------------------------------------------------
# Core Simulation Endpoints
# ---------------------------------------------------------------------------

#
# @router.post(
#     "/simulate",
#     response_model=SimulationResult,
#     status_code=status.HTTP_200_OK,
#     summary="Simulate single test case",
#     description="""
#     Simulate a single test case against a policy draft.
#
#     This endpoint creates an isolated PDP instance with the draft policy,
#     evaluates the test case, and returns detailed results including whether
#     the test passed and a full explanation of the decision.
#
#     **Use case**: Test a specific access scenario before deploying a policy change.
#
#     **Example**:
#     ```json
#     {
#         "policy_draft_id": "draft-123",
#         "test_case": {
#             "subject": {"email": "dev@example.com", "roles": ["developer"]},
#             "action": "tools.invoke",
#             "resource": {"type": "tool", "id": "db-query"},
#             "expected_decision": "allow"
#         },
#         "include_explanation": true
#     }
#     ```
#     """,
# )
# async def simulate_single_request(
#     request: SimulateRequest,
#     sandbox: SandboxService = Depends(get_sandbox_service),
# ) -> SimulationResult:
#     """Simulate a single test case against a policy draft.
#
#     Args:
#         request: Simulation request containing policy draft ID and test case
#         sandbox: Injected sandbox service
#
#     Returns:
#         SimulationResult with actual vs expected decision, timing, and explanation
#
#     Raises:
#         HTTPException: 404 if policy draft not found, 500 on evaluation error
#     """
#     logger.info(
#         "Simulating single test case against policy draft %s",
#         request.policy_draft_id,
#     )
#
#     try:
#         result = await sandbox.simulate_single(
#             policy_draft_id=request.policy_draft_id,
#             test_case=request.test_case,
#             include_explanation=request.include_explanation,
#         )
#
#         logger.info(
#             "Simulation complete: test_case=%s, passed=%s, duration=%.1fms",
#             result.test_case_id,
#             result.passed,
#             result.execution_time_ms,
#         )
#
#         return result
#
#     except ValueError as e:
#         logger.error("Policy draft not found: %s", e)
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Policy draft not found: {request.policy_draft_id}",
#         ) from e
#
#     except Exception as e:
#         logger.error("Simulation failed: %s", e, exc_info=True)
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Simulation failed: {str(e)}",
#         ) from e
#


@router.post(
    "/batch",
    response_model=BatchSimulationResult,
    status_code=status.HTTP_200_OK,
    summary="Execute batch test cases",
    description="""
    Execute multiple test cases in batch against a policy draft.
    
    Tests can be executed in parallel (faster) or sequentially (deterministic).
    Returns aggregated statistics and individual results.
    
    **Use case**: Run a full test suite before deploying a policy change.
    
    **Example**:
    ```json
    {
        "policy_draft_id": "draft-123",
        "test_cases": [
            {"subject": {...}, "action": "...", "resource": {...}, "expected_decision": "allow"},
            {"subject": {...}, "action": "...", "resource": {...}, "expected_decision": "deny"}
        ],
        "parallel_execution": true
    }
    ```
    """,
)
async def run_batch_tests(
    request: BatchSimulateRequest,
    sandbox: SandboxService = Depends(get_sandbox_service),
) -> BatchSimulationResult:
    """Execute multiple test cases in batch.

    Args:
        request: Batch simulation request with test cases
        sandbox: Injected sandbox service

    Returns:
        BatchSimulationResult with summary statistics and individual results

    Raises:
        HTTPException: 404 if policy draft not found, 500 on evaluation error
    """
    logger.info(
        "Running batch simulation: %d test cases against policy draft %s",
        len(request.test_cases),
        request.policy_draft_id,
    )

    try:
        result = await sandbox.run_batch(
            policy_draft_id=request.policy_draft_id,
            test_cases=request.test_cases,
            test_suite_id=request.test_suite_id,
            parallel_execution=request.parallel_execution,
        )

        logger.info(
            "Batch complete: %d/%d passed (%.1f%%), %.1fms total",
            result.passed,
            result.total_tests,
            result.pass_rate,
            result.total_duration_ms,
        )

        return result

    except ValueError as e:
        logger.error("Policy draft not found: %s", e)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy draft not found: {request.policy_draft_id}",
        ) from e

    except Exception as e:
        logger.error("Batch simulation failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch simulation failed: {str(e)}",
        ) from e


@router.post(
    "/regression",
    response_model=RegressionReport,
    status_code=status.HTTP_200_OK,
    summary="Run regression tests",
    description="""
    Run regression tests by replaying historical production decisions.
    
    Fetches historical decisions from audit logs and replays them against
    the policy draft to identify regressions (unintended behavior changes).
    
    **Use case**: Verify a policy change doesn't break existing access patterns.
    
    **Example**:
    ```json
    {
        "policy_draft_id": "draft-123",
        "baseline_policy_version": "prod-v2.1",
        "replay_last_days": 7,
        "sample_size": 1000
    }
    ```
    
    Returns a report with:
    - Total decisions replayed
    - Number of regressions found
    - Regression breakdown by severity (critical, high, medium, low)
    - Detailed comparison for each regression
    """,
)
async def run_regression_tests(
    request: RegressionTestRequest,
    sandbox: SandboxService = Depends(get_sandbox_service),
) -> RegressionReport:
    """Run regression tests against historical decisions.

    Args:
        request: Regression test request with parameters
        sandbox: Injected sandbox service

    Returns:
        RegressionReport with comparisons and regression analysis

    Raises:
        HTTPException: 404 if policy not found, 500 on evaluation error
    """
    logger.info(
        "Running regression test: policy_draft=%s, baseline=%s, days=%d",
        request.policy_draft_id,
        request.baseline_policy_version,
        request.replay_last_days,
    )

    try:
        report = await sandbox.run_regression(
            policy_draft_id=request.policy_draft_id,
            baseline_policy_version=request.baseline_policy_version or "production",
            replay_last_days=request.replay_last_days,
            sample_size=request.sample_size or 1000,
            filter_by_subject=request.filter_by_subject,
            filter_by_action=request.filter_by_action,
        )

        logger.info(
            "Regression test complete: %d regressions (%.1f%%), critical=%d, high=%d",
            report.different_decisions,
            report.regression_rate,
            report.critical_regressions,
            report.high_regressions,
        )

        return report

    except ValueError as e:
        logger.error("Policy or baseline not found: %s", e)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy not found: {str(e)}",
        ) from e

    except Exception as e:
        logger.error("Regression test failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Regression test failed: {str(e)}",
        ) from e


# ---------------------------------------------------------------------------
# Test Suite Management Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/suites",
    response_model=TestSuite,
    status_code=status.HTTP_201_CREATED,
    summary="Create test suite",
    description="""
    Create a new test suite with a collection of test cases.
    
    Test suites allow organizing related test cases together for reuse.
    
    **Example**:
    ```json
    {
        "name": "developer-rbac-tests",
        "description": "RBAC tests for developer role",
        "test_cases": [...],
        "tags": ["rbac", "developers"]
    }
    ```
    """,
)
async def create_test_suite(
    test_suite: TestSuite,
    db: Session = Depends(get_db),
) -> TestSuite:
    """Create a new test suite.

    Args:
        test_suite: Test suite to create
        db: Database session

    Returns:
        Created test suite with generated ID

    Raises:
        HTTPException: 500 on database error
    """
    logger.info("Creating test suite: %s", test_suite.name)

    try:
        # TODO: Implement database storage
        # For now, just return the test suite with generated ID
        logger.warning("Test suite storage not implemented - returning input")
        return test_suite

    except Exception as e:
        logger.error("Failed to create test suite: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create test suite: {str(e)}",
        ) from e


@router.get(
    "/suites/{suite_id}",
    response_model=TestSuite,
    status_code=status.HTTP_200_OK,
    summary="Get test suite",
    description="Retrieve a test suite by ID.",
)
async def get_test_suite(
    suite_id: str,
    db: Session = Depends(get_db),
) -> TestSuite:
    """Get a test suite by ID.

    Args:
        suite_id: Test suite ID
        db: Database session

    Returns:
        Test suite

    Raises:
        HTTPException: 404 if suite not found
    """
    logger.info("Fetching test suite: %s", suite_id)

    try:
        # TODO: Implement database query
        logger.warning("Test suite retrieval not implemented")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test suite not found: {suite_id}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch test suite: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch test suite: {str(e)}",
        ) from e


@router.get(
    "/suites",
    response_model=list[TestSuite],
    status_code=status.HTTP_200_OK,
    summary="List test suites",
    description="List all test suites with optional filtering by tags.",
)
async def list_test_suites(
    tags: Optional[str] = None,
    db: Session = Depends(get_db),
) -> list[TestSuite]:
    """List all test suites.

    Args:
        tags: Comma-separated tags to filter by
        db: Database session

    Returns:
        List of test suites

    Raises:
        HTTPException: 500 on database error
    """
    logger.info("Listing test suites, tags=%s", tags)

    try:
        # TODO: Implement database query
        logger.warning("Test suite listing not implemented")
        return []

    except Exception as e:
        logger.error("Failed to list test suites: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list test suites: {str(e)}",
        ) from e


# ---------------------------------------------------------------------------
# Health & Status Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Sandbox health check",
    description="Check if the sandbox service is operational.",
)
async def health_check() -> dict:
    """Health check endpoint.

    Returns:
        Health status dictionary
    """
    return {
        "status": "healthy",
        "service": "sandbox",
        "version": "1.0.0",
    }


@router.get(
    "/info",
    status_code=status.HTTP_200_OK,
    summary="Sandbox service information",
    description="Get information about sandbox capabilities and configuration.",
)
async def service_info() -> dict:
    """Service information endpoint.

    Returns:
        Service information dictionary
    """
    return {
        "name": "Policy Testing Sandbox",
        "version": "1.0.0",
        "capabilities": [
            "single_simulation",
            "batch_simulation",
            "regression_testing",
            "test_suite_management",
        ],
        "features": {
            "parallel_execution": True,
            "decision_explanation": True,
            "regression_severity": True,
            "historical_replay": True,
        },
    }


# Add this to mcpgateway/routes/sandbox.py
# Place after the existing POST /sandbox/simulate endpoint


@router.post("/sandbox/simulate", response_class=HTMLResponse)
async def simulate_form_submit(
    request: Request,
    current_user=Depends(get_current_user),
    policy_draft_id: str = Form(...),
    subject_email: str = Form(...),
    subject_roles: str = Form(...),
    subject_team_id: str = Form(None),
    action: str = Form(...),
    resource_type: str = Form(...),
    resource_id: str = Form(...),
    resource_server: str = Form(None),
    expected_decision: str = Form(...),
    sandbox: SandboxService = Depends(get_sandbox_service),
):
    """Handle simulation form submission and return HTML results.

    This endpoint is called via HTMX when the simulation form is submitted.
    It returns HTML that will be injected into the results container.
    """
    try:
        # Parse roles (comma-separated)
        roles = [r.strip() for r in subject_roles.split(",") if r.strip()]

        # Create test case from form data
        # First-Party
        from mcpgateway.schemas.sandbox import TestCase
        from plugins.unified_pdp.pdp_models import Context, Decision, Resource, Subject

        test_case = TestCase(
            subject=Subject(
                email=subject_email,
                roles=roles,
                team_id=subject_team_id or None,
            ),
            action=action,
            resource=Resource(
                type=resource_type,
                id=resource_id,
                server=resource_server or None,
            ),
            context=Context(),
            expected_decision=Decision.ALLOW if expected_decision.lower() == "allow" else Decision.DENY,
            description=f"Test {action} on {resource_type} {resource_id}",
        )

        # Run simulation
        result = await sandbox.simulate_single(
            policy_draft_id=policy_draft_id,
            test_case=test_case,
            include_explanation=True,
        )

        # Render template response with auto-escaping
        return request.app.state.templates.TemplateResponse(request, "sandbox_simulate_results.html", {"result": result})

    except Exception as e:
        logger.exception("Error running simulation")
        return request.app.state.templates.TemplateResponse(request, "sandbox_simulate_error.html", {"error_message": str(e)}, status_code=500)
