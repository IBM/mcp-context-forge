# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/tools_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tools page object for Tool management features.
"""

# Standard Library
import re

# Third-Party
from playwright.sync_api import expect, Locator

# Local
from .base_page import BasePage


class ToolsPage(BasePage):
    """Page object for Tool management features."""

    # ==================== Panel Elements ====================

    @property
    def tools_panel(self) -> Locator:
        """Tools panel container."""
        return self.page.locator("#tools-panel")

    # ==================== Tool Form Elements ====================

    @property
    def add_tool_form(self) -> Locator:
        """Add tool form."""
        return self.page.locator("#add-tool-form")

    @property
    def tool_name_input(self) -> Locator:
        """Tool name input field."""
        return self.add_tool_form.locator('[name="name"]')

    @property
    def tool_url_input(self) -> Locator:
        """Tool URL input field."""
        return self.add_tool_form.locator('[name="url"]')

    @property
    def tool_description_input(self) -> Locator:
        """Tool description input field."""
        return self.add_tool_form.locator('[name="description"]')

    @property
    def tool_integration_type_select(self) -> Locator:
        """Tool integration type select field."""
        return self.add_tool_form.locator('[name="integrationType"]')

    @property
    def add_tool_btn(self) -> Locator:
        """Add tool submit button."""
        return self.add_tool_form.locator('button[type="submit"]')

    # ==================== Tool Table Elements ====================

    @property
    def tools_table(self) -> Locator:
        """Tools table."""
        return self.page.locator("#tools-table")

    @property
    def tools_table_body(self) -> Locator:
        """Tools table body."""
        return self.page.locator("#tools-table-body")

    @property
    def tool_rows(self) -> Locator:
        """All tool table rows."""
        return self.tools_table_body.locator("tr")

    # ==================== Tool Modal Elements ====================

    @property
    def tool_modal(self) -> Locator:
        """Tool details modal."""
        return self.page.locator("#tool-modal")

    @property
    def tool_edit_modal(self) -> Locator:
        """Tool edit modal."""
        return self.page.locator("#tool-edit-modal")

    @property
    def tool_test_modal(self) -> Locator:
        """Tool test modal."""
        return self.page.locator("#tool-test-modal")

    @property
    def tool_details_content(self) -> Locator:
        """Tool details content area in view modal."""
        return self.page.locator("#tool-details")

    @property
    def tool_modal_close_btn(self) -> Locator:
        """Close button in tool view modal."""
        return self.tool_modal.locator('button:has-text("Close")')

    @property
    def tool_edit_name_input(self) -> Locator:
        """Tool name input in edit modal."""
        return self.tool_edit_modal.locator("#edit-tool-custom-name")

    @property
    def tool_edit_save_btn(self) -> Locator:
        """Save button in tool edit modal."""
        return self.tool_edit_modal.locator('button:has-text("Save")')

    @property
    def tool_edit_cancel_btn(self) -> Locator:
        """Cancel button in tool edit modal."""
        return self.tool_edit_modal.locator('button:has-text("Cancel")')

    @property
    def tool_test_form(self) -> Locator:
        """Tool test form in test modal."""
        return self.page.locator("#tool-test-form")

    @property
    def tool_test_close_btn(self) -> Locator:
        """Close button in tool test modal."""
        return self.tool_test_modal.locator('button:has-text("Close")')

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_tools_tab(self) -> None:
        """Navigate to Tools tab and wait for panel to be visible."""
        self.sidebar.click_tools_tab()

    # ==================== High-Level Tool Operations ====================

    def wait_for_tools_table_loaded(self, timeout: int = 60000) -> None:
        """Wait for tools table to be loaded and ready.

        Handles the Alpine.js x-init / HTMX load race where the tools table
        content may not load on the first attempt. Unlike other tabs, showTab()
        has no retry logic for "tools", so the initial hx-trigger="load" is
        the only chance. If it misses, we reload the page to re-run the sequence.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("#tools-panel:not(.hidden)", timeout=timeout)
        try:
            # Use shorter timeout for initial check so we retry quickly on HTMX race
            self.wait_for_attached(self.tools_table_body, timeout=15000)
        except AssertionError:
            # Alpine.js x-init / HTMX load race: reload to re-run the sequence.
            # showTab() does NOT set location.hash, so after reload the page
            # defaults to the gateways tab. We must wait for JS init and then
            # re-navigate to the tools tab.
            self.page.reload(wait_until="domcontentloaded")
            self.page.wait_for_function(
                "typeof window.showTab === 'function' && typeof window.htmx !== 'undefined'",
                timeout=30000,
            )
            self.sidebar.click_tools_tab()
            self.page.wait_for_selector("#tools-panel:not(.hidden)", timeout=timeout)
            self.wait_for_attached(self.tools_table_body, timeout=timeout)

    def create_tool(self, name: str, url: str, description: str, integration_type: str) -> None:
        """Create a new tool by filling and submitting the form.

        Args:
            name: Tool name
            url: Tool URL
            description: Tool description
            integration_type: Integration type (e.g., "REST", "GraphQL")
        """
        self.fill_locator(self.tool_name_input, name)
        self.fill_locator(self.tool_url_input, url)
        self.fill_locator(self.tool_description_input, description)
        self.tool_integration_type_select.select_option(integration_type)
        self.click_locator(self.add_tool_btn)

    def fill_tool_form(self, name: str, url: str, description: str, integration_type: str) -> None:
        """Fill the add tool form with provided data (without submitting).

        Args:
            name: Tool name
            url: Tool URL
            description: Tool description
            integration_type: Integration type (e.g., "REST", "GraphQL")
        """
        self.fill_locator(self.tool_name_input, name)
        self.fill_locator(self.tool_url_input, url)
        self.fill_locator(self.tool_description_input, description)
        self.tool_integration_type_select.select_option(integration_type)

    def submit_tool_form(self) -> None:
        """Submit the add tool form."""
        self.click_locator(self.add_tool_btn)

    def get_tool_row(self, tool_index: int) -> Locator:
        """Get a specific tool row by index.

        Args:
            tool_index: Index of the tool row

        Returns:
            Locator for the tool row
        """
        return self.tool_rows.nth(tool_index)

    def tool_exists(self, tool_name: str) -> bool:
        """Check if a tool with the given name exists in the table.

        Args:
            tool_name: The name of the tool to check

        Returns:
            True if tool exists, False otherwise
        """
        return self.page.locator(f"text={tool_name}").is_visible()

    # ==================== Tool Modal Interactions ====================

    def _click_and_wait_for_tool_fetch(self, button: Locator, modal_id: str) -> None:
        """Click a button that triggers an async tool API fetch, then wait for the modal.

        editTool(), testTool(), and viewTool() all fetch /admin/tools/{id}
        before opening their respective modals.  If the API returns an error
        (e.g., RBAC 403), the JS catch block shows an error toast but never
        calls openModal(), so waiting for the modal selector would hang until
        timeout.  This method intercepts the API response and raises early.
        """
        with self.page.expect_response(
            lambda resp: (
                re.search(r"/ui/tools/[0-9a-f]", resp.url) is not None and "/partial" not in resp.url and "/search" not in resp.url and "/ids" not in resp.url and resp.request.method == "GET"
            ),
            timeout=30000,
        ) as response_info:
            self.click_locator(button)
        response = response_info.value
        if response.status >= 400:
            raise AssertionError(f"Tool API fetch failed with HTTP {response.status} for {response.url}")
        # API succeeded — wait for the JS to open the modal
        self.page.wait_for_selector(f"#{modal_id}:not(.hidden)", state="visible", timeout=30000)

    def open_tool_view_modal(self, tool_index: int = 0) -> None:
        """Open the tool view modal for a specific tool.

        Args:
            tool_index: Index of the tool row (default: 0 for first tool)
        """
        tool_row = self.tool_rows.nth(tool_index)
        view_btn = tool_row.locator('button:has-text("View")')
        self._click_and_wait_for_tool_fetch(view_btn, "tool-modal")
        self.wait_for_visible(self.tool_modal)

    def close_tool_modal(self) -> None:
        """Close the tool view modal."""
        self.click_locator(self.tool_modal_close_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#tool-modal.hidden", state="hidden", timeout=30000)

    def open_tool_edit_modal(self, tool_index: int = 0) -> None:
        """Open the tool edit modal for a specific tool.

        Args:
            tool_index: Index of the tool row (default: 0 for first tool)
        """
        tool_row = self.tool_rows.nth(tool_index)
        edit_btn = tool_row.locator('button:has-text("Edit")')
        self._click_and_wait_for_tool_fetch(edit_btn, "tool-edit-modal")
        self.wait_for_visible(self.tool_edit_modal)

    def edit_tool_name(self, new_name: str) -> None:
        """Edit the tool name in the edit modal.

        Args:
            new_name: New name for the tool
        """
        self.fill_locator(self.tool_edit_name_input, new_name)

    def save_tool_edit(self) -> None:
        """Save changes in the tool edit modal."""
        self.click_locator(self.tool_edit_save_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#tool-edit-modal.hidden", state="hidden", timeout=30000)

    def cancel_tool_edit(self) -> None:
        """Cancel editing and close the tool edit modal."""
        self.click_locator(self.tool_edit_cancel_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#tool-edit-modal.hidden", state="hidden", timeout=30000)

    def open_tool_test_modal(self, tool_index: int = 0) -> None:
        """Open the tool test modal for a specific tool.

        Args:
            tool_index: Index of the tool row (default: 0 for first tool)
        """
        tool_row = self.tool_rows.nth(tool_index)
        test_btn = tool_row.locator('button:has-text("Test")')
        self._click_and_wait_for_tool_fetch(test_btn, "tool-test-modal")
        self.wait_for_visible(self.tool_test_modal)

    def run_tool_test(self, params: dict = None) -> None:
        """Run a tool test with optional parameters.

        Args:
            params: Optional dictionary of test parameters to fill in the form
        """
        if params:
            # Fill in test parameters if provided
            for key, value in params.items():
                input_field = self.tool_test_form.locator(f'[name="{key}"]')
                if input_field.count() > 0:
                    self.fill_locator(input_field, str(value))

        # Submit the test form
        submit_btn = self.tool_test_form.locator('button[type="submit"]')
        if submit_btn.count() > 0:
            self.click_locator(submit_btn)

    def close_tool_test_modal(self) -> None:
        """Close the tool test modal."""
        self.click_locator(self.tool_test_close_btn)
        # Wait for modal to close
        self.page.wait_for_selector("#tool-test-modal.hidden", state="hidden", timeout=30000)

    def wait_for_tool_visible(self, tool_name: str, timeout: int = 30000) -> None:
        """Wait for a tool to be visible in the table.

        Args:
            tool_name: The name of the tool
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector(f"text={tool_name}", timeout=timeout)
        expect(self.page.locator(f"text={tool_name}")).to_be_visible()
