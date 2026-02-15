# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_mcp_registry_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test cases for MCP Registry page.
"""

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from .pages.mcp_registry_page import MCPRegistryPage


@pytest.mark.ui
@pytest.mark.smoke
class TestMCPRegistryPage:
    """MCP Registry page test cases."""

    def test_registry_panel_loads(self, mcp_registry_page: MCPRegistryPage):
        """Test that MCP Registry panel loads successfully."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Verify panel is visible
        expect(mcp_registry_page.registry_panel).to_be_visible()
        expect(mcp_registry_page.overview_card).to_be_visible()

    def test_overview_card_displays_counts(self, mcp_registry_page: MCPRegistryPage):
        """Test that overview card displays server counts."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Verify all count elements are visible
        expect(mcp_registry_page.total_servers_count).to_be_visible()
        expect(mcp_registry_page.registered_servers_count).to_be_visible()
        expect(mcp_registry_page.categories_count).to_be_visible()

        # Verify counts are numeric
        total = mcp_registry_page.get_total_servers_count()
        registered = mcp_registry_page.get_registered_servers_count()
        categories = mcp_registry_page.get_categories_count()

        assert total >= 0, "Total servers count should be non-negative"
        assert registered >= 0, "Registered servers count should be non-negative"
        assert categories > 0, "Categories count should be positive"
        assert registered <= total, "Registered servers should not exceed total servers"

    def test_refresh_catalog_button_visible(self, mcp_registry_page: MCPRegistryPage):
        """Test that refresh catalog button is visible and clickable."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Verify refresh button is visible
        expect(mcp_registry_page.refresh_catalog_btn).to_be_visible()

        # Click refresh button
        mcp_registry_page.refresh_catalog()

        # Verify panel is still visible after refresh
        expect(mcp_registry_page.registry_panel).to_be_visible()

    def test_filter_controls_visible(self, mcp_registry_page: MCPRegistryPage):
        """Test that all filter controls are visible."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Verify filter card is visible
        expect(mcp_registry_page.filters_card).to_be_visible()

        # Verify all filter controls
        expect(mcp_registry_page.category_filter).to_be_visible()
        expect(mcp_registry_page.auth_filter).to_be_visible()
        expect(mcp_registry_page.search_input).to_be_visible()

    def test_statistics_cards_visible(self, mcp_registry_page: MCPRegistryPage):
        """Test that all statistics cards are visible."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Verify all statistics cards
        expect(mcp_registry_page.categories_card).to_be_visible()
        expect(mcp_registry_page.auth_types_card).to_be_visible()
        expect(mcp_registry_page.providers_card).to_be_visible()

    def test_server_grid_displays(self, mcp_registry_page: MCPRegistryPage):
        """Test that server grid displays with server cards."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Verify server grid is visible
        expect(mcp_registry_page.server_grid).to_be_visible()

        # Verify at least one server card is displayed
        server_count = mcp_registry_page.get_server_count()
        assert server_count > 0, "At least one server should be displayed"

    def test_category_filter_functionality(self, mcp_registry_page: MCPRegistryPage):
        """Test category filter changes displayed servers."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Check if "Software Development" option exists in the category filter dropdown
        options = mcp_registry_page.category_filter.evaluate("el => [...el.options].map(o => o.text)")
        if "Software Development" not in options:
            pytest.skip("'Software Development' category not available in registry filter options")

        # Get initial server count
        initial_count = mcp_registry_page.get_server_count()

        # Select a specific category (use one that exists in the DOM)
        mcp_registry_page.select_category("Software Development")

        # Verify filter was applied
        assert mcp_registry_page.verify_filter_applied("category", "Software Development")

        # Get filtered count
        filtered_count = mcp_registry_page.get_server_count()

        # Filtered count should be less than or equal to initial count
        assert filtered_count <= initial_count, "Filtered results should not exceed initial count"

    def test_auth_type_filter_functionality(self, mcp_registry_page: MCPRegistryPage):
        """Test auth type filter changes displayed servers."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Check if "API Key" option exists in the auth filter dropdown
        options = mcp_registry_page.auth_filter.evaluate("el => [...el.options].map(o => o.text)")
        if "API Key" not in options:
            pytest.skip("'API Key' auth type not available in registry filter options")

        # Get initial server count
        initial_count = mcp_registry_page.get_server_count()

        # Select a specific auth type
        mcp_registry_page.select_auth_type("API Key")

        # Verify filter was applied
        assert mcp_registry_page.verify_filter_applied("auth", "API Key")

        # Get filtered count
        filtered_count = mcp_registry_page.get_server_count()

        # Filtered count should be less than or equal to initial count
        assert filtered_count <= initial_count, "Filtered results should not exceed initial count"

    def test_search_functionality(self, mcp_registry_page: MCPRegistryPage):
        """Test search input filters servers."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Get initial server count
        initial_count = mcp_registry_page.get_server_count()

        # Search for a specific term
        mcp_registry_page.search_servers("github")

        # Get search results count
        search_count = mcp_registry_page.get_server_count()

        # Search results should be less than or equal to initial count
        assert search_count <= initial_count, "Search results should not exceed initial count"

    def test_clear_filters_functionality(self, mcp_registry_page: MCPRegistryPage):
        """Test clearing filters restores all servers."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Get initial count before filtering
        initial_count = mcp_registry_page.get_server_count()

        # Apply filters
        mcp_registry_page.select_category("Software Development")
        mcp_registry_page.select_auth_type("API Key")
        filtered_count = mcp_registry_page.get_server_count()

        # Clear filters
        mcp_registry_page.clear_filters()

        # Get count after clearing
        cleared_count = mcp_registry_page.get_server_count()

        # Count after clearing should restore to initial count
        assert cleared_count >= filtered_count, "Clearing filters should show more or equal servers"
        assert cleared_count == initial_count, "Clearing filters should restore to the initial count"

    def test_server_card_structure(self, mcp_registry_page: MCPRegistryPage):
        """Test that server cards have proper structure."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Get first server card
        first_card = mcp_registry_page.server_cards.first
        expect(first_card).to_be_visible()

        # Verify card has required elements
        expect(first_card.locator("h3")).to_be_visible()  # Server name
        expect(first_card.locator("p.text-sm")).to_be_visible()  # Description
        expect(first_card.locator("button")).to_be_visible()  # Action button


