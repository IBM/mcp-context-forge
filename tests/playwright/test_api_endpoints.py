# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_api_endpoints.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test API endpoints through UI interactions.
"""

# Standard
import re

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
        assert response.ok

        servers = response.json()
        assert isinstance(servers, list)

    def test_list_tools(self, api_request_context: APIRequestContext):
        """Test list tools endpoint."""
        response = api_request_context.get("/tools")
        assert response.ok

        tools = response.json()
        assert isinstance(tools, list)

    def test_rpc_endpoint(self, api_request_context: APIRequestContext):
        """Test JSON-RPC endpoint."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "system.listMethods", "params": {}}

        response = api_request_context.post("/rpc", data=payload)
        assert response.ok

        result = response.json()
        assert result.get("jsonrpc") == "2.0"
        assert "result" in result or "error" in result

    def test_api_docs_accessible(self, admin_page, base_url: str):
        """Test that API documentation is accessible."""
        # Test Swagger UI
        admin_page.page.goto(f"{base_url}/docs")
        expect(admin_page.page).to_have_title(re.compile(r"ContextForge - Swagger UI"))
        assert admin_page.page.is_visible(".swagger-ui")

        # Test ReDoc
        admin_page.page.goto(f"{base_url}/redoc")
        expect(admin_page.page).to_have_title(re.compile(r"ReDoc", re.IGNORECASE))
