# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Services Package.
Exposes core ContextForge services:
- Tool management
- Resource handling
- Prompt templates
- Gateway coordination
"""

from mcpgateway.services.gateway_service import GatewayError, GatewayService
from mcpgateway.services.prompt_service import PromptError, PromptService
from mcpgateway.services.resource_service import ResourceError, ResourceService
from mcpgateway.services.tool_service import ToolError, ToolService
from mcpgateway.services.server_service import ServerService

__all__ = [
    "ToolService",
    "ToolError",
    "ResourceService",
    "ResourceError",
    "PromptService",
    "PromptError",
    "GatewayService",
    "GatewayError",
    "ServerService",
]
