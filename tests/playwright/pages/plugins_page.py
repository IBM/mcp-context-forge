# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/plugins_page.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Plugins page object for admin panel Playwright tests.
"""

# Standard
from typing import List

# Third-Party
from playwright.sync_api import Locator, Page

# Local
from .base_page import BasePage

UNIFIED_MODE_LABELS = {
    "Sequential (Enforce)",
    "Sequential (Ignore Error)",
    "Transform (Permissive)",
    "Concurrent",
    "Audit",
    "Fire And Forget",
    "Disabled",
}

RAW_LEGACY_MODES = {"enforce", "permissive", "enforce_ignore_error"}


class PluginsPage(BasePage):
    """Page object for the plugins tab in the admin panel."""

    def __init__(self, page: Page):
        super().__init__(page)

    # ==================== Locators ====================

    @property
    def plugins_panel(self) -> Locator:
        return self.page.locator("#plugins-panel")

    @property
    def plugin_grid(self) -> Locator:
        return self.page.locator("#plugin-grid")

    @property
    def plugin_cards(self) -> Locator:
        return self.page.locator(".plugin-card")

    @property
    def mode_filter(self) -> Locator:
        return self.page.locator("#plugin-mode-filter")

    @property
    def search_input(self) -> Locator:
        return self.page.locator("#plugin-search")

    @property
    def status_filter(self) -> Locator:
        return self.page.locator("#plugin-status-filter")

    @property
    def details_modal(self) -> Locator:
        return self.page.locator("#plugin-details-modal")

    @property
    def modal_plugin_name(self) -> Locator:
        return self.page.locator("#modal-plugin-name")

    @property
    def modal_content(self) -> Locator:
        return self.page.locator("#modal-plugin-content")

    @property
    def modal_close_btn(self) -> Locator:
        return self.page.locator("[data-close-plugin-modal]")

    # ==================== Navigation ====================

    def navigate_to_plugins(self) -> None:
        self.sidebar.click_tab_by_id("tab-plugins", "plugins-panel")
        self.page.wait_for_selector("#plugin-grid", timeout=30000)

    # ==================== Helpers ====================

    def get_visible_cards(self) -> List[Locator]:
        count = self.plugin_cards.count()
        return [self.plugin_cards.nth(i) for i in range(count) if self.plugin_cards.nth(i).is_visible()]

    def get_mode_filter_options(self) -> List[str]:
        options = self.mode_filter.locator("option")
        return [options.nth(i).text_content().strip() for i in range(options.count())]

    def open_plugin_detail(self, plugin_name: str) -> None:
        btn = self.page.locator(f'[data-show-plugin="{plugin_name}"]')
        btn.click()
        self.page.wait_for_selector("#plugin-details-modal:not(.hidden)", timeout=10000)

    def close_detail_modal(self) -> None:
        self.modal_close_btn.click()
        self.page.wait_for_selector("#plugin-details-modal.hidden", timeout=5000)
