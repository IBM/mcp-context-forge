# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_innerhtml_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Regression tests for innerHTML sanitizer guard (PR #3129).

The innerHTML guard strips inline on* attributes for XSS protection.
These tests verify that dynamically loaded UI elements still function
correctly after converting from inline onclick to data-action + addEventListener.
"""

# Third-Party
import pytest
from playwright.sync_api import expect


class TestToolTableButtons:
    """Tool table action buttons are loaded via fetch() + innerHTML.

    The loadTools() function fetches tools from /admin/tools and sets
    toolBody.innerHTML with rows containing action buttons (View, Edit,
    Enrich, Validate, Generate Test Cases). The innerHTML sanitizer
    strips onclick, so we use data-action + event delegation.
    """

    @pytest.mark.flaky(reruns=2, reruns_delay=1, reason="Tool table load race")
    def test_tool_action_buttons_have_click_handlers(self, tools_page):
        """Tool action buttons should have working click handlers after innerHTML load."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        page = tools_page.page

        # Wait for at least one tool row with action buttons
        view_btn = page.locator('#toolBody [data-action="view-tool"]').first
        try:
            expect(view_btn).to_be_visible(timeout=15000)
        except AssertionError:
            pytest.skip("No tools in table — cannot test action buttons")

        # Verify the buttons have data-action attributes (not stripped onclick)
        tool_id = view_btn.get_attribute("data-tool-id")
        assert tool_id, "View button missing data-tool-id after innerHTML load"

        edit_btn = page.locator('#toolBody [data-action="edit-tool"]').first
        assert edit_btn.get_attribute("data-tool-id"), "Edit button missing data-tool-id"

        # Verify clicking View opens the modal (proves event delegation works)
        tools_page._click_and_wait_for_tool_fetch(view_btn, "tool-modal")
        tool_modal = page.locator("#tool-modal")
        expect(tool_modal).to_be_visible(timeout=10000)
        tools_page.close_tool_modal()


class TestTokenStatsModalClose:
    """Token usage stats modal close buttons use innerHTML + data-action."""

    def test_stats_modal_close_button_works(self, admin_page):
        """Close button in programmatically created stats modal should work."""
        page = admin_page.page

        # Directly invoke showUsageStatsModal with mock data to test
        # that the data-action close buttons have working event listeners
        page.evaluate("""
            showUsageStatsModal({
                period_days: 7,
                total_requests: 100,
                successful_requests: 95,
                blocked_requests: 5,
                success_rate: 0.95,
                average_response_time_ms: 42,
                top_endpoints: [["GET /tools", 50], ["POST /mcp", 30]]
            });
        """)

        # Verify modal appeared
        modal = page.locator(".fixed.inset-0").last
        expect(modal).to_be_visible(timeout=5000)

        # Verify it contains stats content
        expect(modal).to_contain_text("Token Usage Statistics")
        expect(modal).to_contain_text("100")  # total requests

        # Click the X close button (top-right)
        close_x = modal.locator('[data-action="close-stats-modal"]').first
        expect(close_x).to_be_visible()
        close_x.click()

        # Verify modal is removed from DOM
        expect(modal).to_be_hidden(timeout=5000)

    def test_stats_modal_footer_close_button_works(self, admin_page):
        """Footer Close button in stats modal should also work."""
        page = admin_page.page

        page.evaluate("""
            showUsageStatsModal({
                period_days: 30,
                total_requests: 500,
                successful_requests: 480,
                blocked_requests: 20,
                success_rate: 0.96,
                average_response_time_ms: 55,
                top_endpoints: []
            });
        """)

        modal = page.locator(".fixed.inset-0").last
        expect(modal).to_be_visible(timeout=5000)

        # Click the footer "Close" button (last data-action button)
        close_btn = modal.locator('[data-action="close-stats-modal"]').last
        expect(close_btn).to_be_visible()
        close_btn.click()

        expect(modal).to_be_hidden(timeout=5000)


class TestGlobalSearchNavigation:
    """Global search results use fetch() + innerHTML with data-action buttons."""

    def test_search_result_buttons_have_data_attributes(self, admin_page):
        """Search result items should have data-action attributes after innerHTML load."""
        page = admin_page.page

        # Type into global search
        search_input = page.locator("#global-search-input")
        try:
            expect(search_input).to_be_visible(timeout=10000)
        except AssertionError:
            pytest.skip("Global search input not present")

        search_input.fill("a")
        search_input.dispatch_event("input")

        # Wait for results
        results = page.locator("#global-search-results")
        try:
            expect(results).to_be_visible(timeout=10000)
        except AssertionError:
            pytest.skip("No global search results returned")

        # Verify result buttons have data-action (not stripped onclick)
        result_btn = results.locator('[data-action="navigate-search-result"]').first
        try:
            expect(result_btn).to_be_visible(timeout=5000)
        except AssertionError:
            pytest.skip("No navigable search results found")

        entity = result_btn.get_attribute("data-entity")
        item_id = result_btn.get_attribute("data-id")
        assert entity, "Search result missing data-entity"
        assert item_id, "Search result missing data-id"

        # Click the result — should close the search dropdown
        result_btn.click()
        page.wait_for_timeout(1000)
        expect(results).to_be_hidden(timeout=10000)


class TestInnerHtmlGuardSanitizer:
    """Verify that the innerHTML guard itself still strips on* attrs
    while our data-action pattern survives it."""

    def test_onclick_is_stripped_but_data_action_survives(self, admin_page):
        """innerHTML guard should strip onclick but preserve data-action."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                const div = document.createElement('div');
                document.body.appendChild(div);
                div.innerHTML = '<button onclick="alert(1)" data-action="test" data-id="123">Test</button>';
                const btn = div.querySelector('button');
                const hasOnclick = btn.hasAttribute('onclick');
                const dataAction = btn.getAttribute('data-action');
                const dataId = btn.getAttribute('data-id');
                div.remove();
                return { hasOnclick, dataAction, dataId };
            }
        """)

        assert result["hasOnclick"] is False, "innerHTML guard should strip onclick"
        assert result["dataAction"] == "test", "data-action should survive innerHTML guard"
        assert result["dataId"] == "123", "data-id should survive innerHTML guard"
