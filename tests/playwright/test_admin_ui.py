# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_admin_ui.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

Test cases for admin UI.
"""

# Standard
import re
from typing import List

# Third-Party
from playwright.sync_api import ConsoleMessage, expect, Page
import pytest

# Local
from .pages.admin_page import AdminPage

# Console error patterns that are expected and should be ignored.
# Each entry is a regex matched against the error message text.
KNOWN_CONSOLE_ERROR_PATTERNS: List[str] = [
    r"/auth/sso/providers.*404",  # SSO providers endpoint when SSO is not configured
    r"Failed to load resource.*sso/providers",  # Same, alternate wording
]


def _is_known_error(message: str) -> bool:
    """Return True if the console error matches a known/expected pattern."""
    return any(re.search(pattern, message, re.IGNORECASE) for pattern in KNOWN_CONSOLE_ERROR_PATTERNS)


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


@pytest.mark.ui
@pytest.mark.smoke
class TestAdminConsoleErrors:
    """Verify the admin UI produces no unexpected JavaScript errors.

    Catches regressions like broken Alpine.js x-data attributes, Jinja2
    template rendering issues, and other client-side errors that would
    degrade the admin experience.
    """

    def test_no_console_errors_on_tab_navigation(self, admin_page: AdminPage):
        """Navigate through all major tabs and assert zero unexpected JS errors."""
        page: Page = admin_page.page
        errors: List[str] = []

        # Collect console errors as they occur
        def _on_console(msg: ConsoleMessage) -> None:
            if msg.type == "error":
                errors.append(msg.text)

        page.on("console", _on_console)

        try:
            # Fresh navigation to reset console state
            admin_page.navigate()

            # Visit each major tab — the sidebar helpers wait for the panel
            admin_page.click_servers_tab()
            admin_page.click_tools_tab()
            admin_page.click_gateways_tab()
            admin_page.click_resources_tab()
            admin_page.click_prompts_tab()
            admin_page.click_metrics_tab()

            # Within Metrics, click through Top Performers sub-tabs
            # (these use pagination_controls.html with query_params)
            for tab_label in ["Resources", "Prompts", "Servers", "Tools"]:
                btn = page.get_by_role("button", name=tab_label, exact=True).first
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(500)

            # Let any deferred JS settle
            page.wait_for_timeout(1000)
        finally:
            page.remove_listener("console", _on_console)

        # Filter out known/expected errors
        unexpected = [e for e in errors if not _is_known_error(e)]

        assert unexpected == [], (
            f"Found {len(unexpected)} unexpected console error(s) while navigating admin tabs:\n"
            + "\n".join(f"  - {e}" for e in unexpected)
        )
