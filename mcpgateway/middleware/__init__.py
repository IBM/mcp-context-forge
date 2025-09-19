# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Middleware package for MCP Gateway.
Contains various middleware components for request processing.
"""

from mcpgateway.middleware.token_scoping import TokenScopingMiddleware, token_scoping_middleware

__all__ = ["TokenScopingMiddleware", "token_scoping_middleware"]
