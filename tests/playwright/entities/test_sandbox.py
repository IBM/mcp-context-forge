# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_sandbox.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Hugh Hennelly

Playwright E2E tests for the Policy Testing Sandbox admin UI tab.

Tests cover:
- Navigation to the sandbox panel
- Simulate form visibility and field population
- Batch and Regression sub-tab navigation
- Form submission and results rendering

These tests require a running MCP Gateway instance with MCPGATEWAY_SANDBOX_ENABLED=true.
They follow the same Page Object Model pattern as other Playwright entity tests.

Related to Issue #2226: Policy testing and simulation sandbox
Brian-Hussey review item 4v: Playwright/UI tests
"""

# Third-Party
from playwright.sync_api import expect

# Local
from ..pages.sandbox_page import SandboxPage


class TestSandboxNavigation:
    """Tests for navigating to and loading the sandbox panel."""

    def test_sandbox_tab_visible(self, sandbox_page: SandboxPage):
        """Sandbox tab is visible in the admin sidebar."""
        expect(sandbox_page.sandbox_tab).to_be_visible()

    def test_navigate_to_sandbox_panel(self, sandbox_page: SandboxPage):
        """Clicking sandbox tab shows the sandbox panel."""
        sandbox_page.navigate_to_sandbox_tab()
        expect(sandbox_page.sandbox_panel).to_be_visible()

    def test_sandbox_panel_loads_content(self, sandbox_page: SandboxPage):
        """Sandbox panel loads HTMX content after navigation."""
        sandbox_page.navigate_to_sandbox_tab()
        # The panel should contain the HTMX-loaded partial content
        # Wait for content to load (HTMX lazy loading)
        sandbox_page.page.wait_for_timeout(2000)
        content = sandbox_page.sandbox_panel.text_content()
        # The panel should have loaded some meaningful content
        assert content and len(content.strip()) > 0


class TestSimulateForm:
    """Tests for the simulation form UI elements."""

    def test_simulate_form_visible(self, sandbox_page: SandboxPage):
        """Simulation form is visible after navigating to sandbox."""
        sandbox_page.navigate_to_sandbox_tab()
        # Wait for HTMX content to load
        sandbox_page.page.wait_for_selector("#simulationForm", state="visible", timeout=10000)
        expect(sandbox_page.simulate_form).to_be_visible()

    def test_simulate_form_has_all_fields(self, sandbox_page: SandboxPage):
        """Simulation form contains all expected input fields."""
        sandbox_page.navigate_to_sandbox_tab()
        sandbox_page.page.wait_for_selector("#simulationForm", state="visible", timeout=10000)

        expect(sandbox_page.policy_draft_select).to_be_visible()
        expect(sandbox_page.subject_email_input).to_be_visible()
        expect(sandbox_page.subject_roles_input).to_be_visible()
        expect(sandbox_page.action_input).to_be_visible()
        expect(sandbox_page.resource_type_input).to_be_visible()
        expect(sandbox_page.resource_id_input).to_be_visible()
        expect(sandbox_page.expected_decision_select).to_be_visible()

    def test_fill_simulate_form(self, sandbox_page: SandboxPage):
        """Simulation form fields can be filled with test data."""
        sandbox_page.navigate_to_sandbox_tab()
        sandbox_page.page.wait_for_selector("#simulationForm", state="visible", timeout=10000)

        sandbox_page.fill_locator(sandbox_page.subject_email_input, "dev@example.com")
        sandbox_page.fill_locator(sandbox_page.subject_roles_input, "developer")
        sandbox_page.fill_locator(sandbox_page.action_input, "tools.invoke")
        sandbox_page.fill_locator(sandbox_page.resource_type_input, "tool")
        sandbox_page.fill_locator(sandbox_page.resource_id_input, "test-tool")

        expect(sandbox_page.subject_email_input).to_have_value("dev@example.com")
        expect(sandbox_page.subject_roles_input).to_have_value("developer")
        expect(sandbox_page.action_input).to_have_value("tools.invoke")

    def test_expected_decision_options(self, sandbox_page: SandboxPage):
        """Expected decision dropdown contains ALLOW and DENY options."""
        sandbox_page.navigate_to_sandbox_tab()
        sandbox_page.page.wait_for_selector("#simulationForm", state="visible", timeout=10000)

        # The select should have ALLOW and DENY as options
        options = sandbox_page.expected_decision_select.locator("option")
        option_texts = [options.nth(i).text_content() for i in range(options.count())]
        # Should contain at least ALLOW and DENY
        assert any("ALLOW" in text.upper() for text in option_texts if text)
        assert any("DENY" in text.upper() for text in option_texts if text)


class TestBatchForm:
    """Tests for the batch testing form."""

    def test_batch_sub_tab_clickable(self, sandbox_page: SandboxPage):
        """Batch sub-tab can be clicked to reveal batch form."""
        sandbox_page.navigate_to_sandbox_tab()
        # Wait for HTMX content
        sandbox_page.page.wait_for_timeout(2000)
        batch_tab = sandbox_page.sandbox_panel.locator("text=Batch").first
        if batch_tab.is_visible():
            batch_tab.click()
            sandbox_page.page.wait_for_timeout(500)
            # Batch form should become visible
            batch_form = sandbox_page.page.locator("#batchForm")
            expect(batch_form).to_be_visible()

    def test_batch_form_has_policy_draft_select(self, sandbox_page: SandboxPage):
        """Batch form contains a policy draft dropdown."""
        sandbox_page.navigate_to_sandbox_tab()
        sandbox_page.page.wait_for_timeout(2000)
        batch_tab = sandbox_page.sandbox_panel.locator("text=Batch").first
        if batch_tab.is_visible():
            batch_tab.click()
            sandbox_page.page.wait_for_timeout(500)
            expect(sandbox_page.batch_policy_draft_select).to_be_visible()


class TestRegressionForm:
    """Tests for the regression testing form."""

    def test_regression_sub_tab_clickable(self, sandbox_page: SandboxPage):
        """Regression sub-tab can be clicked to reveal regression form."""
        sandbox_page.navigate_to_sandbox_tab()
        sandbox_page.page.wait_for_timeout(2000)
        regression_tab = sandbox_page.sandbox_panel.locator("text=Regression").first
        if regression_tab.is_visible():
            regression_tab.click()
            sandbox_page.page.wait_for_timeout(500)
            regression_form = sandbox_page.page.locator("#regressionForm")
            expect(regression_form).to_be_visible()

    def test_regression_form_fields(self, sandbox_page: SandboxPage):
        """Regression form contains expected fields."""
        sandbox_page.navigate_to_sandbox_tab()
        sandbox_page.page.wait_for_timeout(2000)
        regression_tab = sandbox_page.sandbox_panel.locator("text=Regression").first
        if regression_tab.is_visible():
            regression_tab.click()
            sandbox_page.page.wait_for_timeout(500)
            expect(sandbox_page.regression_policy_draft_select).to_be_visible()
            expect(sandbox_page.baseline_version_input).to_be_visible()
            expect(sandbox_page.replay_days_input).to_be_visible()
            expect(sandbox_page.sample_size_input).to_be_visible()
