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
from mcpgateway.plugins.framework.hook_registry import HookRegistry, get_hook_registry
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.manager import PluginManager
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
    "ConfigLoader",
    "ExternalPluginServer",
    "GlobalContext",
    "HookRegistry",
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
]
