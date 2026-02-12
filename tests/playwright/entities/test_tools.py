# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/playwright/entities/test_tools.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

# Third-Party
import pytest

# Local
from ..pages.admin_utils import cleanup_tool, delete_tool, find_tool
from ..pages.tools_page import ToolsPage


class TestToolsCRUD:
    """CRUD tests for Tools entity in MCP Gateway Admin UI.

    Examples:
        pytest tests/playwright/entities/test_tools.py
    """

    def test_create_new_tool(self, tools_page: ToolsPage, test_tool_data):
        """Test creating a new tool with debug screenshots and waits."""
        # Go to the Global Tools tab
        tools_page.navigate_to_tools_tab()

        # Fill the form using Page Object properties
        tools_page.fill_locator(tools_page.tool_name_input, test_tool_data["name"])
        tools_page.fill_locator(tools_page.tool_url_input, test_tool_data["url"])
        tools_page.fill_locator(tools_page.tool_description_input, test_tool_data["description"])
        tools_page.tool_integration_type_select.select_option(test_tool_data["integrationType"])

        # Submit the form and assert success response
        with tools_page.page.expect_response(lambda response: "/admin/tools" in response.url and response.request.method == "POST") as response_info:
            tools_page.click_locator(tools_page.add_tool_btn)
        response = response_info.value
        if response.status in (401, 403):
            pytest.skip(f"Tool creation blocked by auth/RBAC (HTTP {response.status})")

        # Verify tool exists via JSON list (avoids cached HTML)
        created_tool = find_tool(tools_page.page, test_tool_data["name"])
        assert created_tool is not None, f"Newly created tool not found via admin API (status {response.status})"

        # Cleanup: delete the created tool for idempotency
        cleanup_tool(tools_page.page, test_tool_data["name"])

    def test_delete_tool(self, tools_page: ToolsPage, test_tool_data):
        """Test deleting a tool."""
        # Go to the Global Tools tab
        tools_page.navigate_to_tools_tab()

        # Create tool first using Page Object properties
        tools_page.fill_locator(tools_page.tool_name_input, test_tool_data["name"])
        tools_page.fill_locator(tools_page.tool_url_input, test_tool_data["url"])
        tools_page.fill_locator(tools_page.tool_description_input, test_tool_data["description"])
        tools_page.tool_integration_type_select.select_option(test_tool_data["integrationType"])
        with tools_page.page.expect_response(lambda response: "/admin/tools" in response.url and response.request.method == "POST") as response_info:
            tools_page.click_locator(tools_page.add_tool_btn)
        response = response_info.value
        if response.status in (401, 403):
            pytest.skip(f"Tool creation blocked by auth/RBAC (HTTP {response.status})")
        created_tool = find_tool(tools_page.page, test_tool_data["name"])
        assert created_tool is not None, f"Created tool not found for deletion (status {response.status})"

        # Delete via centralized helper and verify removal
        delete_success = delete_tool(tools_page.page, created_tool["id"])
        if not delete_success:
            # Deletion may fail due to RBAC (allow_admin_bypass=False on tools.delete)
            pytest.skip("Tool deletion blocked by auth/RBAC permissions")
        assert find_tool(tools_page.page, test_tool_data["name"]) is None, "Tool still exists after deletion"
