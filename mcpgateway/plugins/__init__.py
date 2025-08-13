# -*- coding: utf-8 -*-
"""Services Package.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Exposes core MCP Gateway plugin components:
- Context
- Manager
- Payloads
- Models
"""

from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework.models import GlobalContext, PluginViolation, PromptPosthookPayload, PromptPrehookPayload, ToolPostInvokePayload, ToolPreInvokePayload
from mcpgateway.plugins.framework.errors import PluginViolationError, PluginError

__all__ = ["GlobalContext", "PluginError", "PluginManager", "PluginViolation", "PluginViolationError", "PromptPosthookPayload", "PromptPrehookPayload", "ToolPostInvokePayload", "ToolPreInvokePayload"]
