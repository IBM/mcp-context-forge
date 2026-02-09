# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/mcp_registry_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Registry page object for browsing and registering MCP servers.
"""

# Third-Party
from playwright.sync_api import expect, Locator

# Local
from .base_page import BasePage


class MCPRegistryPage(BasePage):
    """Page object for MCP Registry features."""

    # ==================== Panel Elements ====================

    @property
    def registry_panel(self) -> Locator:
        """MCP Registry panel container."""
        return self.page.locator("#mcp-registry-panel")

    @property
    def registry_servers_container(self) -> Locator:
        """MCP Registry servers container (HTMX target)."""
        return self.page.locator("#mcp-registry-servers")

    # ==================== Overview Card ====================

    @property
    def overview_card(self) -> Locator:
        """MCP Registry overview card with gradient background."""
        return self.registry_servers_container.locator(".bg-gradient-to-r").first

    @property
    def total_servers_count(self) -> Locator:
        """Total servers count display."""
        return self.overview_card.locator("div.text-3xl.font-bold").first

    @property
    def registered_servers_count(self) -> Locator:
        """Registered servers count display."""
        return self.overview_card.locator("div.text-3xl.font-bold").nth(1)

    @property
    def categories_count(self) -> Locator:
        """Categories count display."""
        return self.overview_card.locator("div.text-3xl.font-bold").nth(2)

    @property
    def refresh_catalog_btn(self) -> Locator:
        """Refresh catalog button."""
        return self.overview_card.locator('button:has-text("Refresh")')

    # ==================== Filter Elements ====================

    @property
    def filters_card(self) -> Locator:
        """Filters card container."""
        return self.registry_servers_container.locator(".bg-white.rounded-lg.shadow-sm").first

    @property
    def category_filter(self) -> Locator:
        """Category filter dropdown."""
        return self.page.locator("#category-filter")

    @property
    def auth_filter(self) -> Locator:
        """Auth type filter dropdown."""
        return self.page.locator("#auth-filter")

    @property
    def search_input(self) -> Locator:
        """Search input field."""
        return self.page.locator("#search-input")

    # ==================== Statistics Cards ====================

    @property
    def categories_card(self) -> Locator:
        """Categories statistics card."""
        return self.registry_servers_container.locator(".bg-white.rounded-lg.shadow").first

    @property
    def auth_types_card(self) -> Locator:
        """Authentication types statistics card."""
        return self.registry_servers_container.locator(".bg-white.rounded-lg.shadow").nth(1)

    @property
    def providers_card(self) -> Locator:
        """Providers statistics card."""
        return self.registry_servers_container.locator(".bg-white.rounded-lg.shadow").nth(2)

    def get_category_badge(self, category: str) -> Locator:
        """Get a specific category badge by name.

        Args:
            category: Category name (e.g., "Software Development")

        Returns:
            Locator for the category badge
        """
        return self.categories_card.locator(f'span:has-text("{category}")')

    def get_auth_type_item(self, auth_type: str) -> Locator:
        """Get a specific auth type item by name.

        Args:
            auth_type: Auth type name (e.g., "OAuth2.1", "API Key")

        Returns:
            Locator for the auth type item
        """
        return self.auth_types_card.locator(f'span:has-text("{auth_type}")').first

    def get_provider_badge(self, provider: str) -> Locator:
        """Get a specific provider badge by name.

        Args:
            provider: Provider name (e.g., "GitHub", "Stripe")

        Returns:
            Locator for the provider badge
        """
        return self.providers_card.locator(f'span:has-text("{provider}")')

    # ==================== Server Grid ====================

    @property
    def server_grid(self) -> Locator:
        """Server grid container."""
        return self.page.locator("#server-grid")

    @property
    def server_cards(self) -> Locator:
        """All server cards in the grid."""
        return self.server_grid.locator(".server-card")

    def get_server_card_by_name(self, server_name: str) -> Locator:
        """Get a specific server card by name.

        Args:
            server_name: Server name (e.g., "GitHub", "Stripe")

        Returns:
            Locator for the server card
        """
        return self.server_grid.locator(f'.server-card:has(h3:has-text("{server_name}"))')

    def get_server_add_button(self, server_name: str) -> Locator:
        """Get the 'Add Server' button for a specific server.

        Args:
            server_name: Server name

        Returns:
            Locator for the add button
        """
        return self.get_server_card_by_name(server_name).locator('button:has-text("Add Server")')

    # ==================== API Key Modal ====================

    @property
    def api_key_modal(self) -> Locator:
        """API Key modal container within MCP registry servers."""
        return self.page.locator("#mcp-registry-servers #api-key-modal")

    @property
    def modal_server_name(self) -> Locator:
        """Server name in modal header."""
        return self.api_key_modal.locator("#modal-server-name")

    @property
    def modal_custom_name_input(self) -> Locator:
        """Custom name input in modal."""
        return self.api_key_modal.locator("#modal-custom-name")

    @property
    def modal_api_key_input(self) -> Locator:
        """API key input in modal."""
        return self.api_key_modal.locator("#modal-api-key")

    @property
    def modal_register_button(self) -> Locator:
        """Register button in modal."""
        return self.api_key_modal.locator('button:has-text("Register Server")')

    @property
    def modal_close_button(self) -> Locator:
        """Close button in modal."""
        return self.api_key_modal.locator('button[onclick*="closeApiKeyModal"]')

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_registry_tab(self) -> None:
        """Navigate to MCP Registry tab and wait for panel to be visible."""
        self.sidebar.click_registry_tab()

    # ==================== High-Level Filter Operations ====================

    def select_category(self, category: str) -> None:
        """Select a category from the filter dropdown.

        Args:
            category: Category name to select
        """
        self.category_filter.select_option(category)
        # Wait for HTMX to update the content
        self.page.wait_for_timeout(1000)

    def select_auth_type(self, auth_type: str) -> None:
        """Select an auth type from the filter dropdown.

        Args:
            auth_type: Auth type to select (e.g., "OAuth2.1", "API Key")
        """
        self.auth_filter.select_option(auth_type)
        # Wait for HTMX to update the content
        self.page.wait_for_timeout(1000)

    def search_servers(self, query: str) -> None:
        """Search for servers using the search input.

        Args:
            query: Search query string
        """
        self.search_input.fill(query)
        # Wait for HTMX debounced search (500ms delay)
        self.page.wait_for_timeout(1000)

    def clear_filters(self) -> None:
        """Clear all filters and search."""
        self.category_filter.select_option("")
        self.auth_filter.select_option("")
        self.search_input.fill("")
        self.page.wait_for_timeout(1000)

    def click_category_badge(self, category: str) -> None:
        """Click on a category badge to filter by that category.

        Args:
            category: Category name to filter by
        """
        badge = self.get_category_badge(category)
        badge.click()
        self.page.wait_for_timeout(1000)

    def click_auth_type_item(self, auth_type: str) -> None:
        """Click on an auth type item to filter by that type.

        Args:
            auth_type: Auth type to filter by
        """
        item = self.get_auth_type_item(auth_type)
        item.click()
        self.page.wait_for_timeout(1000)

    # ==================== High-Level Server Operations ====================

    def get_server_count(self) -> int:
        """Get the number of servers currently displayed.

        Returns:
            Number of visible server cards
        """
        return self.server_cards.count()

    def get_total_servers_count(self) -> int:
        """Get the total servers count from overview card.

        Returns:
            Total servers count as integer
        """
        count_text = self.total_servers_count.text_content().strip()
        return int(count_text)

    def get_registered_servers_count(self) -> int:
        """Get the registered servers count from overview card.

        Returns:
            Registered servers count as integer
        """
        count_text = self.registered_servers_count.text_content().strip()
        return int(count_text)

    def get_categories_count(self) -> int:
        """Get the categories count from overview card.

        Returns:
            Categories count as integer
        """
        count_text = self.categories_count.text_content().strip()
        return int(count_text)

    def refresh_catalog(self) -> None:
        """Click the refresh catalog button."""
        self.refresh_catalog_btn.click()
        self.page.wait_for_timeout(1000)

    def server_exists(self, server_name: str) -> bool:
        """Check if a server with the given name exists in the grid.

        Args:
            server_name: Server name to check

        Returns:
            True if server exists, False otherwise
        """
        return self.get_server_card_by_name(server_name).count() > 0

    # ==================== High-Level Modal Operations ====================

    def open_add_server_modal(self, server_name: str) -> None:
        """Open the API key modal for a specific server.

        Args:
            server_name: Server name to add
        """
        add_button = self.get_server_add_button(server_name)
        add_button.click()
        expect(self.api_key_modal).to_be_visible(timeout=5000)

    def is_modal_visible(self) -> bool:
        """Check if the API key modal is visible.

        Returns:
            True if modal is visible, False otherwise
        """
        return self.api_key_modal.is_visible()

    def close_modal(self) -> None:
        """Close the API key modal."""
        self.modal_close_button.click()
        expect(self.api_key_modal).to_be_hidden(timeout=5000)

    def fill_api_key_form(self, api_key: str, custom_name: str = None) -> None:
        """Fill the API key form in the modal.

        Args:
            api_key: API key to enter
            custom_name: Optional custom name for the server
        """
        if custom_name:
            self.modal_custom_name_input.fill(custom_name)
        self.modal_api_key_input.fill(api_key)

    def submit_api_key_form(self) -> None:
        """Submit the API key form."""
        self.modal_register_button.click()

    def register_server_with_api_key(self, server_name: str, api_key: str, custom_name: str = None) -> None:
        """Complete flow to register a server with API key.

        Args:
            server_name: Server name to register
            api_key: API key for authentication
            custom_name: Optional custom name for the server
        """
        self.open_add_server_modal(server_name)
        self.fill_api_key_form(api_key, custom_name)
        self.submit_api_key_form()
        # Wait for registration to complete
        self.page.wait_for_timeout(2000)

    # ==================== High-Level Verification Methods ====================

    def get_server_card_info(self, server_name: str) -> dict:
        """Get information from a server card.

        Args:
            server_name: Server name

        Returns:
            Dictionary with server card information
        """
        card = self.get_server_card_by_name(server_name)

        return {
            "name": card.locator("h3").text_content().strip(),
            "description": card.locator("p.text-sm").text_content().strip(),
            "provider": card.locator('div:has-text("Provider:")').text_content().replace("Provider:", "").strip(),
            "url": card.locator('div:has-text("URL:")').text_content().replace("URL:", "").strip(),
            "auth_badge": card.locator("span.bg-yellow-100, span.bg-green-100").first.text_content().strip() if card.locator("span.bg-yellow-100, span.bg-green-100").count() > 0 else None,
            "category_badge": card.locator("span.bg-purple-100").first.text_content().strip() if card.locator("span.bg-purple-100").count() > 0 else None,
        }

    def wait_for_registry_loaded(self, timeout: int = 30000) -> None:
        """Wait for MCP Registry panel to be loaded and ready.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        expect(self.registry_panel).to_be_visible(timeout=timeout)
        expect(self.overview_card).to_be_visible(timeout=timeout)
        expect(self.server_grid).to_be_visible(timeout=timeout)

    def verify_filter_applied(self, filter_type: str, filter_value: str) -> bool:
        """Verify that a filter has been applied correctly.

        Args:
            filter_type: Type of filter ("category" or "auth")
            filter_value: Expected filter value

        Returns:
            True if filter is applied correctly
        """
        if filter_type == "category":
            selected = self.category_filter.input_value()
            return selected == filter_value
        if filter_type == "auth":
            selected = self.auth_filter.input_value()
            return selected == filter_value
        return False
