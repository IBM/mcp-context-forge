# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_htmx_interactions.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

HTMX and dynamic UI interaction tests for MCP Gateway Admin UI.
"""

# Standard
import re
from typing import Any, Dict

# Third-Party
from playwright.sync_api import expect, Page
import pytest


class TestHTMXInteractions:
    """HTMX and UI interaction tests for MCP Gateway Admin UI.

    Tests dynamic content loading, form submissions, modals, and real-time updates
    that are powered by HTMX in the admin interface.

    Examples:
        pytest tests/playwright/test_htmx_interactions.py
        pytest tests/playwright/test_htmx_interactions.py -v -k "tab_content"
    """

    @staticmethod
    def _prepare_tools_table(page: Page) -> None:
        """Ensure tools table is loaded."""
        page.wait_for_selector("#tools-panel:not(.hidden)")
        page.wait_for_selector("#tools-table-body")

    TAB_PANEL_CHECKS = [
        ("overview", "overview-panel", None),
        ("logs", "logs-panel", "#log-level-filter"),
        ("export-import", "export-import-panel", "#export-tools"),
        ("version-info", "version-info-panel", None),
        ("maintenance", "maintenance-panel", None),
        ("plugins", "plugins-panel", None),
        ("performance", "performance-panel", None),
        ("observability", "observability-panel", None),
        ("llm-chat", "llm-chat-panel", "#llm-connect-btn"),
        ("llm-settings", "llm-settings-panel", "#llm-settings-tab-providers"),
        ("mcp-registry", "mcp-registry-panel", "#mcp-registry-servers"),
        ("catalog", "catalog-panel", '[data-testid="server-list"]'),
        ("tools", "tools-panel", "#add-tool-form"),
        ("tool-ops", "tool-ops-panel", "#searchBox"),
        ("resources", "resources-panel", "#resources-search-input"),
        ("prompts", "prompts-panel", "#add-prompt-form"),
        ("gateways", "gateways-panel", "#gateways-search-input"),
        ("teams", "teams-panel", "#create-team-btn"),
        ("users", "users-panel", "#create-user-form"),
        ("tokens", "tokens-panel", "#create-token-form"),
        ("a2a-agents", "a2a-agents-panel", "#a2a-agents-search-input"),
        ("grpc-services", "grpc-services-panel", "#add-grpc-service-form"),
        ("roots", "roots-panel", "table"),
        ("metrics", "metrics-panel", "#top-performers-panel-tools"),
    ]

    @staticmethod
    def _find_tool(page: Page, tool_name: str, retries: int = 5):
        """Find a tool by name via the admin JSON endpoint."""
        for _ in range(retries):
            response = page.request.get("/admin/tools?per_page=500")
            if response.ok:
                payload = response.json()
                data = payload.get("data", [])
                for tool in data:
                    if tool.get("name") == tool_name:
                        return tool
            page.wait_for_timeout(200)
        return None

    @pytest.fixture(autouse=True)
    def setup(self, admin_page):
        """Login and setup before each test."""
        # admin_page fixture handles authentication

    def test_tab_content_loading_via_javascript(self, page: Page):
        """Test tab switching and content loading via JavaScript.

        Note: The admin interface uses JavaScript for tab switching, not HTMX.
        """
        # Start on the default tab (catalog)
        if page.locator("#catalog-panel").count() == 0:
            pytest.skip("Catalog panel not available in this UI configuration.")
        if not page.locator("#catalog-panel:not(.hidden)").is_visible():
            if page.locator("#tab-catalog").count() > 0:
                page.click("#tab-catalog")
                page.wait_for_selector("#catalog-panel:not(.hidden)", state="visible")
        expect(page.locator("#catalog-panel")).to_be_visible()

        # Click tools tab and verify content loads
        if page.locator("#tab-tools").count() > 0:
            page.click("#tab-tools")
            page.wait_for_selector("#tools-panel:not(.hidden)", state="visible")
            expect(page.locator("#tools-panel")).to_be_visible()
            expect(page.locator("#catalog-panel")).to_have_class(re.compile(r"hidden"))

            # Verify tools table is present
            self._prepare_tools_table(page)
            expect(page.locator("#tools-table")).to_be_visible()

        # Switch to resources tab
        if page.locator("#tab-resources").count() > 0:
            page.click("#tab-resources")
            page.wait_for_selector("#resources-panel:not(.hidden)", state="visible")
            expect(page.locator("#resources-panel")).to_be_visible()
            expect(page.locator("#tools-panel")).to_have_class(re.compile(r"hidden"))

        # Switch to prompts tab
        if page.locator("#tab-prompts").count() > 0:
            page.click("#tab-prompts")
            page.wait_for_selector("#prompts-panel:not(.hidden)", state="visible")
            expect(page.locator("#prompts-panel")).to_be_visible()

        # Switch to gateways tab
        if page.locator("#tab-gateways").count() > 0:
            page.click("#tab-gateways")
            page.wait_for_selector("#gateways-panel:not(.hidden)", state="visible")
            expect(page.locator("#gateways-panel")).to_be_visible()

    def test_tool_form_submission(self, page: Page, test_tool_data: Dict[str, Any]):
        """Test creating a new tool via the inline form."""
        # Navigate to tools tab
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

        # Fill the tool form
        form = page.locator("#add-tool-form")
        form.locator('[name="name"]').fill(test_tool_data["name"])
        form.locator('[name="url"]').fill(test_tool_data["url"])
        form.locator('[name="description"]').fill(test_tool_data["description"])
        form.locator('[name="integrationType"]').select_option(test_tool_data["integrationType"])

        # Submit the form and assert success response
        with page.expect_response(lambda response: "/admin/tools" in response.url and response.request.method == "POST") as response_info:
            form.locator('button[type="submit"]').click()
        response = response_info.value
        assert response.status < 400

        created_tool = self._find_tool(page, test_tool_data["name"])
        if created_tool:
            page.request.post(
                f"/admin/tools/{created_tool['id']}/delete",
                data="is_inactive_checked=false",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

    def test_tool_modal_interactions(self, admin_page: Page):
        """Test tool detail and edit modal functionality."""
        # Navigate to tools tab
        admin_page.click("#tab-tools")
        self._prepare_tools_table(admin_page)

        # Click on a tool's view button (if any tools exist)
        tool_rows = admin_page.locator("#tools-table-body tr")
        if tool_rows.count() == 0:
            pytest.skip("No tools available to view in this UI configuration.")

        # Click the first tool's View button
        tool_rows.first.locator('button:has-text("View")').click()

        # Wait for and verify the modal opens
        admin_page.wait_for_selector("#tool-modal:not(.hidden)", state="visible", timeout=10000)
        expect(admin_page.locator("#tool-modal")).to_be_visible()
        expect(admin_page.locator("#tool-details")).to_be_visible()

        # Close the modal
        admin_page.click('#tool-modal button:has-text("Close")')
        admin_page.wait_for_selector("#tool-modal.hidden", state="hidden", timeout=10000)

    def test_tool_edit_modal(self, admin_page: Page):
        """Test editing a tool via modal."""
        # Open edit modal for an existing tool (avoid cache-dependent list updates)
        admin_page.click("#tab-tools")
        self._prepare_tools_table(admin_page)
        tool_row = admin_page.locator("#tools-table-body tr").first
        if tool_row.count() == 0:
            pytest.skip("No tools available to edit in this UI configuration.")
        tool_row.locator('button:has-text("Edit")').click()

        # Wait for the edit modal to open
        admin_page.wait_for_selector("#tool-edit-modal:not(.hidden)", state="visible", timeout=10000)

        # Modify the tool name
        admin_page.fill("#edit-tool-custom-name", "Updated Tool Name")

        # Cancel to avoid mutating shared data in cached lists
        admin_page.click('#tool-edit-modal button:has-text("Cancel")')
        admin_page.wait_for_selector("#tool-edit-modal.hidden", state="hidden", timeout=10000)

    def test_tool_test_modal(self, admin_page: Page):
        """Test the tool testing functionality via modal."""
        # Navigate to tools tab
        admin_page.click("#tab-tools")
        self._prepare_tools_table(admin_page)

        # Check if there are any tools with a Test button
        tool_rows = admin_page.locator("#tools-table-body tr")
        if tool_rows.count() == 0:
            pytest.skip("No tools available to test in this UI configuration.")

        # Look for a Test button
        test_buttons = tool_rows.first.locator('button:has-text("Test")')
        if test_buttons.count() == 0:
            pytest.skip("No Test button available for tools.")

        test_buttons.first.click()

        # Wait for and verify test modal opens
        admin_page.wait_for_selector("#tool-test-modal:not(.hidden)", state="visible", timeout=10000)
        expect(admin_page.locator("#tool-test-modal")).to_be_visible()
        expect(admin_page.locator("#tool-test-form")).to_be_visible()

        # Close the modal
        admin_page.click('#tool-test-modal button:has-text("Close")')
        admin_page.wait_for_selector("#tool-test-modal.hidden", state="hidden", timeout=10000)

    def test_search_functionality_realtime(self, page: Page):
        """Test real-time search filtering."""
        # Navigate to servers/catalog tab
        page.click("#tab-catalog")
        page.wait_for_selector("#catalog-panel:not(.hidden)")

        # Type in search box
        search_input = page.locator('[data-testid="search-input"]')

        # Get initial server count
        initial_rows = page.locator('[data-testid="server-item"]').count()
        if initial_rows == 0:
            pytest.skip("No servers available to validate search filtering.")

        # Type a search term that likely won't match
        search_input.fill("xyznonexistentserver123")

        # Wait a moment for any filtering to apply
        page.wait_for_timeout(500)

        # Check if the table has been filtered (this depends on implementation)
        # If search is implemented client-side, rows should be hidden
        # If server-side, a request would be made
        filtered_visible = page.locator('[data-testid="server-item"]:visible').count()
        assert filtered_visible < initial_rows

        # Clear search
        search_input.fill("")
        page.wait_for_timeout(500)

        # Verify rows are restored
        restored_rows = page.locator('[data-testid="server-item"]').count()
        assert restored_rows == initial_rows

    def test_form_validation_feedback(self, page: Page):
        """Test form validation and error feedback."""
        # Navigate to tools tab
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

        # Try to submit empty form
        form = page.locator("#add-tool-form")
        submit_button = form.locator('button[type="submit"]')

        # Click submit without filling required fields
        submit_button.click()

        # Check for HTML5 validation (browser will prevent submission)
        # The name field should be invalid
        name_field = form.locator('[name="name"]')
        # Use evaluate to check validity in a more reliable way
        is_valid = name_field.evaluate("el => el.checkValidity()")
        assert is_valid is False

    def test_inactive_items_toggle(self, page: Page):
        """Test showing/hiding inactive items functionality."""
        # Test on tools tab
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

        # Find the inactive checkbox
        inactive_checkbox = page.locator("#show-inactive-tools")

        # Check initial state
        initial_checked = inactive_checkbox.is_checked()

        # Toggle the checkbox
        inactive_checkbox.click()

        # When checkbox is toggled, it triggers a page reload with query parameter
        # Wait for the page to reload
        page.wait_for_timeout(500)

        # After reload, verify the checkbox state persisted
        # The checkbox state is maintained via URL parameter
        inactive_checkbox_after = page.locator("#show-inactive-tools")
        assert inactive_checkbox_after.is_checked() != initial_checked

    def test_multi_select_tools_in_server_form(self, page: Page):
        """Test multi-select functionality for associating tools with servers."""
        # Navigate to catalog tab
        page.click("#tab-catalog")
        page.wait_for_selector("#catalog-panel:not(.hidden)")

        # Find the tools select element
        tools_select = page.locator("#associatedTools")

        # Check if there are options available
        options = tools_select.locator("option")
        if options.count() > 1:  # More than just the placeholder
            # Select multiple tools
            tools_select.select_option(index=[0, 1])

            # Verify pills are created (based on the JS code)
            pills_container = page.locator("#selectedToolsPills")
            expect(pills_container).to_be_visible()

            # Check warning if more than 6 tools selected
            if options.count() > 6:
                for i in range(7):
                    tools_select.select_option(index=list(range(i + 1)))

                warning = page.locator("#selectedToolsWarning")
                expect(warning).to_contain_text("more than 6 tools")

    def test_metrics_tab_data_loading(self, page: Page):
        """Test metrics tab and data visualization."""
        # Navigate to metrics tab
        if page.locator("#tab-metrics").count() == 0:
            pytest.skip("Metrics tab not available in this UI configuration.")
        page.click("#tab-metrics")
        page.wait_for_selector("#metrics-panel:not(.hidden)")

        # Prefer the top performers panel; aggregated metrics are hidden by default
        if page.locator("#top-performers-panel-tools").count() == 0:
            pytest.skip("Top performers panel not available in this UI configuration.")
        expect(page.locator("#top-performers-panel-tools")).to_be_visible()

        # Check if content is loaded (might be empty if no metrics)
        # assert page.locator("#top-tools-content-visible").count() > 0

        # Click refresh metrics button to trigger loading
        refresh_button = page.locator('button:has-text("Refresh Metrics")')
        if refresh_button.count() > 0:
            refresh_button.click()

        # Wait for the loadAggregatedMetrics function to potentially update content
        page.wait_for_timeout(3000)

        # Test expandable sections
        sections = ["top-tools", "top-resources", "top-servers", "top-prompts"]
        for section in sections:
            details = page.locator(f"#{section}-details")
            if details.is_visible():
                # Click to expand
                details.locator("summary").click()
                # Verify content area is created
                expect(page.locator(f"#{section}-content")).to_be_visible()

    def test_delete_with_confirmation(self, page: Page):
        """Test delete functionality with confirmation dialog."""
        # Use an existing tool row to verify confirmation dialog without mutating data
        page.click("#tab-tools")
        self._prepare_tools_table(page)

        tool_row = page.locator("#tools-table-body tr").first
        if tool_row.count() == 0:
            pytest.skip("No tools available for delete confirmation test.")

        dialog_seen = {"value": False}
        page.on("dialog", lambda dialog: (dialog.dismiss(), dialog_seen.__setitem__("value", True)))

        delete_form = tool_row.locator('form[action*="/delete"]')
        if delete_form.count() > 0:
            delete_form.locator('button[type="submit"]').click()

        # Wait a moment for dialog handling
        page.wait_for_timeout(500)
        assert dialog_seen["value"] is True

    @pytest.mark.slow
    def test_network_error_handling(self, page: Page):
        """Test UI behavior during network errors."""
        # Navigate to tools tab
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

        failed_requests = []

        def handle_request_failed(request):
            if "/admin/tools" in request.url and request.method == "POST":
                failed_requests.append(request.url)

        page.on("requestfailed", handle_request_failed)

        # Intercept network requests to simulate failure
        def handle_route(route):
            if "/admin/tools" in route.request.url and route.request.method == "POST":
                route.abort("failed")
            else:
                route.continue_()

        page.route("**/*", handle_route)

        # Try to create a tool
        form = page.locator("#add-tool-form")
        form.locator('[name="name"]').fill("Network Error Test")
        form.locator('[name="url"]').fill("http://example.com")

        # Select first available integration type
        integration_select = form.locator('[name="integrationType"]')
        options = integration_select.locator("option")
        if options.count() > 0:
            for i in range(options.count()):
                value = options.nth(i).get_attribute("value")
                if value:
                    integration_select.select_option(value)
                    break

        # Submit and expect error handling
        form.locator('button[type="submit"]').click()

        # Ensure the failed request is observed
        page.wait_for_timeout(1000)
        assert failed_requests, "Expected tool creation request to fail, but no failed request was captured."

        # Clean up route
        page.unroute("**/*")

    def test_version_info_tab(self, page: Page):
        """Test version info tab functionality."""
        if page.locator("#tab-version-info").count() == 0:
            pytest.skip("Version info tab not available in this UI configuration.")

        # Click version info tab
        page.click("#tab-version-info")

        # This might trigger HTMX request based on setupHTMXHooks
        # Wait for content to load
        page.wait_for_selector("#version-info-panel:not(.hidden)")

        # Verify panel is visible
        expect(page.locator("#version-info-panel")).to_be_visible()

    @pytest.mark.parametrize(
        "tab_name,panel_id,selector",
        TAB_PANEL_CHECKS,
    )
    def test_all_tabs_navigation(self, page: Page, tab_name: str, panel_id: str, selector: str | None):
        """Test navigation to all available tabs and key controls."""
        tab_selector = f"#tab-{tab_name}"
        panel_selector = f"#{panel_id}"
        if page.locator(tab_selector).count() == 0:
            pytest.skip(f"Tab {tab_name} not available in this UI configuration.")

        # Click the tab
        page.click(tab_selector)

        # Wait for panel to become visible
        page.wait_for_selector(f"{panel_selector}:not(.hidden)", state="visible")

        # Verify panel is visible and others are hidden
        expect(page.locator(panel_selector)).to_be_visible()
        expect(page.locator(panel_selector)).not_to_have_class(re.compile(r"hidden"))

        if selector:
            target = page.locator(panel_selector).locator(selector)
            expect(target.first).to_be_visible()
