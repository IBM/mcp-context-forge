# -*- coding: utf-8 -*-
"""Unit tests for sandbox route handlers.
Location: ./tests/unit/mcpgateway/routers/test_sandbox_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Hugh Hennelly

Tests each sandbox endpoint handler directly with mocked dependencies.
Follows the same pattern as test_rbac_router.py — calling async handler
functions with mock services rather than going through HTTP.

Related to Issue #2226: Policy testing and simulation sandbox
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.routes import sandbox as sandbox_mod
from mcpgateway.routes.sandbox import (
    _SANDBOX_INPUT_MAX_LENGTH,
    _validate_sandbox_form_input,
    SANDBOX_SERVICE_NAME,
    SANDBOX_SERVICE_VERSION,
)
from mcpgateway.schemas import (
    BatchSimulateRequest,
    BatchSimulationResult,
    RegressionReport,
    RegressionTestRequest,
    SimulationResult,
    TestCase,
    TestSuite,
)
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
def mock_sandbox_service():
    """Return a fully-mocked SandboxService with AsyncMock methods."""
    svc = MagicMock()
    svc.run_batch = AsyncMock()
    svc.run_regression = AsyncMock()
    svc.simulate_single = AsyncMock()
    return svc


@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    return {"email": "test@example.com", "is_admin": True}


@pytest.fixture
def sample_test_case():
    """Create a sample test case."""
    return TestCase(
        subject=Subject(email="dev@example.com", roles=["developer"]),
        action="tools.invoke",
        resource=Resource(type="tool", id="db-query"),
        expected_decision=Decision.ALLOW,
        description="Test developer access",
    )


@pytest.fixture
def sample_simulation_result():
    """Create a sample simulation result."""
    return SimulationResult(
        test_case_id="tc-1",
        actual_decision=Decision.ALLOW,
        expected_decision=Decision.ALLOW,
        passed=True,
        execution_time_ms=42.5,
        policy_draft_id="draft-123",
        reason="All engines allowed",
    )


@pytest.fixture
def sample_batch_result(sample_simulation_result):
    """Create a sample batch simulation result."""
    return BatchSimulationResult(
        policy_draft_id="draft-123",
        total_tests=1,
        passed=1,
        failed=0,
        pass_rate=100.0,
        total_duration_ms=42.5,
        avg_duration_ms=42.5,
        results=[sample_simulation_result],
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_regression_report():
    """Create a sample regression report."""
    return RegressionReport(
        policy_draft_id="draft-123",
        baseline_policy_version="prod-v1",
        total_decisions=10,
        matching_decisions=9,
        different_decisions=1,
        regression_rate=10.0,
        critical_regressions=0,
        high_regressions=1,
        medium_regressions=0,
        low_regressions=0,
        duration_ms=500.0,
    )


@pytest.fixture
def sample_test_suite(sample_test_case):
    """Create a sample test suite."""
    return TestSuite(
        name="test-suite",
        description="A test suite",
        test_cases=[sample_test_case],
        tags=["rbac"],
    )


# ---------------------------------------------------------------------------
# Tests: Batch Endpoint
# ---------------------------------------------------------------------------


class TestRunBatchTests:
    """Tests for POST /sandbox/batch handler."""

    @pytest.mark.asyncio
    async def test_batch_success(self, mock_sandbox_service, mock_user, sample_test_case, sample_batch_result):
        """Batch endpoint returns results on success."""
        mock_sandbox_service.run_batch.return_value = sample_batch_result

        request = BatchSimulateRequest(
            policy_draft_id="draft-123",
            test_cases=[sample_test_case],
        )

        result = await sandbox_mod.run_batch_tests(
            request=request,
            sandbox=mock_sandbox_service,
            current_user=mock_user,
        )

        assert result.total_tests == 1
        assert result.passed == 1
        assert result.pass_rate == 100.0
        mock_sandbox_service.run_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_batch_not_found(self, mock_sandbox_service, mock_user, sample_test_case):
        """Batch endpoint raises 404 when policy draft not found."""
        mock_sandbox_service.run_batch.side_effect = ValueError("not found")

        request = BatchSimulateRequest(
            policy_draft_id="missing-draft",
            test_cases=[sample_test_case],
        )

        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            await sandbox_mod.run_batch_tests(
                request=request,
                sandbox=mock_sandbox_service,
                current_user=mock_user,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_batch_internal_error(self, mock_sandbox_service, mock_user, sample_test_case):
        """Batch endpoint raises 500 on unexpected errors."""
        mock_sandbox_service.run_batch.side_effect = RuntimeError("boom")

        request = BatchSimulateRequest(
            policy_draft_id="draft-123",
            test_cases=[sample_test_case],
        )

        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            await sandbox_mod.run_batch_tests(
                request=request,
                sandbox=mock_sandbox_service,
                current_user=mock_user,
            )

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Tests: Regression Endpoint
# ---------------------------------------------------------------------------


class TestRunRegressionTests:
    """Tests for POST /sandbox/regression handler."""

    @pytest.mark.asyncio
    async def test_regression_success(self, mock_sandbox_service, mock_user, sample_regression_report):
        """Regression endpoint returns report on success."""
        mock_sandbox_service.run_regression.return_value = sample_regression_report

        request = RegressionTestRequest(
            policy_draft_id="draft-123",
            baseline_policy_version="prod-v1",
            replay_last_days=7,
        )

        result = await sandbox_mod.run_regression_tests(
            request=request,
            sandbox=mock_sandbox_service,
            current_user=mock_user,
        )

        assert result.total_decisions == 10
        assert result.regression_rate == 10.0
        mock_sandbox_service.run_regression.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_regression_not_found(self, mock_sandbox_service, mock_user):
        """Regression endpoint raises 404 when policy not found."""
        mock_sandbox_service.run_regression.side_effect = ValueError("not found")

        request = RegressionTestRequest(
            policy_draft_id="missing",
        )

        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            await sandbox_mod.run_regression_tests(
                request=request,
                sandbox=mock_sandbox_service,
                current_user=mock_user,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_regression_internal_error(self, mock_sandbox_service, mock_user):
        """Regression endpoint raises 500 on unexpected errors."""
        mock_sandbox_service.run_regression.side_effect = RuntimeError("boom")

        request = RegressionTestRequest(
            policy_draft_id="draft-123",
        )

        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            await sandbox_mod.run_regression_tests(
                request=request,
                sandbox=mock_sandbox_service,
                current_user=mock_user,
            )

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_regression_with_filters(self, mock_sandbox_service, mock_user, sample_regression_report):
        """Regression endpoint passes filter parameters through."""
        mock_sandbox_service.run_regression.return_value = sample_regression_report

        request = RegressionTestRequest(
            policy_draft_id="draft-123",
            filter_by_subject="dev@example.com",
            filter_by_action="tools.invoke",
        )

        await sandbox_mod.run_regression_tests(
            request=request,
            sandbox=mock_sandbox_service,
            current_user=mock_user,
        )

        call_kwargs = mock_sandbox_service.run_regression.call_args[1]
        assert call_kwargs["filter_by_subject"] == "dev@example.com"
        assert call_kwargs["filter_by_action"] == "tools.invoke"


# ---------------------------------------------------------------------------
# Tests: Test Suite Management Endpoints
# ---------------------------------------------------------------------------


class TestCreateTestSuite:
    """Tests for POST /sandbox/suites handler."""

    @pytest.mark.asyncio
    async def test_create_suite_success(self, mock_sandbox_service, mock_user, sample_test_suite):
        """Create suite persists and returns the suite."""
        mock_sandbox_service.create_test_suite = MagicMock(return_value=sample_test_suite)

        result = await sandbox_mod.create_test_suite(
            test_suite=sample_test_suite,
            sandbox=mock_sandbox_service,
            current_user=mock_user,
        )

        assert result.name == "test-suite"
        assert len(result.test_cases) == 1
        mock_sandbox_service.create_test_suite.assert_called_once()


class TestGetTestSuite:
    """Tests for GET /sandbox/suites/{suite_id} handler."""

    @pytest.mark.asyncio
    async def test_get_suite_returns_404_when_not_found(self, mock_sandbox_service, mock_user):
        """Get suite returns 404 when suite does not exist."""
        mock_sandbox_service.get_test_suite = MagicMock(return_value=None)

        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            await sandbox_mod.get_test_suite(
                suite_id="suite-1",
                sandbox=mock_sandbox_service,
                current_user=mock_user,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_suite_success(self, mock_sandbox_service, mock_user, sample_test_suite):
        """Get suite returns the suite when found."""
        mock_sandbox_service.get_test_suite = MagicMock(return_value=sample_test_suite)

        result = await sandbox_mod.get_test_suite(
            suite_id="suite-1",
            sandbox=mock_sandbox_service,
            current_user=mock_user,
        )

        assert result.name == "test-suite"


class TestListTestSuites:
    """Tests for GET /sandbox/suites handler."""

    @pytest.mark.asyncio
    async def test_list_suites_returns_empty(self, mock_sandbox_service, mock_user):
        """List suites returns empty list when none exist."""
        mock_sandbox_service.list_test_suites = MagicMock(return_value=[])

        result = await sandbox_mod.list_test_suites(
            tags=None,
            sandbox=mock_sandbox_service,
            current_user=mock_user,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_list_suites_with_tags(self, mock_sandbox_service, mock_user, sample_test_suite):
        """List suites accepts and parses tags parameter."""
        mock_sandbox_service.list_test_suites = MagicMock(return_value=[sample_test_suite])

        result = await sandbox_mod.list_test_suites(
            tags="rbac,security",
            sandbox=mock_sandbox_service,
            current_user=mock_user,
        )

        assert len(result) == 1
        # Verify tags were parsed and passed through
        call_kwargs = mock_sandbox_service.list_test_suites.call_args[1]
        assert call_kwargs["tags"] == ["rbac", "security"]


# ---------------------------------------------------------------------------
# Tests: Health & Info Endpoints
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Tests for GET /sandbox/health handler."""

    @pytest.mark.asyncio
    async def test_health_check_returns_healthy(self):
        """Health check returns healthy status with version."""
        result = await sandbox_mod.health_check()

        assert result["status"] == "healthy"
        assert result["service"] == "sandbox"
        assert result["version"] == SANDBOX_SERVICE_VERSION
        assert result["check_type"] == "liveness"

    @pytest.mark.asyncio
    async def test_health_check_version_matches_constant(self):
        """Health check version matches the module-level constant."""
        result = await sandbox_mod.health_check()
        assert result["version"] == SANDBOX_SERVICE_VERSION


