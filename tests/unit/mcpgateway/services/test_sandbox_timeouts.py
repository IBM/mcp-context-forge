# -*- coding: utf-8 -*-
"""Unit tests for sandbox timeout and failure scenarios.
Location: ./tests/unit/mcpgateway/services/test_sandbox_timeouts.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Hugh Hennelly

Tests timeout handling, batch size limits, and repeated failure scenarios
in the SandboxService. These exercise the asyncio.wait_for timeout path,
the configurable batch size enforcement, and concurrent execution limits.

Covers Brian-Hussey review items:
- 4iii: Limit testing of failure scenarios
- 4iv: Tests for timeout scenarios (circuit breaker pattern feedback)

Related to Issue #2226: Policy testing and simulation sandbox
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.schemas import (
    SimulationResult,
    TestCase,
)
from mcpgateway.services.sandbox_service import SandboxService
from plugins.unified_pdp.pdp_models import (
    AccessDecision,
    CombinationMode,
    Decision,
    DecisionExplanation,
    Resource,
    Subject,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Provide a mock database session."""
    return MagicMock()


@pytest.fixture
def sandbox_service(mock_db):
    """Create a SandboxService with a mock database session."""
    return SandboxService(mock_db)


@pytest.fixture
def sample_test_case():
    """Create a basic test case for timeout testing."""
    return TestCase(
        subject=Subject(email="dev@example.com", roles=["developer"]),
        action="tools.invoke",
        resource=Resource(type="tool", id="db-query"),
        expected_decision=Decision.ALLOW,
        description="Timeout test case",
    )


@pytest.fixture
def sample_test_cases(sample_test_case):
    """Create multiple test cases for batch testing."""
    cases = []
    for i in range(5):
        cases.append(
            TestCase(
                id=f"tc-{i}",
                subject=Subject(email=f"user{i}@example.com", roles=["developer"]),
                action="tools.invoke",
                resource=Resource(type="tool", id=f"tool-{i}"),
                expected_decision=Decision.ALLOW,
                description=f"Test case {i}",
            )
        )
    return cases


def _make_explanation(decision=Decision.ALLOW):
    """Create a real DecisionExplanation for mocked PDP calls."""
    return DecisionExplanation(
        decision=decision,
        summary="Allowed by default policy",
        combination_mode=CombinationMode.ALL_MUST_ALLOW,
    )


def _make_mock_decision(decision=Decision.ALLOW):
    """Create a real AccessDecision for mocked PDP calls."""
    return AccessDecision(
        decision=decision,
        matching_policies=["default-allow"],
        reason="Allowed by default",
    )


# ---------------------------------------------------------------------------
# Tests: Timeout Scenarios (asyncio.wait_for)
# ---------------------------------------------------------------------------


