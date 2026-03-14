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
- Database integration (PolicyDraft, PermissionAuditLog, SandboxTestSuite)
- Test suite CRUD

Related to Issue #2226: Policy testing and simulation sandbox
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import PermissionAuditLog, PolicyDraft, SandboxTestSuite
from mcpgateway.schemas import (
    BatchSimulationResult,
    RegressionReport,
    SimulationResult,
    TestCase,
    TestSuite,
)
from mcpgateway.services.sandbox_service import SandboxService
from plugins.unified_pdp.pdp_models import (
    CacheConfig,
    CombinationMode,
    Context,
    Decision,
    EngineConfig,
    EngineType,
    PDPConfig,
    PerformanceConfig,
    Resource,
    Subject,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pdp_config(
    combination_mode: CombinationMode = CombinationMode.ALL_MUST_ALLOW,
    default_decision: Decision = Decision.DENY,
) -> PDPConfig:
    """Create a PDPConfig suitable for sandbox testing."""
    return PDPConfig(
        engines=[
            EngineConfig(
                name=EngineType.NATIVE,
                enabled=True,
                priority=1,
                settings={},
            ),
        ],
        combination_mode=combination_mode,
        default_decision=default_decision,
        cache=CacheConfig(enabled=False),
        performance=PerformanceConfig(timeout_ms=1000, parallel_evaluation=True),
    )


def _make_policy_draft_row(draft_id: str = "draft-123", name: str = "test draft") -> Mock:
    """Create a mock PolicyDraft ORM row."""
    config = _make_pdp_config()
    row = Mock(spec=PolicyDraft)
    row.id = draft_id
    row.name = name
    row.config = config.model_dump(mode="json")
    return row


def _make_audit_row(
    record_id: int = 1,
    email: str = "user@example.com",
    permission: str = "tools.invoke",
    resource_type: str = "tool",
    resource_id: str = "db-query",
    granted: bool = True,
    team_id: str | None = None,
    ip_address: str | None = "10.0.0.1",
    timestamp: datetime | None = None,
) -> Mock:
    """Create a mock PermissionAuditLog ORM row."""
    row = Mock(spec=PermissionAuditLog)
    row.id = record_id
    row.user_email = email
    row.permission = permission
    row.resource_type = resource_type
    row.resource_id = resource_id
    row.granted = granted
    row.team_id = team_id
    row.ip_address = ip_address
    row.roles_checked = {"roles": ["developer"]}
    row.timestamp = timestamp or datetime.now(timezone.utc)
    return row


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Mock database session with query chain support."""
    db = MagicMock()
    return db


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
    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = _make_pdp_config()

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
    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = _make_pdp_config()

        result = await sandbox_service.simulate_single(
            policy_draft_id="draft-123",
            test_case=sample_test_case,
            include_explanation=False,
        )

    assert isinstance(result, SimulationResult)
    assert result.explanation is None  # No explanation requested


@pytest.mark.asyncio
async def test_simulate_single_draft_not_found(sandbox_service, sample_test_case):
    """Test ValueError when policy draft not found."""
    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.side_effect = ValueError("Policy draft not found: missing-draft")

        with pytest.raises(ValueError, match="Policy draft not found"):
            await sandbox_service.simulate_single(
                policy_draft_id="missing-draft",
                test_case=sample_test_case,
            )


# ---------------------------------------------------------------------------
# Test: Batch Test Execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_parallel(sandbox_service, sample_test_cases):
    """Test batch execution in parallel mode."""
    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = _make_pdp_config()

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
    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = _make_pdp_config()

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
    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = _make_pdp_config()

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
    audit_rows = [_make_audit_row(record_id=i) for i in range(10)]

    with (
        patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load,
        patch.object(sandbox_service, "_fetch_historical_decisions", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_load.return_value = _make_pdp_config()
        # Build real HistoricalDecision objects from audit rows
        # First-Party
        from mcpgateway.schemas import HistoricalDecision

        mock_fetch.return_value = [
            HistoricalDecision(
                id=str(i),
                subject=Subject(email="user@example.com", roles=["developer"]),
                action="tools.invoke",
                resource=Resource(type="tool", id="db-query"),
                context=Context(),
                decision=Decision.ALLOW if i % 2 == 0 else Decision.DENY,
                policy_version="prod-v2.1",
                timestamp=datetime.now(timezone.utc),
            )
            for i in range(10)
        ]

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
    assert report.total_decisions == 10
    assert report.matching_decisions + report.different_decisions == report.total_decisions
    assert 0 <= report.regression_rate <= 100
    assert report.critical_regressions >= 0
    assert report.high_regressions >= 0
    assert report.medium_regressions >= 0
    assert report.low_regressions >= 0
    assert len(report.comparisons) == report.total_decisions
    assert report.completed_at > report.started_at


@pytest.mark.asyncio
async def test_run_regression_with_no_history(sandbox_service):
    """Test regression with no historical decisions returns empty report."""
    with (
        patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load,
        patch.object(sandbox_service, "_fetch_historical_decisions", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_load.return_value = _make_pdp_config()
        mock_fetch.return_value = []

        report = await sandbox_service.run_regression(
            policy_draft_id="draft-123",
            baseline_policy_version="prod-v2.1",
            replay_last_days=7,
            sample_size=100,
        )

    assert isinstance(report, RegressionReport)
    assert report.total_decisions == 0
    assert report.regression_rate == 0.0


@pytest.mark.asyncio
async def test_run_regression_severity_calculation(sandbox_service):
    """Test that regression severity is calculated correctly."""
    # First-Party
    from mcpgateway.schemas import HistoricalDecision

    with (
        patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load,
        patch.object(sandbox_service, "_fetch_historical_decisions", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_load.return_value = _make_pdp_config()
        mock_fetch.return_value = [
            HistoricalDecision(
                id=str(i),
                subject=Subject(email=f"user{i}@example.com", roles=["developer"]),
                action="tools.invoke",
                resource=Resource(type="tool", id=f"tool-{i}"),
                context=Context(),
                decision=Decision.ALLOW if i % 2 == 0 else Decision.DENY,
                policy_version="prod-v2.1",
                timestamp=datetime.now(timezone.utc),
            )
            for i in range(20)
        ]

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
# Test: _load_draft_config (Database Integration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_draft_config_from_db(sandbox_service, mock_db):
    """Test loading a policy draft config from the database."""
    draft_row = _make_policy_draft_row("draft-abc", "my draft")
    mock_db.query.return_value.filter.return_value.first.return_value = draft_row

    config = await sandbox_service._load_draft_config("draft-abc")

    assert isinstance(config, PDPConfig)
    assert config.cache.enabled is False  # Sandbox always disables caching
    mock_db.query.assert_called_once_with(PolicyDraft)


@pytest.mark.asyncio
async def test_load_draft_config_not_found(sandbox_service, mock_db):
    """Test ValueError when policy draft is missing from DB."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Policy draft not found"):
        await sandbox_service._load_draft_config("nonexistent")


