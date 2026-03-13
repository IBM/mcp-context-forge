# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/playwright/test_api_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module documentation...
"""

# Standard
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, expect, Locator, Page
import pytest


@pytest.fixture
def json_param_tool(api_request_context: APIRequestContext):
    """Create a REST tool with an object-type parameter via API, clean up after.

    Yields the tool name so tests can locate it in the UI by name.
    """
    tool_name = f"test-json-tool-{uuid.uuid4().hex[:8]}"
    payload = {
        "tool": {
            "name": tool_name,
            "url": "http://localhost:8080/health",
            "integration_type": "REST",
            "request_type": "POST",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "description": "Configuration object",
                    }
                },
                "required": ["config"],
            },
        }
    }
    resp = api_request_context.post("/tools/", data=payload)
    assert resp.ok, f"Failed to create test tool: {resp.text()}"
    tool_id = resp.json()["id"]

    yield tool_name

    api_request_context.delete(f"/tools/{tool_id}")


def _close_and_reopen_test_modal(page: Page, test_btn: Locator) -> None:
    """Close the tool test modal and reopen it, waiting for form fields.

    The testTool() JS function has a 2000ms debounce (enhancedDebounceDelay)
    that rejects rapid re-clicks, so we must wait for that to expire before
    reopening.
    """
    close_btn = page.locator("#tool-test-modal button:has-text('Close')")
    close_btn.click()
    expect(page.locator("#tool-test-modal")).to_be_hidden(timeout=5000)
    # Wait for testTool() 2000ms debounce to expire before re-clicking
    page.wait_for_timeout(2500)
    test_btn.click()
    expect(page.locator("#tool-test-modal")).to_be_visible(timeout=10000)
    page.wait_for_selector("#tool-test-form-fields", state="visible", timeout=10000)


def _fill_and_submit_expecting_error(page: Page, value: str) -> None:
    """Fill the first textarea with value, submit, and assert an error toast appears."""
    page.locator("#tool-test-form-fields textarea").first.fill(value)
    page.click('button:has-text("Run Tool")')
    error_toast = page.locator("div.fixed.bg-red-600")
    expect(error_toast).to_be_visible(timeout=5000)
    # Wait for the 5s auto-dismiss so it won't bleed into the next assertion
    expect(error_toast).to_be_hidden(timeout=10000)


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

    def test_should_handle_object_parameter_validation(self, page: Page, admin_page, json_param_tool: str):
        """Test object parameter validation in tool test modal.

        Verifies that object-type parameters using textarea fields properly
        validate JSON input and reject invalid formats (malformed JSON,
        arrays, strings, and null).

        Uses the json_param_tool fixture to guarantee a tool with an object
        parameter exists before the test runs.
        """
        page.click('[data-testid="tools-tab"]')
        page.wait_for_selector("#tools-panel:not(.hidden)")

        # Search for the fixture-created tool by name to avoid pagination issues
        search_input = page.locator("#tools-search-input")
        search_input.wait_for(state="visible", timeout=10000)
        search_input.fill(json_param_tool)
        search_input.press("Enter")

        tool_row = page.locator(f'#tools-table-body tr:has-text("{json_param_tool}")')
        tool_row.wait_for(state="visible", timeout=10000)
        test_btn = tool_row.locator('button:has-text("Test")')
        test_btn.click()

        expect(page.locator("#tool-test-modal")).to_be_visible(timeout=10000)
        page.wait_for_selector("#tool-test-form-fields", state="visible", timeout=10000)

        # Fixture guarantees an object-type textarea exists
        textareas = page.locator("#tool-test-form-fields textarea")
        expect(textareas.first).to_be_visible(timeout=5000)

        # Test valid JSON object — intercept request to verify parsed payload
        textareas.first.fill('{"key": "value", "number": 42}')
        with page.expect_request(lambda req: "/rpc" in req.url and req.method == "POST") as req_info:
            page.click('button:has-text("Run Tool")')
        payload = req_info.value.post_data_json
        assert isinstance(payload["params"]["config"], dict), "config should be a parsed dict, not a string"
        assert payload["params"]["config"] == {"key": "value", "number": 42}
        page.wait_for_selector("#tool-test-result", timeout=30000)
        expect(page.locator("#tool-test-result")).to_be_visible()

        # Test invalid inputs — each should show an error toast
        invalid_cases = [
            '{"invalid": json}',  # malformed JSON
            '[1, 2, 3]',          # array (not object)
            '"just a string"',    # string primitive
            'null',               # null (typeof null === "object" in JS)
        ]
        for invalid_value in invalid_cases:
            _close_and_reopen_test_modal(page, test_btn)
            _fill_and_submit_expecting_error(page, invalid_value)

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
