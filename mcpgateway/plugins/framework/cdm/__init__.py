# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/cdm/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Common Data Model (CDM) Package.

Provides a unified message format and zero-copy view adapter for
security policy evaluation across different LLM providers and
agentic frameworks.

Key Components:
- Message: Universal message format (role, content, channel)
- ContentPart: Building block for multimodal content
- MessageView: Zero-copy adapter for policy evaluation
- ViewKind/ViewAction: Enums for view classification

Example Usage:
    >>> from mcpgateway.plugins.framework.cdm import (
    ...     Message, Role, ContentPart, ContentType, ToolCall,
    ...     MessageView, ViewKind
    ... )
    >>>
    >>> # Create a message with a tool call
    >>> tool_call = ToolCall(name="search", arguments={"query": "python"})
    >>> msg = Message(
    ...     role=Role.ASSISTANT,
    ...     content=[ContentPart(type=ContentType.TOOL_CALL, tool_call=tool_call)]
    ... )
    >>>
    >>> # Iterate over message views for policy evaluation
    >>> for view in msg.iter_message_views():
    ...     if view.kind == ViewKind.TOOL_CALL:
    ...         print(f"Tool: {view.name}, Args: {view.args}")
"""

from mcpgateway.plugins.framework.cdm.models import (
    # Enums
    Channel,
    ContentType,
    ResourceType,
    Role,
    StopReason,
    # Content building blocks
    ContentPart,
    ImageSource,
    PromptArgument,
    PromptRequest,
    PromptResult,
    Resource,
    ResourceReference,
    ToolCall,
    ToolResult,
    # Message types
    Conversation,
    Message,
    MessageMetadata,
    OutputConstraint,
    TokenUsage,
)
from mcpgateway.plugins.framework.cdm.view import (
    iter_message_views,
    MessageView,
    ViewAction,
    ViewKind,
)

__all__ = [
    # === Enums ===
    "Channel",
    "ContentType",
    "ResourceType",
    "Role",
    "StopReason",
    "ViewAction",
    "ViewKind",
    # === Content Building Blocks ===
    "ContentPart",
    "ImageSource",
    "PromptArgument",
    "PromptRequest",
    "PromptResult",
    "Resource",
    "ResourceReference",
    "ToolCall",
    "ToolResult",
    # === Message Types ===
    "Conversation",
    "Message",
    "MessageMetadata",
    "OutputConstraint",
    "TokenUsage",
    # === View/Policy Evaluation ===
    "iter_message_views",
    "MessageView",
]
