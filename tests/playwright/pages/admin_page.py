# -*- coding: utf-8 -*-
"""Admin panel page object."""

# Third-Party
from playwright.sync_api import Page

# Local
from .base_page import BasePage


class AdminPage(BasePage):
    """Admin panel page object."""

    # Selectors - Updated to match actual HTML
    SERVERS_TAB = '[data-testid="servers-tab"]'  # This is the Virtual Servers Catalog tab
    TOOLS_TAB = '[data-testid="tools-tab"]'
    GATEWAYS_TAB = '[data-testid="gateways-tab"]'
    ADD_SERVER_BTN = '[data-testid="add-server-btn"]'
    SERVER_LIST = '[data-testid="server-list"]'  # This is the tbody element
    SERVER_ITEM = '[data-testid="server-item"]'  # These are the tr elements
    SEARCH_INPUT = '[data-testid="search-input"]'
    SERVER_NAME_INPUT = 'input[name="name"]'
    SERVER_ICON_INPUT = 'input[name="icon"]'

    def __init__(self, page: Page, base_url: str):
        super().__init__(page)
        self.url = f"{base_url}/admin"

    def navigate(self) -> None:
        """Navigate to admin panel."""
        self.navigate_to(self.url)
        # Wait for admin panel to load
        self.wait_for_element(self.SERVERS_TAB)

    def click_servers_tab(self) -> None:
        """Click on servers tab."""
        self.click_element(self.SERVERS_TAB)

    def click_tools_tab(self) -> None:
        """Click on tools tab."""
        self.click_element(self.TOOLS_TAB)

    def click_gateways_tab(self) -> None:
        """Click on gateways tab."""
        self.click_element(self.GATEWAYS_TAB)

    def add_server(self, name: str, icon_url: str) -> None:
        """Add a new server."""
        self.fill_input(self.SERVER_NAME_INPUT, name)
        self.fill_input(self.SERVER_ICON_INPUT, icon_url)
        self.click_element(self.ADD_SERVER_BTN)

    def search_servers(self, query: str) -> None:
        """Search for servers."""
        self.fill_input(self.SEARCH_INPUT, query)

    def get_server_count(self) -> int:
        """Get number of servers displayed."""
        # Make sure the server list is loaded
        self.page.wait_for_selector(self.SERVER_LIST, state="visible")
        return len(self.page.query_selector_all(self.SERVER_ITEM))

    def server_exists(self, name: str) -> bool:
        """Check if server with name exists."""
        # Wait for the server list to be visible
        self.page.wait_for_selector(self.SERVER_LIST, state="visible")

        # Check each server item for the name
        server_items = self.page.query_selector_all(self.SERVER_ITEM)
        for item in server_items:
            if name in item.text_content():
                return True
        return False
