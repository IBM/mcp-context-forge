# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/version_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Version/System Information page object for Version Info panel.
"""

# Third-Party
from playwright.sync_api import expect, Locator

# Local
from .base_page import BasePage


class VersionPage(BasePage):
    """Page object for Version Information and System Diagnostics."""

    # ==================== Panel Elements ====================

    @property
    def version_panel(self) -> Locator:
        """Version info panel container."""
        return self.page.locator("#version-info-panel")

    # ==================== Application Overview Card ====================

    @property
    def app_overview_card(self) -> Locator:
        """Application overview card with gradient background."""
        return self.version_panel.locator(".bg-gradient-to-r").first

    @property
    def app_name(self) -> Locator:
        """Application name display."""
        return self.app_overview_card.locator("div.text-2xl.font-bold").first

    @property
    def app_host(self) -> Locator:
        """Host identifier display."""
        return self.app_overview_card.locator("div.text-2xl.font-bold").nth(1)

    @property
    def mcp_protocol_version(self) -> Locator:
        """MCP Protocol version display."""
        return self.app_overview_card.locator("div.text-2xl.font-bold").nth(2)

    @property
    def uptime(self) -> Locator:
        """System uptime display."""
        return self.app_overview_card.locator("div.text-2xl.font-bold").nth(3)

    @property
    def app_version(self) -> Locator:
        """Application version display."""
        return self.app_overview_card.locator("div.text-blue-100.font-mono")

    # ==================== Platform & Runtime Card ====================

    @property
    def platform_runtime_card(self) -> Locator:
        """Platform & Runtime card container."""
        return self.version_panel.locator("div.bg-white.rounded-lg.shadow").first

    @property
    def python_version(self) -> Locator:
        """Python version display."""
        return self.platform_runtime_card.locator("div.text-lg.font-semibold").first

    @property
    def fastapi_version(self) -> Locator:
        """FastAPI version display."""
        return self.platform_runtime_card.locator("div.text-lg.font-semibold").nth(1)

    @property
    def operating_system(self) -> Locator:
        """Operating system display."""
        return self.platform_runtime_card.locator("div.text-lg.font-semibold").nth(2)

    # ==================== Services Status Card ====================

    @property
    def services_status_card(self) -> Locator:
        """Services status card container."""
        return self.version_panel.locator("div.bg-white.rounded-lg.shadow").nth(1)

    @property
    def database_status_card(self) -> Locator:
        """Database status card."""
        return self.services_status_card.locator("div.border.rounded-lg").first

    @property
    def database_status_badge(self) -> Locator:
        """Database status badge (Reachable/Unreachable)."""
        return self.database_status_card.locator("span.inline-flex")

    @property
    def cache_status_card(self) -> Locator:
        """Cache/Redis status card."""
        return self.services_status_card.locator("div.border.rounded-lg").nth(1)

    @property
    def cache_status_badge(self) -> Locator:
        """Cache status badge (Connected/Disconnected)."""
        return self.cache_status_card.locator("span.inline-flex")

    # ==================== System Resources Card ====================

    @property
    def system_resources_card(self) -> Locator:
        """System resources card container."""
        return self.version_panel.locator("div.bg-white.rounded-lg.shadow").nth(2)

    @property
    def cpu_info(self) -> Locator:
        """CPU information display."""
        return self.system_resources_card.locator("div.flex.justify-between").first

    @property
    def memory_info(self) -> Locator:
        """Memory information display."""
        return self.system_resources_card.locator("div.flex.justify-between").nth(1)

    @property
    def disk_info(self) -> Locator:
        """Disk information display."""
        return self.system_resources_card.locator("div.flex.justify-between").nth(2)

    @property
    def boot_time(self) -> Locator:
        """Boot time display."""
        return self.system_resources_card.locator("div.flex.justify-between").nth(3)

    # ==================== Support Bundle Card ====================

    @property
    def support_bundle_card(self) -> Locator:
        """Support bundle download card container."""
        return self.version_panel.locator("div.bg-white.rounded-lg.shadow").nth(3)

    @property
    def download_support_bundle_btn(self) -> Locator:
        """Download support bundle button."""
        return self.support_bundle_card.locator('a[href*="/ui/support-bundle/generate"]')

    @property
    def security_notice(self) -> Locator:
        """Security notice section."""
        return self.support_bundle_card.locator("div.bg-yellow-50")

    @property
    def cli_command_code(self) -> Locator:
        """CLI command code block."""
        return self.support_bundle_card.locator("code")

    # ==================== Bundle Contents Checkmarks ====================

    def get_bundle_content_item(self, item_text: str) -> Locator:
        """Get a specific bundle content item by its text.

        Args:
            item_text: Text of the bundle content item (e.g., "Version Information")

        Returns:
            Locator for the bundle content item
        """
        return self.support_bundle_card.locator(f"span:has-text('{item_text}')")

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_version_tab(self) -> None:
        """Navigate to Version Info tab and wait for panel to be visible."""
        self.sidebar.click_version_tab()

    # ==================== High-Level Verification Methods ====================

    def is_database_healthy(self) -> bool:
        """Check if database status shows as healthy/reachable.

        Returns:
            True if database is reachable, False otherwise
        """
        badge_text = self.database_status_badge.text_content()
        return "Reachable" in badge_text or "✅" in badge_text

    def is_cache_healthy(self) -> bool:
        """Check if cache/Redis status shows as healthy/connected.

        Returns:
            True if cache is connected, False otherwise
        """
        badge_text = self.cache_status_badge.text_content()
        return "Connected" in badge_text or "✅" in badge_text

    def get_app_name(self) -> str:
        """Get the application name.

        Returns:
            Application name as string
        """
        return self.app_name.text_content().strip()

    def get_app_version(self) -> str:
        """Get the application version.

        Returns:
            Application version as string
        """
        return self.app_version.text_content().strip()

    def get_python_version(self) -> str:
        """Get the Python version.

        Returns:
            Python version as string
        """
        return self.python_version.text_content().strip()

    def get_fastapi_version(self) -> str:
        """Get the FastAPI version.

        Returns:
            FastAPI version as string
        """
        return self.fastapi_version.text_content().strip()

    def get_operating_system(self) -> str:
        """Get the operating system information.

        Returns:
            Operating system as string
        """
        return self.operating_system.text_content().strip()

    def get_cpu_info(self) -> str:
        """Get CPU information.

        Returns:
            CPU info as string
        """
        return self.cpu_info.locator("span.font-medium").text_content().strip()

    def get_memory_info(self) -> str:
        """Get memory information.

        Returns:
            Memory info as string
        """
        return self.memory_info.locator("span.font-medium").text_content().strip()

    def get_disk_info(self) -> str:
        """Get disk information.

        Returns:
            Disk info as string
        """
        return self.disk_info.locator("span.font-medium").text_content().strip()

    def get_boot_time(self) -> str:
        """Get system boot time.

        Returns:
            Boot time as string
        """
        return self.boot_time.locator("span.font-medium").text_content().strip()

    def verify_bundle_contents_visible(self) -> bool:
        """Verify that all expected bundle content items are visible.

        Returns:
            True if all items are visible, False otherwise
        """
        expected_items = ["Version Information", "System Diagnostics", "Configuration (sanitized)", "Application Logs", "Platform Details", "Service Status"]

        for item in expected_items:
            if not self.get_bundle_content_item(item).is_visible():
                return False
        return True

    def wait_for_version_panel_loaded(self, timeout: int = 30000) -> None:
        """Wait for version panel to be loaded and ready.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        expect(self.version_panel).to_be_visible(timeout=timeout)
        expect(self.app_overview_card).to_be_visible(timeout=timeout)
