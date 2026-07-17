# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Middleware package for ContextForge.
Contains various middleware components for request processing.
"""

from mcpgateway.middleware.forwarded_host import ForwardedHostMiddleware
from mcpgateway.middleware.token_scoping import TokenScopingMiddleware, token_scoping_middleware

__all__ = ["ForwardedHostMiddleware", "TokenScopingMiddleware", "token_scoping_middleware"]
