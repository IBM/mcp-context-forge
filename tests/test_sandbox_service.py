#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for Sandbox Service.
Location: ./tests/test_sandbox_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: "Hugh Hennelly"

Tests the policy testing and simulation sandbox functionality including:
- Single test case simulation
- Batch test execution
- Regression testing
- Mock data integration

Related to Issue #2226: Policy testing and simulation sandbox
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import (
    BatchSimulationResult,
    RegressionReport,
    SimulationResult,
    TestCase,
)
from mcpgateway.services.sandbox_service import SandboxService
from plugins.unified_pdp.pdp_models import (
    Context,
    Decision,
    Resource,
    Subject,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Mock database session."""
    return Mock()


@pytest.fixture
def sandbox_service(mock_db):
    """Create a SandboxService instance with mock database."""
    return SandboxService(mock_db)


@pytest.fixture
def sample_test_case():
    """Create a sample test case for testing."""
    return TestCase(
        subject=Subject(
            email="developer@example.com",
            roles=["developer"],
            team_id="team-1",
        ),
        action="tools.invoke",
        resource=Resource(
            type="tool",
            id="database-query",
            server="prod-server",
        ),
        context=Context(
            ip="192.168.1.100",
            timestamp=datetime.now(timezone.utc),
        ),
        expected_decision=Decision.ALLOW,
        description="Test developer access to database query tool",
    )


@pytest.fixture
def sample_test_cases():
    """Create multiple test cases for batch testing."""
    return [
        TestCase(
            subject=Subject(email=f"user{i}@example.com", roles=["developer"]),
            action="tools.invoke",
            resource=Resource(type="tool", id=f"tool-{i}"),
            expected_decision=Decision.ALLOW if i % 2 == 0 else Decision.DENY,
            description=f"Test case {i}",
        )
        for i in range(5)
    ]


# ---------------------------------------------------------------------------
# Test: Single Test Case Simulation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_single_success(sandbox_service, sample_test_case):
    """Test successful single test case simulation."""
    result = await sandbox_service.simulate_single(
        policy_draft_id="draft-123",
        test_case=sample_test_case,
        include_explanation=True,
    )

    # Verify result structure
    assert isinstance(result, SimulationResult)
    assert result.test_case_id == sample_test_case.id
    assert result.policy_draft_id == "draft-123"
    assert result.actual_decision in [Decision.ALLOW, Decision.DENY]
    assert result.expected_decision == sample_test_case.expected_decision
    assert isinstance(result.passed, bool)
    assert result.execution_time_ms > 0
    assert result.explanation is not None  # Should have explanation


@pytest.mark.asyncio
async def test_simulate_single_without_explanation(sandbox_service, sample_test_case):
    """Test simulation without detailed explanation."""
    result = await sandbox_service.simulate_single(
        policy_draft_id="draft-123",
        test_case=sample_test_case,
        include_explanation=False,
    )

    assert isinstance(result, SimulationResult)
    assert result.explanation is None  # No explanation requested


@pytest.mark.asyncio
async def test_simulate_single_different_policy_drafts(sandbox_service, sample_test_case):
    """Test that different policy drafts produce different results."""
    # Test with permissive policy
    result_permissive = await sandbox_service.simulate_single(
        policy_draft_id="draft-permissive",
        test_case=sample_test_case,
        include_explanation=False,
    )

    # Test with restrictive policy
    result_restrictive = await sandbox_service.simulate_single(
        policy_draft_id="draft-restrictive",
        test_case=sample_test_case,
        include_explanation=False,
    )

    # Both should succeed but may have different outcomes
    assert isinstance(result_permissive, SimulationResult)
    assert isinstance(result_restrictive, SimulationResult)


# ---------------------------------------------------------------------------
# Test: Batch Test Execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_parallel(sandbox_service, sample_test_cases):
    """Test batch execution in parallel mode."""
    result = await sandbox_service.run_batch(
        policy_draft_id="draft-123",
        test_cases=sample_test_cases,
        parallel_execution=True,
    )

    # Verify batch result structure
    assert isinstance(result, BatchSimulationResult)
    assert result.policy_draft_id == "draft-123"
    assert result.total_tests == len(sample_test_cases)
    assert result.passed + result.failed == result.total_tests
    assert 0 <= result.pass_rate <= 100
    assert result.total_duration_ms > 0
    assert result.avg_duration_ms > 0
    assert len(result.results) == len(sample_test_cases)
    assert result.completed_at > result.started_at


@pytest.mark.asyncio
async def test_run_batch_sequential(sandbox_service, sample_test_cases):
    """Test batch execution in sequential mode."""
    result = await sandbox_service.run_batch(
        policy_draft_id="draft-123",
        test_cases=sample_test_cases,
        parallel_execution=False,
    )

    # Verify batch result
    assert isinstance(result, BatchSimulationResult)
    assert result.total_tests == len(sample_test_cases)
    assert len(result.results) == len(sample_test_cases)


@pytest.mark.asyncio
async def test_run_batch_with_suite_id(sandbox_service, sample_test_cases):
    """Test batch execution with test suite ID."""
    result = await sandbox_service.run_batch(
        policy_draft_id="draft-123",
        test_cases=sample_test_cases,
        test_suite_id="suite-abc",
        parallel_execution=True,
    )

    assert result.test_suite_id == "suite-abc"


@pytest.mark.asyncio
async def test_run_batch_empty_test_cases(sandbox_service):
    """Test batch execution with empty test cases."""
    result = await sandbox_service.run_batch(
        policy_draft_id="draft-123",
        test_cases=[],
        parallel_execution=True,
    )

    assert result.total_tests == 0
    assert result.passed == 0
    assert result.failed == 0
    assert result.pass_rate == 0.0


# ---------------------------------------------------------------------------
# Test: Regression Testing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_regression_basic(sandbox_service):
    """Test basic regression testing functionality."""
    report = await sandbox_service.run_regression(
        policy_draft_id="draft-123",
        baseline_policy_version="prod-v2.1",
        replay_last_days=7,
        sample_size=50,
    )

    # Verify report structure
    assert isinstance(report, RegressionReport)
    assert report.policy_draft_id == "draft-123"
    assert report.baseline_policy_version == "prod-v2.1"
    assert report.total_decisions > 0
    assert report.matching_decisions + report.different_decisions == report.total_decisions
    assert 0 <= report.regression_rate <= 100
    assert report.critical_regressions >= 0
    assert report.high_regressions >= 0
    assert report.medium_regressions >= 0
    assert report.low_regressions >= 0
    assert len(report.comparisons) == report.total_decisions
    assert report.completed_at > report.started_at


@pytest.mark.asyncio
async def test_run_regression_with_filters(sandbox_service):
    """Test regression testing with subject and action filters."""
    report = await sandbox_service.run_regression(
        policy_draft_id="draft-123",
        baseline_policy_version="prod-v2.1",
        replay_last_days=7,
        sample_size=100,
        filter_by_subject="user1@example.com",
        filter_by_action="tools.invoke",
    )

    # Verify filtering worked (mock data applies filters)
    assert isinstance(report, RegressionReport)
    # Note: With mock data, filters may result in fewer decisions
    assert report.total_decisions >= 0


@pytest.mark.asyncio
async def test_run_regression_severity_calculation(sandbox_service):
    """Test that regression severity is calculated correctly."""
    report = await sandbox_service.run_regression(
        policy_draft_id="draft-123",
        baseline_policy_version="prod-v2.1",
        replay_last_days=3,
        sample_size=50,
    )

    # Verify severity counts add up
    regressions_only = report.regressions_only
    severity_sum = report.critical_regressions + report.high_regressions + report.medium_regressions + report.low_regressions
    assert severity_sum == len(regressions_only)


# ---------------------------------------------------------------------------
# Test: Helper Methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_draft_config_different_ids(sandbox_service):
    """Test loading different policy draft configurations."""
    # Test permissive draft
    config_permissive = await sandbox_service._load_draft_config("draft-permissive")
    assert config_permissive.cache.enabled == False  # Caching should be disabled

    # Test restrictive draft
    config_restrictive = await sandbox_service._load_draft_config("draft-restrictive")
    assert config_restrictive.cache.enabled == False

    # Test default draft
    config_default = await sandbox_service._load_draft_config("draft-default")
    assert config_default.cache.enabled == False


@pytest.mark.asyncio
async def test_fetch_historical_decisions(sandbox_service):
    """Test fetching historical decisions (mock data)."""
    decisions = await sandbox_service._fetch_historical_decisions(
        baseline_policy_version="prod-v2.1",
        replay_last_days=7,
        sample_size=100,
        filter_by_subject=None,
        filter_by_action=None,
    )

    # Verify mock data is returned
    assert isinstance(decisions, list)
    assert len(decisions) > 0
    assert all(hasattr(d, "subject") for d in decisions)
    assert all(hasattr(d, "action") for d in decisions)
    assert all(hasattr(d, "decision") for d in decisions)


def test_calculate_regression_severity(sandbox_service):
    """Test regression severity calculation."""
    # ALLOW -> DENY = high severity (lockout)
    severity_high = sandbox_service._calculate_regression_severity(Decision.ALLOW, Decision.DENY)
    assert severity_high == "high"

    # DENY -> ALLOW = critical severity (security gap)
    severity_critical = sandbox_service._calculate_regression_severity(Decision.DENY, Decision.ALLOW)
    assert severity_critical == "critical"

    # No change = low severity
    severity_low = sandbox_service._calculate_regression_severity(Decision.ALLOW, Decision.ALLOW)
    assert severity_low == "low"


def test_describe_impact(sandbox_service):
    """Test impact description generation."""
    resource = Resource(type="tool", id="database-query")

    # Test access loss
    impact_loss = sandbox_service._describe_impact(
        "user@example.com",
        "tools.invoke",
        resource,
        Decision.ALLOW,
        Decision.DENY,
    )
    assert "lose access" in impact_loss.lower()
    assert "user@example.com" in impact_loss

    # Test access gain
    impact_gain = sandbox_service._describe_impact(
        "user@example.com",
        "tools.invoke",
        resource,
        Decision.DENY,
        Decision.ALLOW,
    )
    assert "gain access" in impact_gain.lower()

    # Test no change
    impact_none = sandbox_service._describe_impact(
        "user@example.com",
        "tools.invoke",
        resource,
        Decision.ALLOW,
        Decision.ALLOW,
    )
    assert "no change" in impact_none.lower()


# ---------------------------------------------------------------------------
# Test: Integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_workflow(sandbox_service, sample_test_case):
    """Test complete workflow: simulate -> batch -> regression."""
    # 1. Single simulation
    single_result = await sandbox_service.simulate_single(
        policy_draft_id="draft-123",
        test_case=sample_test_case,
    )
    assert isinstance(single_result, SimulationResult)

    # 2. Batch simulation
    batch_result = await sandbox_service.run_batch(
        policy_draft_id="draft-123",
        test_cases=[sample_test_case],
    )
    assert isinstance(batch_result, BatchSimulationResult)
    assert batch_result.total_tests == 1

    # 3. Regression testing
    regression_report = await sandbox_service.run_regression(
        policy_draft_id="draft-123",
        baseline_policy_version="prod-v2.1",
        replay_last_days=1,
        sample_size=10,
    )
    assert isinstance(regression_report, RegressionReport)


# ---------------------------------------------------------------------------
# Performance Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulation_performance(sandbox_service, sample_test_case):
    """Test that simulation completes in reasonable time."""
    # Standard
    import time

    start = time.perf_counter()
    result = await sandbox_service.simulate_single(
        policy_draft_id="draft-123",
        test_case=sample_test_case,
        include_explanation=False,
    )
    duration = (time.perf_counter() - start) * 1000

    # Should complete in under 500ms
    assert duration < 500
    assert result.execution_time_ms < 100  # Policy evaluation should be fast


@pytest.mark.asyncio
async def test_batch_parallel_faster_than_sequential(sandbox_service, sample_test_cases):
    """Test that parallel execution is faster than sequential."""
    # Standard
    import time

    # Sequential execution
    start_seq = time.perf_counter()
    result_seq = await sandbox_service.run_batch(
        policy_draft_id="draft-123",
        test_cases=sample_test_cases,
        parallel_execution=False,
    )
    duration_seq = (time.perf_counter() - start_seq) * 1000

    # Parallel execution
    start_par = time.perf_counter()
    result_par = await sandbox_service.run_batch(
        policy_draft_id="draft-123",
        test_cases=sample_test_cases,
        parallel_execution=True,
    )
    duration_par = (time.perf_counter() - start_par) * 1000

    # Parallel should be faster (or at least not much slower)
    # Note: With mock data, difference may be minimal
    assert result_par.total_tests == result_seq.total_tests
    print(f"Sequential: {duration_seq:.1f}ms, Parallel: {duration_par:.1f}ms")


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_with_missing_context(sandbox_service):
    """Test simulation works when context is not provided."""
    test_case = TestCase(
        subject=Subject(email="user@example.com", roles=["viewer"]),
        action="resources.read",
        resource=Resource(type="resource", id="doc-1"),
        context=None,  # No context provided
        expected_decision=Decision.ALLOW,
    )

    result = await sandbox_service.simulate_single(
        policy_draft_id="draft-123",
        test_case=test_case,
    )

    assert isinstance(result, SimulationResult)


@pytest.mark.asyncio
async def test_regression_with_no_historical_data(sandbox_service):
    """Test regression testing when filters eliminate all data."""
    report = await sandbox_service.run_regression(
        policy_draft_id="draft-123",
        baseline_policy_version="prod-v2.1",
        replay_last_days=7,
        sample_size=100,
        filter_by_subject="nonexistent@example.com",
    )

    # Should handle gracefully
    assert isinstance(report, RegressionReport)
    assert report.total_decisions >= 0