class TestSimulateTimeout:
    """Tests for timeout handling in simulate_single."""

    @pytest.mark.asyncio
    async def test_timeout_raises_on_slow_evaluation(self, sandbox_service, sample_test_case):
        """Simulation that exceeds timeout raises asyncio.TimeoutError."""
        # Create a PDP mock that hangs indefinitely
        mock_pdp = MagicMock()

        async def slow_check_access(**kwargs):
            """Simulate a slow PDP evaluation that exceeds timeout."""
            await asyncio.sleep(10)  # Sleep longer than any reasonable timeout
            return _make_mock_decision()

        mock_pdp.check_access = slow_check_access
        mock_pdp.close = AsyncMock()

        with (
            patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load,
            patch.object(sandbox_service, "_create_sandbox_pdp", return_value=mock_pdp),
            patch("mcpgateway.services.sandbox_service.settings") as mock_settings,
        ):
            mock_load.return_value = MagicMock()
            # Set a very short timeout (10ms) to trigger TimeoutError quickly
            mock_settings.mcpgateway_sandbox_timeout_per_case_ms = 10

            with pytest.raises(asyncio.TimeoutError):
                await sandbox_service.simulate_single(
                    policy_draft_id="draft-123",
                    test_case=sample_test_case,
                    include_explanation=False,
                )

        # Verify PDP was still closed despite timeout
        mock_pdp.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_still_closes_pdp(self, sandbox_service, sample_test_case):
        """PDP resources are cleaned up even when timeout occurs."""
        mock_pdp = MagicMock()

        async def slow_check(**kwargs):
            """Slow evaluation exceeding timeout."""
            await asyncio.sleep(10)
            return _make_mock_decision()

        mock_pdp.check_access = slow_check
        mock_pdp.close = AsyncMock()

        with (
            patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load,
            patch.object(sandbox_service, "_create_sandbox_pdp", return_value=mock_pdp),
            patch("mcpgateway.services.sandbox_service.settings") as mock_settings,
        ):
            mock_load.return_value = MagicMock()
            mock_settings.mcpgateway_sandbox_timeout_per_case_ms = 10

            with pytest.raises(asyncio.TimeoutError):
                await sandbox_service.simulate_single("draft-123", sample_test_case)

        # The finally block should always close the PDP
        mock_pdp.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_pdp_close_error_is_suppressed(self, sandbox_service, sample_test_case):
        """Error closing the PDP is logged but not raised."""
        mock_pdp = MagicMock()
        mock_pdp.check_access = AsyncMock(return_value=_make_mock_decision())
        mock_pdp.explain_decision = AsyncMock(return_value=_make_explanation())
        # Simulate error on close
        mock_pdp.close = AsyncMock(side_effect=RuntimeError("Connection reset"))

        with (
            patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load,
            patch.object(sandbox_service, "_create_sandbox_pdp", return_value=mock_pdp),
            patch("mcpgateway.services.sandbox_service.settings") as mock_settings,
        ):
            mock_load.return_value = MagicMock()
            mock_settings.mcpgateway_sandbox_timeout_per_case_ms = 5000

            # Should NOT raise despite close error
            result = await sandbox_service.simulate_single("draft-123", sample_test_case, include_explanation=True)

        assert result.passed is True
        mock_pdp.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_normal_evaluation_within_timeout(self, sandbox_service, sample_test_case):
        """Evaluation that completes within timeout succeeds normally."""
        mock_pdp = MagicMock()

        async def fast_check(**kwargs):
            """Fast evaluation well within timeout."""
            await asyncio.sleep(0.001)
            return _make_mock_decision()

        mock_pdp.check_access = fast_check
        mock_pdp.explain_decision = AsyncMock(return_value=_make_explanation())
        mock_pdp.close = AsyncMock()

        with (
            patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load,
            patch.object(sandbox_service, "_create_sandbox_pdp", return_value=mock_pdp),
            patch("mcpgateway.services.sandbox_service.settings") as mock_settings,
        ):
            mock_load.return_value = MagicMock()
            mock_settings.mcpgateway_sandbox_timeout_per_case_ms = 5000

            result = await sandbox_service.simulate_single("draft-123", sample_test_case, include_explanation=True)

        assert result.passed is True
        assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# Tests: Batch Size Limits
# ---------------------------------------------------------------------------


