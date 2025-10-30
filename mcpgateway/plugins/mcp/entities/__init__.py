"""Location: ./mcpgateway/plugins/mcp/entities/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

MCP Plugins Entities Package.
"""

# First-Party
from mcpgateway.plugins.mcp.entities.models import (
    HttpHeaderPayload,
    HttpHeaderPayloadResult,
    HookType,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    PromptResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

from mcpgateway.plugins.mcp.entities.base import MCPPlugin

__all__ = [
    "HookType",
    "HttpHeaderPayload",
    "HttpHeaderPayloadResult",
    "MCPPlugin",
    "PromptPosthookPayload",
    "PromptPosthookResult",
    "PromptPrehookPayload",
    "PromptPrehookResult",
    "PromptResult",
    "ResourcePostFetchPayload",
    "ResourcePostFetchResult",
    "ResourcePreFetchPayload",
    "ResourcePreFetchResult",
    "ToolPostInvokePayload",
    "ToolPostInvokeResult",
    "ToolPreInvokePayload",
    "ToolPreInvokeResult",
]
