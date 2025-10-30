# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/mcp/entities/base.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Base plugin implementation.
This module implements the base plugin object.
It supports pre and post hooks AI safety, security and business processing
for the following locations in the server:
server_pre_register / server_post_register - for virtual server verification
tool_pre_invoke / tool_post_invoke - for guardrails
prompt_pre_fetch / prompt_post_fetch - for prompt filtering
resource_pre_fetch / resource_post_fetch - for content filtering
auth_pre_check / auth_post_check - for custom auth logic
federation_pre_sync / federation_post_sync - for gateway federation
"""

# Standard

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig, PluginContext
from mcpgateway.plugins.mcp.entities.models import (
    HookType,
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


def _register_mcp_hooks():
    """Register MCP hooks in the global registry.

    This is called lazily to avoid circular import issues.
    """
    # Import here to avoid circular dependency at module load time
    # First-Party
    from mcpgateway.plugins.framework.hook_registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    # Only register if not already registered (idempotent)
    if not registry.is_registered(HookType.PROMPT_PRE_FETCH):
        registry.register_hook(HookType.PROMPT_PRE_FETCH, PromptPrehookPayload, PromptPrehookResult)
        registry.register_hook(HookType.PROMPT_POST_FETCH, PromptPosthookPayload, PromptPosthookResult)
        registry.register_hook(HookType.RESOURCE_PRE_FETCH, ResourcePreFetchPayload, ResourcePreFetchResult)
        registry.register_hook(HookType.RESOURCE_POST_FETCH, ResourcePostFetchPayload, ResourcePostFetchResult)
        registry.register_hook(HookType.TOOL_PRE_INVOKE, ToolPreInvokePayload, ToolPreInvokeResult)
        registry.register_hook(HookType.TOOL_POST_INVOKE, ToolPostInvokePayload, ToolPostInvokeResult)


class MCPPlugin(Plugin):
    """Base mcp plugin object for pre/post processing of inputs and outputs at various locations throughout the server.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginConfig, PluginMode
        >>> from mcpgateway.plugins.mcp.entities import HookType
        >>> config = PluginConfig(
        ...     name="test_plugin",
        ...     description="Test plugin",
        ...     author="test",
        ...     kind="mcpgateway.plugins.framework.Plugin",
        ...     version="1.0.0",
        ...     hooks=[HookType.PROMPT_PRE_FETCH],
        ...     tags=["test"],
        ...     mode=PluginMode.ENFORCE,
        ...     priority=50
        ... )
        >>> plugin = MCPPlugin(config)
        >>> plugin.name
        'test_plugin'
        >>> plugin.priority
        50
        >>> plugin.mode
        <PluginMode.ENFORCE: 'enforce'>
        >>> HookType.PROMPT_PRE_FETCH in plugin.hooks
        True
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize a plugin with a configuration and context.

        Args:
            config: The plugin configuration

        Examples:
            >>> from mcpgateway.plugins.framework import PluginConfig
            >>> from mcpgateway.plugins.mcp.entities import HookType
            >>> config = PluginConfig(
            ...     name="simple_plugin",
            ...     description="Simple test",
            ...     author="test",
            ...     kind="test.Plugin",
            ...     version="1.0.0",
            ...     hooks=[HookType.PROMPT_POST_FETCH],
            ...     tags=["simple"]
            ... )
            >>> plugin = MCPPlugin(config)
            >>> plugin._config.name
            'simple_plugin'
        """
        super().__init__(config)

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call. Including why it was called.

        Raises:
            NotImplementedError: needs to be implemented by sub class.
        """
        raise NotImplementedError(
            f"""'prompt_pre_fetch' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Raises:
            NotImplementedError: needs to be implemented by sub class.
        """
        raise NotImplementedError(
            f"""'prompt_post_fetch' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Raises:
            NotImplementedError: needs to be implemented by sub class.
        """
        raise NotImplementedError(
            f"""'tool_pre_invoke' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Raises:
            NotImplementedError: needs to be implemented by sub class.
        """
        raise NotImplementedError(
            f"""'tool_post_invoke' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Plugin hook run before a resource is fetched.

        Args:
            payload: The resource payload to be analyzed.
            context: Contextual information about the hook call.

        Raises:
            NotImplementedError: needs to be implemented by sub class.
        """
        raise NotImplementedError(
            f"""'resource_pre_fetch' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Plugin hook run after a resource is fetched.

        Args:
            payload: The resource content payload to be analyzed.
            context: Contextual information about the hook call.

        Raises:
            NotImplementedError: needs to be implemented by sub class.
        """
        raise NotImplementedError(
            f"""'resource_post_fetch' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )


# Register MCP hooks when this module is imported
_register_mcp_hooks()
