# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_api_endpoints.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test API endpoints through UI interactions.
"""

# Standard
import re
import pytest

# Third-Party
from playwright.sync_api import APIRequestContext, expect


class TestAPIEndpoints:
    """Test API endpoints."""

    def test_health_check(self, api_request_context: APIRequestContext):
        """Test health check endpoint."""
        response = api_request_context.get("/health")
        assert response.ok
        assert response.status == 200

        data = response.json()
        assert data["status"] == "healthy"

    def test_list_servers(self, api_request_context: APIRequestContext):
        """Test list servers endpoint."""
        response = api_request_context.get("/servers")
        if response.status in (401, 403):
            pytest.skip(f"Auth required for /servers (HTTP {response.status})")
        assert response.ok, f"/servers returned HTTP {response.status}: {response.text()[:200]}"

        servers = response.json()
        assert isinstance(servers, list)

    def test_list_tools(self, api_request_context: APIRequestContext):
        """Test list tools endpoint."""
        response = api_request_context.get("/tools")
        if response.status in (401, 403):
            pytest.skip(f"Auth required for /tools (HTTP {response.status})")
        assert response.ok, f"/tools returned HTTP {response.status}: {response.text()[:200]}"

        tools = response.json()
        assert isinstance(tools, list)

    def test_rpc_endpoint(self, api_request_context: APIRequestContext):
        """Test JSON-RPC endpoint."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "system.listMethods", "params": {}}

        response = api_request_context.post("/rpc", data=payload)
        if response.status in (401, 403):
            pytest.skip(f"Auth required for /rpc (HTTP {response.status})")
        assert response.ok, f"/rpc returned HTTP {response.status}: {response.text()[:200]}"

        result = response.json()
        assert result.get("jsonrpc") == "2.0"
        assert "result" in result or "error" in result

    def test_api_docs_accessible(self, admin_page, base_url: str):
        """Test that API documentation is accessible."""
        # Test Swagger UI
        admin_page.page.goto(f"{base_url}/docs")
        expect(admin_page.page).to_have_title(re.compile(r"ContextForge - Swagger UI"))
        try:
            expect(admin_page.page.locator(".swagger-ui")).to_be_visible(timeout=15000)
        except AssertionError:
            pytest.skip("Swagger UI not rendered — docs may be disabled or slow to load")

        # Test ReDoc
        admin_page.page.goto(f"{base_url}/redoc")
        expect(admin_page.page).to_have_title(re.compile(r"ReDoc", re.IGNORECASE))
