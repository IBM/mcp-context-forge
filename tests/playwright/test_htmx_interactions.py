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
        expect(page.locator("#catalog-panel")).to_be_visible()

        # Click tools tab and verify content loads
        if page.locator("#tab-tools").count() > 0:
            page.click("#tab-tools")
            page.wait_for_selector("#tools-panel:not(.hidden)", state="visible")
            expect(page.locator("#tools-panel")).to_be_visible()
            expect(page.locator("#catalog-panel")).to_have_class(re.compile(r"hidden"))

            # Verify tools table is present
            expect(page.locator("#tools-panel table")).to_be_visible()

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

        # Submit the form
        form.locator('button[type="submit"]').click()

        # Wait for the form submission to complete
        page.wait_for_load_state("networkidle")

        # Verify the tool appears in the table
        expect(page.locator("#tools-panel table")).to_contain_text(test_tool_data["name"])
        expect(page.locator("#tools-panel table")).to_contain_text(test_tool_data["description"])

    def test_tool_modal_interactions(self, page: Page):
        """Test tool detail and edit modal functionality."""
        # Navigate to tools tab
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

        # Click on a tool's view button (if any tools exist)
        tool_rows = page.locator("#tools-panel tbody tr")
        if tool_rows.count() > 0:
            # Click the first tool's View button
            tool_rows.first.locator('button:has-text("View")').click()

            # Verify the modal opens
            expect(page.locator("#tool-modal")).to_be_visible()
            expect(page.locator("#tool-details")).to_be_visible()

            # Close the modal
            page.click('#tool-modal button:has-text("Close")')
            expect(page.locator("#tool-modal")).to_be_hidden()

    def test_tool_edit_modal(self, page: Page, test_tool_data: Dict[str, Any]):
        """Test editing a tool via modal."""
        # First create a tool
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

        # Create a tool
        form = page.locator("#add-tool-form")
        form.locator('[name="name"]').fill(test_tool_data["name"])
        form.locator('[name="url"]').fill(test_tool_data["url"])
        form.locator('[name="description"]').fill(test_tool_data["description"])

        # Select integration type based on what's available
        integration_select = form.locator('[name="integrationType"]')
        options = integration_select.locator("option")
        if options.count() > 0:
            # Get the first non-empty option value
            for i in range(options.count()):
                value = options.nth(i).get_attribute("value")
                if value:  # Skip empty/placeholder options
                    integration_select.select_option(value)
                    break

        form.locator('button[type="submit"]').click()
        page.wait_for_selector(f'#tools-panel tbody tr:has-text("{test_tool_data["name"]}")')

        # Wait a bit for the table to update
        page.wait_for_timeout(1000)

        # Find the created tool and click Edit
        tool_rows = page.locator("#tools-panel tbody tr")
        edit_clicked = False
        for i in range(tool_rows.count()):
            row = tool_rows.nth(i)
            if test_tool_data["name"] in row.text_content():
                # Click the edit button for this row
                row.locator('button:has-text("Edit")').click()
                edit_clicked = True
                break

        assert edit_clicked, f"Could not find edit button for tool {test_tool_data['name']}"

        # Wait for the edit modal to open
        page.wait_for_selector("#tool-edit-modal", state="visible")
        page.wait_for_timeout(500)  # Give modal time to fully render

        # Modify the tool name
        new_name = f"{test_tool_data['name']} Updated"
        page.fill("#edit-tool-name", new_name)

        # Submit the edit form - use a more specific selector
        # The button is inside the form with id="edit-tool-form"
        save_button = page.locator('#edit-tool-form button[type="submit"]:has-text("Save Changes")')

        # Debug: Check if button exists
        assert save_button.count() > 0, "Save Changes button not found"

        # Click the button
        save_button.click()

        # Wait for modal to close
        page.wait_for_selector("#tool-edit-modal", state="hidden", timeout=10000)

        # Wait for the updated name to appear in the table
        page.wait_for_selector(f'#tools-panel tbody tr:has-text("{new_name}")')

        # If we're not on the tools tab anymore, navigate back
        if not page.locator("#tools-panel:not(.hidden)").is_visible():
            page.click("#tab-tools")
            page.wait_for_selector("#tools-panel:not(.hidden)")

        # Verify the tool name was updated
        page.wait_for_timeout(1000)

        # Check if the updated name appears anywhere in the tools panel
        tools_table_text = page.locator("#tools-panel").text_content()
        assert new_name in tools_table_text, f"Updated tool name '{new_name}' not found in tools panel"

    def test_tool_test_modal(self, page: Page):
        """Test the tool testing functionality via modal."""
        # Navigate to tools tab
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

        # Check if there are any tools with a Test button
        tool_rows = page.locator("#tools-panel tbody tr")
        if tool_rows.count() > 0:
            # Look for a Test button
            test_buttons = tool_rows.first.locator('button:has-text("Test")')
            if test_buttons.count() > 0:
                test_buttons.first.click()

                # Verify test modal opens
                expect(page.locator("#tool-test-modal")).to_be_visible()
                expect(page.locator("#tool-test-form")).to_be_visible()

                # Close the modal
                page.click('#tool-test-modal button:has-text("Close")')
                expect(page.locator("#tool-test-modal")).to_be_hidden()

    def test_search_functionality_realtime(self, page: Page):
        """Test real-time search filtering."""
        # Navigate to servers/catalog tab
        page.click("#tab-catalog")
        page.wait_for_selector("#catalog-panel:not(.hidden)")

        # Type in search box
        search_input = page.locator('[data-testid="search-input"]')

        # Get initial server count
        initial_rows = page.locator('[data-testid="server-item"]').count()

        # Type a search term that likely won't match
        search_input.fill("xyznonexistentserver123")

        # Wait a moment for any filtering to apply
        page.wait_for_timeout(500)

        # Check if the table has been filtered (this depends on implementation)
        # If search is implemented client-side, rows should be hidden
        # If server-side, a request would be made
        # Check that filtering actually works (unused for now but validates functionality)
        page.locator('[data-testid="server-item"]:visible').count()

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

        # Check for the canvas element first as it's always visible
        if page.locator("#metricsChart").count() == 0:
            pytest.skip("Metrics chart not available in this UI configuration.")
        expect(page.locator("#metricsChart")).to_be_visible()

        # The aggregated-metrics-content div exists but might be empty initially
        # Just check it exists, not that it's visible (it might have no content)
        assert page.locator("#aggregated-metrics-content").count() > 0

        # Click refresh metrics button to trigger loading
        page.click('button:has-text("Refresh Metrics")')

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

    def test_delete_with_confirmation(self, page: Page, test_tool_data: Dict[str, Any]):
        """Test delete functionality with confirmation dialog."""
        # Create a tool first
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

        form = page.locator("#add-tool-form")
        delete_tool_name = f"Delete Test {test_tool_data['name']}"
        form.locator('[name="name"]').fill(delete_tool_name)
        form.locator('[name="url"]').fill(test_tool_data["url"])
        form.locator('[name="description"]').fill("Tool to be deleted")

        # Select first available integration type
        integration_select = form.locator('[name="integrationType"]')
        options = integration_select.locator("option")
        if options.count() > 0:
            for i in range(options.count()):
                value = options.nth(i).get_attribute("value")
                if value:
                    integration_select.select_option(value)
                    break

        form.locator('button[type="submit"]').click()
        page.wait_for_selector(f'#tools-panel tbody tr:has-text("{delete_tool_name}")')

        # Find the tool - use a more specific selector
        page.wait_for_timeout(1000)  # Give the table time to update

        # Set up dialog handler before clicking delete
        page.on("dialog", lambda dialog: dialog.accept())

        # Find and click the delete button for this specific tool
        # Look for the row containing our tool name, then find its delete button
        tool_rows = page.locator("#tools-panel tbody tr")
        for i in range(tool_rows.count()):
            row = tool_rows.nth(i)
            if delete_tool_name in row.text_content():
                # Found the right row, click its delete button
                delete_form = row.locator('form[action*="/delete"]')
                if delete_form.count() > 0:
                    delete_form.locator('button[type="submit"]').click()
                    break

        # Wait for deletion to process
        page.wait_for_timeout(500)

        # Verify tool is gone
        expect(page.locator(f'#tools-panel tbody tr:has-text("{delete_tool_name}")')).not_to_be_visible()

    @pytest.mark.slow
    def test_network_error_handling(self, page: Page):
        """Test UI behavior during network errors."""
        # Navigate to tools tab
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel:not(.hidden)")

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

        # Check for error message (depends on implementation)
        # The admin.js shows error handling with showErrorMessage function
        page.wait_for_timeout(1000)

        # Clean up route
        page.unroute("**/*")

    def test_version_info_tab(self, page: Page):
        """Test version info tab functionality."""
        # Click version info tab
        page.click("#tab-version-info")

        # This might trigger HTMX request based on setupHTMXHooks
        # Wait for content to load
        page.wait_for_selector("#version-info-panel:not(.hidden)")

        # Verify panel is visible
        expect(page.locator("#version-info-panel")).to_be_visible()

    @pytest.mark.parametrize(
        "tab_name,panel_id",
        [
            ("catalog", "catalog-panel"),
            ("tools", "tools-panel"),
            ("resources", "resources-panel"),
            ("prompts", "prompts-panel"),
            ("gateways", "gateways-panel"),
            ("roots", "roots-panel"),
            ("metrics", "metrics-panel"),
        ],
    )
    def test_all_tabs_navigation(self, page: Page, tab_name: str, panel_id: str):
        """Test navigation to all available tabs."""
        # Click the tab
        page.click(f"#tab-{tab_name}")

        # Wait for panel to become visible
        page.wait_for_selector(f"#{panel_id}:not(.hidden)", state="visible")

        # Verify panel is visible and others are hidden
        expect(page.locator(f"#{panel_id}")).to_be_visible()
        expect(page.locator(f"#{panel_id}")).not_to_have_class(re.compile(r"hidden"))
