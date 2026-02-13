# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/components/sidebar_component.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Sidebar component for admin panel navigation.
"""

# Third-Party
from playwright.sync_api import Locator, Page


class SidebarComponent:
    """Reusable sidebar component for admin panel tab navigation."""

    def __init__(self, page: Page):
        self.page = page

    # ==================== Tab Locators ====================

    @property
    def servers_tab(self) -> Locator:
        """Virtual Servers Catalog tab button."""
        return self.page.locator('[data-testid="servers-tab"]')

    @property
    def tools_tab(self) -> Locator:
        """Global Tools tab button."""
        return self.page.locator('[data-testid="tools-tab"]')

    @property
    def gateways_tab(self) -> Locator:
        """Gateways tab button."""
        return self.page.locator('[data-testid="gateways-tab"]')

    @property
    def resources_tab(self) -> Locator:
        """Resources tab button."""
        return self.page.locator("#tab-resources")

    @property
    def prompts_tab(self) -> Locator:
        """Prompts tab button."""
        return self.page.locator("#tab-prompts")

    @property
    def teams_tab(self) -> Locator:
        """Teams tab button."""
        return self.page.locator('[data-testid="teams-tab"]')

    @property
    def users_tab(self) -> Locator:
        """Users tab button."""
        return self.page.locator("#tab-users")

    @property
    def tokens_tab(self) -> Locator:
        """API Tokens tab button."""
        return self.page.locator("#tab-tokens")

    @property
    def metrics_tab(self) -> Locator:
        """Metrics tab button."""
        return self.page.locator("#tab-metrics")

    @property
    def logs_tab(self) -> Locator:
        """Logs tab button."""
        return self.page.locator("#tab-logs")

    @property
    def version_tab(self) -> Locator:
        """Version Info tab button."""
        return self.page.locator("#tab-version-info")

    @property
    def registry_tab(self) -> Locator:
        """MCP Registry tab button."""
        return self.page.locator("#tab-mcp-registry")

    # ==================== Navigation Methods ====================

    def click_servers_tab(self) -> None:
        """Click on servers/catalog tab and wait for panel."""
        self.servers_tab.click()
        self.page.wait_for_selector("#catalog-panel:not(.hidden)")

    def click_tools_tab(self) -> None:
        """Click on tools tab and wait for panel."""
        self.tools_tab.click()
        self.page.wait_for_selector("#tools-panel:not(.hidden)")

    def click_gateways_tab(self) -> None:
        """Click on gateways tab and wait for panel."""
        self.gateways_tab.click()
        self.page.wait_for_selector("#gateways-panel:not(.hidden)")

    def click_resources_tab(self) -> None:
        """Click on resources tab and wait for panel."""
        self.resources_tab.click()
        self.page.wait_for_selector("#resources-panel:not(.hidden)")

    def click_prompts_tab(self) -> None:
        """Click on prompts tab and wait for panel."""
        self.prompts_tab.click()
        self.page.wait_for_selector("#prompts-panel:not(.hidden)")

    def click_teams_tab(self) -> None:
        """Click on teams tab and wait for panel."""
        self.teams_tab.click()
        self.page.wait_for_selector("#teams-panel:not(.hidden)")

    def click_users_tab(self) -> None:
        """Click on users tab and wait for panel."""
        self.users_tab.click()
        self.page.wait_for_selector("#users-panel:not(.hidden)")

    def click_tokens_tab(self) -> None:
        """Click on tokens tab and wait for panel."""
        self.tokens_tab.click()
        self.page.wait_for_selector("#tokens-panel:not(.hidden)")
        # Wait for the form to be ready
        self.page.wait_for_selector("#create-token-form", state="visible")
        # Wait a bit for any JavaScript initialization
        self.page.wait_for_timeout(500)

    def click_metrics_tab(self) -> None:
        """Click on metrics tab and wait for panel."""
        self.metrics_tab.click()
        self.page.wait_for_selector("#metrics-panel:not(.hidden)")

    def click_logs_tab(self) -> None:
        """Click on logs tab and wait for panel."""
        self.logs_tab.click()
        self.page.wait_for_selector("#logs-panel:not(.hidden)")

    def click_version_tab(self) -> None:
        """Click on version info tab and wait for panel."""
        self.version_tab.click()
        self.page.wait_for_selector("#version-info-panel:not(.hidden)")

    def click_registry_tab(self) -> None:
        """Click on MCP Registry tab and wait for panel."""
        self.registry_tab.click()
        self.page.wait_for_selector("#mcp-registry-panel:not(.hidden)")

    def click_tab_by_id(self, tab_id: str, panel_id: str = None) -> None:
        """Click on any tab by its ID and wait for corresponding panel.

        Args:
            tab_id: Tab element ID (e.g., "tab-catalog", "tab-tools")
            panel_id: Optional panel ID to wait for. If not provided, derives from tab_id
        """
        tab_locator = self.page.locator(f"#{tab_id}")
        tab_locator.click()
        # Derive panel ID if not provided
        if panel_id is None:
            panel_id = tab_id.replace("tab-", "") + "-panel"
        self.page.wait_for_selector(f"#{panel_id}:not(.hidden)")
