# -*- coding: utf-8 -*-
"""Test API endpoints through UI interactions."""

# Third-Party
from playwright.sync_api import APIRequestContext, expect, Page
import pytest


class TestAPIEndpoints:
    """Test API endpoints."""

    def test_health_check(self, api_request_context: APIRequestContext):
        """Test health check endpoint."""
        response = api_request_context.get("/health")
        assert response.ok
        assert response.status == 200

        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_list_servers(self, api_request_context: APIRequestContext):
        """Test list servers endpoint."""
        response = api_request_context.get("/servers")
        assert response.ok

        servers = response.json()
        assert isinstance(servers, list)

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_list_tools(self, api_request_context: APIRequestContext):
        """Test list tools endpoint."""
        response = api_request_context.get("/tools")
        assert response.ok

        tools = response.json()
        assert isinstance(tools, list)

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_rpc_endpoint(self, api_request_context: APIRequestContext):
        """Test JSON-RPC endpoint."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "system.listMethods", "params": {}}

        response = api_request_context.post("/rpc", data=payload)
        assert response.ok

        result = response.json()
        assert result.get("jsonrpc") == "2.0"
        assert "result" in result or "error" in result

    @pytest.mark.skip(reason="Temporarily disabled for demonstration purposes")
    def test_api_docs_accessible(self, page: Page, base_url: str):
        """Test that API documentation is accessible."""
        # Test Swagger UI
        page.goto(f"{base_url}/docs")
        expect(page).to_have_title("MCP Gateway - Swagger UI")
        assert page.is_visible(".swagger-ui")

        # Test ReDoc
        page.goto(f"{base_url}/redoc")
        assert page.is_visible("#redoc")
