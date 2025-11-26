# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/validation/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Validation Package.
Provides validation components for the MCP Gateway including:
- JSON-RPC request/response validation
- Tag validation and normalization
"""

from mcpgateway.validation.jsonrpc import JSONRPCError, validate_request, validate_response
from mcpgateway.validation.tags import TagValidator, validate_tags_field

__all__ = ["validate_request", "validate_response", "JSONRPCError", "TagValidator", "validate_tags_field"]
