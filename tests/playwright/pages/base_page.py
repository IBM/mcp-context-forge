# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/base_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Base page object for common functionality.
"""

# Third-Party
from playwright.sync_api import Page


class BasePage:
    """Base page with common methods."""

    def __init__(self, page: Page):
        self.page = page
        self.timeout = 30000  # 30 seconds default timeout

    def navigate_to(self, url: str) -> None:
        """Navigate to specified URL."""
        # networkidle can hang on pages with long-polling/SSE; domcontentloaded is more reliable for admin UI
        self.page.goto(url, wait_until="domcontentloaded")

    def wait_for_element(self, selector: str) -> None:
        """Wait for element to be visible."""
        self.page.wait_for_selector(selector, state="visible", timeout=self.timeout)

    def click_element(self, selector: str) -> None:
        """Click an element."""
        self.page.click(selector)

    def fill_input(self, selector: str, value: str) -> None:
        """Fill input field."""
        self.page.fill(selector, value)

    def get_text(self, selector: str) -> str:
        """Get text content of element."""
        return self.page.text_content(selector)

    def element_exists(self, selector: str) -> bool:
        """Check if element exists."""
        return self.page.is_visible(selector)

    def wait_for_response(self, url_pattern: str):
        """Wait for API response."""
        return self.page.wait_for_response(url_pattern)

    def take_screenshot(self, name: str) -> None:
        """Take a screenshot."""
        self.page.screenshot(path=f"tests/playwright/screenshots/{name}.png")
