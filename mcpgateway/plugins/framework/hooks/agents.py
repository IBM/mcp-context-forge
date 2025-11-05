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

    def model_dump_pb(self):
        """Convert to protobuf AgentPreInvokePayload message.

        Returns:
            agents_pb2.AgentPreInvokePayload: Protobuf message.
        """
        # Third-Party
        from google.protobuf import json_format, struct_pb2

        # First-Party
        from mcpgateway.plugins.framework.generated import agents_pb2

        # Convert messages list to repeated Struct
        messages_pb = []
        for msg in self.messages:
            msg_struct = struct_pb2.Struct()
            msg_dict = msg.model_dump(mode="json")
            json_format.ParseDict(msg_dict, msg_struct)
            messages_pb.append(msg_struct)

        # Convert parameters dict to Struct
        parameters_struct = struct_pb2.Struct()
        if self.parameters:
            json_format.ParseDict(self.parameters, parameters_struct)

        # Convert headers if present
        headers_pb = None
        if self.headers:
            # First-Party
            from mcpgateway.plugins.framework.generated import types_pb2

            # HttpHeaderPayload is a RootModel, extract the root dict
            headers_dict = self.headers.root if hasattr(self.headers, "root") else self.headers
            headers_pb = types_pb2.HttpHeaders(headers=headers_dict)

        return agents_pb2.AgentPreInvokePayload(
            agent_id=self.agent_id,
            messages=messages_pb,
            tools=self.tools or [],
            headers=headers_pb,
            model=self.model or "",
            system_prompt=self.system_prompt or "",
            parameters=parameters_struct,
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "AgentPreInvokePayload":
        """Create from protobuf AgentPreInvokePayload message.

        Args:
            proto: agents_pb2.AgentPreInvokePayload protobuf message.

        Returns:
            AgentPreInvokePayload: Pydantic model instance.
        """
        # Third-Party
        from google.protobuf import json_format

        # Convert repeated Struct to list of Message
        messages = []
        for msg_struct in proto.messages:
            msg_dict = json_format.MessageToDict(msg_struct)
            messages.append(Message.model_validate(msg_dict))

        # Convert Struct to dict
        parameters = {}
        if proto.HasField("parameters"):
            parameters = json_format.MessageToDict(proto.parameters)

        # Convert headers if present
        headers = None
        if proto.HasField("headers"):
            # First-Party
            from mcpgateway.plugins.framework.hooks.http import HttpHeaderPayload

            headers = HttpHeaderPayload(dict(proto.headers.headers))

        return cls(
            agent_id=proto.agent_id,
            messages=messages,
            tools=list(proto.tools) if proto.tools else None,
            headers=headers,
            model=proto.model if proto.model else None,
            system_prompt=proto.system_prompt if proto.system_prompt else None,
            parameters=parameters,
        )


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

    def model_dump_pb(self):
        """Convert to protobuf AgentPostInvokePayload message.

        Returns:
            agents_pb2.AgentPostInvokePayload: Protobuf message.
        """
        # Third-Party
        from google.protobuf import json_format, struct_pb2

        # First-Party
        from mcpgateway.plugins.framework.generated import agents_pb2

        # Convert messages list to repeated Struct
        messages_pb = []
        for msg in self.messages:
            msg_struct = struct_pb2.Struct()
            msg_dict = msg.model_dump(mode="json")
            json_format.ParseDict(msg_dict, msg_struct)
            messages_pb.append(msg_struct)

        # Convert tool_calls list to repeated Struct
        tool_calls_pb = []
        if self.tool_calls:
            for tool_call in self.tool_calls:
                tool_call_struct = struct_pb2.Struct()
                json_format.ParseDict(tool_call, tool_call_struct)
                tool_calls_pb.append(tool_call_struct)

        return agents_pb2.AgentPostInvokePayload(
            agent_id=self.agent_id,
            messages=messages_pb,
            tool_calls=tool_calls_pb,
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "AgentPostInvokePayload":
        """Create from protobuf AgentPostInvokePayload message.

        Args:
            proto: agents_pb2.AgentPostInvokePayload protobuf message.

        Returns:
            AgentPostInvokePayload: Pydantic model instance.
        """
        # Third-Party
        from google.protobuf import json_format

        # Convert repeated Struct to list of Message
        messages = []
        for msg_struct in proto.messages:
            msg_dict = json_format.MessageToDict(msg_struct)
            messages.append(Message.model_validate(msg_dict))

        # Convert repeated Struct to list of tool calls
        tool_calls = None
        if proto.tool_calls:
            tool_calls = []
            for tool_call_struct in proto.tool_calls:
                tool_call_dict = json_format.MessageToDict(tool_call_struct)
                tool_calls.append(tool_call_dict)

        return cls(
            agent_id=proto.agent_id,
            messages=messages,
            tool_calls=tool_calls,
        )


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
