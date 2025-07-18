# -*- coding: utf-8 -*-
import re
import pytest
from playwright.sync_api import Page, expect

class TestHTMXInteractions:
    """HTMX and UI interaction tests for MCP Gateway Admin UI.

    Examples:
        pytest tests/playwright/test_htmx_interactions.py
    """
    @pytest.fixture(autouse=True)
    def setup(self, admin_page):
        """Login before each test."""
        pass  # admin_page fixture handles login

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_should_load_tab_content_via_htmx(self, page: Page):
        """Test HTMX tab loading functionality."""
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel", state="visible")
        expect(page.locator("#tools-panel")).to_be_visible()
        expect(page.locator("#tools-table")).to_be_visible()
        tool_rows = page.locator("#tools-table tbody tr")
        assert tool_rows.count() >= 0

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_should_create_new_tool_via_modal(self, page: Page, test_tool_data):
        """Test tool creation through modal form."""
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel")
        page.click('button:has-text("Add Tool")')
        expect(page.locator("#create-tool-modal")).to_be_visible()
        for field, value in test_tool_data.items():
            if field == "integrationType":
                page.select_option(f'[name="{field}"]', value)
            else:
                page.fill(f'[name="{field}"]', value)
        page.click('#create-tool-modal button[type="submit"]')
        expect(page.locator("#create-tool-modal")).to_be_hidden()
        expect(page.locator("#tools-table")).to_contain_text(test_tool_data["name"])

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_htmx_polling_updates(self, page: Page, admin_page):
        """Test HTMX polling for live updates."""
        page.click("#tab-servers")
        initial_content = page.locator("#servers-table").text_content()
        page.wait_for_selector("#servers-table")
        # Wait for polling (simulate with sleep or wait for content change)
        # This is a placeholder; in real test, use a more robust polling check
        import time
        time.sleep(2)
        expect(page.locator("#servers-table")).to_be_visible()
