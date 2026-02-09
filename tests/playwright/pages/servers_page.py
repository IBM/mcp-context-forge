# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/servers_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Servers page object for Virtual MCP Server management features.
"""

# Third-Party
from playwright.sync_api import expect, Locator

# Local
from .base_page import BasePage


class ServersPage(BasePage):
    """Page object for Virtual MCP Server management features.

    This page manages the Virtual Servers (Catalog) tab where users can:
    - View and search virtual MCP servers
    - Create new virtual servers
    - Associate tools, resources, and prompts with servers
    - Configure OAuth settings
    - Manage server visibility and tags
    """

    # ==================== Panel Elements ====================

    @property
    def catalog_panel(self) -> Locator:
        """Catalog/Servers panel container."""
        return self.page.locator("#catalog-panel")

    @property
    def panel_title(self) -> Locator:
        """Panel title 'Virtual MCP Servers'."""
        return self.catalog_panel.locator("h2:has-text('Virtual MCP Servers')")

    # ==================== Search and Filter Elements ====================

    @property
    def search_input(self) -> Locator:
        """Server search input."""
        return self.page.locator('[data-testid="search-input"]')

    @property
    def clear_search_btn(self) -> Locator:
        """Clear search button."""
        return self.page.locator("#catalog-clear-search")

    @property
    def show_inactive_checkbox(self) -> Locator:
        """Show inactive servers checkbox."""
        return self.page.locator("#show-inactive-servers")

    # ==================== Server Table Elements ====================

    @property
    def servers_table(self) -> Locator:
        """Servers table."""
        return self.page.locator("#servers-table")

    @property
    def servers_table_body(self) -> Locator:
        """Servers table body."""
        return self.page.locator("#servers-table-body")

    @property
    def server_list(self) -> Locator:
        """Server list tbody element (alternative selector)."""
        return self.page.locator('[data-testid="server-list"]')

    @property
    def server_rows(self) -> Locator:
        """All server table rows."""
        return self.servers_table_body.locator("tr")

    @property
    def server_items(self) -> Locator:
        """All server items (alternative selector)."""
        return self.page.locator('[data-testid="server-item"]')

    # ==================== Server Form Elements ====================

    @property
    def add_server_form(self) -> Locator:
        """Add server form."""
        return self.page.locator("#add-server-form")

    @property
    def server_id_input(self) -> Locator:
        """Custom UUID input field (optional)."""
        return self.add_server_form.locator('[name="id"]')

    @property
    def server_name_input(self) -> Locator:
        """Server name input field."""
        return self.add_server_form.locator('[name="name"]')

    @property
    def server_description_input(self) -> Locator:
        """Server description textarea."""
        return self.add_server_form.locator('[name="description"]')

    @property
    def server_icon_input(self) -> Locator:
        """Server icon URL input field."""
        return self.add_server_form.locator('[name="icon"]')

    @property
    def server_tags_input(self) -> Locator:
        """Server tags input field."""
        return self.add_server_form.locator('[name="tags"]')

    @property
    def add_server_btn(self) -> Locator:
        """Add server submit button."""
        return self.add_server_form.locator('button[type="submit"]')

    # ==================== Associated Items Elements ====================

    @property
    def associated_gateways_container(self) -> Locator:
        """Associated MCP Servers container."""
        return self.page.locator("#associatedGateways")

    @property
    def associated_tools_container(self) -> Locator:
        """Associated Tools container."""
        return self.page.locator("#associatedTools")

    @property
    def associated_resources_container(self) -> Locator:
        """Associated Resources container."""
        return self.page.locator("#associatedResources")

    @property
    def associated_prompts_container(self) -> Locator:
        """Associated Prompts container."""
        return self.page.locator("#associatedPrompts")

    @property
    def search_tools_input(self) -> Locator:
        """Search tools input."""
        return self.page.locator("#searchTools")

    @property
    def search_resources_input(self) -> Locator:
        """Search resources input."""
        return self.page.locator("#searchResources")

    @property
    def search_prompts_input(self) -> Locator:
        """Search prompts input."""
        return self.page.locator("#searchPrompts")

    @property
    def select_all_tools_btn(self) -> Locator:
        """Select all tools button."""
        return self.page.locator("#selectAllToolsBtn")

    @property
    def clear_all_tools_btn(self) -> Locator:
        """Clear all tools button."""
        return self.page.locator("#clearAllToolsBtn")

    # ==================== Visibility Radio Buttons ====================

    @property
    def visibility_public_radio(self) -> Locator:
        """Public visibility radio button."""
        return self.page.locator("#server-visibility-public")

    @property
    def visibility_team_radio(self) -> Locator:
        """Team visibility radio button."""
        return self.page.locator("#server-visibility-team")

    @property
    def visibility_private_radio(self) -> Locator:
        """Private visibility radio button."""
        return self.page.locator("#server-visibility-private")

    # ==================== OAuth Configuration Elements ====================

    @property
    def oauth_enabled_checkbox(self) -> Locator:
        """Enable OAuth 2.0 checkbox."""
        return self.page.locator("#server-oauth-enabled")

    @property
    def oauth_config_section(self) -> Locator:
        """OAuth configuration section."""
        return self.page.locator("#server-oauth-config-section")

    @property
    def oauth_authorization_server_input(self) -> Locator:
        """OAuth authorization server URL input."""
        return self.page.locator("#server-oauth-authorization-server")

    @property
    def oauth_scopes_input(self) -> Locator:
        """OAuth scopes input."""
        return self.page.locator("#server-oauth-scopes")

    @property
    def oauth_token_endpoint_input(self) -> Locator:
        """OAuth token endpoint URL input."""
        return self.page.locator("#server-oauth-token-endpoint")

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_servers_tab(self) -> None:
        """Navigate to Servers/Catalog tab and wait for panel to be visible."""
        self.sidebar.click_servers_tab()

    # ==================== High-Level Server Operations ====================

    def wait_for_servers_table_loaded(self, timeout: int = 30000) -> None:
        """Wait for servers table to be loaded and ready.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("#catalog-panel:not(.hidden)", timeout=timeout)
        # Wait for table body to exist in DOM (may be empty, so don't require visible)
        self.wait_for_attached(self.servers_table_body, timeout=timeout)

    def create_server(self, name: str, icon: str = "", description: str = "", tags: str = "", visibility: str = "public") -> None:
        """Create a new virtual server by filling and submitting the form.

        Args:
            name: Server name (required)
            icon: Server icon URL (optional)
            description: Server description (optional)
            tags: Comma-separated tags (optional)
            visibility: Visibility setting - "public", "team", or "private" (default: "public")
        """
        self.fill_locator(self.server_name_input, name)
        if icon:
            self.fill_locator(self.server_icon_input, icon)
        if description:
            self.fill_locator(self.server_description_input, description)
        if tags:
            self.fill_locator(self.server_tags_input, tags)

        # Set visibility
        if visibility == "team":
            self.click_locator(self.visibility_team_radio)
        elif visibility == "private":
            self.click_locator(self.visibility_private_radio)
        else:
            self.click_locator(self.visibility_public_radio)

        self.click_locator(self.add_server_btn)

    def fill_server_form(self, name: str, icon: str = "", description: str = "", tags: str = "", custom_id: str = "") -> None:
        """Fill the add server form with provided data (without submitting).

        Args:
            name: Server name (required)
            icon: Server icon URL (optional)
            description: Server description (optional)
            tags: Comma-separated tags (optional)
            custom_id: Custom UUID (optional)
        """
        if custom_id:
            self.fill_locator(self.server_id_input, custom_id)
        self.fill_locator(self.server_name_input, name)
        if icon:
            self.fill_locator(self.server_icon_input, icon)
        if description:
            self.fill_locator(self.server_description_input, description)
        if tags:
            self.fill_locator(self.server_tags_input, tags)

    def submit_server_form(self) -> None:
        """Submit the add server form."""
        self.click_locator(self.add_server_btn)

    def search_servers(self, query: str) -> None:
        """Search for servers using the search input.

        Args:
            query: Search query string
        """
        self.fill_locator(self.search_input, query)

    def clear_search(self) -> None:
        """Clear the server search."""
        self.click_locator(self.clear_search_btn)

    def toggle_show_inactive(self, show: bool = True) -> None:
        """Toggle the show inactive servers checkbox.

        Args:
            show: True to show inactive servers, False to hide them
        """
        is_checked = self.show_inactive_checkbox.is_checked()
        if (show and not is_checked) or (not show and is_checked):
            self.click_locator(self.show_inactive_checkbox)

    def get_server_count(self) -> int:
        """Get number of servers displayed.

        Returns:
            Number of visible server rows
        """
        self.page.wait_for_selector('[data-testid="server-list"]', state="attached")
        return self.server_items.locator(":visible").count()

    def server_exists(self, server_name: str) -> bool:
        """Check if a server with the given name exists in the table.

        Args:
            server_name: The name of the server to check

        Returns:
            True if server exists, False otherwise
        """
        return self.page.locator(f"text={server_name}").is_visible()

    def get_server_row(self, server_index: int) -> Locator:
        """Get a specific server row by index.

        Args:
            server_index: Index of the server row

        Returns:
            Locator for the server row
        """
        return self.server_rows.nth(server_index)

    # ==================== OAuth Configuration Methods ====================

    def enable_oauth(self, authorization_server: str, scopes: str = "openid profile email", token_endpoint: str = "") -> None:
        """Enable and configure OAuth 2.0 for the server.

        Args:
            authorization_server: OAuth authorization server URL (required)
            scopes: Space-separated OAuth scopes (default: "openid profile email")
            token_endpoint: OAuth token endpoint URL (optional)
        """
        # Enable OAuth
        if not self.oauth_enabled_checkbox.is_checked():
            self.click_locator(self.oauth_enabled_checkbox)

        # Wait for config section to be visible
        self.wait_for_visible(self.oauth_config_section)

        # Fill OAuth configuration
        self.fill_locator(self.oauth_authorization_server_input, authorization_server)
        self.fill_locator(self.oauth_scopes_input, scopes)
        if token_endpoint:
            self.fill_locator(self.oauth_token_endpoint_input, token_endpoint)

    def disable_oauth(self) -> None:
        """Disable OAuth 2.0 for the server."""
        if self.oauth_enabled_checkbox.is_checked():
            self.click_locator(self.oauth_enabled_checkbox)

    # ==================== Associated Items Methods ====================

    def select_tool(self, tool_name: str) -> None:
        """Select a tool to associate with the server.

        Args:
            tool_name: Name of the tool to select
        """
        tool_checkbox = self.associated_tools_container.locator(f'label:has-text("{tool_name}") input[type="checkbox"]')
        if not tool_checkbox.is_checked():
            self.click_locator(tool_checkbox)

    def select_all_tools(self) -> None:
        """Select all available tools."""
        self.click_locator(self.select_all_tools_btn)

    def clear_all_tools(self) -> None:
        """Clear all selected tools."""
        self.click_locator(self.clear_all_tools_btn)

    def wait_for_server_visible(self, server_name: str, timeout: int = 30000) -> None:
        """Wait for a server to be visible in the table.

        Args:
            server_name: The name of the server
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector(f"text={server_name}", timeout=timeout)
        expect(self.page.locator(f"text={server_name}")).to_be_visible()

    def wait_for_server_hidden(self, server_name: str) -> None:
        """Wait for a server to be hidden from the table.

        Args:
            server_name: The name of the server
        """
        expect(self.page.locator(f"text={server_name}")).to_be_hidden()
