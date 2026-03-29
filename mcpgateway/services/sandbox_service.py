#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sandbox Service for Policy Testing and Simulation.
Location: ./mcpgateway/services/sandbox_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: "Hugh Hennelly"

This service provides isolated policy evaluation for testing policy drafts
before deployment. It creates temporary PDP instances with draft policies,
executes test cases, and compares results against expectations.

Related to Issue #2226: Policy testing and simulation sandbox

Database integration:
- PolicyDraft table stores draft policy configurations.
- SandboxTestSuite table persists reusable test suites.
- PermissionAuditLog table provides historical decisions for regression testing.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import List, Optional

# Third-Party
from fastapi import Depends
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db, PermissionAuditLog, PolicyDraft, SandboxTestSuite
from plugins.unified_pdp.pdp import PolicyDecisionPoint
from plugins.unified_pdp.pdp_models import (
    Context,
    Decision,
    PDPConfig,
    Resource,
    Subject,
)

# Local
from ..schemas import (
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
            # 3. Evaluate the test case (with configurable timeout)
            timeout_seconds = settings.mcpgateway_sandbox_timeout_per_case_ms / 1000.0
            start_time = time.perf_counter()
            actual_decision_obj = await asyncio.wait_for(
                pdp.check_access(
                    subject=test_case.subject,
                    action=test_case.action,
                    resource=test_case.resource,
                    context=test_case.context or Context(),
                ),
                timeout=timeout_seconds,
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
            try:
                await pdp.close()
            except Exception as close_err:
                logger.warning("Error closing sandbox PDP instance: %s", close_err)

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

        Raises:
            ValueError: If batch size exceeds the configured maximum

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

        # Enforce max test cases per run from configuration
        max_cases = settings.mcpgateway_sandbox_max_test_cases_per_run
        if len(test_cases) > max_cases:
            raise ValueError(f"Batch size {len(test_cases)} exceeds maximum of {max_cases} " f"(MCPGATEWAY_SANDBOX_MAX_TEST_CASES_PER_RUN)")

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
        regression_rate = (different_decisions / total_decisions * 100) if total_decisions > 0 else 0.0

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
        """Load policy draft configuration from the database.

        Queries the ``policy_drafts`` table for the given ID and converts the
        stored JSON configuration into a ``PDPConfig`` instance.

        Args:
            policy_draft_id: ID of the policy draft

        Returns:
            PDPConfig for the draft policy

        Raises:
            ValueError: If draft not found in the database
        """
        draft = self.db.query(PolicyDraft).filter(PolicyDraft.id == policy_draft_id).first()
        if not draft:
            raise ValueError(f"Policy draft not found: {policy_draft_id}")

        logger.info("Loaded policy draft %s (%s) from database", policy_draft_id, draft.name)

        try:
            config = PDPConfig(**draft.config)
        except Exception as exc:
            logger.error("Invalid configuration in policy draft %s: %s", policy_draft_id, exc)
            raise ValueError(f"Invalid configuration in policy draft {policy_draft_id}: {exc}") from exc

        return config

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
        """Execute test cases in parallel with concurrency limiting.

        Respects ``MCPGATEWAY_SANDBOX_MAX_CONCURRENT_TESTS`` to avoid
        overwhelming the system with too many concurrent evaluations.

        Args:
            policy_draft_id: Policy draft to test
            test_cases: Test cases to execute

        Returns:
            List of simulation results
        """
        semaphore = asyncio.Semaphore(settings.mcpgateway_sandbox_max_concurrent_tests)

        async def _limited(tc: TestCase) -> SimulationResult:
            """Run a single test case under the concurrency semaphore.

            Args:
                tc: Test case to execute

            Returns:
                Simulation result for the test case
            """
            async with semaphore:
                return await self.simulate_single(policy_draft_id, tc, include_explanation=False)

        tasks = [_limited(tc) for tc in test_cases]
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
            result = await self.simulate_single(policy_draft_id, tc, include_explanation=False)
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
        """Fetch historical production decisions from the PermissionAuditLog.

        Queries the ``permission_audit_log`` table for recent permission
        checks and converts them into ``HistoricalDecision`` objects that
        can be replayed against a policy draft.

        Args:
            baseline_policy_version: Label for the baseline policy version
            replay_last_days: Number of days of history to query
            sample_size: Maximum number of decisions to return
            filter_by_subject: Optional filter by user email
            filter_by_action: Optional filter by permission/action string

        Returns:
            List of historical decisions
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=replay_last_days)

        query = self.db.query(PermissionAuditLog).filter(
            PermissionAuditLog.timestamp >= cutoff_date,
        )

        if filter_by_subject:
            query = query.filter(PermissionAuditLog.user_email == filter_by_subject)
        if filter_by_action:
            query = query.filter(PermissionAuditLog.permission == filter_by_action)

        audit_records = query.order_by(PermissionAuditLog.timestamp.desc()).limit(sample_size).all()

        logger.info(
            "Fetched %d historical decisions from permission_audit_log (cutoff=%s)",
            len(audit_records),
            cutoff_date.isoformat(),
        )

        decisions: List[HistoricalDecision] = []
        for record in audit_records:
            # Reconstruct roles from the stored JSON (may be None)
            roles: List[str] = []
            if record.roles_checked and isinstance(record.roles_checked, dict):
                roles = list(record.roles_checked.get("roles", []))

            decisions.append(
                HistoricalDecision(
                    id=str(record.id),
                    subject=Subject(
                        email=record.user_email or "unknown@example.com",
                        roles=roles,
                        team_id=record.team_id,
                    ),
                    action=record.permission,
                    resource=Resource(
                        type=record.resource_type or "unknown",
                        id=record.resource_id or "unknown",
                    ),
                    context=Context(
                        ip=record.ip_address,
                        timestamp=record.timestamp,
                    ),
                    decision=Decision.ALLOW if record.granted else Decision.DENY,
                    reason="Granted by policy" if record.granted else "Denied by policy",
                    matching_policies=[],
                    policy_version=baseline_policy_version,
                    timestamp=record.timestamp,
                )
            )

        return decisions

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
            result = await self.simulate_single(policy_draft_id, test_case, include_explanation=False)

            # Compare
            is_regression = result.actual_decision != hist.decision
            severity = self._calculate_regression_severity(hist.decision, result.actual_decision)

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

    def _calculate_regression_severity(self, historical: Decision, simulated: Decision) -> str:
        """Calculate the severity of a regression.

        Args:
            historical: Historical decision
            simulated: New simulated decision

        Returns:
            str: Severity level - 'critical', 'high', 'medium', or 'low'
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
        resource: Resource,
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
            return f"{subject_email} will lose access to {resource.type} " f"'{resource.id}' for action '{action}'"
        else:
            return f"{subject_email} will gain access to {resource.type} " f"'{resource.id}' for action '{action}'"

    # ---------------------------------------------------------------------------
    # Test Suite CRUD Methods
    # ---------------------------------------------------------------------------

    def create_test_suite(self, suite: TestSuite, created_by: str) -> TestSuite:
        """Persist a new test suite to the database.

        Args:
            suite: Pydantic TestSuite with name, description, test_cases, tags
            created_by: Email of the user creating the suite

        Returns:
            The TestSuite with its persisted ID and timestamps
        """
        db_suite = SandboxTestSuite(
            id=suite.id,
            name=suite.name,
            description=suite.description,
            test_cases=[tc.model_dump(mode="json") for tc in suite.test_cases],
            tags=suite.tags,
            created_by=created_by,
        )
        self.db.add(db_suite)
        self.db.flush()

        logger.info("Created test suite %s (%s) by %s", db_suite.id, db_suite.name, created_by)

        return self._db_suite_to_schema(db_suite)

    def get_test_suite(self, suite_id: str) -> Optional[TestSuite]:
        """Retrieve a test suite by ID.

        Args:
            suite_id: The suite's primary key

        Returns:
            TestSuite if found, None otherwise
        """
        db_suite = self.db.query(SandboxTestSuite).filter(SandboxTestSuite.id == suite_id).first()
        if not db_suite:
            return None
        return self._db_suite_to_schema(db_suite)

    def list_test_suites(self, tags: Optional[List[str]] = None) -> List[TestSuite]:
        """List all test suites, optionally filtered by tags.

        Args:
            tags: If provided, only return suites containing ALL of these tags

        Returns:
            List of matching TestSuite objects
        """
        query = self.db.query(SandboxTestSuite).order_by(SandboxTestSuite.created_at.desc())
        db_suites = query.all()

        results = [self._db_suite_to_schema(s) for s in db_suites]

        # Filter by tags in Python (JSON column filtering varies by RDBMS)
        if tags:
            results = [s for s in results if all(t in s.tags for t in tags)]

        return results

    @staticmethod
    def _db_suite_to_schema(db_suite: SandboxTestSuite) -> TestSuite:
        """Convert a SandboxTestSuite ORM instance to a Pydantic TestSuite.

        Args:
            db_suite: The ORM model instance

        Returns:
            Pydantic TestSuite
        """
        test_cases = [TestCase(**tc) for tc in (db_suite.test_cases or [])]
        now = datetime.now(timezone.utc)
        return TestSuite(
            id=db_suite.id,
            name=db_suite.name,
            description=db_suite.description,
            test_cases=test_cases,
            tags=db_suite.tags or [],
            created_at=db_suite.created_at or now,
            updated_at=db_suite.updated_at or now,
        )


# ---------------------------------------------------------------------------
# Dependency Injection Helper
# ---------------------------------------------------------------------------


def get_sandbox_service(db: Session = Depends(get_db)) -> SandboxService:
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