class TestServiceInfo:
    """Tests for GET /sandbox/info handler."""

    @pytest.mark.asyncio
    async def test_info_returns_capabilities(self):
        """Info endpoint returns name, version, and capabilities."""
        result = await sandbox_mod.service_info()

        assert result["name"] == SANDBOX_SERVICE_NAME
        assert result["version"] == SANDBOX_SERVICE_VERSION
        assert "single_simulation" in result["capabilities"]
        assert "batch_simulation" in result["capabilities"]
        assert "regression_testing" in result["capabilities"]
        assert "test_suite_management" in result["capabilities"]

    @pytest.mark.asyncio
    async def test_info_features(self):
        """Info endpoint reports feature flags."""
        result = await sandbox_mod.service_info()

        assert result["features"]["parallel_execution"] is True
        assert result["features"]["decision_explanation"] is True
        assert result["features"]["regression_severity"] is True
        assert result["features"]["historical_replay"] is True

    @pytest.mark.asyncio
    async def test_info_version_matches_health(self):
        """Info and health endpoints report the same version."""
        info = await sandbox_mod.service_info()
        health = await sandbox_mod.health_check()
        assert info["version"] == health["version"]


# ---------------------------------------------------------------------------
# Tests: Input Validation Helper
# ---------------------------------------------------------------------------


