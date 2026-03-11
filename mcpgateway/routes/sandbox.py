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
import re
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse

# First-Party
from mcpgateway.auth import get_current_user

# Local
from ..schemas import (
    BatchSimulateRequest,
    BatchSimulationResult,
    RegressionReport,
    RegressionTestRequest,
    TestSuite,
)
from ..services.sandbox_service import get_sandbox_service, SandboxService

logger = logging.getLogger(__name__)

# Service version constant - used in health check and info endpoints
SANDBOX_SERVICE_VERSION = "1.0.0"
SANDBOX_SERVICE_NAME = "Policy Testing Sandbox"

# Create router with prefix and tags
router = APIRouter(
    prefix="",
    tags=["Policy Sandbox"],
    responses={
        404: {"description": "Policy draft or test suite not found"},
        500: {"description": "Internal server error during simulation"},
    },
)


# ---------------------------------------------------------------------------
# Core Simulation Endpoints
# ---------------------------------------------------------------------------


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
    current_user=Depends(get_current_user),
) -> BatchSimulationResult:
    """Execute multiple test cases in batch.

    Args:
        request: Batch simulation request with test cases
        sandbox: Injected sandbox service
        current_user: Authenticated user from JWT dependency

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
    current_user=Depends(get_current_user),
) -> RegressionReport:
    """Run regression tests against historical decisions.

    Args:
        request: Regression test request with parameters
        sandbox: Injected sandbox service
        current_user: Authenticated user from JWT dependency

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
    sandbox: SandboxService = Depends(get_sandbox_service),
    current_user=Depends(get_current_user),
) -> TestSuite:
    """Create a new test suite.

    Args:
        test_suite: Test suite to create
        sandbox: Injected sandbox service
        current_user: Authenticated user

    Returns:
        Created test suite with generated ID

    Raises:
        HTTPException: 500 on database error
    """
    logger.info("Creating test suite: %s", test_suite.name)

    try:
        created_by = getattr(current_user, "email", None) or getattr(current_user, "username", "unknown")
        return sandbox.create_test_suite(test_suite, created_by=created_by)

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
    sandbox: SandboxService = Depends(get_sandbox_service),
    current_user=Depends(get_current_user),
) -> TestSuite:
    """Get a test suite by ID.

    Args:
        suite_id: Test suite ID
        sandbox: Injected sandbox service
        current_user: Authenticated user

    Returns:
        Test suite

    Raises:
        HTTPException: 404 if suite not found
    """
    logger.info("Fetching test suite: %s", suite_id)

    try:
        suite = sandbox.get_test_suite(suite_id)
        if not suite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Test suite not found: {suite_id}",
            )
        return suite

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
    sandbox: SandboxService = Depends(get_sandbox_service),
    current_user=Depends(get_current_user),
) -> list[TestSuite]:
    """List all test suites.

    Args:
        tags: Comma-separated tags to filter by
        sandbox: Injected sandbox service
        current_user: Authenticated user

    Returns:
        List of test suites

    Raises:
        HTTPException: 500 on database error
    """
    logger.info("Listing test suites, tags=%s", tags)

    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        return sandbox.list_test_suites(tags=tag_list)

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
    """Liveness health check endpoint.

    This is a liveness-only probe: it verifies the sandbox service is
    responsive. It does not perform deep dependency checks (e.g. database
    connectivity or PDP engine availability).

    Returns:
        Health status dictionary
    """
    return {
        "status": "healthy",
        "service": "sandbox",
        "version": SANDBOX_SERVICE_VERSION,
        "check_type": "liveness",
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
        "name": SANDBOX_SERVICE_NAME,
        "version": SANDBOX_SERVICE_VERSION,
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


@router.post("/simulate", response_class=HTMLResponse)
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

    Args:
        request: The incoming HTTP request
        policy_draft_id: ID of the policy draft to test
        subject_email: Email of the subject being tested
        subject_roles: Comma-separated roles for the subject
        subject_team_id: Optional team ID for the subject
        action: The action being tested (e.g. 'tools.invoke')
        resource_type: Type of resource (e.g. 'tool', 'prompt')
        resource_id: ID of the resource being accessed
        resource_server: Optional server hosting the resource
        expected_decision: Expected outcome ('allow' or 'deny')
        sandbox: Injected sandbox service
        current_user: Authenticated user from JWT dependency

    Returns:
        TemplateResponse with simulation results or error HTML

    Raises:
        HTTPException: Re-raised if caught during processing
    """
    try:
        # Validate and sanitize form inputs
        _validate_sandbox_form_input(policy_draft_id, "policy_draft_id")
        _validate_sandbox_form_input(subject_email, "subject_email")
        _validate_sandbox_form_input(action, "action")
        _validate_sandbox_form_input(resource_type, "resource_type")
        _validate_sandbox_form_input(resource_id, "resource_id")
        _validate_sandbox_form_input(expected_decision, "expected_decision")
        if subject_team_id:
            _validate_sandbox_form_input(subject_team_id, "subject_team_id")
        if resource_server:
            _validate_sandbox_form_input(resource_server, "resource_server")

        # Parse and validate roles (comma-separated)
        roles = [r.strip() for r in subject_roles.split(",") if r.strip()]
        for role in roles:
            _validate_sandbox_form_input(role, "role")

        # Create test case from form data
        # First-Party
        from mcpgateway.schemas import TestCase
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

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error running simulation")
        return request.app.state.templates.TemplateResponse(request, "sandbox_simulate_error.html", {"error_message": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Input Validation Helpers
# ---------------------------------------------------------------------------

# Regex pattern for allowed sandbox form input characters:
# alphanumeric, hyphens, underscores, dots, @, literal spaces (not \s to exclude \n, \r, \t)
_SANDBOX_INPUT_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.@ ]+$")
_SANDBOX_INPUT_MAX_LENGTH = 256


def _validate_sandbox_form_input(value: str, field_name: str) -> None:
    """Validate and sanitize a sandbox form input value.

    Ensures the value is non-empty, within length limits, and contains
    only safe characters to prevent injection attacks.

    Args:
        value: The input string to validate
        field_name: Name of the field (for error messages)

    Raises:
        HTTPException: 422 if validation fails
    """
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Field '{field_name}' must not be empty",
        )

    if len(value) > _SANDBOX_INPUT_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Field '{field_name}' exceeds maximum length of {_SANDBOX_INPUT_MAX_LENGTH}",
        )

    if not _SANDBOX_INPUT_PATTERN.match(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Field '{field_name}' contains invalid characters. Only alphanumeric, hyphens, underscores, dots, @, and spaces are allowed.",
        )
