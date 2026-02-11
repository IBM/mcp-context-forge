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
from playwright.sync_api import expect
import pytest

# Local
from .pages.admin_page import AdminPage


@pytest.mark.ui
@pytest.mark.smoke
class TestAdminUI:
    """Admin UI test cases."""

    def test_admin_panel_loads(self, admin_page: AdminPage):
        """Test that admin panel loads successfully."""
        # admin_page fixture already navigated and authenticated
        # Verify admin panel loaded (no need to navigate again)
        expect(admin_page.page).to_have_title(re.compile(r"(MCP Gateway Admin|ContextForge - Gateway Administration)"))
        expect(admin_page.servers_tab).to_be_visible()
        expect(admin_page.tools_tab).to_be_visible()
        expect(admin_page.gateways_tab).to_be_visible()

    def test_navigate_between_tabs(self, admin_page: AdminPage, base_url: str):
        """Test navigation between different tabs."""
        admin_page.navigate()

        # Test servers tab (it's actually "catalog" in the URL)
        admin_page.click_servers_tab()
        # Accept both with and without trailing slash
        expect(admin_page.page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#catalog"))

        # Test tools tab
        admin_page.click_tools_tab()
        expect(admin_page.page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#tools"))

        # Test gateways tab
        admin_page.click_gateways_tab()
        expect(admin_page.page).to_have_url(re.compile(f"{re.escape(base_url)}/admin/?#gateways"))

    def test_search_functionality(self, admin_page: AdminPage):
        """Test search functionality in admin panel."""
        admin_page.navigate()
        admin_page.click_servers_tab()

        # Get initial server count (server_list may be empty/hidden, so use attached)
        admin_page.wait_for_attached(admin_page.server_list)
        initial_count = admin_page.get_server_count()

        # Search for non-existent server
        admin_page.search_servers("nonexistentserver123")

        # Wait for filtering to take effect
        admin_page.wait_for_count_change(admin_page.server_items, initial_count, timeout=5000)

        # Should show no results or fewer results
        search_count = admin_page.get_server_count()
        if initial_count > 0:
            assert search_count < initial_count
        else:
            pytest.skip("No servers available to validate search filtering.")

    def test_responsive_design(self, admin_page: AdminPage):
        """Test admin panel responsive design."""
        # Test mobile viewport
        admin_page.page.set_viewport_size({"width": 375, "height": 667})
        admin_page.navigate()

        # Since there's no mobile menu implementation, let's check if the page is still functional
        # and that key elements are visible
        expect(admin_page.servers_tab).to_be_visible()

        # The tabs should still be accessible even in mobile view
        # Check if the page adapts by verifying the main content area
        assert admin_page.catalog_panel.locator(":visible").count() > 0 or admin_page.tools_panel.locator(":visible").count() > 0 or admin_page.gateways_panel.locator(":visible").count() > 0

        # Test tablet viewport
        admin_page.page.set_viewport_size({"width": 768, "height": 1024})
        admin_page.navigate()
        expect(admin_page.servers_tab).to_be_visible()

        # Test desktop viewport
        admin_page.page.set_viewport_size({"width": 1920, "height": 1080})
        admin_page.navigate()
        expect(admin_page.servers_tab).to_be_visible()
