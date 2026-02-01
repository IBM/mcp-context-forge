# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_admin_ui.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

Test cases for admin UI.
"""

# Standard
import uuid
import re
import time

# Third-Party
from playwright.sync_api import expect, Page
import pytest

# Local
from .pages.admin_page import AdminPage


class TestAdminUI:
    """Admin UI test cases."""

    def _find_server(self, page: Page, server_name: str, retries: int = 5):
        """Find a server by name via the admin JSON endpoint."""
        for _ in range(retries):
            cache_bust = str(int(time.time() * 1000))
            response = page.request.get(f"/admin/servers?per_page=500&cache_bust={cache_bust}")
            if response.ok:
                payload = response.json()
                data = payload.get("data", [])
                for server in data:
                    if server.get("name") == server_name:
                        return server
            time.sleep(0.5)
        return None

    def test_admin_panel_loads(self, admin_page: Page, base_url: str):
        """Test that admin panel loads successfully."""
        admin_ui = AdminPage(admin_page, base_url)
        admin_ui.navigate()

        # Verify admin panel loaded
        expect(admin_page).to_have_title(re.compile(r"(MCP Gateway Admin|ContextForge - Gateway Administration)"))
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

    def test_search_functionality(self, admin_page: Page, base_url: str):
        """Test search functionality in admin panel."""
        admin_ui = AdminPage(admin_page, base_url)
        admin_ui.navigate()
        admin_ui.click_servers_tab()

        # Get initial server count
        admin_page.wait_for_selector('[data-testid="server-list"]')
        initial_count = admin_ui.get_server_count()

        # Search for non-existent server
        admin_ui.search_servers("nonexistentserver123")
        admin_page.wait_for_timeout(500)

        # Should show no results or fewer results
        search_count = admin_ui.get_server_count()
        if initial_count > 0:
            assert search_count < initial_count
        else:
            pytest.skip("No servers available to validate search filtering.")

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
        visible_panels = admin_page.locator("#catalog-panel:visible, #tools-panel:visible, #gateways-panel:visible")
        assert visible_panels.count() > 0

        # Test tablet viewport
        admin_page.set_viewport_size({"width": 768, "height": 1024})
        admin_ui.navigate()
        expect(admin_page.locator('[data-testid="servers-tab"]')).to_be_visible()

        # Test desktop viewport
        admin_page.set_viewport_size({"width": 1920, "height": 1080})
        admin_ui.navigate()
        expect(admin_page.locator('[data-testid="servers-tab"]')).to_be_visible()
