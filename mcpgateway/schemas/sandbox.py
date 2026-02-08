#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pydantic models for the Policy Testing and Simulation Sandbox.
Location: ./mcpgateway/schemas/sandbox.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: "Hugh Hennelly"

This module defines all data structures needed for testing policies before
deployment, running regression tests, and simulating policy decisions in
an isolated environment.

Related to Issue #2226: Policy testing and simulation sandbox
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

# Third-Party
from pydantic import BaseModel, Field

# Local
# Import existing PDP models
from ..plugins.unified_pdp.pdp_models import (
    AccessDecision,
    Context,
    Decision,
    DecisionExplanation,
    Resource,
    Subject,
)

# ---------------------------------------------------------------------------
# Test Case Models
# ---------------------------------------------------------------------------


class TestCase(BaseModel):
    """Single test case for policy simulation.

    Represents one access request that should be evaluated against a policy
    draft. Contains the request parameters (subject, action, resource, context)
    and the expected outcome for assertion.

    Example:
        >>> test_case = TestCase(
        ...     subject=Subject(email="dev@example.com", roles=["developer"]),
        ...     action="tools.invoke",
        ...     resource=Resource(type="tool", id="db-query"),
        ...     expected_decision=Decision.ALLOW,
        ...     description="Developers should access db-query tool"
        ... )
    """

    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique test case identifier")
    subject: Subject = Field(..., description="The entity requesting access")
    action: str = Field(..., description="The action being performed (e.g., 'tools.invoke', 'resources.read')")
    resource: Resource = Field(..., description="The resource being accessed")
    context: Optional[Context] = Field(default_factory=Context, description="Request context")
    expected_decision: Decision = Field(..., description="Expected decision: ALLOW or DENY")
    description: Optional[str] = Field(None, description="Human-readable description of what this test verifies")
    tags: List[str] = Field(default_factory=list, description="Tags for organizing tests (e.g., ['regression', 'rbac'])")

    class Config:
        json_schema_extra = {
            "example": {
                "subject": {"email": "developer@example.com", "roles": ["developer"], "team_id": "engineering"},
                "action": "tools.invoke",
                "resource": {"type": "tool", "id": "db-query", "server": "postgres-prod"},
                "context": {"ip": "192.168.1.100", "timestamp": "2024-01-15T10:30:00Z"},
                "expected_decision": "allow",
                "description": "Developers can query production database during business hours",
                "tags": ["rbac", "production"],
            }
        }


class TestSuite(BaseModel):
    """Collection of related test cases.

    Groups test cases together for organized testing. Can represent:
    - Regression tests for a specific feature
    - Compliance tests for a regulation (GDPR, SOC2)
    - Role-based access patterns

    Example:
        >>> suite = TestSuite(
        ...     name="production-access-patterns",
        ...     description="Tests for production system access",
        ...     test_cases=[test_case1, test_case2, test_case3]
        ... )
    """

    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique test suite identifier")
    name: str = Field(..., description="Name of the test suite (e.g., 'production-access-patterns')")
    description: Optional[str] = Field(None, description="Purpose and scope of this test suite")
    test_cases: List[TestCase] = Field(..., description="Test cases in this suite")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_schema_extra = {"example": {"name": "developer-rbac-tests", "description": "Role-based access control tests for developer role", "test_cases": [], "tags": ["rbac", "developers"]}}


# ---------------------------------------------------------------------------
# Simulation Result Models
# ---------------------------------------------------------------------------


class SimulationResult(BaseModel):
    """Result from simulating a single test case.

    Contains the actual decision from policy evaluation, comparison with
    expected decision, timing information, and detailed explanation.

    Attributes:
        test_case_id: ID of the test case that was simulated
        actual_decision: What the policy engine decided
        expected_decision: What the test case expected
        passed: True if actual matches expected
        execution_time_ms: How long the evaluation took
        explanation: Detailed breakdown of why the decision was made
        policy_draft_id: Which policy draft was evaluated
    """

    test_case_id: str = Field(..., description="ID of the test case that was simulated")
    actual_decision: Decision = Field(..., description="Actual decision from policy evaluation")
    expected_decision: Decision = Field(..., description="Expected decision from test case")
    passed: bool = Field(..., description="Whether actual matches expected")
    execution_time_ms: float = Field(..., description="Policy evaluation duration in milliseconds")
    explanation: Optional[DecisionExplanation] = Field(None, description="Detailed decision explanation")
    policy_draft_id: str = Field(..., description="ID of the policy draft that was evaluated")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Additional metadata for debugging
    access_decision: Optional[AccessDecision] = Field(None, description="Full AccessDecision object from PDP")
    matching_policies: List[str] = Field(default_factory=list, description="Policy IDs that matched")
    reason: str = Field(default="", description="Human-readable reason for the decision")

    class Config:
        json_schema_extra = {
            "example": {
                "test_case_id": "tc-12345",
                "actual_decision": "allow",
                "expected_decision": "allow",
                "passed": True,
                "execution_time_ms": 45.2,
                "policy_draft_id": "draft-123",
                "reason": "[all_must_allow] All engines allowed",
            }
        }


