# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_version_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test cases for Version Info page.
"""

# Standard
import re

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from .pages.version_page import VersionPage


@pytest.mark.ui
@pytest.mark.smoke
class TestVersionPage:
    """Version Info page test cases."""

    def test_version_panel_loads(self, version_page: VersionPage):
        """Test that version info panel loads successfully."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify panel is visible
        expect(version_page.version_panel).to_be_visible()
        expect(version_page.app_overview_card).to_be_visible()

    def test_application_overview_card_displays(self, version_page: VersionPage):
        """Test that application overview card displays all required information."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify all overview elements are visible
        expect(version_page.app_name).to_be_visible()
        expect(version_page.app_host).to_be_visible()
        expect(version_page.mcp_protocol_version).to_be_visible()
        expect(version_page.uptime).to_be_visible()
        expect(version_page.app_version).to_be_visible()

        # Verify app name is not empty
        app_name = version_page.get_app_name()
        assert len(app_name) > 0, "Application name should not be empty"

        # Verify version format (should contain numbers and possibly dots/dashes)
        app_version = version_page.get_app_version()
        assert len(app_version) > 0, "Application version should not be empty"
        assert re.search(r"\d+", app_version), "Version should contain numbers"

    def test_platform_runtime_card_displays(self, version_page: VersionPage):
        """Test that platform & runtime card displays all required information."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify platform runtime card is visible
        expect(version_page.platform_runtime_card).to_be_visible()

        # Verify all platform elements are visible
        expect(version_page.python_version).to_be_visible()
        expect(version_page.fastapi_version).to_be_visible()
        expect(version_page.operating_system).to_be_visible()

        # Verify Python version format
        python_version = version_page.get_python_version()
        assert re.search(r"\d+\.\d+", python_version), "Python version should be in format X.Y.Z"

        # Verify FastAPI version format
        fastapi_version = version_page.get_fastapi_version()
        assert re.search(r"\d+\.\d+", fastapi_version), "FastAPI version should be in format X.Y.Z"

        # Verify OS info is not empty
        os_info = version_page.get_operating_system()
        assert len(os_info) > 0, "Operating system info should not be empty"

    def test_services_status_card_displays(self, version_page: VersionPage):
        """Test that services status card displays database and cache status."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify services status card is visible
        expect(version_page.services_status_card).to_be_visible()

        # Verify database status card
        expect(version_page.database_status_card).to_be_visible()
        expect(version_page.database_status_badge).to_be_visible()

        # Verify cache status card
        expect(version_page.cache_status_card).to_be_visible()
        expect(version_page.cache_status_badge).to_be_visible()

    def test_database_status_indicator(self, version_page: VersionPage):
        """Test that database status indicator shows correct state."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Check database health status
        is_healthy = version_page.is_database_healthy()

        # Verify badge text contains status information
        badge_text = version_page.database_status_badge.text_content()
        assert badge_text is not None and len(badge_text) > 0, "Database status badge should have text"

        # If healthy, should contain positive indicators
        if is_healthy:
            assert "Reachable" in badge_text or "✅" in badge_text, "Healthy database should show 'Reachable' or checkmark"

    def test_cache_status_indicator(self, version_page: VersionPage):
        """Test that cache/Redis status indicator shows correct state."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Check cache health status
        is_healthy = version_page.is_cache_healthy()

        # Verify badge text contains status information
        badge_text = version_page.cache_status_badge.text_content()
        assert badge_text is not None and len(badge_text) > 0, "Cache status badge should have text"

        # If healthy, should contain positive indicators
        if is_healthy:
            assert "Connected" in badge_text or "✅" in badge_text, "Healthy cache should show 'Connected' or checkmark"

    def test_system_resources_card_displays(self, version_page: VersionPage):
        """Test that system resources card displays all resource information."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify system resources card is visible
        expect(version_page.system_resources_card).to_be_visible()

        # Verify all resource elements are visible
        expect(version_page.cpu_info).to_be_visible()
        expect(version_page.memory_info).to_be_visible()
        expect(version_page.disk_info).to_be_visible()
        expect(version_page.boot_time).to_be_visible()

        # Verify CPU info contains numbers
        cpu_info = version_page.get_cpu_info()
        assert re.search(r"\d+", cpu_info), "CPU info should contain numbers"

        # Verify memory info contains numbers and units
        memory_info = version_page.get_memory_info()
        assert re.search(r"\d+", memory_info), "Memory info should contain numbers"
        assert "MB" in memory_info or "GB" in memory_info, "Memory info should contain units"

        # Verify disk info contains numbers and units
        disk_info = version_page.get_disk_info()
        assert re.search(r"\d+", disk_info), "Disk info should contain numbers"
        assert "GB" in disk_info or "TB" in disk_info, "Disk info should contain units"

        # Verify boot time is in valid format
        boot_time = version_page.get_boot_time()
        assert len(boot_time) > 0, "Boot time should not be empty"

    def test_support_bundle_card_displays(self, version_page: VersionPage):
        """Test that support bundle card displays with all elements."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify support bundle card is visible
        expect(version_page.support_bundle_card).to_be_visible()

        # Verify download button is visible and has correct href
        expect(version_page.download_support_bundle_btn).to_be_visible()
        href = version_page.download_support_bundle_btn.get_attribute("href")
        assert "/admin/support-bundle/generate" in href, "Download button should link to support bundle endpoint"

        # Verify security notice is visible
        expect(version_page.security_notice).to_be_visible()

        # Verify CLI command is visible
        expect(version_page.cli_command_code).to_be_visible()
        cli_command = version_page.cli_command_code.text_content()
        assert "mcpgateway" in cli_command, "CLI command should contain 'mcpgateway'"
        assert "--support-bundle" in cli_command, "CLI command should contain '--support-bundle' flag"

    def test_bundle_contents_list_displays(self, version_page: VersionPage):
        """Test that bundle contents list shows all expected items."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify all bundle content items are visible
        assert version_page.verify_bundle_contents_visible(), "All bundle content items should be visible"

        # Verify specific items
        expected_items = ["Version Information", "System Diagnostics", "Configuration (sanitized)", "Application Logs", "Platform Details", "Service Status"]

        for item in expected_items:
            item_locator = version_page.get_bundle_content_item(item)
            expect(item_locator).to_be_visible(timeout=5000)

    def test_download_support_bundle_link(self, version_page: VersionPage):
        """Test that download support bundle link is properly configured."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Get the download button
        download_btn = version_page.download_support_bundle_btn

        # Verify it's a link (anchor tag)
        tag_name = download_btn.evaluate("el => el.tagName")
        assert tag_name.lower() == "a", "Download button should be an anchor tag"

        # Verify it has download attribute
        has_download = download_btn.evaluate("el => el.hasAttribute('download')")
        assert has_download, "Download button should have download attribute"

        # Verify href contains log_lines parameter
        href = download_btn.get_attribute("href")
        assert "log_lines=" in href, "Download link should include log_lines parameter"

    def test_version_panel_responsive_design(self, version_page: VersionPage):
        """Test that version panel adapts to different viewport sizes."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Test mobile viewport
        version_page.page.set_viewport_size({"width": 375, "height": 667})
        expect(version_page.version_panel).to_be_visible()
        expect(version_page.app_overview_card).to_be_visible()

        # Test tablet viewport
        version_page.page.set_viewport_size({"width": 768, "height": 1024})
        expect(version_page.version_panel).to_be_visible()
        expect(version_page.platform_runtime_card).to_be_visible()

        # Test desktop viewport
        version_page.page.set_viewport_size({"width": 1920, "height": 1080})
        expect(version_page.version_panel).to_be_visible()
        expect(version_page.services_status_card).to_be_visible()

    def test_all_cards_visible_on_load(self, version_page: VersionPage):
        """Test that all major cards are visible when version panel loads."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify all major cards are visible
        expect(version_page.app_overview_card).to_be_visible()
        expect(version_page.platform_runtime_card).to_be_visible()
        expect(version_page.services_status_card).to_be_visible()
        expect(version_page.system_resources_card).to_be_visible()
        expect(version_page.support_bundle_card).to_be_visible()


@pytest.mark.ui
@pytest.mark.integration
class TestVersionPageIntegration:
    """Integration tests for Version Info page."""

    def test_navigate_from_other_tabs(self, version_page: VersionPage):
        """Test navigation to version tab from other tabs."""
        # Start from servers tab
        version_page.sidebar.click_servers_tab()
        version_page.page.wait_for_timeout(500)

        # Navigate to version tab
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify we're on version tab
        expect(version_page.version_panel).to_be_visible()

        # Navigate to tools tab and back
        version_page.sidebar.click_tools_tab()
        version_page.page.wait_for_timeout(500)

        version_page.navigate_to_version_tab()
        expect(version_page.version_panel).to_be_visible()

    def test_version_data_consistency(self, version_page: VersionPage):
        """Test that version data remains consistent across page refreshes."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Get initial values
        initial_app_name = version_page.get_app_name()
        initial_version = version_page.get_app_version()
        initial_python = version_page.get_python_version()

        # Navigate away and back
        version_page.sidebar.click_servers_tab()
        version_page.page.wait_for_timeout(500)
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Verify values are consistent
        assert version_page.get_app_name() == initial_app_name, "App name should remain consistent"
        assert version_page.get_app_version() == initial_version, "App version should remain consistent"
        assert version_page.get_python_version() == initial_python, "Python version should remain consistent"

    def test_services_status_reflects_system_state(self, version_page: VersionPage):
        """Test that services status indicators reflect actual system state."""
        version_page.navigate_to_version_tab()
        version_page.wait_for_version_panel_loaded()

        # Get service statuses
        db_healthy = version_page.is_database_healthy()
        cache_healthy = version_page.is_cache_healthy()

        # Both services should typically be healthy in test environment
        # If not, the test environment may have issues
        assert db_healthy or cache_healthy, "At least one service should be healthy in test environment"

        # Verify status cards have appropriate styling based on health
        db_card_classes = version_page.database_status_card.get_attribute("class")
        if db_healthy:
            assert "green" in db_card_classes, "Healthy database card should have green styling"

        cache_card_classes = version_page.cache_status_card.get_attribute("class")
        if cache_healthy:
            assert "green" in cache_card_classes, "Healthy cache card should have green styling"
