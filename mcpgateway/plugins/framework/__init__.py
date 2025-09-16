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
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    HttpHeaderPayload,
    HttpHeaderPayloadResult,
    HookType,
    PluginCondition,
    PluginConfig,
    PluginContext,
    PluginErrorModel,
    PluginMode,
    PluginResult,
    PluginViolation,
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

__all__ = [
    "ConfigLoader",
    "ExternalPluginServer",
    "GlobalContext",
    "HookType",
    "HttpHeaderPayload",
    "HttpHeaderPayloadResult",
    "Plugin",
    "PluginCondition",
    "PluginConfig",
    "PluginContext",
    "PluginError",
    "PluginErrorModel",
    "PluginLoader",
    "PluginManager",
    "PluginMode",
    "PluginResult",
    "PluginViolation",
    "PluginViolationError",
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
