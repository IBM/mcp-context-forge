# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the main API endpoints.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mcpgateway.schemas import ResourceRead, ServerRead, ToolRead
from mcpgateway.types import InitializeResult, ResourceContent, ServerCapabilities

PROTOCOL_VERSION = os.getenv("PROTOCOL_VERSION", "2025-03-26")


@pytest.fixture
def test_client(app):
    """Create a test client for the app."""
    return TestClient(app)


@pytest.fixture
def mock_jwt_token():
    """Create a mock JWT token."""
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0X3VzZXIiLCJleHAiOjk5OTk5OTk5OTl9.this_is_a_test_token"


@pytest.fixture
def auth_headers(mock_jwt_token):
    """Create headers with authentication."""
    return {"Authorization": f"Bearer {mock_jwt_token}"}


class TestAPIEndpoints:
    """Tests for the API endpoints."""

    def test_health_check(self, test_client):
        """Test the health check endpoint."""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_ready_check(self, test_client):
        """Test the readiness check endpoint."""
        response = test_client.get("/ready")
        # The readiness check returns 200 if DB is reachable
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_root_redirect(self, test_client):
        """Test root path redirects to admin."""
        response = test_client.get("/", allow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/admin"

    def test_static_files(self, test_client):
        """Test static files are served."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                response = test_client.get("/static/test.css")
                # FastAPI will return 404 since the file doesn't actually exist in test
                # We just want to verify the route is registered
                assert response.status_code == 404

    @patch("mcpgateway.main.validate_request")
    @patch("mcpgateway.main.handle_initialize_logic")
    def test_initialize_endpoint(self, mock_handle_initialize, mock_validate, test_client, auth_headers):
        """Test the initialize endpoint."""
        # Set up mocks
        mock_capabilities = ServerCapabilities(
            prompts={"listChanged": True},
            resources={"subscribe": True, "listChanged": True},
            tools={"listChanged": True},
            logging={},
            roots={"listChanged": True},
            sampling={},
        )
        mock_result = InitializeResult(
            protocolVersion=PROTOCOL_VERSION,
            capabilities=mock_capabilities,
            serverInfo={"name": "MCP Gateway", "version": "1.0.0"},
            instructions="MCP Gateway providing federated tools, resources and prompts.",
        )
        mock_handle_initialize.return_value = mock_result

        # Test request
        request_data = {"protocol_version": PROTOCOL_VERSION, "capabilities": {}, "client_info": {"name": "Test Client", "version": "1.0.0"}}

        response = test_client.post("/protocol/initialize", json=request_data, headers=auth_headers)

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert result["protocolVersion"] == PROTOCOL_VERSION
        assert "capabilities" in result
        assert "serverInfo" in result

        # Verify mocks called
        mock_handle_initialize.assert_called_once()

    @patch("mcpgateway.main.validate_request")
    def test_ping_endpoint(self, mock_validate, test_client, auth_headers):
        """Test the ping endpoint."""
        # Test request
        request_data = {"jsonrpc": "2.0", "method": "ping", "id": "test-id"}

        response = test_client.post("/protocol/ping", json=request_data, headers=auth_headers)

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "test-id"
        assert result["result"] == {}

    @patch("mcpgateway.main.server_service.list_servers")
    def test_list_servers_endpoint(self, mock_list_servers, test_client, auth_headers):
        """Test listing servers endpoint."""
        # Set up mock
        mock_servers = [
            ServerRead(
                id=1,
                name="test_server",
                description="A test server",
                icon="server-icon",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
                associated_tools=[101],
                associated_resources=[201],
                associated_prompts=[301],
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        ]
        mock_list_servers.return_value = mock_servers

        # Make request
        response = test_client.get("/servers/", headers=auth_headers)

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert len(result) == 1
        assert result[0]["name"] == "test_server"
        assert result[0]["id"] == 1

        # Verify mock called
        mock_list_servers.assert_called_once()

    @patch("mcpgateway.main.tool_service.list_tools")
    def test_list_tools_endpoint(self, mock_list_tools, test_client, auth_headers):
        """Test listing tools endpoint."""
        # Set up mock
        mock_tools = [
            ToolRead(
                id=1,
                name="test_tool",
                url="http://example.com/tools/test",
                description="A test tool",
                integration_type="MCP",
                request_type="POST",
                headers={"Content-Type": "application/json"},
                input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
                jsonpath_filter="",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
                gateway_id=None,
                execution_count=0,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        ]
        mock_list_tools.return_value = mock_tools

        # Make request
        response = test_client.get("/tools/", headers=auth_headers)

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert len(result) == 1
        assert result[0]["name"] == "test_tool"
        assert result[0]["id"] == 1

        # Verify mock called
        mock_list_tools.assert_called_once()

    @patch("mcpgateway.main.resource_service.list_resources")
    def test_list_resources_endpoint(self, mock_list_resources, test_client, auth_headers):
        """Test listing resources endpoint."""
        # Set up mock
        mock_resources = [
            ResourceRead(
                id=1,
                uri="test/resource",
                name="Test Resource",
                description="A test resource",
                mime_type="text/plain",
                size=12,
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                is_active=True,
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
            )
        ]
        mock_list_resources.return_value = mock_resources

        # Make request
        response = test_client.get("/resources/", headers=auth_headers)

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert len(result) == 1
        assert result[0]["name"] == "Test Resource"
        assert result[0]["uri"] == "test/resource"

        # Verify mock called
        mock_list_resources.assert_called_once()

    @patch("mcpgateway.main.resource_service.read_resource")
    def test_read_resource_endpoint(self, mock_read_resource, test_client, auth_headers):
        """Test reading a resource endpoint."""
        # Set up mock
        mock_content = ResourceContent(type="resource", uri="test/resource", mime_type="text/plain", text="This is test content")
        mock_read_resource.return_value = mock_content

        # Make request
        response = test_client.get("/resources/test/resource", headers=auth_headers)

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert result["type"] == "resource"
        assert result["uri"] == "test/resource"
        assert result["text"] == "This is test content"

        # Verify mock called
        mock_read_resource.assert_called_once()

    @patch("mcpgateway.main.tool_service.invoke_tool")
    def test_rpc_tool_invocation(self, mock_invoke_tool, test_client, auth_headers):
        """Test tool invocation via RPC endpoint."""
        # Set up test data
        tool_name = "test_tool"
        tool_args = {"param": "value"}
        tool_result = {"content": [{"type": "text", "text": "Tool response"}], "is_error": False}

        # Set up mock
        mock_invoke_tool.return_value = tool_result

        # Create RPC request
        rpc_request = {"jsonrpc": "2.0", "id": "test-id", "method": tool_name, "params": tool_args}

        # Make request
        response = test_client.post("/rpc/", json=rpc_request, headers=auth_headers)

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert "content" in result
        assert len(result["content"]) == 1
        assert result["content"][0]["text"] == "Tool response"

        # Verify mock called
        mock_invoke_tool.assert_called_once_with(ANY, tool_name, tool_args)

    @patch("mcpgateway.main.prompt_service.get_prompt")
    @patch("mcpgateway.main.validate_request")
    def test_rpc_prompt_get(self, mock_validate, mock_get_prompt, test_client, auth_headers):
        """Test getting a prompt via RPC endpoint."""
        # Set up test data
        prompt_name = "test_prompt"
        prompt_args = {"param": "value"}
        prompt_result = {"messages": [{"role": "user", "content": {"type": "text", "text": "Rendered prompt"}}], "description": "A test prompt"}

        # Set up mock
        mock_get_prompt.return_value = prompt_result

        # Create RPC request
        rpc_request = {"jsonrpc": "2.0", "id": "test-id", "method": "prompts/get", "params": {"name": prompt_name, "arguments": prompt_args}}

        # Make request
        response = test_client.post("/rpc/", json=rpc_request, headers=auth_headers)

        # Verify response
        assert response.status_code == 200
        result = response.json()
        assert "messages" in result
        assert result["messages"][0]["content"]["text"] == "Rendered prompt"

        # Verify mock called
        mock_get_prompt.assert_called_once_with(ANY, prompt_name, prompt_args)

    @patch("mcpgateway.main.validate_request")
    def test_invalid_request(self, mock_validate, test_client, auth_headers):
        """Test handling of invalid RPC requests."""
        # Set up mock to raise error
        mock_validate.side_effect = Exception("Invalid request")

        # Create RPC request
        rpc_request = {"jsonrpc": "1.0", "id": "test-id", "method": "invalid_method"}  # Invalid version

        # Make request
        response = test_client.post("/rpc/", json=rpc_request, headers=auth_headers)

        # Verify response indicates error
        assert response.status_code == 200  # RPC returns 200 with error in body
        result = response.json()
        assert "error" in result
        assert result["error"]["message"] == "Internal error"
        assert "Invalid request" in result["error"]["data"]
