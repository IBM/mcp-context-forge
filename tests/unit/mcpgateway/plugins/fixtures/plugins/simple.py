# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/fixtures/plugins/simple.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Test Suite

Simple minimal plugins for testing the plugin framework.
These plugins provide basic passthrough implementations for testing
registration, priority sorting, hook filtering, etc.
"""

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)


class SimplePromptPlugin(Plugin):
    """Minimal plugin with prompt hooks for testing."""

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Passthrough prompt pre-fetch hook."""
        return PromptPrehookResult(continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Passthrough prompt post-fetch hook."""
        return PromptPosthookResult(continue_processing=True)


class SimpleToolPlugin(Plugin):
    """Minimal plugin with tool hooks for testing."""

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Passthrough tool pre-invoke hook."""
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Passthrough tool post-invoke hook."""
        return ToolPostInvokeResult(continue_processing=True)