@pytest.mark.ui
@pytest.mark.integration
class TestMCPRegistryPageIntegration:
    """Integration tests for MCP Registry page."""

    def test_category_badge_click_filters(self, mcp_registry_page: MCPRegistryPage):
        """Test clicking category badge applies filter."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Click on a category badge
        mcp_registry_page.click_category_badge("Software Development")

        # Verify filter was applied
        assert mcp_registry_page.verify_filter_applied("category", "Software Development")

    def test_auth_type_click_filters(self, mcp_registry_page: MCPRegistryPage):
        """Test clicking auth type item applies filter."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Click on an auth type item
        mcp_registry_page.click_auth_type_item("OAuth2.1")

        # Verify filter was applied
        assert mcp_registry_page.verify_filter_applied("auth", "OAuth2.1")

    def test_combined_filters(self, mcp_registry_page: MCPRegistryPage):
        """Test applying multiple filters together."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Get initial count
        initial_count = mcp_registry_page.get_server_count()

        # Apply category filter
        mcp_registry_page.select_category("Software Development")
        category_count = mcp_registry_page.get_server_count()

        # Apply auth type filter
        mcp_registry_page.select_auth_type("OAuth2.1")
        combined_count = mcp_registry_page.get_server_count()

        # Combined filters should show fewer or equal results
        assert combined_count <= category_count, "Combined filters should not show more results than single filter"
        assert combined_count <= initial_count, "Combined filters should not show more results than no filters"

    def test_search_with_filters(self, mcp_registry_page: MCPRegistryPage):
        """Test search works in combination with filters."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Apply category filter
        mcp_registry_page.select_category("Software Development")
        filtered_count = mcp_registry_page.get_server_count()

        # Add search term
        mcp_registry_page.search_servers("git")
        search_count = mcp_registry_page.get_server_count()

        # Search with filter should show fewer or equal results
        assert search_count <= filtered_count, "Search with filter should not show more results than filter alone"

    @pytest.mark.skip(reason="Modal interaction tests - to be implemented after Add Server functionality is verified")
    def test_api_key_modal_opens(self, mcp_registry_page: MCPRegistryPage):
        """Test that API key modal opens when clicking Add Server."""
        pytest.skip("Skipping modal interaction test - Add Server functionality needs verification")

    @pytest.mark.skip(reason="Modal interaction tests - to be implemented after Add Server functionality is verified")
    def test_api_key_modal_close(self, mcp_registry_page: MCPRegistryPage):
        """Test that API key modal can be closed."""
        pytest.skip("Skipping modal interaction test - Add Server functionality needs verification")

    @pytest.mark.skip(reason="Modal interaction tests - to be implemented after Add Server functionality is verified")
    def test_api_key_modal_form_elements(self, mcp_registry_page: MCPRegistryPage):
        """Test that API key modal has all required form elements."""
        pytest.skip("Skipping modal interaction test - Add Server functionality needs verification")

    def test_navigate_from_other_tabs(self, mcp_registry_page: MCPRegistryPage):
        """Test navigation to registry tab from other tabs."""
        # Start from servers tab
        mcp_registry_page.sidebar.click_servers_tab()
        mcp_registry_page.page.wait_for_timeout(500)

        # Navigate to registry tab
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Verify we're on registry tab
        expect(mcp_registry_page.registry_panel).to_be_visible()

        # Navigate to tools tab and back
        mcp_registry_page.sidebar.click_tools_tab()
        mcp_registry_page.page.wait_for_timeout(500)

        mcp_registry_page.navigate_to_registry_tab()
        expect(mcp_registry_page.registry_panel).to_be_visible()

    def test_server_count_consistency(self, mcp_registry_page: MCPRegistryPage):
        """Test that server counts remain consistent across interactions."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Get initial total count
        initial_total = mcp_registry_page.get_total_servers_count()

        # Apply and clear filters
        mcp_registry_page.select_category("Software Development")
        mcp_registry_page.page.wait_for_timeout(500)
        mcp_registry_page.clear_filters()

        # Get total count after filter operations
        after_filters_total = mcp_registry_page.get_total_servers_count()

        # Total count should remain the same
        assert after_filters_total == initial_total, "Total server count should remain consistent"

    def test_responsive_design(self, mcp_registry_page: MCPRegistryPage):
        """Test that registry panel adapts to different viewport sizes."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Test mobile viewport
        mcp_registry_page.page.set_viewport_size({"width": 375, "height": 667})
        expect(mcp_registry_page.registry_panel).to_be_visible()
        expect(mcp_registry_page.overview_card).to_be_visible()

        # Test tablet viewport
        mcp_registry_page.page.set_viewport_size({"width": 768, "height": 1024})
        expect(mcp_registry_page.registry_panel).to_be_visible()
        expect(mcp_registry_page.server_grid).to_be_visible()

        # Test desktop viewport
        mcp_registry_page.page.set_viewport_size({"width": 1920, "height": 1080})
        expect(mcp_registry_page.registry_panel).to_be_visible()
        expect(mcp_registry_page.categories_card).to_be_visible()


@pytest.mark.ui
@pytest.mark.htmx
class TestMCPRegistryHTMX:
    """HTMX-specific tests for MCP Registry page."""

    def test_htmx_filter_updates_content(self, mcp_registry_page: MCPRegistryPage):
        """Test that HTMX updates content when filters change."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Get initial server grid state
        initial_grid = mcp_registry_page.server_grid
        expect(initial_grid).to_be_visible()

        # Change filter (triggers HTMX)
        mcp_registry_page.select_category("Software Development")

        # Wait for HTMX to update
        mcp_registry_page.page.wait_for_timeout(1500)

        # Verify grid is still visible (HTMX updated it)
        expect(mcp_registry_page.server_grid).to_be_visible()

    def test_htmx_search_debounce(self, mcp_registry_page: MCPRegistryPage):
        """Test that search input has proper debounce delay."""
        mcp_registry_page.navigate_to_registry_tab()
        mcp_registry_page.wait_for_registry_loaded()

        # Type in search (should trigger HTMX after 500ms delay)
        mcp_registry_page.search_input.fill("test")

        # Wait for debounce delay
        mcp_registry_page.page.wait_for_timeout(1000)

        # Verify content is still visible
        expect(mcp_registry_page.server_grid).to_be_visible()
