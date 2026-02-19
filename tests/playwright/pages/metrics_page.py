# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/metrics_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Metrics page object for Metrics and Analytics features.
"""

# Third-Party
from playwright.sync_api import expect, Locator

# Local
from .base_page import BasePage


class MetricsPage(BasePage):
    """Page object for Metrics and Analytics features."""

    # ==================== Panel Elements ====================

    @property
    def metrics_panel(self) -> Locator:
        """Metrics panel container."""
        return self.page.locator("#metrics-panel")

    # ==================== Metrics Elements ====================

    @property
    def refresh_metrics_btn(self) -> Locator:
        """Refresh metrics button."""
        return self.page.locator('button:has-text("Refresh Metrics")')

    @property
    def top_performers_panel(self) -> Locator:
        """Top performers panel container."""
        return self.page.locator("#top-performers-panel-tools")

    @property
    def top_tools_details(self) -> Locator:
        """Top tools expandable details section."""
        return self.page.locator("#top-tools-details")

    @property
    def top_resources_details(self) -> Locator:
        """Top resources expandable details section."""
        return self.page.locator("#top-resources-details")

    @property
    def top_servers_details(self) -> Locator:
        """Top servers expandable details section."""
        return self.page.locator("#top-servers-details")

    @property
    def top_prompts_details(self) -> Locator:
        """Top prompts expandable details section."""
        return self.page.locator("#top-prompts-details")

    def get_metric_content(self, section_name: str) -> Locator:
        """Get the content area for a specific metrics section.

        Args:
            section_name: Name of the section. Valid values:
                         "top-tools", "top-resources", "top-servers", "top-prompts"

        Returns:
            Locator for the content area
        """
        return self.page.locator(f"#{section_name}-content")

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_metrics_tab(self) -> None:
        """Navigate to Metrics tab and wait for panel to be visible."""
        self.sidebar.click_metrics_tab()

    # ==================== High-Level Metrics Operations ====================

    def refresh_metrics(self) -> None:
        """Click the refresh metrics button to reload metrics data."""
        if self.refresh_metrics_btn.count() > 0:
            self.click_locator(self.refresh_metrics_btn)
            # Wait for metrics to potentially update
            self.page.wait_for_timeout(1000)

    def expand_metric_section(self, section_name: str) -> None:
        """Expand a specific metrics section by clicking its summary.

        Args:
            section_name: Name of the section to expand. Valid values:
                         "top-tools", "top-resources", "top-servers", "top-prompts"
        """
        section_map = {
            "top-tools": self.top_tools_details,
            "top-resources": self.top_resources_details,
            "top-servers": self.top_servers_details,
            "top-prompts": self.top_prompts_details,
        }

        if section_name not in section_map:
            raise ValueError(f"Invalid section name: {section_name}. Must be one of {list(section_map.keys())}")

        details = section_map[section_name]
        if details.is_visible():
            # Click the summary to expand
            details.locator("summary").click()
            # Wait for content to be visible
            content = self.get_metric_content(section_name)
            expect(content).to_be_visible(timeout=5000)

    def is_section_expanded(self, section_name: str) -> bool:
        """Check if a metrics section is currently expanded.

        Args:
            section_name: Name of the section to check

        Returns:
            True if section is expanded, False otherwise
        """
        content = self.get_metric_content(section_name)
        return content.is_visible()

    def wait_for_metrics_loaded(self, timeout: int = 30000) -> None:
        """Wait for metrics panel to be loaded and ready.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("#metrics-panel:not(.hidden)", timeout=timeout)
        if self.top_performers_panel.count() > 0:
            expect(self.top_performers_panel).to_be_visible(timeout=timeout)
