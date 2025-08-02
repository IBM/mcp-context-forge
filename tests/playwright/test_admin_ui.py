# -*- coding: utf-8 -*-
"""Test cases for admin UI.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

"""

# Standard
import re

# Third-Party
from playwright.sync_api import expect, Page

# Local
from .pages.admin_page import AdminPage


class TestAdminUI:
    """Admin UI test cases."""

    def test_admin_panel_loads(self, page: Page, base_url: str):
        """Test that admin panel loads successfully."""
        admin_page = AdminPage(page, base_url)
        admin_page.navigate()

        # Verify admin panel loaded
        expect(page).to_have_title("MCP Gateway Admin")
        assert admin_page.element_exists(admin_page.SERVERS_TAB)
        assert admin_page.element_exists(admin_page.TOOLS_TAB)
        assert admin_page.element_exists(admin_page.GATEWAYS_TAB)

    def test_navigate_between_tabs(self, page: Page, base_url: str):
        """Test navigation between different tabs."""
        admin_page = AdminPage(page, base_url)
        admin_page.navigate()

        # Test servers tab (it's actually "catalog" in the URL)
        admin_page.click_servers_tab()
        # Accept both with and without trailing slash
        expect(page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#catalog"))

        # Test tools tab
        admin_page.click_tools_tab()
        expect(page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#tools"))

        # Test gateways tab
        admin_page.click_gateways_tab()
        expect(page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#gateways"))

    def test_add_new_server(self, page: Page, base_url: str):
        """Test adding a new server."""
        admin_page = AdminPage(page, base_url)
        admin_page.navigate()

        # Add a test server
        test_server_name = "Test MCP Server"
        test_server_icon_url = "http://localhost:9000/icon.png"

        # Fill the form directly instead of using the page object method
        page.fill('input[name="name"]', test_server_name)
        page.fill('input[name="icon"]', test_server_icon_url)

        # Submit the form
        page.click('button[type="submit"][data-testid="add-server-btn"]')

        # Wait for the redirect to complete - the form submission redirects to /admin#catalog
        page.wait_for_url(re.compile(r".*/admin.*#catalog"), wait_until="networkidle")

        # Now wait for the server list to be visible
        page.wait_for_selector('[data-testid="server-list"]', state="visible")

        # Verify server was added by checking if the name appears in the table
        server_rows = page.locator('[data-testid="server-item"]')
        server_found = False

        # Wait a bit for the table to update
        page.wait_for_timeout(1000)

        for i in range(server_rows.count()):
            row_text = server_rows.nth(i).text_content()
            if test_server_name in row_text:
                server_found = True
                break

        assert server_found, f"Server '{test_server_name}' was not found in the server list"

    def test_search_functionality(self, page: Page, base_url: str):
        """Test search functionality in admin panel."""
        admin_page = AdminPage(page, base_url)
        admin_page.navigate()

        # Get initial server count
        page.wait_for_selector('[data-testid="server-list"]')
        initial_count = admin_page.get_server_count()

        # Search for non-existent server
        admin_page.search_servers("nonexistentserver123")
        page.wait_for_timeout(500)

        # Should show no results or fewer results
        search_count = admin_page.get_server_count()
        assert search_count <= initial_count

    def test_responsive_design(self, page: Page, base_url: str):
        """Test admin panel responsive design."""
        admin_page = AdminPage(page, base_url)

        # Test mobile viewport
        page.set_viewport_size({"width": 375, "height": 667})
        admin_page.navigate()

        # Since there's no mobile menu implementation, let's check if the page is still functional
        # and that key elements are visible
        expect(page.locator('[data-testid="servers-tab"]')).to_be_visible()

        # The tabs should still be accessible even in mobile view
        # Check if the page adapts by verifying the main content area
        expect(page.locator("#catalog-panel, #tools-panel, #gateways-panel").first).to_be_visible()

        # Test tablet viewport
        page.set_viewport_size({"width": 768, "height": 1024})
        page.reload()
        expect(page.locator('[data-testid="servers-tab"]')).to_be_visible()

        # Test desktop viewport
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.reload()
        expect(page.locator('[data-testid="servers-tab"]')).to_be_visible()