class TestValidateSandboxFormInput:
    """Tests for _validate_sandbox_form_input helper."""

    def test_valid_alphanumeric(self):
        """Valid alphanumeric input passes."""
        _validate_sandbox_form_input("draft-123", "test_field")

    def test_valid_email(self):
        """Valid email-like input passes."""
        _validate_sandbox_form_input("user@example.com", "email")

    def test_valid_dotted(self):
        """Valid dotted input passes."""
        _validate_sandbox_form_input("tools.invoke", "action")

    def test_valid_with_spaces(self):
        """Input with spaces passes."""
        _validate_sandbox_form_input("my resource", "field")

    def test_valid_with_underscores(self):
        """Input with underscores passes."""
        _validate_sandbox_form_input("team_alpha_1", "field")

    def test_empty_string_rejected(self):
        """Empty string is rejected."""
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input("", "field")
        assert exc_info.value.status_code == 422
        assert "must not be empty" in exc_info.value.detail

    def test_whitespace_only_rejected(self):
        """Whitespace-only string is rejected."""
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input("   ", "field")
        assert exc_info.value.status_code == 422
        assert "must not be empty" in exc_info.value.detail

    def test_exceeds_max_length(self):
        """String exceeding max length is rejected."""
        long_input = "a" * (_SANDBOX_INPUT_MAX_LENGTH + 1)
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input(long_input, "field")
        assert exc_info.value.status_code == 422
        assert "exceeds maximum length" in exc_info.value.detail

    def test_at_max_length_passes(self):
        """String at exactly max length passes."""
        exact_input = "a" * _SANDBOX_INPUT_MAX_LENGTH
        _validate_sandbox_form_input(exact_input, "field")

    def test_html_injection_rejected(self):
        """HTML/script injection is rejected."""
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input("<script>alert(1)</script>", "field")
        assert exc_info.value.status_code == 422
        assert "invalid characters" in exc_info.value.detail

    def test_sql_injection_rejected(self):
        """SQL injection attempt is rejected."""
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input("'; DROP TABLE users;--", "field")
        assert exc_info.value.status_code == 422

    def test_path_traversal_rejected(self):
        """Path traversal is rejected (contains / and ..)."""
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input("../../etc/passwd", "field")
        assert exc_info.value.status_code == 422

    def test_shell_injection_rejected(self):
        """Shell metacharacters are rejected."""
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input("$(whoami)", "field")
        assert exc_info.value.status_code == 422

    def test_newline_rejected(self):
        """Newlines are rejected to prevent header injection."""
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input("line1\nline2", "field")
        assert exc_info.value.status_code == 422

    @pytest.mark.parametrize(
        "bad_input",
        [
            "value;cmd",
            "value|pipe",
            "value&bg",
            'value"quoted',
            "value'quoted",
            "value{brace}",
            "value=equals",
            "value+plus",
        ],
        ids=["semicolon", "pipe", "ampersand", "double_quote", "single_quote", "braces", "equals", "plus"],
    )
    def test_special_characters_rejected(self, bad_input):
        """Various special characters are rejected."""
        with pytest.raises(sandbox_mod.HTTPException) as exc_info:
            _validate_sandbox_form_input(bad_input, "field")
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Tests: Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_version_is_semver(self):
        """Version follows semantic versioning format."""
        # Standard
        import re

        assert re.match(r"^\d+\.\d+\.\d+$", SANDBOX_SERVICE_VERSION)

    def test_service_name_non_empty(self):
        """Service name is a non-empty string."""
        assert isinstance(SANDBOX_SERVICE_NAME, str)
        assert len(SANDBOX_SERVICE_NAME) > 0
