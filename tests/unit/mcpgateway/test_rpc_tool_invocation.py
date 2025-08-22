# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rpc_tool_invocation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test RPC tool invocation after PR #746 changes.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from mcpgateway.main import app
from mcpgateway.models import Tool
from mcpgateway.services.tool_service import ToolService
from mcpgateway.config import settings


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_tool_service():
    """Create a mock tool service."""
    service = AsyncMock(spec=ToolService)
    return service


@pytest.fixture
def sample_tool():
    """Create a sample tool for testing."""
    return Tool(
        name="test_tool",
        url="http://localhost:8000/test",
        description="A test tool",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "number", "default": 5}}, "required": ["query"]},
    )


class TestRPCToolInvocation:
    """Test class for RPC tool invocation."""

    def test_tools_call_method_new_format(self, client, mock_db):
        """Test tool invocation using the new tools/call method format."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.tool_service.invoke_tool", new_callable=AsyncMock) as mock_invoke:
                    mock_invoke.return_value = {"result": "success", "data": "test data"}

                    request_body = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "test_tool", "arguments": {"query": "test", "limit": 5}}, "id": 1}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert result["id"] == 1

                    mock_invoke.assert_called_once()
                    call_args = mock_invoke.call_args
                    assert call_args.kwargs["name"] == "test_tool"
                    assert call_args.kwargs["arguments"] == {"query": "test", "limit": 5}

    def test_direct_tool_invocation_fails(self, client, mock_db):
        """Test that direct tool invocation (old format) now fails with 'Invalid method'."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                request_body = {"jsonrpc": "2.0", "method": "test_tool", "params": {"query": "test", "limit": 5}, "id": 1}  # Direct tool name as method (old format)

                response = client.post("/rpc", json=request_body)

                assert response.status_code == 200
                result = response.json()
                assert result["jsonrpc"] == "2.0"
                assert "error" in result
                assert result["error"]["code"] == -32000
                assert result["error"]["message"] == "Invalid method"
                assert result["error"]["data"] == {"query": "test", "limit": 5}
                assert result["id"] == 1

    def test_tools_list_method(self, client, mock_db):
        """Test the tools/list method."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.tool_service.list_tools", new_callable=AsyncMock) as mock_list:
                    sample_tool = MagicMock()
                    sample_tool.model_dump.return_value = {"name": "test_tool", "description": "A test tool"}
                    mock_list.return_value = [sample_tool]

                    request_body = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert "tools" in result["result"]
                    assert len(result["result"]["tools"]) == 1
                    assert result["result"]["tools"][0]["name"] == "test_tool"

    def test_resources_read_method(self, client, mock_db):
        """Test the resources/read method."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.resource_service.read_resource", new_callable=AsyncMock) as mock_read:
                    mock_read.return_value = {"uri": "test://resource", "content": "test content"}

                    request_body = {"jsonrpc": "2.0", "method": "resources/read", "params": {"uri": "test://resource"}, "id": 3}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert "contents" in result["result"]

    def test_prompts_get_method(self, client, mock_db):
        """Test the prompts/get method."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.prompt_service.get_prompt", new_callable=AsyncMock) as mock_get:
                    mock_prompt = MagicMock()
                    mock_prompt.model_dump.return_value = {"name": "test_prompt", "description": "A test prompt", "messages": []}
                    mock_get.return_value = mock_prompt

                    request_body = {"jsonrpc": "2.0", "method": "prompts/get", "params": {"name": "test_prompt", "arguments": {}}, "id": 4}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result

    def test_initialize_method(self, client, mock_db):
        """Test the initialize method."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.session_registry.handle_initialize_logic", new_callable=AsyncMock) as mock_init:
                    mock_init.return_value = MagicMock(model_dump=MagicMock(return_value={"protocolVersion": "1.0", "capabilities": {}, "serverInfo": {"name": "test-server"}}))

                    request_body = {"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "1.0", "capabilities": {}, "clientInfo": {"name": "test-client"}}, "id": 5}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert result["result"]["protocolVersion"] == "1.0"

    @pytest.mark.parametrize(
        "method,expected_result_key",
        [
            ("tools/list", "tools"),
            ("resources/list", "resources"),
            ("prompts/list", "prompts"),
            ("list_gateways", "gateways"),
            ("list_roots", "roots"),
        ],
    )
    def test_list_methods_return_proper_structure(self, client, mock_db, method, expected_result_key):
        """Test that all list methods return results in the proper structure."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                # Mock all possible service methods
                with patch("mcpgateway.main.tool_service.list_tools", new_callable=AsyncMock, return_value=[]):
                    with patch("mcpgateway.main.resource_service.list_resources", new_callable=AsyncMock, return_value=[]):
                        with patch("mcpgateway.main.prompt_service.list_prompts", new_callable=AsyncMock, return_value=[]):
                            with patch("mcpgateway.main.gateway_service.list_gateways", new_callable=AsyncMock, return_value=[]):
                                with patch("mcpgateway.main.root_service.list_roots", new_callable=AsyncMock, return_value=[]):
                                    request_body = {"jsonrpc": "2.0", "method": method, "params": {}, "id": 100}

                                    response = client.post("/rpc", json=request_body)

                                    assert response.status_code == 200
                                    result = response.json()
                                    assert result["jsonrpc"] == "2.0"
                                    assert "result" in result
                                    assert expected_result_key in result["result"]
                                    assert isinstance(result["result"][expected_result_key], list)

    def test_unknown_method_returns_error(self, client, mock_db):
        """Test that unknown methods return an appropriate error."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                request_body = {"jsonrpc": "2.0", "method": "unknown/method", "params": {}, "id": 999}

                response = client.post("/rpc", json=request_body)

                assert response.status_code == 200
                result = response.json()
                assert result["jsonrpc"] == "2.0"
                assert "error" in result
                assert result["error"]["code"] == -32000
                assert result["error"]["message"] == "Invalid method"
                assert result["id"] == 999


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