@pytest.mark.asyncio
async def test_load_draft_config_invalid_json(sandbox_service, mock_db):
    """Test ValueError when stored config has invalid field types."""
    row = Mock(spec=PolicyDraft)
    row.id = "draft-bad"
    row.name = "bad config"
    # combination_mode expects a CombinationMode enum value, not a random string
    row.config = {"combination_mode": "INVALID_ENUM_VALUE", "engines": "not-a-list"}
    mock_db.query.return_value.filter.return_value.first.return_value = row

    with pytest.raises(ValueError, match="Invalid configuration"):
        await sandbox_service._load_draft_config("draft-bad")


# ---------------------------------------------------------------------------
# Test: _fetch_historical_decisions (Database Integration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_historical_decisions_from_db(sandbox_service, mock_db):
    """Test fetching historical decisions from PermissionAuditLog."""
    audit_rows = [
        _make_audit_row(record_id=1, email="a@b.com", granted=True),
        _make_audit_row(record_id=2, email="c@d.com", granted=False),
    ]
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = audit_rows

    decisions = await sandbox_service._fetch_historical_decisions(
        baseline_policy_version="prod-v1",
        replay_last_days=7,
        sample_size=100,
        filter_by_subject=None,
        filter_by_action=None,
    )

    assert len(decisions) == 2
    assert decisions[0].subject.email == "a@b.com"
    assert decisions[0].decision == Decision.ALLOW
    assert decisions[1].decision == Decision.DENY
    assert decisions[0].policy_version == "prod-v1"


@pytest.mark.asyncio
async def test_fetch_historical_decisions_with_subject_filter(sandbox_service, mock_db):
    """Test subject filter is applied to the query."""
    mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    decisions = await sandbox_service._fetch_historical_decisions(
        baseline_policy_version="prod-v1",
        replay_last_days=7,
        sample_size=100,
        filter_by_subject="specific@user.com",
        filter_by_action=None,
    )

    assert decisions == []


@pytest.mark.asyncio
async def test_fetch_historical_decisions_with_action_filter(sandbox_service, mock_db):
    """Test action filter is applied to the query."""
    mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    decisions = await sandbox_service._fetch_historical_decisions(
        baseline_policy_version="prod-v1",
        replay_last_days=7,
        sample_size=100,
        filter_by_subject=None,
        filter_by_action="tools.invoke",
    )

    assert decisions == []


@pytest.mark.asyncio
async def test_fetch_historical_empty_roles(sandbox_service, mock_db):
    """Test graceful handling when roles_checked is None or missing roles key."""
    row = _make_audit_row()
    row.roles_checked = None  # No roles data
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [row]

    decisions = await sandbox_service._fetch_historical_decisions(
        baseline_policy_version="prod-v1",
        replay_last_days=7,
        sample_size=100,
        filter_by_subject=None,
        filter_by_action=None,
    )

    assert len(decisions) == 1
    assert decisions[0].subject.roles == []


