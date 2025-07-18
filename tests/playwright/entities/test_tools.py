# -*- coding: utf-8 -*-
import pytest
from playwright.sync_api import Page, expect

class TestToolsCRUD:
    """CRUD tests for Tools entity in MCP Gateway Admin UI.

    Examples:
        pytest tests/playwright/entities/test_tools.py
    """
    def test_create_new_tool(self, page: Page, test_tool_data, admin_page):
        """Test creating a new tool with debug screenshots and waits."""
        # Go to the Global Tools tab (if not already there)
        page.click('[data-testid="tools-tab"]')

        # Wait for the tools panel to be visible
        page.wait_for_selector('#tools-panel:not(.hidden)')

        # Add a small delay to ensure the UI has time to update
        page.wait_for_timeout(500)

        # Fill the always-visible form
        page.locator('#add-tool-form [name="name"]').fill(test_tool_data["name"])
        page.wait_for_timeout(300)
        page.locator('#add-tool-form [name="url"]').fill(test_tool_data["url"])
        page.wait_for_timeout(300)
        page.locator('#add-tool-form [name="description"]').fill(test_tool_data["description"])
        page.wait_for_timeout(300)
        page.locator('#add-tool-form [name="integrationType"]').select_option(test_tool_data["integrationType"])
        page.wait_for_timeout(300)

        # Submit the form
        page.click('#add-tool-form button[type="submit"]')

        # Assert the tool appears in the table
        expect(page.locator("#tools-panel table")).to_contain_text(test_tool_data["name"])

    def test_delete_tool(self, page: Page, test_tool_data, admin_page):
        """Test deleting a tool."""
        # Go to the Global Tools tab (if not already there)
        page.click('[data-testid="tools-tab"]')

        # Wait for the tools panel to be visible
        page.wait_for_selector('#tools-panel:not(.hidden)')

        # Create tool first
        page.locator('#add-tool-form [name="name"]').fill(test_tool_data["name"])
        page.wait_for_timeout(300)
        page.locator('#add-tool-form [name="url"]').fill(test_tool_data["url"])
        page.wait_for_timeout(300)
        page.locator('#add-tool-form [name="description"]').fill(test_tool_data["description"])
        page.wait_for_timeout(300)
        page.locator('#add-tool-form [name="integrationType"]').select_option(test_tool_data["integrationType"])
        page.wait_for_timeout(300)
        page.click('#add-tool-form button[type="submit"]')
        expect(page.locator("#tools-panel table")).to_contain_text(test_tool_data["name"])

        # Delete tool
        tool_row = page.locator(f'#tools-panel tbody tr:has-text("{test_tool_data["name"]}")')

        # Set up dialog handler before clicking delete
        page.on("dialog", lambda dialog: dialog.accept())

        tool_row.locator('button:has-text("Delete")').click()

        # Wait a moment for the deletion to process
        page.wait_for_timeout(1000)

        # Assert the tool is no longer in the table
        expect(page.locator(f'#tools-panel tbody tr:has-text("{test_tool_data["name"]}")')).not_to_be_visible()
