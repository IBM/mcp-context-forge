# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/models/agents.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic models for agent plugins.
This module implements the pydantic models associated with
the base plugin layer including configurations, and contexts.
"""

# Standard
from enum import Enum
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import Field

# First-Party
from mcpgateway.common.models import Message
from mcpgateway.plugins.framework.hooks.http import HttpHeaderPayload
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class AgentHookType(str, Enum):
    """Agent hook points.

    Attributes:
        AGENT_PRE_INVOKE: Before agent invocation.
        AGENT_POST_INVOKE: After agent responds.

    Examples:
        >>> AgentHookType.AGENT_PRE_INVOKE
        <AgentHookType.AGENT_PRE_INVOKE: 'agent_pre_invoke'>
        >>> AgentHookType.AGENT_PRE_INVOKE.value
        'agent_pre_invoke'
        >>> AgentHookType('agent_post_invoke')
        <AgentHookType.AGENT_POST_INVOKE: 'agent_post_invoke'>
        >>> list(AgentHookType)
        [<AgentHookType.AGENT_PRE_INVOKE: 'agent_pre_invoke'>, <AgentHookType.AGENT_POST_INVOKE: 'agent_post_invoke'>]
    """

    AGENT_PRE_INVOKE = "agent_pre_invoke"
    AGENT_POST_INVOKE = "agent_post_invoke"


class AgentPreInvokePayload(PluginPayload):
    """Agent payload for pre-invoke hook.

    Attributes:
        agent_id: The agent identifier (can be modified for routing).
        messages: Conversation messages (can be filtered/transformed).
        tools: Optional list of tools available to agent.
        headers: Optional HTTP headers.
        model: Optional model override.
        system_prompt: Optional system instructions.
        parameters: Optional LLM parameters (temperature, max_tokens, etc.).

    Examples:
        >>> payload = AgentPreInvokePayload(agent_id="agent-123", messages=[])
        >>> payload.agent_id
        'agent-123'
        >>> payload.messages
        []
        >>> payload.tools is None
        True
        >>> from mcpgateway.common.models import Message, Role, TextContent
        >>> msg = Message(role=Role.USER, content=TextContent(type="text", text="Hello"))
        >>> payload = AgentPreInvokePayload(
        ...     agent_id="agent-456",
        ...     messages=[msg],
        ...     tools=["search", "calculator"],
        ...     model="claude-3-5-sonnet-20241022"
        ... )
        >>> payload.tools
        ['search', 'calculator']
        >>> payload.model
        'claude-3-5-sonnet-20241022'
    """

    agent_id: str
    messages: List[Message]
    tools: Optional[List[str]] = None
    headers: Optional[HttpHeaderPayload] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AgentPostInvokePayload(PluginPayload):
    """Agent payload for post-invoke hook.

    Attributes:
        agent_id: The agent identifier.
        messages: Response messages from agent (can be filtered/transformed).
        tool_calls: Optional tool invocations made by agent.

    Examples:
        >>> payload = AgentPostInvokePayload(agent_id="agent-123", messages=[])
        >>> payload.agent_id
        'agent-123'
        >>> payload.messages
        []
        >>> payload.tool_calls is None
        True
        >>> from mcpgateway.common.models import Message, Role, TextContent
        >>> msg = Message(role=Role.ASSISTANT, content=TextContent(type="text", text="Response"))
        >>> payload = AgentPostInvokePayload(
        ...     agent_id="agent-456",
        ...     messages=[msg],
        ...     tool_calls=[{"name": "search", "arguments": {"query": "test"}}]
        ... )
        >>> payload.tool_calls
        [{'name': 'search', 'arguments': {'query': 'test'}}]
    """

    agent_id: str
    messages: List[Message]
    tool_calls: Optional[List[Dict[str, Any]]] = None


AgentPreInvokeResult = PluginResult[AgentPreInvokePayload]
AgentPostInvokeResult = PluginResult[AgentPostInvokePayload]


def _register_agent_hooks() -> None:
    """Register agent hooks in the global registry.

    This is called lazily to avoid circular import issues.
    """
    # Import here to avoid circular dependency at module load time
    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    # Only register if not already registered (idempotent)
    if not registry.is_registered(AgentHookType.AGENT_PRE_INVOKE):
        registry.register_hook(AgentHookType.AGENT_PRE_INVOKE, AgentPreInvokePayload, AgentPreInvokeResult)
        registry.register_hook(AgentHookType.AGENT_POST_INVOKE, AgentPostInvokePayload, AgentPostInvokeResult)


_register_agent_hooks()
