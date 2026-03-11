# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/sandbox_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Hugh Hennelly

Sandbox page object for Policy Testing Sandbox admin UI features.
"""

# Third-Party
from playwright.sync_api import Locator

# Local
from .base_page import BasePage


class SandboxPage(BasePage):
    """Page object for the Policy Testing Sandbox admin panel.

    This page manages the Sandbox tab where users can:
    - Simulate individual policy evaluations
    - Run batch tests against policy drafts
    - Compare regression results between policy versions
    - Manage reusable test suites
    """

    # ==================== Panel Elements ====================

    @property
    def sandbox_panel(self) -> Locator:
        """Sandbox panel container."""
        return self.page.locator("#sandbox-panel")

    @property
    def sandbox_tab(self) -> Locator:
        """Sandbox tab button in the sidebar."""
        return self.page.locator('[data-testid="sandbox-tab"]')

    # ==================== Sub-tab Navigation ====================

    @property
    def simulate_sub_tab(self) -> Locator:
        """Simulate sub-tab within sandbox panel."""
        return self.sandbox_panel.locator("text=Simulate")

    @property
    def batch_sub_tab(self) -> Locator:
        """Batch sub-tab within sandbox panel."""
        return self.sandbox_panel.locator("text=Batch")

    @property
    def regression_sub_tab(self) -> Locator:
        """Regression sub-tab within sandbox panel."""
        return self.sandbox_panel.locator("text=Regression")

    @property
    def test_suites_sub_tab(self) -> Locator:
        """Test Suites sub-tab within sandbox panel."""
        return self.sandbox_panel.locator("text=Test Suites")

    # ==================== Simulate Form Elements ====================

    @property
    def simulate_form(self) -> Locator:
        """Simulation form element."""
        return self.page.locator("#simulationForm")

    @property
    def policy_draft_select(self) -> Locator:
        """Policy draft dropdown."""
        return self.page.locator("#policyDraft")

    @property
    def subject_email_input(self) -> Locator:
        """Subject email input field."""
        return self.page.locator("#subjectEmail")

    @property
    def subject_team_input(self) -> Locator:
        """Subject team input field."""
        return self.page.locator("#subjectTeam")

    @property
    def subject_roles_input(self) -> Locator:
        """Subject roles input field."""
        return self.page.locator("#subjectRoles")

    @property
    def action_input(self) -> Locator:
        """Action input field."""
        return self.page.locator("#action")

    @property
    def resource_type_input(self) -> Locator:
        """Resource type input field."""
        return self.page.locator("#resourceType")

    @property
    def resource_id_input(self) -> Locator:
        """Resource ID input field."""
        return self.page.locator("#resourceId")

    @property
    def resource_server_input(self) -> Locator:
        """Resource server input field."""
        return self.page.locator("#resourceServer")

    @property
    def expected_decision_select(self) -> Locator:
        """Expected decision dropdown."""
        return self.page.locator("#expectedDecision")

    @property
    def simulation_results(self) -> Locator:
        """Simulation results container."""
        return self.page.locator("#simulationResults")

    @property
    def loading_indicator(self) -> Locator:
        """Loading indicator shown during simulation."""
        return self.page.locator("#loadingIndicator")

    # ==================== Batch Form Elements ====================

    @property
    def batch_form(self) -> Locator:
        """Batch test form element."""
        return self.page.locator("#batchForm")

    @property
    def batch_policy_draft_select(self) -> Locator:
        """Batch policy draft dropdown."""
        return self.page.locator("#batchPolicyDraft")

    @property
    def test_suite_select(self) -> Locator:
        """Test suite dropdown."""
        return self.page.locator("#testSuite")

    @property
    def parallel_execution_checkbox(self) -> Locator:
        """Parallel execution checkbox."""
        return self.page.locator("#parallelExecution")

    @property
    def batch_results(self) -> Locator:
        """Batch test results container."""
        return self.page.locator("#batchResults")

    # ==================== Regression Form Elements ====================

    @property
    def regression_form(self) -> Locator:
        """Regression testing form element."""
        return self.page.locator("#regressionForm")

    @property
    def regression_policy_draft_select(self) -> Locator:
        """Regression policy draft dropdown."""
        return self.page.locator("#regressionPolicyDraft")

    @property
    def baseline_version_input(self) -> Locator:
        """Baseline version input field."""
        return self.page.locator("#baselineVersion")

    @property
    def replay_days_input(self) -> Locator:
        """Replay days input field."""
        return self.page.locator("#replayDays")

    @property
    def sample_size_input(self) -> Locator:
        """Sample size input field."""
        return self.page.locator("#sampleSize")

    # ==================== Navigation Methods ====================

    def navigate_to_sandbox_tab(self) -> None:
        """Navigate to Sandbox tab and wait for panel to be visible."""
        self.sidebar.click_sandbox_tab()
        self.wait_for_visible(self.sandbox_panel)

    # ==================== Simulate Actions ====================

    def fill_simulate_form(
        self,
        policy_draft: str = "",
        email: str = "test@example.com",
        team: str = "team-a",
        roles: str = "developer",
        action: str = "tools.invoke",
        resource_type: str = "tool",
        resource_id: str = "test-tool",
        resource_server: str = "",
        expected_decision: str = "ALLOW",
    ) -> None:
        """Fill the simulation form with provided values.

        Args:
            policy_draft: Policy draft ID to select
            email: Subject email
            team: Subject team
            roles: Comma-separated roles
            action: Action to simulate
            resource_type: Resource type
            resource_id: Resource ID
            resource_server: Resource server (optional)
            expected_decision: Expected decision (ALLOW/DENY)
        """
        if policy_draft:
            self.policy_draft_select.select_option(policy_draft)

        self.fill_locator(self.subject_email_input, email)
        self.fill_locator(self.subject_team_input, team)
        self.fill_locator(self.subject_roles_input, roles)
        self.fill_locator(self.action_input, action)
        self.fill_locator(self.resource_type_input, resource_type)
        self.fill_locator(self.resource_id_input, resource_id)

        if resource_server:
            self.fill_locator(self.resource_server_input, resource_server)

        self.expected_decision_select.select_option(expected_decision)

    def submit_simulate_form(self) -> None:
        """Submit the simulation form."""
        submit_btn = self.simulate_form.locator('button[type="submit"]')
        self.click_locator(submit_btn)

    def wait_for_simulation_results(self, timeout: int | None = None) -> None:
        """Wait for simulation results to appear."""
        self.wait_for_visible(self.simulation_results, timeout=timeout or self.timeout)

    # ==================== Batch Actions ====================

    def fill_batch_form(self, policy_draft: str = "", test_suite: str = "", parallel: bool = True) -> None:
        """Fill the batch test form.

        Args:
            policy_draft: Policy draft ID to select
            test_suite: Test suite to select
            parallel: Whether to enable parallel execution
        """
        if policy_draft:
            self.batch_policy_draft_select.select_option(policy_draft)
        if test_suite:
            self.test_suite_select.select_option(test_suite)
        if not parallel:
            # Uncheck if currently checked
            if self.parallel_execution_checkbox.is_checked():
                self.click_locator(self.parallel_execution_checkbox)

    def submit_batch_form(self) -> None:
        """Submit the batch test form."""
        submit_btn = self.batch_form.locator('button[type="submit"]')
        self.click_locator(submit_btn)

    # ==================== Regression Actions ====================

    def fill_regression_form(
        self,
        policy_draft: str = "",
        baseline_version: str = "",
        replay_days: str = "7",
        sample_size: str = "100",
    ) -> None:
        """Fill the regression testing form.

        Args:
            policy_draft: Policy draft ID to select
            baseline_version: Baseline version identifier
            replay_days: Number of days to replay
            sample_size: Sample size for regression test
        """
        if policy_draft:
            self.regression_policy_draft_select.select_option(policy_draft)
        if baseline_version:
            self.fill_locator(self.baseline_version_input, baseline_version)
        self.fill_locator(self.replay_days_input, replay_days)
        self.fill_locator(self.sample_size_input, sample_size)

    def submit_regression_form(self) -> None:
        """Submit the regression test form."""
        submit_btn = self.regression_form.locator('button[type="submit"]')
        self.click_locator(submit_btn)
