# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/agent/base.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Base plugin for agents.
This module implements the base plugin object for agent hooks.
It supports pre and post hooks for AI safety, security and business processing
for agent invocations:
- agent_pre_invoke: Before sending messages to agent
- agent_post_invoke: After receiving agent response
"""

# First-Party
from mcpgateway.plugins.agent.models import (
    AgentHookType,
    AgentPostInvokePayload,
    AgentPostInvokeResult,
    AgentPreInvokePayload,
    AgentPreInvokeResult,
)
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig, PluginContext


def _register_agent_hooks():
    """Register agent hooks in the global registry.

    This is called lazily to avoid circular import issues.
    """
    # Import here to avoid circular dependency at module load time
    # First-Party
    from mcpgateway.plugins.framework.hook_registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    # Only register if not already registered (idempotent)
    if not registry.is_registered(AgentHookType.AGENT_PRE_INVOKE):
        registry.register_hook(AgentHookType.AGENT_PRE_INVOKE, AgentPreInvokePayload, AgentPreInvokeResult)
        registry.register_hook(AgentHookType.AGENT_POST_INVOKE, AgentPostInvokePayload, AgentPostInvokeResult)


class AgentPlugin(Plugin):
    """Base agent plugin for pre/post processing of agent invocations.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginConfig, PluginMode
        >>> from mcpgateway.plugins.agent import AgentHookType
        >>> config = PluginConfig(
        ...     name="test_agent_plugin",
        ...     description="Test agent plugin",
        ...     author="test",
        ...     kind="mcpgateway.plugins.agent.AgentPlugin",
        ...     version="1.0.0",
        ...     hooks=[AgentHookType.AGENT_PRE_INVOKE],
        ...     tags=["test"],
        ...     mode=PluginMode.ENFORCE,
        ...     priority=50
        ... )
        >>> plugin = AgentPlugin(config)
        >>> plugin.name
        'test_agent_plugin'
        >>> plugin.priority
        50
        >>> plugin.mode
        <PluginMode.ENFORCE: 'enforce'>
        >>> AgentHookType.AGENT_PRE_INVOKE in plugin.hooks
        True
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize an agent plugin with configuration.

        Args:
            config: The plugin configuration

        Examples:
            >>> from mcpgateway.plugins.framework import PluginConfig
            >>> from mcpgateway.plugins.agent import AgentHookType
            >>> config = PluginConfig(
            ...     name="simple_agent_plugin",
            ...     description="Simple test",
            ...     author="test",
            ...     kind="test.AgentPlugin",
            ...     version="1.0.0",
            ...     hooks=[AgentHookType.AGENT_POST_INVOKE],
            ...     tags=["simple"]
            ... )
            >>> plugin = AgentPlugin(config)
            >>> plugin._config.name
            'simple_agent_plugin'
        """
        super().__init__(config)
        _register_agent_hooks()

    async def agent_pre_invoke(self, payload: AgentPreInvokePayload, context: PluginContext) -> AgentPreInvokeResult:
        """Hook before agent invocation.

        Args:
            payload: Agent pre-invoke payload.
            context: Plugin execution context.

        Raises:
            NotImplementedError: needs to be implemented by sub class.

        Examples:
            >>> import asyncio
            >>> from mcpgateway.plugins.framework import PluginConfig, GlobalContext, PluginContext
            >>> from mcpgateway.plugins.agent import AgentHookType, AgentPreInvokePayload
            >>> config = PluginConfig(
            ...     name="test_plugin",
            ...     description="Test",
            ...     author="test",
            ...     kind="test.Plugin",
            ...     version="1.0.0",
            ...     hooks=[AgentHookType.AGENT_PRE_INVOKE]
            ... )
            >>> plugin = AgentPlugin(config)
            >>> payload = AgentPreInvokePayload(agent_id="agent-123", messages=[])
            >>> ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
            >>> result = asyncio.run(plugin.agent_pre_invoke(payload, ctx))
            >>> result.continue_processing
            True
        """
        raise NotImplementedError(
            f"""'agent_pre_invoke' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )

    async def agent_post_invoke(self, payload: AgentPostInvokePayload, context: PluginContext) -> AgentPostInvokeResult:
        """Hook after agent responds.

        Args:
            payload: Agent post-invoke payload.
            context: Plugin execution context.

        Raises:
            NotImplementedError: needs to be implemented by sub class.

        Examples:
            >>> import asyncio
            >>> from mcpgateway.plugins.framework import PluginConfig, GlobalContext, PluginContext
            >>> from mcpgateway.plugins.agent import AgentHookType, AgentPostInvokePayload
            >>> config = PluginConfig(
            ...     name="test_plugin",
            ...     description="Test",
            ...     author="test",
            ...     kind="test.Plugin",
            ...     version="1.0.0",
            ...     hooks=[AgentHookType.AGENT_POST_INVOKE]
            ... )
            >>> plugin = AgentPlugin(config)
            >>> payload = AgentPostInvokePayload(agent_id="agent-123", messages=[])
            >>> ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
            >>> result = asyncio.run(plugin.agent_post_invoke(payload, ctx))
            >>> result.continue_processing
            True
        """
        raise NotImplementedError(
            f"""'agent_post_invoke' not implemented for plugin {self._config.name}
                                    of plugin type {type(self)}
                                   """
        )
