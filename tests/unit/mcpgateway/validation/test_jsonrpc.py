# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/validation/test_jsonrpc.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.validation.jsonrpc import (
    INVALID_REQUEST,
    JSONRPCError,
    validate_request,
    validate_response,
)


class TestJSONRPCValidation:
    """Tests for JSON-RPC validation functions."""

    def test_validate_valid_request(self):
        """Test validation of valid JSON-RPC requests."""
        # Minimal valid request
        valid_request = {"jsonrpc": "2.0", "method": "test_method", "id": 1}
        validate_request(valid_request)  # Should not raise

        # Request with params as object
        valid_request_with_params = {
            "jsonrpc": "2.0",
            "method": "test_method",
            "params": {"test": "value"},
            "id": 1,
        }
        validate_request(valid_request_with_params)  # Should not raise

        # Request with params as array
        valid_request_with_array_params = {
            "jsonrpc": "2.0",
            "method": "test_method",
            "params": [1, 2, 3],
            "id": "abc",
        }
        validate_request(valid_request_with_array_params)  # Should not raise

        # Valid notification (without id)
        valid_notification = {"jsonrpc": "2.0", "method": "test_method"}
        validate_request(valid_notification)  # Should not raise

    def test_validate_invalid_request_version(self):
        """Test validation fails with invalid JSON-RPC version."""
        # Missing jsonrpc version
        invalid_request = {"method": "test_method", "id": 1}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid JSON-RPC version" in exc.value.message

        # Wrong jsonrpc version
        invalid_request = {"jsonrpc": "1.0", "method": "test_method", "id": 1}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid JSON-RPC version" in exc.value.message

    def test_validate_invalid_request_method(self):
        """Test validation fails with invalid method."""
        # Missing method
        invalid_request = {"jsonrpc": "2.0", "id": 1}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid or missing method" in exc.value.message

        # Empty method
        invalid_request = {"jsonrpc": "2.0", "method": "", "id": 1}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid or missing method" in exc.value.message

        # Non-string method
        invalid_request = {"jsonrpc": "2.0", "method": 123, "id": 1}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid or missing method" in exc.value.message

    def test_validate_invalid_request_id(self):
        """Test validation fails with invalid request ID."""
        # Boolean ID (not allowed)
        invalid_request = {"jsonrpc": "2.0", "method": "test", "id": True}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid request ID type" in exc.value.message

        # Object ID (not allowed)
        invalid_request = {"jsonrpc": "2.0", "method": "test", "id": {}}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid request ID type" in exc.value.message

    def test_validate_invalid_request_params(self):
        """Test validation fails with invalid params."""
        # Params as boolean (not allowed)
        invalid_request = {"jsonrpc": "2.0", "method": "test", "params": True, "id": 1}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid params type" in exc.value.message

        # Params as string (not allowed)
        invalid_request = {"jsonrpc": "2.0", "method": "test", "params": "string", "id": 1}
        with pytest.raises(JSONRPCError) as exc:
            validate_request(invalid_request)
        assert exc.value.code == INVALID_REQUEST
        assert "Invalid params type" in exc.value.message

    def test_validate_valid_response(self):
        """Test validation of valid JSON-RPC responses."""
        # Valid success response
        valid_response = {"jsonrpc": "2.0", "result": "success", "id": 1}
        validate_response(valid_response)  # Should not raise

        # Valid error response
        valid_error_response = {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "Invalid Request"},
            "id": "abc",
        }
        validate_response(valid_error_response)  # Should not raise

        # Valid response with null ID
        valid_null_id_response = {"jsonrpc": "2.0", "result": "success", "id": None}
        validate_response(valid_null_id_response)  # Should not raise

    def test_jsonrpc_error_to_dict(self):
        """Test conversion of JSONRPCError to dict."""
        # Basic error
        error = JSONRPCError(code=-32600, message="Test Error", request_id="test-id")
        error_dict = error.to_dict()
        assert error_dict["jsonrpc"] == "2.0"
        assert error_dict["error"]["code"] == -32600
        assert error_dict["error"]["message"] == "Test Error"
        assert error_dict["request_id"] == "test-id"
        assert "data" not in error_dict["error"]

        # Error with data
        error = JSONRPCError(code=-32600, message="Test Error", data={"detail": "info"}, request_id=1)
        error_dict = error.to_dict()
        assert error_dict["error"]["data"] == {"detail": "info"}
