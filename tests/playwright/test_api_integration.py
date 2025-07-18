# -*- coding: utf-8 -*-
import pytest
from playwright.sync_api import Page, expect, APIRequestContext

class TestAPIIntegration:
    """API integration tests for MCP protocol and REST endpoints.

    Examples:
        pytest tests/playwright/test_api_integration.py
    """
    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_should_handle_mcp_protocol_requests(self, page: Page, admin_page):
        """Test MCP protocol API integration via UI."""
        api_calls = []
        def handle_request(route):
            api_calls.append(route.request.url)
            route.continue_()
        page.route("/api/mcp/**", handle_request)
        page.click("#tab-tools")
        page.wait_for_selector("#tools-panel")
        first_tool = page.locator("#tools-table tbody tr").first
        first_tool.locator('button:has-text("Execute")').click()
        expect(page.locator("#tool-execution-modal")).to_be_visible()
        page.fill('[name="tool-params"]', '{"test": "value"}')
        page.click('button:has-text("Run Tool")')
        page.wait_for_selector(".tool-result", timeout=10000)
        expect(page.locator(".tool-result")).to_be_visible()
        assert len(api_calls) > 0

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_mcp_initialize_endpoint(self, page: Page, request: APIRequestContext, admin_page):
        """Test MCP initialize endpoint directly via APIRequestContext."""
        cookies = page.context.cookies()
        jwt_cookie = next((c for c in cookies if c["name"] == "jwt_token"), None)
        assert jwt_cookie is not None
        response = request.post("/api/mcp/initialize",
            headers={"Cookie": f"jwt_token={jwt_cookie['value']}"},
            data={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {}
                },
                "id": 1
            }
        )
        assert response.ok
        data = response.json()
        assert "result" in data
