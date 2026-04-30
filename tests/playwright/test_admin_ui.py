# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_admin_ui.py
Copyright 2026
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
        expect(admin_page.page).to_have_title(re.compile(r"(ContextForge Admin|ContextForge - Gateway Administration)"))
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
        assert (
            admin_page.page.locator("#overview-panel:visible").count() > 0
            or admin_page.catalog_panel.locator(":visible").count() > 0
            or admin_page.tools_panel.locator(":visible").count() > 0
            or admin_page.gateways_panel.locator(":visible").count() > 0
        )

        # Test tablet viewport
        admin_page.page.set_viewport_size({"width": 768, "height": 1024})
        admin_page.navigate()
        expect(admin_page.servers_tab).to_be_visible()

        # Test desktop viewport
        admin_page.page.set_viewport_size({"width": 1920, "height": 1080})
        admin_page.navigate()
        expect(admin_page.servers_tab).to_be_visible()

    def test_sidebar_visible_after_mobile_collapse_and_resize(self, admin_page: AdminPage):
        """Test sidebar reappears when resizing from mobile back to desktop (#2947)."""
        sidebar = admin_page.page.locator("#sidebar")

        # Start at desktop size — sidebar should be visible
        admin_page.page.set_viewport_size({"width": 1280, "height": 800})
        admin_page.navigate()
        expect(sidebar).to_be_visible()

        # Shrink to mobile — hide sidebar via Alpine $dispatch, then verify hamburger toggle
        admin_page.page.set_viewport_size({"width": 375, "height": 667})
        admin_page.page.wait_for_timeout(300)
        # Alpine keeps sidebarOpen=true from desktop; force it closed
        admin_page.page.evaluate("""() => {
                const el = document.querySelector('[x-data]');
                if (!el) return;
                // Try Alpine v3 _x_dataStack, then v2 __x
                if (el._x_dataStack) { el._x_dataStack[0].sidebarOpen = false; }
                else if (el.__x) { el.__x.$data.sidebarOpen = false; }
            }""")
        admin_page.page.wait_for_timeout(500)

        hamburger = admin_page.page.locator("button.lg\\:hidden")
        expect(hamburger).to_be_visible(timeout=10000)

        # Open sidebar via hamburger (use force to bypass any residual overlay)
        hamburger.click(force=True, timeout=10000)
        admin_page.page.wait_for_timeout(500)
        expect(sidebar).to_be_visible(timeout=10000)

        # Close sidebar again
        admin_page.page.evaluate("""() => {
                const el = document.querySelector('[x-data]');
                if (!el) return;
                if (el._x_dataStack) { el._x_dataStack[0].sidebarOpen = false; }
                else if (el.__x) { el.__x.$data.sidebarOpen = false; }
            }""")
        admin_page.page.wait_for_timeout(400)

        # Resize back to desktop — sidebar must reappear without page reload
        admin_page.page.set_viewport_size({"width": 1280, "height": 800})
        admin_page.page.wait_for_timeout(300)
        expect(sidebar).to_be_visible()

    def test_scroll_reset_on_tab_navigation(self, admin_page: AdminPage):
        """Test that tab navigation resets scroll position to top (#3748)."""
        admin_page.navigate()

        admin_page.click_servers_tab()
        admin_page.page.wait_for_selector("#catalog-panel", state="visible", timeout=10000)

        main_container = admin_page.page.locator("[data-scroll-container]")
        expect(main_container).to_be_attached()

        # Inject a tall spacer so the container is guaranteed to be scrollable
        # regardless of how much real content is loaded.
        admin_page.page.evaluate("""() => {
                const container = document.querySelector('[data-scroll-container]');
                if (container) {
                    const spacer = document.createElement('div');
                    spacer.id = '_scroll_test_spacer';
                    spacer.style.height = '5000px';
                    container.appendChild(spacer);
                }
            }""")

        # Scroll down and wait for the browser to apply it
        admin_page.page.evaluate("""() => {
                const container = document.querySelector('[data-scroll-container]');
                if (container) { container.scrollTop = 500; }
            }""")
        admin_page.page.wait_for_function(
            "document.querySelector('[data-scroll-container]').scrollTop > 0",
            timeout=5000,
        )

        # Switch tab — showTab() should reset scroll via requestAnimationFrame
        admin_page.click_tools_tab()
        admin_page.page.wait_for_selector("#tools-panel", state="visible", timeout=10000)

        # Wait for the RAF-driven scroll reset rather than a fixed sleep
        admin_page.page.wait_for_function(
            "document.querySelector('[data-scroll-container]').scrollTop === 0",
            timeout=5000,
        )

        # Second round: verify consistency across another tab pair
        admin_page.page.evaluate("""() => {
                const container = document.querySelector('[data-scroll-container]');
                if (container) { container.scrollTop = 300; }
            }""")
        admin_page.page.wait_for_function(
            "document.querySelector('[data-scroll-container]').scrollTop > 0",
            timeout=5000,
        )

        admin_page.click_gateways_tab()
        admin_page.page.wait_for_selector("#gateways-panel", state="visible", timeout=10000)

        admin_page.page.wait_for_function(
            "document.querySelector('[data-scroll-container]').scrollTop === 0",
            timeout=5000,
        )
