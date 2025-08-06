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
from mcpgateway.plugins.framework.models import PluginViolation
from mcpgateway.plugins.framework.plugin_types import GlobalContext, PluginViolationError, PromptPosthookPayload, PromptPrehookPayload

__all__ = [
    "GlobalContext",
    "PluginManager",
    "PluginViolation",
    "PluginViolationError",
    "PromptPosthookPayload",
    "PromptPrehookPayload",
]
