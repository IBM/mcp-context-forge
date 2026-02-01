# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/playwright/test_api_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

# Third-Party
from playwright.sync_api import APIRequestContext, expect, Page
import pytest


class TestAPIIntegration:
    """API integration tests for MCP protocol and REST endpoints.

    Examples:
        pytest tests/playwright/test_api_integration.py
    """

    @pytest.mark.skip(reason="UI selector for tool params mismatch")
    def test_should_handle_mcp_protocol_requests(self, admin_page: Page):
        """Test MCP protocol API integration via UI."""
        api_calls = []

        def handle_request(route):
            api_calls.append(route.request.url)
            route.continue_()

        admin_page.route("/api/mcp/**", handle_request)
        admin_page.click('[data-testid="tools-tab"]')
        admin_page.wait_for_selector("#tools-panel")
        # Wait for tools to load
        admin_page.wait_for_selector("#tools-table tbody tr", timeout=10000)
        first_tool = admin_page.locator("#tools-table tbody tr").first
        first_tool.locator('button:has-text("Test")').click()
        expect(admin_page.locator("#tool-test-modal")).to_be_visible()
        admin_page.fill('#tool-test-params', '{"test": "value"}')
        admin_page.click('button:has-text("Run Tool")')
        admin_page.wait_for_selector(".tool-result", timeout=10000)
        expect(admin_page.locator(".tool-result")).to_be_visible()
        assert len(api_calls) > 0

    def test_mcp_initialize_endpoint(self, page: Page, api_request_context: APIRequestContext, admin_page):
        """Test MCP initialize endpoint directly via APIRequestContext."""
        cookies = page.context.cookies()
        jwt_cookie = next((c for c in cookies if c["name"] == "jwt_token"), None)
        assert jwt_cookie is not None
        response = api_request_context.post(
            "/protocol/initialize",
            headers={"Authorization": f"Bearer {jwt_cookie['value']}"},
            data={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            },
        )
        assert response.ok
        data = response.json()
        assert "protocolVersion" in data
