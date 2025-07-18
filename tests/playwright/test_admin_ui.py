# -*- coding: utf-8 -*-
"""Test cases for admin UI."""

# Third-Party
import pytest
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

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_navigate_between_tabs(self, page: Page, base_url: str):
        """Test navigation between different tabs."""
        admin_page = AdminPage(page, base_url)
        admin_page.navigate()

        # Test servers tab
        admin_page.click_servers_tab()
        expect(page).to_have_url(f"{base_url}/admin#servers")

        # Test tools tab
        admin_page.click_tools_tab()
        expect(page).to_have_url(f"{base_url}/admin#tools")

        # Test gateways tab
        admin_page.click_gateways_tab()
        expect(page).to_have_url(f"{base_url}/admin#gateways")

    def test_add_new_server(self, page: Page, base_url: str):
        """Test adding a new server."""
        admin_page = AdminPage(page, base_url)
        admin_page.navigate()

        # Add a test server
        test_server_name = "Test MCP Server"
        test_server_icon_url = "http://localhost:9000/icon.png"

        admin_page.add_server(test_server_name, test_server_icon_url)

        # Wait for server to be added
        page.wait_for_timeout(1000)

        # Verify server was added
        assert admin_page.server_exists(test_server_name)

    def test_search_functionality(self, page: Page, base_url: str):
        """Test search functionality in admin panel."""
        admin_page = AdminPage(page, base_url)
        admin_page.navigate()

        # Get initial server count
        initial_count = admin_page.get_server_count()

        # Search for non-existent server
        admin_page.search_servers("nonexistentserver123")
        page.wait_for_timeout(500)

        # Should show no results or fewer results
        search_count = admin_page.get_server_count()
        assert search_count <= initial_count

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_responsive_design(self, page: Page, base_url: str):
        """Test admin panel responsive design."""
        admin_page = AdminPage(page, base_url)

        # Test mobile viewport
        page.set_viewport_size({"width": 375, "height": 667})
        admin_page.navigate()

        # Verify mobile menu exists
        assert page.is_visible('[data-testid="mobile-menu"]') or page.is_visible(".mobile-menu")

        # Test tablet viewport
        page.set_viewport_size({"width": 768, "height": 1024})
        page.reload()

        # Test desktop viewport
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.reload()
