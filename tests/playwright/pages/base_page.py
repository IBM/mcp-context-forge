# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/base_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Base page object for common functionality.
"""

# Third-Party
from playwright.sync_api import Page, Locator, expect

# Local
from .components import SidebarComponent


class BasePage:
    """Base page with Locator properties and improved waiting strategies."""

    def __init__(self, page: Page):
        self.page = page
        self.timeout = 30000  # 30 seconds default timeout
        self.sidebar = SidebarComponent(page)  # Sidebar component available to all pages

    # ==================== Navigation ====================

    def navigate_to(self, url: str) -> None:
        """Navigate to specified URL."""
        # networkidle can hang on pages with long-polling/SSE
        # domcontentloaded is more reliable for admin UI
        self.page.goto(url, wait_until="domcontentloaded")

    # ==================== Locator Utilities ====================

    def get_locator(self, selector: str) -> Locator:
        """Return a Locator for the given selector.

        Use this when you need to create dynamic locators.
        For static elements, prefer @property methods.
        """
        return self.page.locator(selector)

    # ==================== Waiting Strategies ====================

    def wait_for_visible(self, locator: Locator, timeout: int | None = None) -> None:
        """Wait for locator to be visible."""
        expect(locator).to_be_visible(timeout=timeout or self.timeout)

    def wait_for_hidden(self, locator: Locator, timeout: int | None = None) -> None:
        """Wait for locator to be hidden."""
        expect(locator).to_be_hidden(timeout=timeout or self.timeout)

    def wait_for_element(self, selector: str) -> None:
        """Wait for element to be visible (legacy method for backward compatibility)."""
        self.page.wait_for_selector(selector, state="visible", timeout=self.timeout)

    def wait_for_attached(self, locator: Locator, timeout: int | None = None) -> None:
        """Wait for locator to be attached to DOM."""
        expect(locator).to_be_attached(timeout=timeout or self.timeout)

    # ==================== Interaction Methods ====================

    def click_element(self, selector: str) -> None:
        """Click an element (legacy method for backward compatibility)."""
        self.page.click(selector)

    def click_locator(self, locator: Locator) -> None:
        """Click a locator."""
        locator.click()

    def fill_input(self, selector: str, value: str) -> None:
        """Fill input field (legacy method for backward compatibility)."""
        self.page.fill(selector, value)

    def fill_locator(self, locator: Locator, value: str) -> None:
        """Fill a locator input field."""
        locator.fill(value)

    def get_text(self, selector: str) -> str:
        """Get text content of element."""
        return self.page.text_content(selector)

    def get_locator_text(self, locator: Locator) -> str:
        """Get text content of locator."""
        return locator.text_content()

    def element_exists(self, selector: str) -> bool:
        """Check if element exists (legacy method)."""
        return self.page.is_visible(selector)

    def locator_is_visible(self, locator: Locator) -> bool:
        """Check if locator is visible."""
        return locator.is_visible()

    # ==================== API Utilities ====================

    def wait_for_response(self, url_pattern: str):
        """Wait for API response."""
        return self.page.wait_for_response(url_pattern)

    # ==================== Screenshot ====================

    def take_screenshot(self, name: str) -> None:
        """Take a screenshot."""
        self.page.screenshot(path=f"tests/playwright/screenshots/{name}.png")
