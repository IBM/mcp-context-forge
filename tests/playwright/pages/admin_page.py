# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/admin_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Admin panel page object with property-based Locators.
"""

# Third-Party
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Local
from .base_page import BasePage


class AdminPage(BasePage):
    """Admin panel page object with comprehensive element coverage."""

    # ==================== Legacy String Selectors (Deprecated) ====================
    # Keep these for backward compatibility during migration
    # TODO: Remove once all tests are migrated to use properties

    SERVERS_TAB = '[data-testid="servers-tab"]'
    TOOLS_TAB = '[data-testid="tools-tab"]'
    GATEWAYS_TAB = '[data-testid="gateways-tab"]'
    ADD_SERVER_BTN = '[data-testid="add-server-btn"]'
    SERVER_LIST = '[data-testid="server-list"]'
    SERVER_ITEM = '[data-testid="server-item"]'
    SEARCH_INPUT = '[data-testid="search-input"]'
    SERVER_NAME_INPUT = 'input[name="name"]'
    SERVER_ICON_INPUT = 'input[name="icon"]'

    def __init__(self, page: Page, base_url: str):
        super().__init__(page)
        self.url = f"{base_url}/admin/"

    # ==================== Navigation ====================

    def navigate(self) -> None:
        """Navigate to admin panel."""
        self.navigate_to(self.url)
        # Wait for admin panel to load
        self.wait_for_visible(self.servers_tab)

    # ==================== Tab Elements (Delegated to Sidebar) ====================
    # Note: Tab locators and navigation are now available via self.sidebar
    # For backward compatibility, we provide property aliases

    @property
    def servers_tab(self) -> Locator:
        """Virtual Servers Catalog tab button (delegated to sidebar)."""
        return self.sidebar.servers_tab

    @property
    def tools_tab(self) -> Locator:
        """Global Tools tab button (delegated to sidebar)."""
        return self.sidebar.tools_tab

    @property
    def gateways_tab(self) -> Locator:
        """Gateways tab button (delegated to sidebar)."""
        return self.sidebar.gateways_tab

    @property
    def resources_tab(self) -> Locator:
        """Resources tab button (delegated to sidebar)."""
        return self.sidebar.resources_tab

    @property
    def prompts_tab(self) -> Locator:
        """Prompts tab button (delegated to sidebar)."""
        return self.sidebar.prompts_tab

    @property
    def teams_tab(self) -> Locator:
        """Teams tab button (delegated to sidebar)."""
        return self.sidebar.teams_tab

    @property
    def users_tab(self) -> Locator:
        """Users tab button (delegated to sidebar)."""
        return self.sidebar.users_tab

    @property
    def tokens_tab(self) -> Locator:
        """API Tokens tab button (delegated to sidebar)."""
        return self.sidebar.tokens_tab

    @property
    def metrics_tab(self) -> Locator:
        """Metrics tab button (delegated to sidebar)."""
        return self.sidebar.metrics_tab

    @property
    def logs_tab(self) -> Locator:
        """Logs tab button (delegated to sidebar)."""
        return self.sidebar.logs_tab

    @property
    def runtime_tab(self) -> Locator:
        """Runtime tab button (delegated to sidebar)."""
        return self.sidebar.runtime_tab

    # ==================== Panel Elements ====================

    @property
    def catalog_panel(self) -> Locator:
        """Catalog/Servers panel container."""
        return self.page.locator("#catalog-panel")

    @property
    def tools_panel(self) -> Locator:
        """Tools panel container."""
        return self.page.locator("#tools-panel")

    @property
    def gateways_panel(self) -> Locator:
        """Gateways panel container."""
        return self.page.locator("#gateways-panel")

    @property
    def resources_panel(self) -> Locator:
        """Resources panel container."""
        return self.page.locator("#resources-panel")

    @property
    def prompts_panel(self) -> Locator:
        """Prompts panel container."""
        return self.page.locator("#prompts-panel")

    @property
    def teams_panel(self) -> Locator:
        """Teams panel container."""
        return self.page.locator("#teams-panel")

    @property
    def users_panel(self) -> Locator:
        """Users panel container."""
        return self.page.locator("#users-panel")

    @property
    def tokens_panel(self) -> Locator:
        """API Tokens panel container."""
        return self.page.locator("#tokens-panel")

    @property
    def metrics_panel(self) -> Locator:
        """Metrics panel container."""
        return self.page.locator("#metrics-panel")

    # ==================== Server/Catalog Elements ====================

    @property
    def server_list(self) -> Locator:
        """Server list tbody element."""
        return self.page.locator('[data-testid="server-list"]').first

    @property
    def server_items(self) -> Locator:
        """All server row items."""
        return self.page.locator('[data-testid="server-item"]')

    @property
    def add_server_form(self) -> Locator:
        """Add server form."""
        return self.page.locator("#add-server-form")

    @property
    def server_name_input(self) -> Locator:
        """Server name input field."""
        return self.add_server_form.locator('input[name="name"]')

    @property
    def server_icon_input(self) -> Locator:
        """Server icon URL input field."""
        return self.add_server_form.locator('input[name="icon"]')

    @property
    def add_server_btn(self) -> Locator:
        """Add server submit button."""
        return self.add_server_form.get_by_role("button", name="Add Server")

    @property
    def search_input(self) -> Locator:
        """Server search input."""
        return self.page.locator('[data-testid="search-input"]')

    # ==================== Form Elements ====================
    # Note: Resource and Prompt forms are now available via ResourcesPage and PromptsPage
    # Team and Token forms are available via TeamPage and TokensPage

    @property
    def create_user_form(self) -> Locator:
        """Create user form."""
        return self.page.locator("#create-user-form")

    # ==================== High-Level Tab Navigation (Delegated to Sidebar) ====================
    # Note: Navigation methods are now available via self.sidebar
    # For backward compatibility, we provide method aliases

    def click_servers_tab(self) -> None:
        """Click on servers/catalog tab and wait for panel (delegated to sidebar)."""
        self.sidebar.click_servers_tab()

    def click_tools_tab(self) -> None:
        """Click on tools tab and wait for panel (delegated to sidebar)."""
        self.sidebar.click_tools_tab()

    def click_gateways_tab(self) -> None:
        """Click on gateways tab and wait for panel (delegated to sidebar)."""
        self.sidebar.click_gateways_tab()

    def click_resources_tab(self) -> None:
        """Click on resources tab and wait for panel (delegated to sidebar)."""
        self.sidebar.click_resources_tab()

    def click_prompts_tab(self) -> None:
        """Click on prompts tab and wait for panel (delegated to sidebar)."""
        self.sidebar.click_prompts_tab()

    def click_metrics_tab(self) -> None:
        """Click on metrics tab and wait for panel (delegated to sidebar)."""
        self.sidebar.click_metrics_tab()

    def click_runtime_tab(self) -> None:
        """Click on runtime tab and wait for panel (delegated to sidebar)."""
        self.sidebar.click_runtime_tab()

    def click_tab_by_id(self, tab_id: str, panel_id: str = None) -> None:
        """Click on any tab by its ID and wait for corresponding panel (delegated to sidebar).

        Args:
            tab_id: Tab element ID (e.g., "tab-catalog", "tab-tools")
            panel_id: Optional panel ID to wait for. If not provided, derives from tab_id
        """
        self.sidebar.click_tab_by_id(tab_id, panel_id)

    # ==================== High-Level Interactions ====================

    def add_server(self, name: str, icon_url: str) -> None:
        """Add a new server."""
        self.fill_locator(self.server_name_input, name)
        self.fill_locator(self.server_icon_input, icon_url)
        self.click_locator(self.add_server_btn)

    def search_servers(self, query: str) -> None:
        """Search for servers.

        Search is server-side via HTMX with a debounce. Avoid Playwright
        ``networkidle`` because admin pages can keep long-lived requests open.
        Wait for table/indicator state instead.
        """
        self.fill_locator(self.search_input, query)

        try:
            self.page.wait_for_selector("#servers-loading.htmx-request", timeout=5000)
        except PlaywrightTimeoutError:
            # Fallback: explicitly trigger the server-side reload for the catalog panel.
            self.page.evaluate(
                "(q) => { const el = document.getElementById('catalog-search-input'); if (el) { el.value = q; } if (window.loadSearchablePanel) { window.loadSearchablePanel('catalog'); } }",
                query,
            )
            try:
                self.page.wait_for_selector("#servers-loading.htmx-request", timeout=5000)
            except PlaywrightTimeoutError:
                pass

        self.page.wait_for_function(
            "() => !document.querySelector('#servers-loading.htmx-request')",
            timeout=15000,
        )
        self.page.wait_for_selector("#servers-table-body", state="attached", timeout=15000)

    def get_server_count(self) -> int:
        """Get number of servers displayed."""
        # Make sure the server list is loaded
        self.page.wait_for_selector('[data-testid="server-list"]', state="attached")
        return self.server_items.locator(":visible").count()

    def server_exists(self, name: str) -> bool:
        """Check if server with name exists."""
        # Wait for the server list to be visible
        self.page.wait_for_selector('[data-testid="server-list"]', state="attached")

        # Check each server item for the name
        server_items = self.server_items.locator(":visible")
        for i in range(server_items.count()):
            if name in server_items.nth(i).text_content():
                return True
        return False
