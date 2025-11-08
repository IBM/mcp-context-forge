# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/fixtures/plugins/agent_plugins.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Test agent plugins for unit testing.
"""

# First-Party
from mcpgateway.common.models import Message, Role, TextContent
from mcpgateway.plugins.framework import (
    Plugin,
    PluginContext,
    AgentPreInvokePayload,
    AgentPreInvokeResult,
    AgentPostInvokePayload,
    AgentPostInvokeResult,
)


class PassThroughAgentPlugin(Plugin):
    """A simple pass-through agent plugin that doesn't modify anything."""

    async def agent_pre_invoke(
        self, payload: AgentPreInvokePayload, context: PluginContext
    ) -> AgentPreInvokeResult:
        """Pass through without modification.

        Args:
            payload: The agent pre-invoke payload.
            context: Contextual information about the hook call.

        Returns:
            The result allowing processing to continue.
        """
        return AgentPreInvokeResult(continue_processing=True)

    async def agent_post_invoke(
        self, payload: AgentPostInvokePayload, context: PluginContext
    ) -> AgentPostInvokeResult:
        """Pass through without modification.

        Args:
            payload: The agent post-invoke payload.
            context: Contextual information about the hook call.

        Returns:
            The result allowing processing to continue.
        """
        return AgentPostInvokeResult(continue_processing=True)


class MessageFilterAgentPlugin(Plugin):
    """An agent plugin that filters messages containing blocked words."""

    async def agent_pre_invoke(
        self, payload: AgentPreInvokePayload, context: PluginContext
    ) -> AgentPreInvokeResult:
        """Filter messages containing blocked words.

        Args:
            payload: The agent pre-invoke payload.
            context: Contextual information about the hook call.

        Returns:
            The result with filtered messages or violation.
        """
        blocked_words = self.config.config.get("blocked_words", [])

        # Filter messages
        filtered_messages = []
        for msg in payload.messages:
            if isinstance(msg.content, TextContent):
                text_lower = msg.content.text.lower()
                if any(word in text_lower for word in blocked_words):
                    # Skip this message
                    continue
            filtered_messages.append(msg)

        # If all messages were blocked, return violation
        if not filtered_messages and payload.messages:
            from mcpgateway.plugins.framework import PluginViolation
            return AgentPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    code="BLOCKED_CONTENT",
                    reason="All messages contained blocked content",
                    description="This is a test of content blocking"
                )
            )

        # Return modified payload if messages were filtered
        if len(filtered_messages) != len(payload.messages):
            modified_payload = AgentPreInvokePayload(
                agent_id=payload.agent_id,
                messages=filtered_messages,
                tools=payload.tools,
                headers=payload.headers,
                model=payload.model,
                system_prompt=payload.system_prompt,
                parameters=payload.parameters
            )
            return AgentPreInvokeResult(modified_payload=modified_payload)

        return AgentPreInvokeResult(continue_processing=True)

    async def agent_post_invoke(
        self, payload: AgentPostInvokePayload, context: PluginContext
    ) -> AgentPostInvokeResult:
        """Filter response messages containing blocked words.

        Args:
            payload: The agent post-invoke payload.
            context: Contextual information about the hook call.

        Returns:
            The result with filtered messages or violation.
        """
        blocked_words = self.config.config.get("blocked_words", [])

        # Filter messages
        filtered_messages = []
        for msg in payload.messages:
            if isinstance(msg.content, TextContent):
                text_lower = msg.content.text.lower()
                if any(word in text_lower for word in blocked_words):
                    # Skip this message
                    continue
            filtered_messages.append(msg)

        # If all messages were blocked, return violation
        if not filtered_messages and payload.messages:
            from mcpgateway.plugins.framework import PluginViolation
            return AgentPostInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    code="BLOCKED_CONTENT",
                    reason="All response messages contained blocked content",
                    description="This is a test of content blocking"
                )
            )

        # Return modified payload if messages were filtered
        if len(filtered_messages) != len(payload.messages):
            modified_payload = AgentPostInvokePayload(
                agent_id=payload.agent_id,
                messages=filtered_messages,
                tool_calls=payload.tool_calls
            )
            return AgentPostInvokeResult(modified_payload=modified_payload)

        return AgentPostInvokeResult(continue_processing=True)


class ContextTrackingAgentPlugin(Plugin):
    """An agent plugin that tracks state in local context."""

    async def agent_pre_invoke(
        self, payload: AgentPreInvokePayload, context: PluginContext
    ) -> AgentPreInvokeResult:
        """Track invocation count in local context.

        Args:
            payload: The agent pre-invoke payload.
            context: Contextual information about the hook call.

        Returns:
            The result with updated local context.
        """
        # Increment counter in local context
        counter = context.metadata.get("invocation_count", 0)
        context.metadata["invocation_count"] = counter + 1
        context.metadata["agent_id"] = payload.agent_id

        return AgentPreInvokeResult(continue_processing=True)

    async def agent_post_invoke(
        self, payload: AgentPostInvokePayload, context: PluginContext
    ) -> AgentPostInvokeResult:
        """Verify context persists from pre-invoke.

        Args:
            payload: The agent post-invoke payload.
            context: Contextual information about the hook call.

        Returns:
            The result after verifying context.
        """
        # Verify context persisted
        counter = context.metadata.get("invocation_count", 0)
        agent_id = context.metadata.get("agent_id", "")

        # Add metadata about the context
        context.metadata["context_verified"] = counter > 0 and agent_id == payload.agent_id

        return AgentPostInvokeResult(continue_processing=True)