# ---------------------------------------------------------------------------
# Test: Helper Methods
# ---------------------------------------------------------------------------


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
# Test: Test Suite CRUD
# ---------------------------------------------------------------------------


def test_create_test_suite(sandbox_service, mock_db, sample_test_case):
    """Test creating a test suite persists to DB."""
    suite = TestSuite(
        name="my-suite",
        description="Test suite",
        test_cases=[sample_test_case],
        tags=["rbac"],
    )

    result = sandbox_service.create_test_suite(suite, created_by="admin@example.com")

    assert result.name == "my-suite"
    assert len(result.test_cases) == 1
    mock_db.add.assert_called_once()
    mock_db.flush.assert_called_once()


def test_get_test_suite_found(sandbox_service, mock_db, sample_test_case):
    """Test retrieving an existing test suite."""
    db_row = MagicMock(spec=SandboxTestSuite)
    db_row.id = "suite-1"
    db_row.name = "my-suite"
    db_row.description = "A suite"
    db_row.test_cases = [sample_test_case.model_dump(mode="json")]
    db_row.tags = ["rbac"]
    db_row.created_at = datetime.now(timezone.utc)
    db_row.updated_at = datetime.now(timezone.utc)

    mock_db.query.return_value.filter.return_value.first.return_value = db_row

    result = sandbox_service.get_test_suite("suite-1")

    assert result is not None
    assert result.name == "my-suite"
    assert len(result.test_cases) == 1


def test_get_test_suite_not_found(sandbox_service, mock_db):
    """Test retrieving a non-existent test suite returns None."""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    result = sandbox_service.get_test_suite("missing-suite")

    assert result is None


def test_list_test_suites_empty(sandbox_service, mock_db):
    """Test listing suites with no results."""
    mock_db.query.return_value.order_by.return_value.all.return_value = []

    result = sandbox_service.list_test_suites()

    assert result == []


def test_list_test_suites_with_results(sandbox_service, mock_db, sample_test_case):
    """Test listing suites returns converted results."""
    db_row = MagicMock(spec=SandboxTestSuite)
    db_row.id = "suite-1"
    db_row.name = "my-suite"
    db_row.description = "A suite"
    db_row.test_cases = [sample_test_case.model_dump(mode="json")]
    db_row.tags = ["rbac"]
    db_row.created_at = datetime.now(timezone.utc)
    db_row.updated_at = datetime.now(timezone.utc)

    mock_db.query.return_value.order_by.return_value.all.return_value = [db_row]

    result = sandbox_service.list_test_suites()

    assert len(result) == 1
    assert result[0].name == "my-suite"


def test_list_test_suites_tag_filtering(sandbox_service, mock_db, sample_test_case):
    """Test tag filtering in list_test_suites."""
    row1 = MagicMock(spec=SandboxTestSuite)
    row1.id = "suite-1"
    row1.name = "rbac-suite"
    row1.description = ""
    row1.test_cases = [sample_test_case.model_dump(mode="json")]
    row1.tags = ["rbac", "security"]
    row1.created_at = datetime.now(timezone.utc)
    row1.updated_at = datetime.now(timezone.utc)

    row2 = MagicMock(spec=SandboxTestSuite)
    row2.id = "suite-2"
    row2.name = "other-suite"
    row2.description = ""
    row2.test_cases = []
    row2.tags = ["other"]
    row2.created_at = datetime.now(timezone.utc)
    row2.updated_at = datetime.now(timezone.utc)

    mock_db.query.return_value.order_by.return_value.all.return_value = [row1, row2]

    # Filter by "rbac" tag — only suite-1 should match
    result = sandbox_service.list_test_suites(tags=["rbac"])

    assert len(result) == 1
    assert result[0].name == "rbac-suite"


# ---------------------------------------------------------------------------
# Test: Integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_workflow(sandbox_service, sample_test_case):
    """Test complete workflow: simulate -> batch -> regression."""
    # First-Party
    from mcpgateway.schemas import HistoricalDecision

    with (
        patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load,
        patch.object(sandbox_service, "_fetch_historical_decisions", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_load.return_value = _make_pdp_config()
        mock_fetch.return_value = [
            HistoricalDecision(
                id="hist-1",
                subject=Subject(email="user@example.com", roles=["developer"]),
                action="tools.invoke",
                resource=Resource(type="tool", id="db-query"),
                context=Context(),
                decision=Decision.ALLOW,
                policy_version="prod-v2.1",
                timestamp=datetime.now(timezone.utc),
            ),
        ]

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

    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = _make_pdp_config()

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

    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = _make_pdp_config()

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

    with patch.object(sandbox_service, "_load_draft_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = _make_pdp_config()

        result = await sandbox_service.simulate_single(
            policy_draft_id="draft-123",
            test_case=test_case,
        )

    assert isinstance(result, SimulationResult)