class BatchSimulationResult(BaseModel):
    """Results from executing multiple test cases in batch.

    Aggregates results from running an entire test suite or list of test cases.
    Provides summary statistics and individual results.

    Example:
        >>> batch_result = BatchSimulationResult(
        ...     policy_draft_id="draft-123",
        ...     total_tests=50,
        ...     passed=48,
        ...     failed=2,
        ...     results=[result1, result2, ...]
        ... )
    """

    batch_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique batch execution identifier")
    policy_draft_id: str = Field(..., description="Policy draft that was tested")
    test_suite_id: Optional[str] = Field(None, description="Test suite ID if applicable")

    # Summary statistics
    total_tests: int = Field(..., description="Total number of test cases executed")
    passed: int = Field(..., description="Number of tests that passed")
    failed: int = Field(..., description="Number of tests that failed")
    pass_rate: float = Field(..., description="Percentage of tests that passed (0-100)")
    total_duration_ms: float = Field(..., description="Total execution time for all tests")
    avg_duration_ms: float = Field(..., description="Average execution time per test")

    # Detailed results
    results: List[SimulationResult] = Field(..., description="Individual test results")

    # Execution metadata
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_schema_extra = {
            "example": {
                "policy_draft_id": "draft-123",
                "test_suite_id": "suite-456",
                "total_tests": 50,
                "passed": 48,
                "failed": 2,
                "pass_rate": 96.0,
                "total_duration_ms": 2500.0,
                "avg_duration_ms": 50.0,
                "results": [],
            }
        }


# ---------------------------------------------------------------------------
# Regression Testing Models
# ---------------------------------------------------------------------------


class HistoricalDecision(BaseModel):
    """Recorded production decision for regression testing.

    Captures a real policy decision from production that can be replayed
    against new policy drafts to ensure behavioral consistency.

    Use case: Before deploying a policy change, replay last 7 days of
    production access patterns to verify no unintended changes in behavior.
    """

    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique record identifier")
    subject: Subject = Field(..., description="Subject that made the request")
    action: str = Field(..., description="Action that was requested")
    resource: Resource = Field(..., description="Resource that was accessed")
    context: Context = Field(..., description="Request context")

    # Original decision
    decision: Decision = Field(..., description="The decision that was made")
    reason: str = Field(default="", description="Reason for the decision")
    matching_policies: List[str] = Field(default_factory=list, description="Policies that matched")

    # Metadata
    policy_version: str = Field(..., description="Policy version/ID that made this decision")
    timestamp: datetime = Field(..., description="When this decision was made")
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionComparison(BaseModel):
    """Comparison between historical and simulated decisions.

    Used in regression testing to identify where a new policy draft
    produces different outcomes than the production policy.

    Attributes:
        historical: The original production decision
        simulated: The new decision from policy draft
        is_regression: True if decisions differ (potential regression)
        severity: How critical the difference is
    """

    historical_id: str = Field(..., description="ID of the historical decision")
    historical_decision: Decision = Field(..., description="Original production decision")
    simulated_decision: Decision = Field(..., description="New decision from policy draft")
    is_regression: bool = Field(..., description="True if decisions differ")

    # Context
    subject_email: str = Field(..., description="Subject email for quick identification")
    action: str = Field(..., description="Action that was evaluated")
    resource_type: str = Field(..., description="Type of resource accessed")
    resource_id: str = Field(..., description="ID of resource accessed")

    # Analysis
    severity: str = Field(..., description="Impact level: 'critical', 'high', 'medium', 'low'")
    impact_description: str = Field(..., description="Human-readable impact description")

    # Detailed comparison
    historical_reason: str = Field(default="", description="Reason from historical decision")
    simulated_reason: str = Field(default="", description="Reason from simulated decision")
    policy_changes: List[str] = Field(default_factory=list, description="Policies that changed behavior")

    class Config:
        json_schema_extra = {
            "example": {
                "historical_id": "hist-789",
                "historical_decision": "allow",
                "simulated_decision": "deny",
                "is_regression": True,
                "subject_email": "contractor@example.com",
                "action": "tools.invoke",
                "resource_type": "tool",
                "resource_id": "db-query",
                "severity": "high",
                "impact_description": "Contractor will lose database access",
            }
        }