class TestBatchSizeLimits:
    """Tests for batch size enforcement from configuration."""

    @pytest.mark.asyncio
    async def test_batch_exceeding_max_raises_value_error(self, sandbox_service):
        """Batch with more test cases than max raises ValueError."""
        # Create more test cases than the limit
        cases = [
            TestCase(
                subject=Subject(email=f"u{i}@b.com", roles=["dev"]),
                action="tools.invoke",
                resource=Resource(type="tool", id=f"t-{i}"),
                expected_decision=Decision.ALLOW,
            )
            for i in range(15)
        ]

        with patch("mcpgateway.services.sandbox_service.settings") as mock_settings:
            mock_settings.mcpgateway_sandbox_max_test_cases_per_run = 10

            with pytest.raises(ValueError, match="exceeds maximum"):
                await sandbox_service.run_batch("draft-123", cases)

    @pytest.mark.asyncio
    async def test_batch_at_exact_limit_does_not_raise(self, sandbox_service, sample_test_cases):
        """Batch at exactly the max limit should not raise."""
        with patch("mcpgateway.services.sandbox_service.settings") as mock_settings, patch.object(sandbox_service, "_execute_parallel", new_callable=AsyncMock) as mock_exec:
            mock_settings.mcpgateway_sandbox_max_test_cases_per_run = 5
            mock_exec.return_value = [
                SimulationResult(
                    test_case_id=f"tc-{i}",
                    actual_decision=Decision.ALLOW,
                    expected_decision=Decision.ALLOW,
                    passed=True,
                    execution_time_ms=10.0,
                    policy_draft_id="draft-123",
                )
                for i in range(5)
            ]

            # Should not raise (5 cases, limit is 5)
            result = await sandbox_service.run_batch("draft-123", sample_test_cases)
            assert result.total_tests == 5

    @pytest.mark.asyncio
    async def test_batch_below_limit_succeeds(self, sandbox_service):
        """Batch below the limit runs normally."""
        cases = [
            TestCase(
                subject=Subject(email="u@b.com", roles=["dev"]),
                action="tools.invoke",
                resource=Resource(type="tool", id="t-1"),
                expected_decision=Decision.ALLOW,
            )
        ]

        with patch("mcpgateway.services.sandbox_service.settings") as mock_settings, patch.object(sandbox_service, "_execute_parallel", new_callable=AsyncMock) as mock_exec:
            mock_settings.mcpgateway_sandbox_max_test_cases_per_run = 1000
            mock_exec.return_value = [
                SimulationResult(
                    test_case_id="tc-0",
                    actual_decision=Decision.ALLOW,
                    expected_decision=Decision.ALLOW,
                    passed=True,
                    execution_time_ms=5.0,
                    policy_draft_id="draft-123",
                )
            ]

            result = await sandbox_service.run_batch("draft-123", cases)
            assert result.total_tests == 1


# ---------------------------------------------------------------------------
# Tests: Concurrent Execution Limits
# ---------------------------------------------------------------------------


class TestConcurrencyLimits:
    """Tests for semaphore-based concurrency limiting in parallel execution."""

    @pytest.mark.asyncio
    async def test_parallel_execution_respects_concurrency_limit(self, sandbox_service, sample_test_cases):
        """Parallel execution uses semaphore to limit concurrency."""
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def tracked_simulate(policy_draft_id, test_case, include_explanation=False):
            """Track concurrent execution count."""
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent

            await asyncio.sleep(0.01)  # Simulate some work

            async with lock:
                current_concurrent -= 1

            return SimulationResult(
                test_case_id=test_case.id or "tc",
                actual_decision=Decision.ALLOW,
                expected_decision=Decision.ALLOW,
                passed=True,
                execution_time_ms=10.0,
                policy_draft_id=policy_draft_id,
            )

        with patch.object(sandbox_service, "simulate_single", side_effect=tracked_simulate), patch("mcpgateway.services.sandbox_service.settings") as mock_settings:
            mock_settings.mcpgateway_sandbox_max_concurrent_tests = 2

            results = await sandbox_service._execute_parallel("draft-123", sample_test_cases)

        assert len(results) == 5
        # The max concurrent should never exceed the semaphore limit
        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_parallel_execution_all_results_returned(self, sandbox_service, sample_test_cases):
        """All test cases produce results even with concurrency limiting."""

        async def mock_simulate(policy_draft_id, test_case, include_explanation=False):
            """Return a result for each test case."""
            return SimulationResult(
                test_case_id=test_case.id or "tc",
                actual_decision=Decision.ALLOW,
                expected_decision=Decision.ALLOW,
                passed=True,
                execution_time_ms=5.0,
                policy_draft_id=policy_draft_id,
            )

        with patch.object(sandbox_service, "simulate_single", side_effect=mock_simulate), patch("mcpgateway.services.sandbox_service.settings") as mock_settings:
            mock_settings.mcpgateway_sandbox_max_concurrent_tests = 3

            results = await sandbox_service._execute_parallel("draft-123", sample_test_cases)

        assert len(results) == 5
        assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# Tests: Repeated Failure / Error Propagation
