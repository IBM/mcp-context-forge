# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/handlers/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Handlers Package.
Provides request handlers for the MCP Gateway including:
- Sampling request handling
"""

from mcpgateway.handlers.sampling import SamplingHandler

__all__ = ["SamplingHandler"]
