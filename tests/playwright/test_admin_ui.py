# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_admin_ui.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

Test cases for admin UI.
"""

# Standard
import re

# Third-Party
from playwright.sync_api import expect, Page

# Local
from .pages.admin_page import AdminPage


class TestAdminUI:
    """Admin UI test cases."""

    def test_admin_panel_loads(self, admin_page: Page, base_url: str):
        """Test that admin panel loads successfully."""
        admin_ui = AdminPage(admin_page, base_url)
        admin_ui.navigate()

        # Verify admin panel loaded
        expect(admin_page).to_have_title("MCP Gateway Admin")
        assert admin_ui.element_exists(admin_ui.SERVERS_TAB)
        assert admin_ui.element_exists(admin_ui.TOOLS_TAB)
        assert admin_ui.element_exists(admin_ui.GATEWAYS_TAB)

    def test_navigate_between_tabs(self, admin_page: Page, base_url: str):
        """Test navigation between different tabs."""
        admin_ui = AdminPage(admin_page, base_url)
        admin_ui.navigate()

        # Test servers tab (it's actually "catalog" in the URL)
        admin_ui.click_servers_tab()
        # Accept both with and without trailing slash
        expect(admin_page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#catalog"))

        # Test tools tab
        admin_ui.click_tools_tab()
        expect(admin_page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#tools"))

        # Test gateways tab
        admin_ui.click_gateways_tab()
        expect(admin_page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#gateways"))

    def test_add_new_server(self, admin_page: Page, base_url: str):
        """Test adding a new server."""
        admin_ui = AdminPage(admin_page, base_url)
        admin_ui.navigate()

        # Add a test server
        test_server_name = "Test MCP Server"
        test_server_icon_url = "http://localhost:9000/icon.png"

        # Fill the form directly instead of using the page object method
        admin_page.fill('input[name="name"]', test_server_name)
        admin_page.fill('input[name="icon"]', test_server_icon_url)

        # Submit the form
        admin_page.click('button[type="submit"][data-testid="add-server-btn"]')

        # Wait for the redirect to complete - the form submission redirects to /admin#catalog
        admin_page.wait_for_url(re.compile(r".*/admin.*#catalog"), wait_until="networkidle")

        # Now wait for the server list to be visible
        admin_page.wait_for_selector('[data-testid="server-list"]', state="visible")

        # Verify server was added by checking if the name appears in the table
        server_rows = admin_page.locator('[data-testid="server-item"]')
        server_found = False

        # Wait a bit for the table to update
        admin_page.wait_for_timeout(1000)

        for i in range(server_rows.count()):
            row_text = server_rows.nth(i).text_content()
            if test_server_name in row_text:
                server_found = True
                break

        assert server_found, f"Server '{test_server_name}' was not found in the server list"

    def test_search_functionality(self, admin_page: Page, base_url: str):
        """Test search functionality in admin panel."""
        admin_ui = AdminPage(admin_page, base_url)
        admin_ui.navigate()

        # Get initial server count
        admin_page.wait_for_selector('[data-testid="server-list"]')
        initial_count = admin_ui.get_server_count()

        # Search for non-existent server
        admin_ui.search_servers("nonexistentserver123")
        admin_page.wait_for_timeout(500)

        # Should show no results or fewer results
        search_count = admin_ui.get_server_count()
        assert search_count <= initial_count

    def test_responsive_design(self, admin_page: Page, base_url: str):
        """Test admin panel responsive design."""
        admin_ui = AdminPage(admin_page, base_url)

        # Test mobile viewport
        admin_page.set_viewport_size({"width": 375, "height": 667})
        admin_ui.navigate()

        # Since there's no mobile menu implementation, let's check if the page is still functional
        # and that key elements are visible
        expect(admin_page.locator('[data-testid="servers-tab"]')).to_be_visible()

        # The tabs should still be accessible even in mobile view
        # Check if the page adapts by verifying the main content area
        expect(admin_page.locator("#catalog-panel, #tools-panel, #gateways-panel").first).to_be_visible()

        # Test tablet viewport
        admin_page.set_viewport_size({"width": 768, "height": 1024})
        admin_page.reload()
        expect(admin_page.locator('[data-testid="servers-tab"]')).to_be_visible()

        # Test desktop viewport
        admin_page.set_viewport_size({"width": 1920, "height": 1080})
        admin_page.reload()
        expect(admin_page.locator('[data-testid="servers-tab"]')).to_be_visible()