# ---------------------------------------------------------------------------


class TestRepeatedFailures:
    """Tests for how the service handles repeated and cascading failures."""

    @pytest.mark.asyncio
    async def test_batch_with_mixed_pass_fail(self, sandbox_service):
        """Batch run correctly counts mixed pass/fail results."""
        cases = [
            TestCase(
                id=f"tc-{i}",
                subject=Subject(email="u@b.com", roles=["dev"]),
                action="tools.invoke",
                resource=Resource(type="tool", id=f"t-{i}"),
                expected_decision=Decision.ALLOW if i % 2 == 0 else Decision.DENY,
            )
            for i in range(4)
        ]

        # Create results where odd-indexed tests fail (ALLOW != DENY expectation)
        mock_results = []
        for i, tc in enumerate(cases):
            mock_results.append(
                SimulationResult(
                    test_case_id=tc.id or f"tc-{i}",
                    actual_decision=Decision.ALLOW,
                    expected_decision=tc.expected_decision,
                    passed=(tc.expected_decision == Decision.ALLOW),
                    execution_time_ms=10.0,
                    policy_draft_id="draft-123",
                )
            )

        with patch("mcpgateway.services.sandbox_service.settings") as mock_settings, patch.object(sandbox_service, "_execute_parallel", new_callable=AsyncMock) as mock_exec:
            mock_settings.mcpgateway_sandbox_max_test_cases_per_run = 100
            mock_exec.return_value = mock_results

            result = await sandbox_service.run_batch("draft-123", cases)

        assert result.total_tests == 4
        assert result.passed == 2
        assert result.failed == 2
        assert result.pass_rate == 50.0

    @pytest.mark.asyncio
    async def test_batch_all_failures(self, sandbox_service):
        """Batch where every test fails returns 0% pass rate."""
        cases = [
            TestCase(
                id="tc-0",
                subject=Subject(email="u@b.com", roles=["dev"]),
                action="tools.invoke",
                resource=Resource(type="tool", id="t-0"),
                expected_decision=Decision.ALLOW,
            )
        ]

        mock_results = [
            SimulationResult(
                test_case_id="tc-0",
                actual_decision=Decision.DENY,
                expected_decision=Decision.ALLOW,
                passed=False,
                execution_time_ms=10.0,
                policy_draft_id="draft-123",
            )
        ]

        with patch("mcpgateway.services.sandbox_service.settings") as mock_settings, patch.object(sandbox_service, "_execute_parallel", new_callable=AsyncMock) as mock_exec:
            mock_settings.mcpgateway_sandbox_max_test_cases_per_run = 100
            mock_exec.return_value = mock_results

            result = await sandbox_service.run_batch("draft-123", cases)

        assert result.total_tests == 1
        assert result.passed == 0
        assert result.failed == 1
        assert result.pass_rate == 0.0

    @pytest.mark.asyncio
    async def test_load_draft_config_not_found(self, sandbox_service, sample_test_case):
        """Simulation with non-existent draft raises ValueError."""
        sandbox_service.db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="Policy draft not found"):
            await sandbox_service._load_draft_config("nonexistent-draft")

    @pytest.mark.asyncio
    async def test_load_draft_invalid_config(self, sandbox_service, sample_test_case):
        """Draft with invalid stored config raises ValueError."""
        mock_draft = MagicMock()
        mock_draft.id = "draft-bad"
        mock_draft.name = "Bad Draft"
        # Use a dict that will fail PDPConfig(**config) validation
        # Setting a non-dict value so that unpacking raises TypeError
        mock_draft.config = "not-a-dict"
        sandbox_service.db.query.return_value.filter.return_value.first.return_value = mock_draft

        with pytest.raises((ValueError, TypeError)):
            await sandbox_service._load_draft_config("draft-bad")
