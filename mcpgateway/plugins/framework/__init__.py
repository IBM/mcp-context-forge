# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Services Package.
Exposes core MCP Gateway plugin components:
- Context
- Manager
- Payloads
- Models
- ExternalPluginServer
"""

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.errors import PluginError, PluginViolationError
from mcpgateway.plugins.framework.external.mcp.server import ExternalPluginServer
from mcpgateway.plugins.framework.hooks.registry import HookRegistry, get_hook_registry
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework.hooks.http import HttpHeaderPayload
from mcpgateway.plugins.framework.hooks.agents import AgentHookType, AgentPostInvokePayload, AgentPostInvokeResult, AgentPreInvokePayload, AgentPreInvokeResult
from mcpgateway.plugins.framework.hooks.resources import ResourceHookType, ResourcePostFetchPayload, ResourcePostFetchResult, ResourcePreFetchPayload, ResourcePreFetchResult
from mcpgateway.plugins.framework.hooks.prompts import (
    PromptHookType,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
)
from mcpgateway.plugins.framework.hooks.tools import ToolHookType, ToolPostInvokePayload, ToolPostInvokeResult, ToolPreInvokeResult, ToolPreInvokePayload
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    MCPServerConfig,
    PluginCondition,
    PluginConfig,
    PluginContext,
    PluginErrorModel,
    PluginMode,
    PluginPayload,
    PluginResult,
    PluginViolation,
)

__all__ = [
    "AgentHookType",
    "AgentPostInvokePayload",
    "AgentPostInvokeResult",
    "AgentPreInvokePayload",
    "AgentPreInvokeResult",
    "ConfigLoader",
    "ExternalPluginServer",
    "GlobalContext",
    "HookRegistry",
    "HttpHeaderPayload",
    "get_hook_registry",
    "MCPServerConfig",
    "Plugin",
    "PluginCondition",
    "PluginConfig",
    "PluginContext",
    "PluginError",
    "PluginErrorModel",
    "PluginLoader",
    "PluginManager",
    "PluginMode",
    "PluginPayload",
    "PluginResult",
    "PluginViolation",
    "PluginViolationError",
    "PromptHookType",
    "PromptPosthookPayload",
    "PromptPosthookResult",
    "PromptPrehookPayload",
    "PromptPrehookResult",
    "ResourceHookType",
    "ResourcePostFetchPayload",
    "ResourcePostFetchResult",
    "ResourcePreFetchPayload",
    "ResourcePreFetchResult",
    "ToolHookType",
    "ToolPostInvokePayload",
    "ToolPostInvokeResult",
    "ToolPreInvokeResult",
    "ToolPreInvokePayload",
]
