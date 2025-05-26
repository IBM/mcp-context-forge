# -*- coding: utf-8 -*-
"""JSON-RPC Validation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module provides validation functions for JSON-RPC 2.0 requests and responses
according to the specification at https://www.jsonrpc.org/specification.

Includes:
- Request validation
- Response validation
- Standard error codes
- Error message formatting
"""

from typing import Any, Dict, Optional, Union


class JSONRPCError(Exception):
    """JSON-RPC protocol error."""

    def __init__(
        self,
        code: int,
        message: str,
        data: Optional[Any] = None,
        request_id: Optional[Union[str, int]] = None,
    ):
        """Initialize JSON-RPC error.

        Args:
            code: Error code
            message: Error message
            data: Optional error data
            request_id: Optional request ID
        """
        self.code = code
        self.message = message
        self.data = data
        self.request_id = request_id
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to JSON-RPC error response dict.

        Returns:
            Error response dictionary
        """
        error = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data

        return {"jsonrpc": "2.0", "error": error, "request_id": self.request_id}


# Standard JSON-RPC error codes
PARSE_ERROR = -32700  # Invalid JSON
INVALID_REQUEST = -32600  # Invalid Request object
METHOD_NOT_FOUND = -32601  # Method not found
INVALID_PARAMS = -32602  # Invalid method parameters
INTERNAL_ERROR = -32603  # Internal JSON-RPC error
SERVER_ERROR_START = -32000  # Start of server error codes
SERVER_ERROR_END = -32099  # End of server error codes


def validate_request(request: Dict[str, Any]) -> None:
    """Validate JSON-RPC request.

    Args:
        request: Request dictionary to validate

    Raises:
        JSONRPCError: If request is invalid
    """
    # Check jsonrpc version
    if request.get("jsonrpc") != "2.0":
        raise JSONRPCError(INVALID_REQUEST, "Invalid JSON-RPC version", request_id=request.get("id"))

    # Check method
    method = request.get("method")
    if not isinstance(method, str) or not method:
        raise JSONRPCError(INVALID_REQUEST, "Invalid or missing method", request_id=request.get("id"))

    # Check ID for requests (not notifications)
    if "id" in request:
        request_id = request["id"]
        if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
            raise JSONRPCError(INVALID_REQUEST, "Invalid request ID type", request_id=None)

    # Check params if present
    params = request.get("params")
    if params is not None:
        if not isinstance(params, (dict, list)):
            raise JSONRPCError(INVALID_REQUEST, "Invalid params type", request_id=request.get("id"))


def validate_response(response: Dict[str, Any]) -> None:
    """Validate JSON-RPC response.

    Args:
        response: Response dictionary to validate

    Raises:
        JSONRPCError: If response is invalid
    """
    # Check jsonrpc version
    if response.get("jsonrpc") != "2.0":
        raise JSONRPCError(INVALID_REQUEST, "Invalid JSON-RPC version", request_id=response.get("id"))

    # Check ID
    if "id" not in response:
        raise JSONRPCError(INVALID_REQUEST, "Missing response ID", request_id=None)

    response_id = response["id"]
    if not isinstance(response_id, (str, int, type(None))) or isinstance(response_id, bool):
        raise JSONRPCError(INVALID_REQUEST, "Invalid response ID type", request_id=None)

    # Check result XOR error
    has_result = "result" in response
    has_error = "error" in response

    if not has_result and not has_error:
        raise JSONRPCError(INVALID_REQUEST, "Response must contain either result or error", request_id=id)
    if has_result and has_error:
        raise JSONRPCError(INVALID_REQUEST, "Response cannot contain both result and error", request_id=id)

    # Validate error object
    if has_error:
        error = response["error"]
        if not isinstance(error, dict):
            raise JSONRPCError(INVALID_REQUEST, "Invalid error object type", request_id=id)

        if "code" not in error or "message" not in error:
            raise JSONRPCError(INVALID_REQUEST, "Error must contain code and message", request_id=id)

        if not isinstance(error["code"], int):
            raise JSONRPCError(INVALID_REQUEST, "Error code must be integer", request_id=id)

        if not isinstance(error["message"], str):
            raise JSONRPCError(INVALID_REQUEST, "Error message must be string", request_id=id)
