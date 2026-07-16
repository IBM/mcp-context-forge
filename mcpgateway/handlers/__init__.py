# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/handlers/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Handlers Package.
Provides request handlers for ContextForge including:
- Sampling request handling
"""

from mcpgateway.handlers.sampling import SamplingHandler

__all__ = ["SamplingHandler"]
