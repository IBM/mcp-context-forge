# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rpc_backward_compatibility.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test backward compatibility for tool invocation after PR #746.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from mcpgateway.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


class TestRPCBackwardCompatibility:
    """Test backward compatibility for RPC tool invocation."""

    def test_old_format_tool_invocation_with_backward_compatibility(self, client, mock_db):
        """Test that old format (direct tool name as method) still works with backward compatibility."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.tool_service.invoke_tool", new_callable=AsyncMock) as mock_invoke:
                    mock_invoke.return_value = {"result": "success", "data": "test data from old format"}

                    # Old format: tool name directly as method
                    request_body = {"jsonrpc": "2.0", "method": "my_custom_tool", "params": {"query": "test query", "limit": 10}, "id": 123}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert result["result"]["result"] == "success"
                    assert result["result"]["data"] == "test data from old format"
                    assert result["id"] == 123

                    # Verify the tool was invoked with correct parameters
                    mock_invoke.assert_called_once()
                    call_args = mock_invoke.call_args
                    assert call_args.kwargs["name"] == "my_custom_tool"
                    assert call_args.kwargs["arguments"] == {"query": "test query", "limit": 10}

    def test_new_format_tool_invocation_still_works(self, client, mock_db):
        """Test that new format (tools/call method) continues to work."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.tool_service.invoke_tool", new_callable=AsyncMock) as mock_invoke:
                    mock_invoke.return_value = {"result": "success", "data": "test data from new format"}

                    # New format: tools/call method
                    request_body = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "my_custom_tool", "arguments": {"query": "test query", "limit": 10}}, "id": 456}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert result["result"]["result"] == "success"
                    assert result["result"]["data"] == "test data from new format"
                    assert result["id"] == 456

                    # Verify the tool was invoked with correct parameters
                    mock_invoke.assert_called_once()
                    call_args = mock_invoke.call_args
                    assert call_args.kwargs["name"] == "my_custom_tool"
                    assert call_args.kwargs["arguments"] == {"query": "test query", "limit": 10}

    def test_both_formats_invoke_same_tool(self, client, mock_db):
        """Test that both old and new formats can invoke the same tool successfully."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.tool_service.invoke_tool", new_callable=AsyncMock) as mock_invoke:
                    mock_invoke.return_value = {"result": "success"}

                    # Test old format
                    old_format_request = {"jsonrpc": "2.0", "method": "search_tool", "params": {"query": "old format"}, "id": 1}

                    response_old = client.post("/rpc", json=old_format_request)
                    assert response_old.status_code == 200

                    # Reset mock
                    mock_invoke.reset_mock()

                    # Test new format
                    new_format_request = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "search_tool", "arguments": {"query": "new format"}}, "id": 2}

                    response_new = client.post("/rpc", json=new_format_request)
                    assert response_new.status_code == 200

                    # Both should have invoked the tool
                    assert mock_invoke.call_count == 1
                    call_args = mock_invoke.call_args
                    assert call_args.kwargs["name"] == "search_tool"
                    assert call_args.kwargs["arguments"]["query"] == "new format"

    def test_invalid_method_still_returns_error(self, client, mock_db):
        """Test that truly invalid methods still return an error."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.tool_service.invoke_tool", new_callable=AsyncMock) as mock_invoke:
                    # Simulate tool not found
                    mock_invoke.side_effect = ValueError("Tool not found")

                    with patch("mcpgateway.main.gateway_service.forward_request", new_callable=AsyncMock) as mock_forward:
                        # Simulate gateway forward also failing
                        mock_forward.side_effect = ValueError("Not a gateway method")

                        request_body = {"jsonrpc": "2.0", "method": "completely_invalid_method", "params": {}, "id": 999}

                        response = client.post("/rpc", json=request_body)

                        assert response.status_code == 200
                        result = response.json()
                        assert result["jsonrpc"] == "2.0"
                        assert "error" in result
                        assert result["error"]["code"] == -32000
                        assert result["error"]["message"] == "Invalid method"
                        assert result["id"] == 999
