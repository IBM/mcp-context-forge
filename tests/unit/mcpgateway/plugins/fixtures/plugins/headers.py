# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/plugins/fixtures/plugins/headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Headers plugin.
"""

import copy
import logging

from mcpgateway.plugins.framework.constants import GATEWAY_METADATA, TOOL_METADATA
from mcpgateway.plugins.framework import (
    PluginContext,
    Plugin,
    HttpHeaderPayload,
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

logger = logging.getLogger("header_plugin")


class HeadersMetaDataPlugin(Plugin):
    """A simple header plugin to read and modify headers."""

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        """
        raise ValueError("Sadly! Prompt prefetch is broken!")

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        raise ValueError("Sadly! Prompt postfetch is broken!")

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        assert TOOL_METADATA in context.global_context.metadata
        tool_meta = context.global_context.metadata[TOOL_METADATA]
        assert tool_meta.original_name == "test_tool"
        assert tool_meta.url.host == "example.com"
        assert tool_meta.integration_type == "REST" or tool_meta.integration_type == "MCP"
        modified_payload = copy.deepcopy(payload)
        if not modified_payload.headers:
            modified_payload.headers = HttpHeaderPayload({})
        if tool_meta.integration_type == "REST":
            assert payload.headers
            assert "Content-Type" in payload.headers
            assert payload.headers["Content-Type"] == "application/json"
        elif tool_meta.integration_type == "MCP":
            assert GATEWAY_METADATA in context.global_context.metadata
            gateway_meta = context.global_context.metadata[GATEWAY_METADATA]
            assert gateway_meta.name == "test_gateway"
            assert gateway_meta.transport == "sse"
            assert gateway_meta.url.host == "example.com"

        modified_payload.headers["User-Agent"] = "Mozilla/5.0"
        modified_payload.headers["Connection"] = "keep-alive"

        return ToolPreInvokeResult(continue_processing=True, modified_payload=modified_payload)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        assert TOOL_METADATA in context.global_context.metadata
        tool_meta = context.global_context.metadata[TOOL_METADATA]
        assert tool_meta.original_name == "test_tool"
        assert tool_meta.url.host == "example.com"
        assert tool_meta.integration_type == "REST" or tool_meta.integration_type == "MCP"
        if tool_meta.integration_type == "MCP":
            assert GATEWAY_METADATA in context.global_context.metadata
            gateway_meta = context.global_context.metadata[GATEWAY_METADATA]
            assert gateway_meta.name == "test_gateway"
            assert gateway_meta.transport == "sse"
            assert gateway_meta.url.host == "example.com"
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


class HeadersPlugin(Plugin):
    """A simple header plugin to read and modify headers."""

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        """
        raise ValueError("Sadly! Prompt prefetch is broken!")

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        raise ValueError("Sadly! Prompt postfetch is broken!")

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        modified_payload = copy.deepcopy(payload)
        if not modified_payload.headers:
            modified_payload.headers = HttpHeaderPayload({})
        else:
            assert payload.headers
            assert "Content-Type" in payload.headers
            assert payload.headers["Content-Type"] == "application/json"
        modified_payload.headers["User-Agent"] = "Mozilla/5.0"
        modified_payload.headers["Connection"] = "keep-alive"
        return ToolPreInvokeResult(continue_processing=True, modified_payload=modified_payload)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        raise ValueError("Sadly! Tool postfetch is broken!")

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
