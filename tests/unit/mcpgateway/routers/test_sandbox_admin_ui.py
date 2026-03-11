# -*- coding: utf-8 -*-
"""Unit tests for sandbox admin UI routes and template rendering.
Location: ./tests/unit/mcpgateway/routers/test_sandbox_admin_ui.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Hugh Hennelly

Tests the HTMX-driven admin UI endpoints (simulate_form_submit) and verifies
that sandbox HTML templates render correctly with expected context variables.

Covers Brian-Hussey review items:
- 4ii: Admin UI routes
- 4vi: Template rendering tests

Related to Issue #2226: Policy testing and simulation sandbox
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.routes.sandbox import simulate_form_submit
from mcpgateway.schemas import SimulationResult
from plugins.unified_pdp.pdp_models import Decision

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sandbox_service():
    """Return a fully-mocked SandboxService with AsyncMock methods."""
    svc = MagicMock()
    svc.simulate_single = AsyncMock()
    svc.run_batch = AsyncMock()
    svc.run_regression = AsyncMock()
    return svc


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    return {"email": "test@example.com", "is_admin": True}


@pytest.fixture
def mock_request():
    """Mock FastAPI request with template support."""
    request = MagicMock()

    # Mock the TemplateResponse to capture what gets rendered
    def mock_template_response(req, template_name, context, **kwargs):
        """Capture template rendering arguments."""
        response = MagicMock()
        response.template_name = template_name
        response.context = context
        response.status_code = kwargs.get("status_code", 200)
        return response

    request.app.state.templates.TemplateResponse = mock_template_response
    return request


@pytest.fixture
def sample_simulation_result():
    """Create a sample simulation result for template rendering."""
    return SimulationResult(
        test_case_id="tc-1",
        actual_decision=Decision.ALLOW,
        expected_decision=Decision.ALLOW,
        passed=True,
        execution_time_ms=42.5,
        policy_draft_id="draft-123",
        reason="All engines allowed",
        matching_policies=["default-allow"],
    )


@pytest.fixture
def sample_failed_result():
    """Create a failing simulation result for template rendering."""
    return SimulationResult(
        test_case_id="tc-2",
        actual_decision=Decision.DENY,
        expected_decision=Decision.ALLOW,
        passed=False,
        execution_time_ms=55.0,
        policy_draft_id="draft-456",
        reason="Permission denied by RBAC engine",
        matching_policies=["deny-all"],
    )


# ---------------------------------------------------------------------------
# Tests: Admin UI Form Submit - Success Paths
# ---------------------------------------------------------------------------


class TestSimulateFormSubmitSuccess:
    """Tests for POST /sandbox/sandbox/simulate (HTMX form handler)."""

    @pytest.mark.asyncio
    async def test_form_submit_renders_results_template(self, mock_request, mock_sandbox_service, mock_user, sample_simulation_result):
        """Successful form submit renders sandbox_simulate_results.html."""
        mock_sandbox_service.simulate_single.return_value = sample_simulation_result

        with (
            patch("mcpgateway.schemas.TestCase") as mock_tc,
            patch("plugins.unified_pdp.pdp_models.Subject"),
            patch("plugins.unified_pdp.pdp_models.Resource"),
            patch("plugins.unified_pdp.pdp_models.Context"),
            patch("plugins.unified_pdp.pdp_models.Decision") as mock_decision_cls,
        ):
            mock_decision_cls.ALLOW = Decision.ALLOW
            mock_decision_cls.DENY = Decision.DENY
            mock_tc.return_value = MagicMock()

            result = await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="dev@example.com",
                subject_roles="developer",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        assert result.template_name == "sandbox_simulate_results.html"
        assert "result" in result.context
        mock_sandbox_service.simulate_single.assert_called_once()

    @pytest.mark.asyncio
    async def test_form_submit_passes_explanation_flag(self, mock_request, mock_sandbox_service, mock_user, sample_simulation_result):
        """Form submit requests explanations from sandbox service."""
        mock_sandbox_service.simulate_single.return_value = sample_simulation_result

        with (
            patch("mcpgateway.schemas.TestCase") as mock_tc,
            patch("plugins.unified_pdp.pdp_models.Subject"),
            patch("plugins.unified_pdp.pdp_models.Resource"),
            patch("plugins.unified_pdp.pdp_models.Context"),
            patch("plugins.unified_pdp.pdp_models.Decision") as mock_decision_cls,
        ):
            mock_decision_cls.ALLOW = Decision.ALLOW
            mock_decision_cls.DENY = Decision.DENY
            mock_tc.return_value = MagicMock()

            await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="dev@example.com",
                subject_roles="developer",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        call_kwargs = mock_sandbox_service.simulate_single.call_args[1]
        assert call_kwargs["include_explanation"] is True

    @pytest.mark.asyncio
    async def test_form_submit_multiple_roles(self, mock_request, mock_sandbox_service, mock_user, sample_simulation_result):
        """Form submit correctly parses comma-separated roles."""
        mock_sandbox_service.simulate_single.return_value = sample_simulation_result

        with (
            patch("mcpgateway.schemas.TestCase") as mock_tc,
            patch("plugins.unified_pdp.pdp_models.Subject") as mock_subject_cls,
            patch("plugins.unified_pdp.pdp_models.Resource"),
            patch("plugins.unified_pdp.pdp_models.Context"),
            patch("plugins.unified_pdp.pdp_models.Decision") as mock_decision_cls,
        ):
            mock_decision_cls.ALLOW = Decision.ALLOW
            mock_decision_cls.DENY = Decision.DENY
            mock_tc.return_value = MagicMock()

            await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="admin@example.com",
                subject_roles="developer, team_admin, viewer",
                subject_team_id="team-1",
                action="resources.read",
                resource_type="resource",
                resource_id="doc-1",
                resource_server="server-1",
                expected_decision="deny",
                sandbox=mock_sandbox_service,
            )

        # Verify Subject was called with parsed roles
        subject_call = mock_subject_cls.call_args
        assert "developer" in subject_call[1]["roles"]
        assert "team_admin" in subject_call[1]["roles"]
        assert "viewer" in subject_call[1]["roles"]


# ---------------------------------------------------------------------------
# Tests: Admin UI Form Submit - Error Paths
# ---------------------------------------------------------------------------


class TestSimulateFormSubmitErrors:
    """Tests for error handling in simulate_form_submit."""

    @pytest.mark.asyncio
    async def test_form_submit_renders_error_on_exception(self, mock_request, mock_sandbox_service, mock_user):
        """Service exception renders sandbox_simulate_error.html."""
        mock_sandbox_service.simulate_single.side_effect = RuntimeError("PDP evaluation failed")

        with (
            patch("mcpgateway.schemas.TestCase") as mock_tc,
            patch("plugins.unified_pdp.pdp_models.Subject"),
            patch("plugins.unified_pdp.pdp_models.Resource"),
            patch("plugins.unified_pdp.pdp_models.Context"),
            patch("plugins.unified_pdp.pdp_models.Decision") as mock_decision_cls,
        ):
            mock_decision_cls.ALLOW = Decision.ALLOW
            mock_decision_cls.DENY = Decision.DENY
            mock_tc.return_value = MagicMock()

            result = await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="dev@example.com",
                subject_roles="developer",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        assert result.template_name == "sandbox_simulate_error.html"
        assert "error_message" in result.context
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_form_submit_validation_empty_policy_id(self, mock_request, mock_sandbox_service, mock_user):
        """Empty policy_draft_id raises 422 via input validation."""
        with pytest.raises(HTTPException) as exc_info:
            await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="",
                subject_email="dev@example.com",
                subject_roles="developer",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        assert exc_info.value.status_code == 422
        assert "policy_draft_id" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_form_submit_validation_xss_in_email(self, mock_request, mock_sandbox_service, mock_user):
        """XSS attempt in subject_email raises 422."""
        with pytest.raises(HTTPException) as exc_info:
            await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="<script>alert(1)</script>",
                subject_roles="developer",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        assert exc_info.value.status_code == 422
        assert "invalid characters" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_form_submit_validation_sql_injection_in_action(self, mock_request, mock_sandbox_service, mock_user):
        """SQL injection attempt in action field raises 422."""
        with pytest.raises(HTTPException) as exc_info:
            await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="dev@example.com",
                subject_roles="developer",
                subject_team_id=None,
                action="'; DROP TABLE users;--",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_form_submit_validation_invalid_role(self, mock_request, mock_sandbox_service, mock_user):
        """Invalid characters in a role raises 422."""
        with pytest.raises(HTTPException) as exc_info:
            await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="dev@example.com",
                subject_roles="developer, $(whoami)",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_form_submit_reraises_http_exception(self, mock_request, mock_sandbox_service, mock_user):
        """HTTPException from service is re-raised, not caught."""
        mock_sandbox_service.simulate_single.side_effect = HTTPException(status_code=404, detail="Draft not found")

        with (
            patch("mcpgateway.schemas.TestCase") as mock_tc,
            patch("plugins.unified_pdp.pdp_models.Subject"),
            patch("plugins.unified_pdp.pdp_models.Resource"),
            patch("plugins.unified_pdp.pdp_models.Context"),
            patch("plugins.unified_pdp.pdp_models.Decision") as mock_decision_cls,
        ):
            mock_decision_cls.ALLOW = Decision.ALLOW
            mock_decision_cls.DENY = Decision.DENY
            mock_tc.return_value = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await simulate_form_submit(
                    request=mock_request,
                    current_user=mock_user,
                    policy_draft_id="draft-123",
                    subject_email="dev@example.com",
                    subject_roles="developer",
                    subject_team_id=None,
                    action="tools.invoke",
                    resource_type="tool",
                    resource_id="db-query",
                    resource_server=None,
                    expected_decision="allow",
                    sandbox=mock_sandbox_service,
                )

            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Template Rendering Context
# ---------------------------------------------------------------------------


class TestTemplateRenderingContext:
    """Tests verifying template context variables are correctly populated."""

    @pytest.mark.asyncio
    async def test_results_template_receives_simulation_result(self, mock_request, mock_sandbox_service, mock_user, sample_simulation_result):
        """Results template receives the full SimulationResult object."""
        mock_sandbox_service.simulate_single.return_value = sample_simulation_result

        with (
            patch("mcpgateway.schemas.TestCase") as mock_tc,
            patch("plugins.unified_pdp.pdp_models.Subject"),
            patch("plugins.unified_pdp.pdp_models.Resource"),
            patch("plugins.unified_pdp.pdp_models.Context"),
            patch("plugins.unified_pdp.pdp_models.Decision") as mock_decision_cls,
        ):
            mock_decision_cls.ALLOW = Decision.ALLOW
            mock_decision_cls.DENY = Decision.DENY
            mock_tc.return_value = MagicMock()

            result = await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="dev@example.com",
                subject_roles="developer",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        sim_result = result.context["result"]
        assert sim_result.passed is True
        assert sim_result.execution_time_ms == 42.5
        assert sim_result.policy_draft_id == "draft-123"

    @pytest.mark.asyncio
    async def test_error_template_receives_error_message(self, mock_request, mock_sandbox_service, mock_user):
        """Error template receives the error message string."""
        mock_sandbox_service.simulate_single.side_effect = ValueError("Invalid draft config")

        with (
            patch("mcpgateway.schemas.TestCase") as mock_tc,
            patch("plugins.unified_pdp.pdp_models.Subject"),
            patch("plugins.unified_pdp.pdp_models.Resource"),
            patch("plugins.unified_pdp.pdp_models.Context"),
            patch("plugins.unified_pdp.pdp_models.Decision") as mock_decision_cls,
        ):
            mock_decision_cls.ALLOW = Decision.ALLOW
            mock_decision_cls.DENY = Decision.DENY
            mock_tc.return_value = MagicMock()

            result = await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-123",
                subject_email="dev@example.com",
                subject_roles="developer",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        assert result.template_name == "sandbox_simulate_error.html"
        assert "Invalid draft config" in result.context["error_message"]

    @pytest.mark.asyncio
    async def test_failed_result_template_shows_failure(self, mock_request, mock_sandbox_service, mock_user, sample_failed_result):
        """Failed result renders results template with passed=False."""
        mock_sandbox_service.simulate_single.return_value = sample_failed_result

        with (
            patch("mcpgateway.schemas.TestCase") as mock_tc,
            patch("plugins.unified_pdp.pdp_models.Subject"),
            patch("plugins.unified_pdp.pdp_models.Resource"),
            patch("plugins.unified_pdp.pdp_models.Context"),
            patch("plugins.unified_pdp.pdp_models.Decision") as mock_decision_cls,
        ):
            mock_decision_cls.ALLOW = Decision.ALLOW
            mock_decision_cls.DENY = Decision.DENY
            mock_tc.return_value = MagicMock()

            result = await simulate_form_submit(
                request=mock_request,
                current_user=mock_user,
                policy_draft_id="draft-456",
                subject_email="dev@example.com",
                subject_roles="developer",
                subject_team_id=None,
                action="tools.invoke",
                resource_type="tool",
                resource_id="db-query",
                resource_server=None,
                expected_decision="allow",
                sandbox=mock_sandbox_service,
            )

        assert result.template_name == "sandbox_simulate_results.html"
        sim_result = result.context["result"]
        assert sim_result.passed is False
        assert sim_result.actual_decision == Decision.DENY
