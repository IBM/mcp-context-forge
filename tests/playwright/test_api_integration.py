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

    def test_should_handle_mcp_protocol_requests(self, page: Page, admin_page):
        """Test MCP tool test modal via UI.

        Verifies the tool test flow: click Test on a tool row, modal opens
        with dynamically generated form fields, click Run Tool, result area
        displays output.
        """
        # admin_page fixture ensures login; use raw page for operations
        page.click('[data-testid="tools-tab"]')
        page.wait_for_selector("#tools-panel:not(.hidden)")

        # Wait for tools table to load
        try:
            page.wait_for_selector("#tools-table-body tr", timeout=10000)
        except Exception:
            pytest.skip("No tools available to test MCP protocol requests")

        first_tool = page.locator("#tools-table-body tr").first
        test_btn = first_tool.locator('button:has-text("Test")')
        if test_btn.count() == 0:
            pytest.skip("No Test button available on first tool")
        test_btn.click()

        # Wait for tool test modal and dynamic form field generation
        expect(page.locator("#tool-test-modal")).to_be_visible(timeout=10000)
        # Wait for dynamic form fields to be generated from schema
        page.wait_for_selector("#tool-test-form-fields", state="visible", timeout=10000)

        # Fill any dynamically generated form fields (schema-based)
        form_fields = page.locator("#tool-test-form-fields input")
        for i in range(form_fields.count()):
            field = form_fields.nth(i)
            if field.input_value() == "":
                field.fill("test")

        # Click Run Tool and verify result area becomes populated
        page.click('button:has-text("Run Tool")')
        page.wait_for_selector("#tool-test-result", timeout=30000)
        expect(page.locator("#tool-test-result")).to_be_visible()

    def test_mcp_initialize_endpoint(self, page: Page, api_request_context: APIRequestContext, admin_page):
        """Test MCP initialize endpoint directly via APIRequestContext."""
        cookies = page.context.cookies()
        jwt_cookie = next((c for c in cookies if c["name"] == "jwt_token"), None)
        assert jwt_cookie is not None
        response = api_request_context.post(
            "/protocol/initialize",
            headers={"Authorization": f"Bearer {jwt_cookie['value']}"},
            data={"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0.0"}},
        )
        assert response.ok
        data = response.json()
        assert "protocolVersion" in data
