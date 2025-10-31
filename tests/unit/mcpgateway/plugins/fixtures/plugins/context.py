# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/plugins/fixtures/plugins/context.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Context plugin.
"""

from mcpgateway.plugins.framework import (
    PluginContext,
    Plugin,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)


class ContextPlugin(Plugin):
    """A simple Context plugin."""

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        """
        context.state["key1"] = "value1"
        return PromptPrehookResult(continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        if "key1" not in context.state or context.state["key1"] != "value1":
            raise ValueError("key1 not in context!! It should be!!")
        return PromptPosthookResult(continue_processing=True)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        context.state["key2"] = "value2"
        context.global_context.state["globkey1"] = "globvalue1"
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        if "key2" not in context.state or context.state["key2"] != "value2":
            raise ValueError("key2 not in context!! It should be!!")
        if "globkey1" not in context.global_context.state or context.global_context.state["globkey1"] != "globvalue1":
            raise ValueError("globkey1 not in context!! It should be!!")
        context.state["key3"] = "value3"
        context.global_context.state["globkey2"] = "globvalue2"
        return ToolPostInvokeResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Plugin hook run after a resource was fetched.

        Args:
            payload: The resource result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the resource result should proceed.
        """
        return ResourcePostFetchResult(continue_processing=True)

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Plugin hook run before a resource was fetched.

        Args:
            payload: The resource result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the resource result should proceed.
        """
        return ResourcePreFetchResult(continue_processing=True)


class ContextPlugin2(Plugin):
    """A simple Context plugin."""

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        """
        if "key1" in context.state:
            raise ValueError("key1 should not be in ContextPlugin2's context")
        # context.state["cp2key1"] = "cp2value1"
        return PromptPrehookResult(continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        if "key1" not in context.state or context.state["key1"] != "value1":
            raise ValueError("key1 not in context!! It should be!!")
        return PromptPosthookResult(continue_processing=True)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        if "key2" in context.state:
            raise ValueError("key2 should not be in ContextPlugin2's context")
        context.state["cp2key1"] = "cp2value1"
        if "globkey1" not in context.global_context.state:
            raise ValueError("globkey1 should be in ContextPlugin2's context")
        context.global_context.state["gcp2globkey1"] = "gcp2globvalue1"
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        if "key2" in context.state:
            raise ValueError("key2 should not be in ContextPlugin2's context")
        if "globkey1" not in context.global_context.state or context.global_context.state["globkey1"] != "globvalue1":
            raise ValueError("globkey1 not in context!! It should be!!")
        context.state["cp2key2"] = "cp2value2"
        context.global_context.state["gcp2globkey2"] = "gcp2globvalue2"
        return ToolPostInvokeResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Plugin hook run after a resource was fetched.

        Args:
            payload: The resource result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the resource result should proceed.
        """
        return ResourcePostFetchResult(continue_processing=True)

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Plugin hook run before a resource was fetched.

        Args:
            payload: The resource result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the resource result should proceed.
        """
        return ResourcePreFetchResult(continue_processing=True)
