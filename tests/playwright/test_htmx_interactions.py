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

# Local
from .pages.admin_page import AdminPage
from .pages.admin_utils import cleanup_tool
from .pages.metrics_page import MetricsPage
from .pages.servers_page import ServersPage
from .pages.tools_page import ToolsPage


class TestHTMXInteractions:
    """HTMX and UI interaction tests for MCP Gateway Admin UI.

    Tests dynamic content loading, form submissions, modals, and real-time updates
    that are powered by HTMX in the admin interface.

    Examples:
        pytest tests/playwright/test_htmx_interactions.py
        pytest tests/playwright/test_htmx_interactions.py -v -k "tab_content"
    """

    @staticmethod
    def _prepare_tools_table(page: Page, admin_ui: AdminPage) -> None:
        """Ensure tools table is loaded."""
        page.wait_for_selector("#tools-panel:not(.hidden)", timeout=30000)
        # Wait for table body to exist in DOM (may be empty, so don't require visible)
        admin_ui.wait_for_attached(admin_ui.tools_table_body, timeout=30000)

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

    # Note: Authentication is handled by individual page fixtures (admin_page, tools_page, etc.)
    # No autouse setup fixture needed as each test requests the appropriate page fixture

    def test_tab_content_loading_via_javascript(self, admin_page: AdminPage, tools_page: ToolsPage):
        """Test tab switching and content loading via JavaScript.

        Note: The admin interface uses JavaScript for tab switching, not HTMX.
        """
        # Start on the default tab (catalog)
        if admin_page.catalog_panel.count() == 0:
            pytest.skip("Catalog panel not available in this UI configuration.")
        # Check if catalog panel is visible (not hidden)
        if admin_page.catalog_panel.get_attribute("class") and "hidden" in admin_page.catalog_panel.get_attribute("class"):
            if admin_page.page.locator("#tab-catalog").count() > 0:
                admin_page.click_tab_by_id("tab-catalog", "catalog-panel")
        expect(admin_page.catalog_panel).to_be_visible()

        # Click tools tab and verify content loads
        if admin_page.tools_tab.count() > 0:
            admin_page.click_tools_tab()
            expect(admin_page.tools_panel).to_be_visible()
            expect(admin_page.catalog_panel).to_have_class(re.compile(r"hidden"))

            # Verify tools table is present using ToolsPage
            tools_page.wait_for_tools_table_loaded()
            expect(tools_page.tools_table).to_be_visible()

        # Switch to resources tab
        if admin_page.resources_tab.count() > 0:
            admin_page.click_resources_tab()
            expect(admin_page.resources_panel).to_be_visible()
            expect(admin_page.tools_panel).to_have_class(re.compile(r"hidden"))

        # Switch to prompts tab
        if admin_page.prompts_tab.count() > 0:
            admin_page.click_prompts_tab()
            expect(admin_page.prompts_panel).to_be_visible()

        # Switch to gateways tab
        if admin_page.gateways_tab.count() > 0:
            admin_page.click_gateways_tab()
            expect(admin_page.gateways_panel).to_be_visible()

    def test_tool_form_submission(self, tools_page: ToolsPage, test_tool_data: Dict[str, Any]):
        """Test creating a new tool via the inline form."""
        # Navigate to tools tab
        tools_page.navigate_to_tools_tab()

        # Fill the tool form
        tools_page.fill_tool_form(test_tool_data["name"], test_tool_data["url"], test_tool_data["description"], test_tool_data["integrationType"])

        # Submit the form and assert success response
        with tools_page.page.expect_response(lambda response: "/admin/tools" in response.url and response.request.method == "POST") as response_info:
            tools_page.submit_tool_form()
        response = response_info.value
        assert response.status < 400

        # Cleanup using centralized helper
        cleanup_tool(tools_page.page, test_tool_data["name"])

    def test_tool_modal_interactions(self, tools_page: ToolsPage):
        """Test tool detail and edit modal functionality."""
        # Navigate to tools tab
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        # Check if any tools exist
        if tools_page.tool_rows.count() == 0:
            pytest.skip("No tools available to view in this UI configuration.")

        # Open the tool view modal using page object method
        # viewTool() fetches /admin/tools/{id} — may fail with RBAC 403
        try:
            tools_page.open_tool_view_modal(tool_index=0)
        except AssertionError as exc:
            if "HTTP 403" in str(exc) or "HTTP 401" in str(exc):
                pytest.skip(f"Tool view blocked by RBAC permissions: {exc}")
            raise

        # Verify the modal and its content are visible
        expect(tools_page.tool_modal).to_be_visible()
        expect(tools_page.tool_details_content).to_be_visible()

        # Close the modal using page object method
        tools_page.close_tool_modal()

    def test_tool_edit_modal(self, tools_page: ToolsPage):
        """Test editing a tool via modal."""
        # Navigate to tools tab
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        # Check if any tools exist
        if tools_page.tool_rows.count() == 0:
            pytest.skip("No tools available to edit in this UI configuration.")

        # Open edit modal — editTool() fetches /admin/tools/{id} before opening
        try:
            tools_page.open_tool_edit_modal(tool_index=0)
        except AssertionError as exc:
            if "HTTP 403" in str(exc) or "HTTP 401" in str(exc):
                pytest.skip(f"Tool edit blocked by RBAC permissions: {exc}")
            raise

        # Modify the tool name
        tools_page.edit_tool_name("Updated Tool Name")

        # Cancel to avoid mutating shared data in cached lists
        tools_page.cancel_tool_edit()

    def test_tool_test_modal(self, tools_page: ToolsPage):
        """Test the tool testing functionality via modal."""
        # Navigate to tools tab
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        # Check if there are any tools
        if tools_page.tool_rows.count() == 0:
            pytest.skip("No tools available to test in this UI configuration.")

        # Check if the first tool has a Test button
        test_buttons = tools_page.tool_rows.first.locator('button:has-text("Test")')
        if test_buttons.count() == 0:
            pytest.skip("No Test button available for tools.")

        # Open test modal — testTool() fetches /admin/tools/{id} before opening
        try:
            tools_page.open_tool_test_modal(tool_index=0)
        except AssertionError as exc:
            if "HTTP 403" in str(exc) or "HTTP 401" in str(exc):
                pytest.skip(f"Tool test blocked by RBAC permissions: {exc}")
            raise

        # Verify test modal and form are visible
        expect(tools_page.tool_test_modal).to_be_visible()
        expect(tools_page.tool_test_form).to_be_visible()

        # Close the modal using page object method
        tools_page.close_tool_test_modal()

    def test_search_functionality_realtime(self, servers_page: ServersPage):
        """Test real-time search filtering on servers."""
        # Navigate to servers/catalog tab
        servers_page.navigate_to_servers_tab()

        # Get initial server count
        initial_rows = servers_page.server_items.count()
        if initial_rows == 0:
            pytest.skip("No servers available to validate search filtering.")

        # Type a search term that likely won't match
        servers_page.search_servers("xyznonexistentserver123")

        # Wait for filtering to take effect (count should change)
        servers_page.wait_for_count_change(servers_page.server_items, initial_rows, timeout=5000)

        # Check if the table has been filtered
        filtered_visible = servers_page.server_items.locator(":visible").count()
        assert filtered_visible < initial_rows

        # Clear search
        servers_page.clear_search()

        # Wait for rows to be restored
        servers_page.wait_for_count_change(servers_page.server_items, filtered_visible, timeout=5000)

        # Verify rows are restored
        restored_rows = servers_page.server_items.count()
        assert restored_rows == initial_rows

    def test_form_validation_feedback(self, tools_page: ToolsPage):
        """Test form validation and error feedback."""
        # Navigate to tools tab
        tools_page.navigate_to_tools_tab()

        # Try to submit empty form - click submit without filling required fields
        tools_page.add_tool_btn.click()

        # Check for HTML5 validation (browser will prevent submission)
        # The name field should be invalid
        is_valid = tools_page.tool_name_input.evaluate("el => el.checkValidity()")
        assert is_valid is False

    def test_inactive_items_toggle(self, tools_page: ToolsPage):
        """Test showing/hiding inactive items functionality."""
        # Test on tools tab
        tools_page.navigate_to_tools_tab()

        # Find the inactive checkbox
        inactive_checkbox = tools_page.page.locator("#show-inactive-tools")

        # Check initial state
        initial_checked = inactive_checkbox.is_checked()

        # Toggle the checkbox
        inactive_checkbox.click()

        # When checkbox is toggled, it triggers a page reload with query parameter
        # Wait for the page to reload
        tools_page.page.wait_for_timeout(500)

        # After reload, verify the checkbox state persisted
        # The checkbox state is maintained via URL parameter
        inactive_checkbox_after = tools_page.page.locator("#show-inactive-tools")
        assert inactive_checkbox_after.is_checked() != initial_checked

    def test_multi_select_tools_in_server_form(self, servers_page: ServersPage):
        """Test multi-select functionality for associating tools with servers."""
        # Navigate to servers tab
        servers_page.navigate_to_servers_tab()

        # Find the tools select element using ServersPage
        tools_select = servers_page.page.locator("#associatedTools")

        # Check if there are options available
        options = tools_select.locator("option")
        if options.count() > 1:  # More than just the placeholder
            # Select multiple tools
            tools_select.select_option(index=[0, 1])

            # Verify pills are created (based on the JS code)
            pills_container = servers_page.page.locator("#selectedToolsPills")
            expect(pills_container).to_be_visible()

            # Check warning if more than 6 tools selected
            if options.count() > 6:
                for i in range(7):
                    tools_select.select_option(index=list(range(i + 1)))

                warning = servers_page.page.locator("#selectedToolsWarning")
                expect(warning).to_contain_text("more than 6 tools")

    def test_metrics_tab_data_loading(self, metrics_page: MetricsPage):
        """Test metrics tab and data visualization."""
        # Navigate to metrics tab
        if metrics_page.sidebar.metrics_tab.count() == 0:
            pytest.skip("Metrics tab not available in this UI configuration.")
        metrics_page.navigate_to_metrics_tab()

        # Prefer the top performers panel; aggregated metrics are hidden by default
        if metrics_page.top_performers_panel.count() == 0:
            pytest.skip("Top performers panel not available in this UI configuration.")
        expect(metrics_page.top_performers_panel).to_be_visible()

        # Click refresh metrics button to trigger loading
        if metrics_page.refresh_metrics_btn.count() > 0:
            metrics_page.refresh_metrics()
            # Wait for the loadAggregatedMetrics function to potentially update content
            metrics_page.page.wait_for_timeout(2000)

        # Test expandable sections using page object methods
        sections = ["top-tools", "top-resources", "top-servers", "top-prompts"]
        for section in sections:
            section_locator = getattr(metrics_page, f"{section.replace('-', '_')}_details")
            if section_locator.is_visible():
                # Expand the section using page object method
                metrics_page.expand_metric_section(section)
                # Verify content area is visible
                expect(metrics_page.get_metric_content(section)).to_be_visible()

    def test_delete_with_confirmation(self, tools_page: ToolsPage):
        """Test delete functionality with confirmation dialog."""
        # Use an existing tool row to verify confirmation dialog without mutating data
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        tool_row = tools_page.tool_rows.first
        if tool_row.count() == 0:
            pytest.skip("No tools available for delete confirmation test.")

        dialog_seen = {"value": False}
        tools_page.page.on("dialog", lambda dialog: (dialog.dismiss(), dialog_seen.__setitem__("value", True)))

        delete_form = tool_row.locator('form[action*="/delete"]')
        if delete_form.count() > 0:
            delete_form.locator('button[type="submit"]').click()

        # Wait a moment for dialog handling
        tools_page.page.wait_for_timeout(500)
        assert dialog_seen["value"] is True

    @pytest.mark.slow
    def test_network_error_handling(self, tools_page: ToolsPage):
        """Test UI behavior during network errors."""
        # Navigate to tools tab
        tools_page.navigate_to_tools_tab()

        failed_requests = []

        def handle_request_failed(request):
            if "/admin/tools" in request.url and request.method == "POST":
                failed_requests.append(request.url)

        tools_page.page.on("requestfailed", handle_request_failed)

        # Intercept network requests to simulate failure
        def handle_route(route):
            if "/admin/tools" in route.request.url and route.request.method == "POST":
                route.abort("failed")
            else:
                route.continue_()

        tools_page.page.route("**/*", handle_route)

        # Try to create a tool
        tools_page.tool_name_input.fill("Network Error Test")
        tools_page.tool_url_input.fill("http://example.com")

        # Select first available integration type
        options = tools_page.tool_integration_type_select.locator("option")
        if options.count() > 0:
            for i in range(options.count()):
                value = options.nth(i).get_attribute("value")
                if value:
                    tools_page.tool_integration_type_select.select_option(value)
                    break

        # Submit and expect error handling
        tools_page.add_tool_btn.click()

        # Ensure the failed request is observed
        tools_page.page.wait_for_timeout(1000)
        assert failed_requests, "Expected tool creation request to fail, but no failed request was captured."

        # Clean up route
        tools_page.page.unroute("**/*")

    def test_version_info_tab(self, admin_page: AdminPage):
        """Test version info tab functionality."""
        if admin_page.page.locator("#tab-version-info").count() == 0:
            pytest.skip("Version info tab not available in this UI configuration.")

        # Click version info tab
        admin_page.click_tab_by_id("tab-version-info", "version-info-panel")

        # Verify panel is visible
        expect(admin_page.page.locator("#version-info-panel")).to_be_visible()

    @pytest.mark.parametrize(
        "tab_name,panel_id,selector",
        TAB_PANEL_CHECKS,
    )
    def test_all_tabs_navigation(self, admin_page: AdminPage, tab_name: str, panel_id: str, selector: str | None):
        """Test navigation to all available tabs and key controls."""
        tab_selector = f"#tab-{tab_name}"
        panel_selector = f"#{panel_id}"
        if admin_page.page.locator(tab_selector).count() == 0:
            pytest.skip(f"Tab {tab_name} not available in this UI configuration.")

        # Click the tab
        admin_page.click_tab_by_id(f"tab-{tab_name}", panel_id)

        # Verify panel is visible and others are hidden
        expect(admin_page.page.locator(panel_selector)).to_be_visible()
        expect(admin_page.page.locator(panel_selector)).not_to_have_class(re.compile(r"hidden"))

        if selector:
            target = admin_page.page.locator(panel_selector).locator(selector)
            if target.count() == 0:
                pytest.skip(
                    f"Selector {selector} not available in panel {panel_id} for this environment/configuration.",
                )
            expect(target.first).to_be_visible()
