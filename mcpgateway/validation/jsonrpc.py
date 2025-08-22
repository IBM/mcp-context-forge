# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/validation/jsonrpc.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

JSON-RPC Validation.
This module provides validation functions for JSON-RPC 2.0 requests and responses
according to the specification at https://www.jsonrpc.org/specification.

Includes:
- Request validation
- Response validation
- Standard error codes
- Error message formatting

Examples:
    >>> from mcpgateway.validation.jsonrpc import JSONRPCError, validate_request
    >>> error = JSONRPCError(-32600, "Invalid Request")
    >>> error.code
    -32600
    >>> error.message
    'Invalid Request'
    >>> validate_request({'jsonrpc': '2.0', 'method': 'test', 'id': 1})
    >>> validate_request({'jsonrpc': '2.0', 'method': 'test'})  # notification
    >>> try:
    ...     validate_request({'method': 'test'})  # missing jsonrpc
    ... except JSONRPCError as e:
    ...     e.code
    -32600
"""

# Standard
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

        Examples:
            Basic error without data:
            >>> error = JSONRPCError(-32600, "Invalid Request", request_id=1)
            >>> error.to_dict()
            {'jsonrpc': '2.0', 'error': {'code': -32600, 'message': 'Invalid Request'}, 'request_id': 1}

            Error with additional data:
            >>> error = JSONRPCError(-32602, "Invalid params", data={"param": "value"}, request_id="abc")
            >>> error.to_dict()
            {'jsonrpc': '2.0', 'error': {'code': -32602, 'message': 'Invalid params', 'data': {'param': 'value'}}, 'request_id': 'abc'}

            Error without request ID (for parse errors):
            >>> error = JSONRPCError(-32700, "Parse error", data="Unexpected EOF")
            >>> error.to_dict()
            {'jsonrpc': '2.0', 'error': {'code': -32700, 'message': 'Parse error', 'data': 'Unexpected EOF'}, 'request_id': None}

            Error with complex data:
            >>> error = JSONRPCError(-32603, "Internal error", data={"details": ["error1", "error2"], "timestamp": 123456}, request_id=42)
            >>> sorted(error.to_dict()['error']['data']['details'])
            ['error1', 'error2']
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

    Examples:
        Valid request:
        >>> validate_request({"jsonrpc": "2.0", "method": "ping", "id": 1})

        Valid notification (no id):
        >>> validate_request({"jsonrpc": "2.0", "method": "notify"})

        Valid request with params:
        >>> validate_request({"jsonrpc": "2.0", "method": "add", "params": [1, 2], "id": 1})
        >>> validate_request({"jsonrpc": "2.0", "method": "add", "params": {"a": 1, "b": 2}, "id": 1})

        Invalid version:
        >>> validate_request({"jsonrpc": "1.0", "method": "ping", "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid JSON-RPC version

        Missing method:
        >>> validate_request({"jsonrpc": "2.0", "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid or missing method

        Empty method:
        >>> validate_request({"jsonrpc": "2.0", "method": "", "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid or missing method

        Invalid params type:
        >>> validate_request({"jsonrpc": "2.0", "method": "test", "params": "invalid", "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid params type

        Invalid ID type:
        >>> validate_request({"jsonrpc": "2.0", "method": "test", "id": True})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid request ID type
    """  # doctest: +ELLIPSIS
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

    Examples:
        Valid success response:
        >>> validate_response({"jsonrpc": "2.0", "result": 42, "id": 1})

        Valid error response:
        >>> validate_response({"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}, "id": 1})

        Valid response with null result:
        >>> validate_response({"jsonrpc": "2.0", "result": None, "id": 1})

        Valid response with null id (for errors during id parsing):
        >>> validate_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})

        Invalid version:
        >>> validate_response({"jsonrpc": "1.0", "result": 42, "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid JSON-RPC version

        Missing ID:
        >>> validate_response({"jsonrpc": "2.0", "result": 42})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Missing response ID

        Invalid ID type (boolean):
        >>> validate_response({"jsonrpc": "2.0", "result": 42, "id": True})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid response ID type

        Invalid ID type (list):
        >>> validate_response({"jsonrpc": "2.0", "result": 42, "id": [1, 2]})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid response ID type

        Missing both result and error:
        >>> validate_response({"jsonrpc": "2.0", "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Response must contain either result or error

        Both result and error present:
        >>> validate_response({"jsonrpc": "2.0", "result": 42, "error": {"code": -1, "message": "Error"}, "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Response cannot contain both result and error

        Invalid error object type:
        >>> validate_response({"jsonrpc": "2.0", "error": "Invalid error", "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Invalid error object type

        Error missing code:
        >>> validate_response({"jsonrpc": "2.0", "error": {"message": "Error"}, "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Error must contain code and message

        Error missing message:
        >>> validate_response({"jsonrpc": "2.0", "error": {"code": -32601}, "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Error must contain code and message

        Invalid error code type:
        >>> validate_response({"jsonrpc": "2.0", "error": {"code": "invalid", "message": "Error"}, "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Error code must be integer

        Invalid error message type:
        >>> validate_response({"jsonrpc": "2.0", "error": {"code": -32601, "message": 123}, "id": 1})  # doctest: +ELLIPSIS
        Traceback (most recent call last):
            ...
        mcpgateway.validation.jsonrpc.JSONRPCError: Error message must be string

        Valid error with additional data:
        >>> validate_response({"jsonrpc": "2.0", "error": {"code": -32602, "message": "Invalid params", "data": {"param": "name"}}, "id": 1})
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
