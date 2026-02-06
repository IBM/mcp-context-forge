"""Sandbox Service for Policy Testing and Simulation.

This service provides isolated policy evaluation for testing policy drafts
before deployment. It creates temporary PDP instances with draft policies,
executes test cases, and compares results against expectations.

Related to Issue #2226: Policy testing and simulation sandbox
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from ..plugins.unified_pdp.pdp import PolicyDecisionPoint
from ..plugins.unified_pdp.pdp_models import (
    CacheConfig,
    Context,
    Decision,
    PDPConfig,
)
from ..schemas.sandbox import (
    BatchSimulationResult,
    DecisionComparison,
    HistoricalDecision,
    RegressionReport,
    SimulationResult,
    TestCase,
    TestSuite,
)

logger = logging.getLogger(__name__)


class SandboxService:
    """Service for testing and simulating policy decisions in isolation.
    
    This service creates isolated PDP instances for testing policy drafts
    without affecting production. It supports:
    - Single test case simulation
    - Batch test execution
    - Regression testing against historical decisions
    - Decision comparison and analysis
    
    Attributes:
        db: Database session for accessing policy drafts and historical data
    """

    def __init__(self, db: Session):
        """Initialize the sandbox service.
        
        Args:
            db: SQLAlchemy database session for accessing data
        """
        self.db = db

    # ---------------------------------------------------------------------------
    # Core Simulation Methods
    # ---------------------------------------------------------------------------

    async def simulate_single(
        self,
        policy_draft_id: str,
        test_case: TestCase,
        include_explanation: bool = True,
    ) -> SimulationResult:
        """Simulate a single test case against a policy draft.
        
        Creates an isolated PDP instance with the draft policy configuration,
        evaluates the test case, and compares the result against the expected
        decision.
        
        Args:
            policy_draft_id: ID of the policy draft to test
            test_case: Test case containing subject, action, resource, and expected decision
            include_explanation: Whether to generate detailed explanation (default: True)
        
        Returns:
            SimulationResult containing actual vs expected decision, timing,
            and optional explanation
        
        Raises:
            ValueError: If policy draft not found
            PolicyEvaluationError: If evaluation fails
        
        Example:
            >>> service = SandboxService(db)
            >>> test_case = TestCase(
            ...     subject=Subject(email="dev@example.com", roles=["developer"]),
            ...     action="tools.invoke",
            ...     resource=Resource(type="tool", id="db-query"),
            ...     expected_decision=Decision.ALLOW
            ... )
            >>> result = await service.simulate_single("draft-123", test_case)
            >>> print(f"Test passed: {result.passed}")
        """
        logger.info(
            "Simulating test case %s against policy draft %s",
            test_case.id,
            policy_draft_id,
        )

        # 1. Load policy draft configuration
        draft_config = await self._load_draft_config(policy_draft_id)

        # 2. Create isolated PDP instance (disable caching for testing)
        pdp = self._create_sandbox_pdp(draft_config)

        try:
            # 3. Evaluate the test case
            start_time = time.perf_counter()
            actual_decision_obj = await pdp.check_access(
                subject=test_case.subject,
                action=test_case.action,
                resource=test_case.resource,
                context=test_case.context or Context(),
            )
            execution_time = (time.perf_counter() - start_time) * 1000

            # 4. Get detailed explanation if requested
            explanation = None
            if include_explanation:
                explanation = await pdp.explain_decision(
                    subject=test_case.subject,
                    action=test_case.action,
                    resource=test_case.resource,
                    context=test_case.context or Context(),
                )

            # 5. Compare actual vs expected
            passed = actual_decision_obj.decision == test_case.expected_decision

            # 6. Build result
            result = SimulationResult(
                test_case_id=test_case.id,
                actual_decision=actual_decision_obj.decision,
                expected_decision=test_case.expected_decision,
                passed=passed,
                execution_time_ms=round(execution_time, 2),
                explanation=explanation,
                policy_draft_id=policy_draft_id,
                access_decision=actual_decision_obj,
                matching_policies=actual_decision_obj.matching_policies,
                reason=actual_decision_obj.reason,
            )

            logger.info(
                "Test case %s: %s (actual=%s, expected=%s, %.1fms)",
                test_case.id,
                "PASSED" if passed else "FAILED",
                actual_decision_obj.decision.value,
                test_case.expected_decision.value,
                execution_time,
            )

            return result

        finally:
            # 7. Cleanup PDP resources
            await pdp.close()

    async def run_batch(
        self,
        policy_draft_id: str,
        test_cases: List[TestCase],
        test_suite_id: Optional[str] = None,
        parallel_execution: bool = True,
    ) -> BatchSimulationResult:
        """Execute multiple test cases in batch against a policy draft.
        
        Runs all test cases and aggregates results. Can run tests in parallel
        for better performance or sequentially for deterministic ordering.
        
        Args:
            policy_draft_id: ID of the policy draft to test
            test_cases: List of test cases to execute
            test_suite_id: Optional test suite ID for tracking
            parallel_execution: Whether to run tests in parallel (default: True)
        
        Returns:
            BatchSimulationResult with summary statistics and individual results
        
        Example:
            >>> results = await service.run_batch(
            ...     "draft-123",
            ...     [test_case1, test_case2, test_case3],
            ...     parallel_execution=True
            ... )
            >>> print(f"Pass rate: {results.pass_rate}%")
        """
        logger.info(
            "Running batch simulation: %d test cases against policy draft %s",
            len(test_cases),
            policy_draft_id,
        )

        started_at = datetime.now(timezone.utc)

        # Execute tests (parallel or sequential)
        if parallel_execution:
            results = await self._execute_parallel(policy_draft_id, test_cases)
        else:
            results = await self._execute_sequential(policy_draft_id, test_cases)

        completed_at = datetime.now(timezone.utc)

        # Calculate statistics
        total_tests = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total_tests - passed
        pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0.0
        total_duration = sum(r.execution_time_ms for r in results)
        avg_duration = total_duration / total_tests if total_tests > 0 else 0.0

        batch_result = BatchSimulationResult(
            policy_draft_id=policy_draft_id,
            test_suite_id=test_suite_id,
            total_tests=total_tests,
            passed=passed,
            failed=failed,
            pass_rate=round(pass_rate, 2),
            total_duration_ms=round(total_duration, 2),
            avg_duration_ms=round(avg_duration, 2),
            results=results,
            started_at=started_at,
            completed_at=completed_at,
        )

        logger.info(
            "Batch complete: %d/%d passed (%.1f%%), %.1fms total",
            passed,
            total_tests,
            pass_rate,
            total_duration,
        )

        return batch_result

    async def run_regression(
        self,
        policy_draft_id: str,
        baseline_policy_version: str,
        replay_last_days: int = 7,
        sample_size: int = 1000,
        filter_by_subject: Optional[str] = None,
        filter_by_action: Optional[str] = None,
    ) -> RegressionReport:
        """Run regression tests by replaying historical decisions.
        
        Fetches historical production decisions and replays them against the
        policy draft to identify regressions (unintended behavior changes).
        
        Args:
            policy_draft_id: ID of the policy draft to test
            baseline_policy_version: Production policy version to compare against
            replay_last_days: Number of days of history to replay (default: 7)
            sample_size: Maximum number of decisions to replay (default: 1000)
            filter_by_subject: Optional filter for specific subject email
            filter_by_action: Optional filter for specific action types
        
        Returns:
            RegressionReport with comparisons and regression analysis
        
        Example:
            >>> report = await service.run_regression(
            ...     "draft-123",
            ...     "prod-v2.1",
            ...     replay_last_days=7,
            ...     sample_size=1000
            ... )
            >>> print(f"Regression rate: {report.regression_rate}%")
            >>> print(f"Critical regressions: {report.critical_regressions}")
        """
        logger.info(
            "Running regression test: policy_draft=%s, baseline=%s, days=%d, sample=%d",
            policy_draft_id,
            baseline_policy_version,
            replay_last_days,
            sample_size,
        )

        started_at = datetime.now(timezone.utc)

        # 1. Fetch historical decisions
        historical_decisions = await self._fetch_historical_decisions(
            baseline_policy_version=baseline_policy_version,
            replay_last_days=replay_last_days,
            sample_size=sample_size,
            filter_by_subject=filter_by_subject,
            filter_by_action=filter_by_action,
        )

        logger.info("Fetched %d historical decisions", len(historical_decisions))

        # 2. Replay each decision against the policy draft
        comparisons = await self._replay_and_compare(
            policy_draft_id=policy_draft_id,
            historical_decisions=historical_decisions,
        )

        completed_at = datetime.now(timezone.utc)
        duration_ms = (completed_at - started_at).total_seconds() * 1000

        # 3. Analyze regressions
        total_decisions = len(comparisons)
        different_decisions = sum(1 for c in comparisons if c.is_regression)
        matching_decisions = total_decisions - different_decisions
        regression_rate = (
            (different_decisions / total_decisions * 100) if total_decisions > 0 else 0.0
        )

        # Count regressions by severity
        regressions_only = [c for c in comparisons if c.is_regression]
        critical = sum(1 for c in regressions_only if c.severity == "critical")
        high = sum(1 for c in regressions_only if c.severity == "high")
        medium = sum(1 for c in regressions_only if c.severity == "medium")
        low = sum(1 for c in regressions_only if c.severity == "low")

        report = RegressionReport(
            policy_draft_id=policy_draft_id,
            baseline_policy_version=baseline_policy_version,
            total_decisions=total_decisions,
            matching_decisions=matching_decisions,
            different_decisions=different_decisions,
            regression_rate=round(regression_rate, 2),
            critical_regressions=critical,
            high_regressions=high,
            medium_regressions=medium,
            low_regressions=low,
            comparisons=comparisons,
            regressions_only=regressions_only,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=round(duration_ms, 2),
        )

        logger.info(
            "Regression test complete: %d regressions (%.1f%%), critical=%d, high=%d",
            different_decisions,
            regression_rate,
            critical,
            high,
        )

        return report

    # ---------------------------------------------------------------------------
    # Helper Methods
    # ---------------------------------------------------------------------------

    async def _load_draft_config(self, policy_draft_id: str) -> PDPConfig:
        """Load policy draft configuration from database.
        
        Args:
            policy_draft_id: ID of the policy draft
        
        Returns:
            PDPConfig for the draft policy
        
        Raises:
            ValueError: If draft not found
        """
        # TODO: Implement database query to fetch policy draft
        # This is a placeholder that would query your database
        # For now, return a basic config
        
        logger.warning(
            "Using placeholder config - implement database query for draft %s",
            policy_draft_id,
        )

        # Placeholder: In real implementation, this would query the database
        # to fetch the actual policy draft configuration
        from ..plugins.unified_pdp.pdp_models import (
            CombinationMode,
            EngineConfig,
            EngineType,
            PerformanceConfig,
        )

        return PDPConfig(
            engines=[
                EngineConfig(
                    name=EngineType.NATIVE,
                    enabled=True,
                    priority=1,
                    settings={},
                ),
            ],
            combination_mode=CombinationMode.ALL_MUST_ALLOW,
            default_decision=Decision.DENY,
            cache=CacheConfig(enabled=False),  # IMPORTANT: Disable cache for testing!
            performance=PerformanceConfig(
                timeout_ms=1000,
                parallel_evaluation=True,
            ),
        )

    def _create_sandbox_pdp(self, config: PDPConfig) -> PolicyDecisionPoint:
        """Create an isolated PDP instance for sandbox testing.
        
        Args:
            config: PDP configuration with draft policies
        
        Returns:
            PolicyDecisionPoint instance configured for sandbox use
        """
        # Ensure caching is disabled for sandbox
        config.cache.enabled = False
        
        return PolicyDecisionPoint(config)

    async def _execute_parallel(
        self,
        policy_draft_id: str,
        test_cases: List[TestCase],
    ) -> List[SimulationResult]:
        """Execute test cases in parallel.
        
        Args:
            policy_draft_id: Policy draft to test
            test_cases: Test cases to execute
        
        Returns:
            List of simulation results
        """
        tasks = [
            self.simulate_single(policy_draft_id, tc, include_explanation=False)
            for tc in test_cases
        ]
        return await asyncio.gather(*tasks)

    async def _execute_sequential(
        self,
        policy_draft_id: str,
        test_cases: List[TestCase],
    ) -> List[SimulationResult]:
        """Execute test cases sequentially.
        
        Args:
            policy_draft_id: Policy draft to test
            test_cases: Test cases to execute
        
        Returns:
            List of simulation results
        """
        results = []
        for tc in test_cases:
            result = await self.simulate_single(
                policy_draft_id, tc, include_explanation=False
            )
            results.append(result)
        return results

    async def _fetch_historical_decisions(
        self,
        baseline_policy_version: str,
        replay_last_days: int,
        sample_size: int,
        filter_by_subject: Optional[str],
        filter_by_action: Optional[str],
    ) -> List[HistoricalDecision]:
        """Fetch historical production decisions for regression testing.
        
        Args:
            baseline_policy_version: Policy version to fetch decisions for
            replay_last_days: Number of days of history
            sample_size: Maximum number of decisions
            filter_by_subject: Optional subject filter
            filter_by_action: Optional action filter
        
        Returns:
            List of historical decisions
        """
        # TODO: Implement database query to fetch historical audit logs
        
        logger.warning(
            "Using placeholder historical decisions - implement database query"
        )

        # Placeholder: In real implementation, query audit logs from database
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=replay_last_days)
        
        # Would execute something like:
        # SELECT * FROM policy_audit_log
        # WHERE policy_version = baseline_policy_version
        #   AND timestamp >= cutoff_date
        #   AND (subject_email = filter_by_subject OR filter_by_subject IS NULL)
        #   AND (action = filter_by_action OR filter_by_action IS NULL)
        # ORDER BY timestamp DESC
        # LIMIT sample_size

        return []  # Return empty list for now

    async def _replay_and_compare(
        self,
        policy_draft_id: str,
        historical_decisions: List[HistoricalDecision],
    ) -> List[DecisionComparison]:
        """Replay historical decisions and compare results.
        
        Args:
            policy_draft_id: Policy draft to test
            historical_decisions: Historical decisions to replay
        
        Returns:
            List of decision comparisons
        """
        comparisons = []

        for hist in historical_decisions:
            # Create test case from historical decision
            test_case = TestCase(
                subject=hist.subject,
                action=hist.action,
                resource=hist.resource,
                context=hist.context,
                expected_decision=hist.decision,
                description=f"Replay of historical decision {hist.id}",
            )

            # Simulate
            result = await self.simulate_single(
                policy_draft_id, test_case, include_explanation=False
            )

            # Compare
            is_regression = result.actual_decision != hist.decision
            severity = self._calculate_regression_severity(
                hist.decision, result.actual_decision
            )

            comparison = DecisionComparison(
                historical_id=hist.id,
                historical_decision=hist.decision,
                simulated_decision=result.actual_decision,
                is_regression=is_regression,
                subject_email=hist.subject.email,
                action=hist.action,
                resource_type=hist.resource.type,
                resource_id=hist.resource.id,
                severity=severity,
                impact_description=self._describe_impact(
                    hist.subject.email,
                    hist.action,
                    hist.resource,
                    hist.decision,
                    result.actual_decision,
                ),
                historical_reason=hist.reason,
                simulated_reason=result.reason,
                policy_changes=result.matching_policies,
            )

            comparisons.append(comparison)

        return comparisons

    def _calculate_regression_severity(
        self, historical: Decision, simulated: Decision
    ) -> str:
        """Calculate the severity of a regression.
        
        Args:
            historical: Historical decision
            simulated: New simulated decision
        
        Returns:
            Severity level: 'critical', 'high', 'medium', 'low'
        """
        if historical == Decision.ALLOW and simulated == Decision.DENY:
            # Access was granted, now denied - HIGH severity (potential lockout)
            return "high"
        elif historical == Decision.DENY and simulated == Decision.ALLOW:
            # Access was denied, now allowed - CRITICAL severity (security gap)
            return "critical"
        else:
            # No change
            return "low"

    def _describe_impact(
        self,
        subject_email: str,
        action: str,
        resource: "Resource",
        old_decision: Decision,
        new_decision: Decision,
    ) -> str:
        """Generate human-readable impact description.
        
        Args:
            subject_email: Subject email
            action: Action being performed
            resource: Resource being accessed
            old_decision: Historical decision
            new_decision: New decision
        
        Returns:
            Human-readable impact description
        """
        if old_decision == new_decision:
            return "No change in behavior"

        if old_decision == Decision.ALLOW and new_decision == Decision.DENY:
            return (
                f"{subject_email} will lose access to {resource.type} "
                f"'{resource.id}' for action '{action}'"
            )
        else:
            return (
                f"{subject_email} will gain access to {resource.type} "
                f"'{resource.id}' for action '{action}'"
            )


# ---------------------------------------------------------------------------
# Dependency Injection Helper
# ---------------------------------------------------------------------------


def get_sandbox_service(db: Session) -> SandboxService:
    """Dependency injection helper for FastAPI routes.
    
    Args:
        db: Database session
    
    Returns:
        SandboxService instance
    
    Example:
        @router.post("/sandbox/simulate")
        async def simulate(
            request: SimulateRequest,
            sandbox: SandboxService = Depends(get_sandbox_service)
        ):
            return await sandbox.simulate_single(...)
    """
    return SandboxService(db)
