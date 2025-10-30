# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/agent/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Agent plugin framework exports.
"""

from mcpgateway.plugins.agent.base import AgentPlugin
from mcpgateway.plugins.agent.models import (
    AgentHookType,
    AgentPreInvokePayload,
    AgentPreInvokeResult,
    AgentPostInvokePayload,
    AgentPostInvokeResult,
)

__all__ = [
    "AgentPlugin",
    "AgentHookType",
    "AgentPreInvokePayload",
    "AgentPreInvokeResult",
    "AgentPostInvokePayload",
    "AgentPostInvokeResult",
]
