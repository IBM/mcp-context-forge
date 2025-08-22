# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Services Package.
Exposes core MCP Gateway services:
- Tool management
- Resource handling
- Prompt templates
- Gateway coordination
"""

from mcpgateway.services.gateway_service import GatewayError, GatewayService
from mcpgateway.services.prompt_service import PromptError, PromptService
from mcpgateway.services.resource_service import ResourceError, ResourceService
from mcpgateway.services.tool_service import ToolError, ToolService

__all__ = [
    "ToolService",
    "ToolError",
    "ResourceService",
    "ResourceError",
    "PromptService",
    "PromptError",
    "GatewayService",
    "GatewayError",
]
