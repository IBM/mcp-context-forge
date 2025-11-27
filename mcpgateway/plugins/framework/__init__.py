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

# Standard
import os
from typing import Optional

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.errors import PluginError, PluginViolationError
from mcpgateway.plugins.framework.external.mcp.server import ExternalPluginServer
from mcpgateway.plugins.framework.hooks.registry import HookRegistry, get_hook_registry
from mcpgateway.plugins.framework.loader.config import ConfigLoader
from mcpgateway.plugins.framework.loader.plugin import PluginLoader
from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework.hooks.http import (
    HttpAuthCheckPermissionPayload,
    HttpAuthCheckPermissionResult,
    HttpAuthCheckPermissionResultPayload,
    HttpAuthResolveUserPayload,
    HttpAuthResolveUserResult,
    HttpHeaderPayload,
    HttpHookType,
    HttpPostRequestPayload,
    HttpPostRequestResult,
    HttpPreRequestPayload,
    HttpPreRequestResult,
)
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
    PluginContextTable,
    PluginErrorModel,
    PluginMode,
    PluginPayload,
    PluginResult,
    PluginViolation,
)

# Plugin manager singleton (lazy initialization)
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> Optional[PluginManager]:
    """Get or initialize the plugin manager singleton.

    This is the public API for accessing the plugin manager from anywhere in the application.
    The plugin manager is lazily initialized on first access if plugins are enabled.

    Returns:
        PluginManager instance if plugins are enabled, None otherwise.

    Examples:
        >>> from mcpgateway.plugins.framework import get_plugin_manager
        >>> pm = get_plugin_manager()
        >>> # Returns PluginManager if plugins are enabled, None otherwise
        >>> pm is None or isinstance(pm, PluginManager)
        True
    """
    global _plugin_manager  # pylint: disable=global-statement
    if _plugin_manager is None:
        # Import here to avoid circular dependency
        from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel

        if settings.plugins_enabled:
            config_file = os.getenv("PLUGIN_CONFIG_FILE", getattr(settings, "plugin_config_file", "plugins/config.yaml"))
            _plugin_manager = PluginManager(config_file)
    return _plugin_manager


__all__ = [
    "AgentHookType",
    "AgentPostInvokePayload",
    "AgentPostInvokeResult",
    "AgentPreInvokePayload",
    "AgentPreInvokeResult",
    "ConfigLoader",
    "ExternalPluginServer",
    "get_hook_registry",
    "get_plugin_manager",
    "GlobalContext",
    "HookRegistry",
    "HttpAuthCheckPermissionPayload",
    "HttpAuthCheckPermissionResult",
    "HttpAuthCheckPermissionResultPayload",
    "HttpAuthResolveUserPayload",
    "HttpAuthResolveUserResult",
    "HttpHeaderPayload",
    "HttpHookType",
    "HttpPostRequestPayload",
    "HttpPostRequestResult",
    "HttpPreRequestPayload",
    "HttpPreRequestResult",
    "MCPServerConfig",
    "Plugin",
    "PluginCondition",
    "PluginConfig",
    "PluginContext",
    "PluginContextTable",
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
