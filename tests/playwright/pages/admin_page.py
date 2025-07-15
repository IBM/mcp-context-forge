# -*- coding: utf-8 -*-
"""Admin panel page object."""

# Third-Party
from playwright.sync_api import Page

# Local
from .base_page import BasePage


class AdminPage(BasePage):
    """Admin panel page object."""

    # Selectors
    SERVERS_TAB = '[data-tab="servers"]'
    TOOLS_TAB = '[data-tab="tools"]'
    GATEWAYS_TAB = '[data-tab="gateways"]'
    ADD_SERVER_BTN = 'button:has-text("Add Server")'
    SERVER_LIST = ".server-list"
    SERVER_ITEM = ".server-item"
    SEARCH_INPUT = 'input[placeholder*="Search"]'

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

    def add_server(self, name: str, url: str) -> None:
        """Add a new server."""
        self.click_element(self.ADD_SERVER_BTN)
        # Wait for modal
        self.wait_for_element('input[name="name"]')
        self.fill_input('input[name="name"]', name)
        self.fill_input('input[name="url"]', url)
        self.click_element('button:has-text("Save")')

    def search_servers(self, query: str) -> None:
        """Search for servers."""
        self.fill_input(self.SEARCH_INPUT, query)

    def get_server_count(self) -> int:
        """Get number of servers displayed."""
        return len(self.page.query_selector_all(self.SERVER_ITEM))

    def server_exists(self, name: str) -> bool:
        """Check if server with name exists."""
        return self.element_exists(f'{self.SERVER_ITEM}:has-text("{name}")')
