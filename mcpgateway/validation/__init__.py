# -*- coding: utf-8 -*-
"""Validation Package.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Provides validation components for the MCP Gateway including:
- JSON-RPC request/response validation
"""

from mcpgateway.validation.jsonrpc import (
    JSONRPCError,
    validate_request,
    validate_response,
)

__all__ = ["validate_request", "validate_response", "JSONRPCError"]
