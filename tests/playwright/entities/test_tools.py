# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/playwright/entities/test_tools.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

# Standard
import time

# Third-Party
from playwright.sync_api import Page


def _find_tool(page: Page, tool_name: str, retries: int = 5):
    """Find a tool by name via the admin JSON endpoint (bypasses cached HTML)."""
    for _ in range(retries):
        cache_bust = str(int(time.time() * 1000))
        response = page.request.get(f"/admin/tools?per_page=500&cache_bust={cache_bust}")
        if response.ok:
            payload = response.json()
            data = payload.get("data", [])
            for tool in data:
                if tool.get("name") == tool_name:
                    return tool
        time.sleep(0.5)
    return None


class TestToolsCRUD:
    """CRUD tests for Tools entity in MCP Gateway Admin UI.

    Examples:
        pytest tests/playwright/entities/test_tools.py
    """

    def test_create_new_tool(self, admin_page: Page, test_tool_data):
        """Test creating a new tool with debug screenshots and waits."""
        # Go to the Global Tools tab (if not already there)
        admin_page.click('[data-testid="tools-tab"]')

        # Wait for the tools panel to be visible
        admin_page.wait_for_selector("#tools-panel:not(.hidden)")

        # Add a small delay to ensure the UI has time to update
        admin_page.wait_for_timeout(500)

        # Fill the always-visible form
        admin_page.locator('#add-tool-form [name="name"]').fill(test_tool_data["name"])
        admin_page.wait_for_timeout(300)
        admin_page.locator('#add-tool-form [name="url"]').fill(test_tool_data["url"])
        admin_page.wait_for_timeout(300)
        admin_page.locator('#add-tool-form [name="description"]').fill(test_tool_data["description"])
        admin_page.wait_for_timeout(300)
        admin_page.locator('#add-tool-form [name="integrationType"]').select_option(test_tool_data["integrationType"])
        admin_page.wait_for_timeout(300)

        # Submit the form and assert success response
        with admin_page.expect_response(lambda response: "/admin/tools" in response.url and response.request.method == "POST") as response_info:
            admin_page.click('#add-tool-form button[type="submit"]')
        response = response_info.value

        # Verify tool exists via JSON list (avoids cached HTML)
        created_tool = _find_tool(admin_page, test_tool_data["name"])
        assert created_tool is not None, f"Newly created tool not found via admin API (status {response.status})"

        # Cleanup: delete the created tool for idempotency
        if created_tool:
            admin_page.request.post(
                f"/admin/tools/{created_tool['id']}/delete",
                data="is_inactive_checked=false",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

    def test_delete_tool(self, admin_page: Page, test_tool_data):
        """Test deleting a tool."""
        # Go to the Global Tools tab (if not already there)
        admin_page.click('[data-testid="tools-tab"]')

        # Wait for the tools panel to be visible
        admin_page.wait_for_selector("#tools-panel:not(.hidden)")

        # Create tool first
        admin_page.locator('#add-tool-form [name="name"]').fill(test_tool_data["name"])
        admin_page.wait_for_timeout(300)
        admin_page.locator('#add-tool-form [name="url"]').fill(test_tool_data["url"])
        admin_page.wait_for_timeout(300)
        admin_page.locator('#add-tool-form [name="description"]').fill(test_tool_data["description"])
        admin_page.wait_for_timeout(300)
        admin_page.locator('#add-tool-form [name="integrationType"]').select_option(test_tool_data["integrationType"])
        admin_page.wait_for_timeout(300)
        with admin_page.expect_response(lambda response: "/admin/tools" in response.url and response.request.method == "POST") as response_info:
            admin_page.click('#add-tool-form button[type="submit"]')
        response = response_info.value
        created_tool = _find_tool(admin_page, test_tool_data["name"])
        assert created_tool is not None, f"Created tool not found for deletion (status {response.status})"

        # Delete via admin endpoint (form-encoded) and verify removal
        delete_response = admin_page.request.post(
            f"/admin/tools/{created_tool['id']}/delete",
            data="is_inactive_checked=false",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert delete_response.status < 400
        assert _find_tool(admin_page, test_tool_data["name"]) is None