class RegressionReport(BaseModel):
    """Comprehensive report from regression testing.

    Compares a policy draft against historical production decisions to
    identify regressions (unintended behavior changes).

    Generated when running: POST /sandbox/regression

    Example workflow:
        1. Fetch last 7 days of production decisions (1000 requests)
        2. Replay each against policy draft
        3. Compare new vs old decisions
        4. Generate this report highlighting differences
    """

    report_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique report identifier")
    policy_draft_id: str = Field(..., description="Policy draft that was tested")
    baseline_policy_version: str = Field(..., description="Production policy version for comparison")

    # Summary statistics
    total_decisions: int = Field(..., description="Total historical decisions replayed")
    matching_decisions: int = Field(..., description="Decisions that stayed the same")
    different_decisions: int = Field(..., description="Decisions that changed")
    regression_rate: float = Field(..., description="Percentage of decisions that changed (0-100)")

    # Regression breakdown by severity
    critical_regressions: int = Field(default=0, description="Count of critical impact changes")
    high_regressions: int = Field(default=0, description="Count of high impact changes")
    medium_regressions: int = Field(default=0, description="Count of medium impact changes")
    low_regressions: int = Field(default=0, description="Count of low impact changes")

    # Detailed comparisons
    comparisons: List[DecisionComparison] = Field(default_factory=list, description="Individual decision comparisons")
    regressions_only: List[DecisionComparison] = Field(default_factory=list, description="Only the regressions for quick review")

    # Execution metadata
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = Field(..., description="Total regression test execution time")

    class Config:
        json_schema_extra = {
            "example": {
                "policy_draft_id": "draft-123",
                "baseline_policy_version": "prod-v2.1",
                "total_decisions": 1000,
                "matching_decisions": 985,
                "different_decisions": 15,
                "regression_rate": 1.5,
                "critical_regressions": 2,
                "high_regressions": 5,
                "medium_regressions": 8,
                "low_regressions": 0,
                "duration_ms": 45000.0,
            }
        }


# ---------------------------------------------------------------------------
# API Request/Response Models
# ---------------------------------------------------------------------------


class SimulateRequest(BaseModel):
    """Request body for POST /sandbox/simulate endpoint.

    Example:
        POST /sandbox/simulate
        {
            "policy_draft_id": "draft-123",
            "test_case": { ... },
            "include_explanation": true
        }
    """

    policy_draft_id: str = Field(..., description="ID of the policy draft to test")
    test_case: TestCase = Field(..., description="Test case to simulate")
    include_explanation: bool = Field(default=True, description="Whether to include detailed explanation")


class BatchSimulateRequest(BaseModel):
    """Request body for POST /sandbox/batch endpoint.

    Example:
        POST /sandbox/batch
        {
            "policy_draft_id": "draft-123",
            "test_cases": [tc1, tc2, tc3]
        }
    """

    policy_draft_id: str = Field(..., description="ID of the policy draft to test")
    test_cases: List[TestCase] = Field(..., description="List of test cases to execute")
    test_suite_id: Optional[str] = Field(None, description="Test suite ID if using saved suite")
    parallel_execution: bool = Field(default=True, description="Whether to run tests in parallel")


class RegressionTestRequest(BaseModel):
    """Request body for POST /sandbox/regression endpoint.

    Example:
        POST /sandbox/regression
        {
            "policy_draft_id": "draft-123",
            "replay_last_days": 7,
            "sample_size": 1000
        }
    """

    policy_draft_id: str = Field(..., description="ID of the policy draft to test")
    baseline_policy_version: Optional[str] = Field(None, description="Production policy version to compare against")
    replay_last_days: int = Field(default=7, description="How many days of history to replay")
    sample_size: Optional[int] = Field(default=1000, description="Maximum number of decisions to replay")
    filter_by_subject: Optional[str] = Field(None, description="Only replay decisions for specific subject")
    filter_by_action: Optional[str] = Field(None, description="Only replay specific action types")
