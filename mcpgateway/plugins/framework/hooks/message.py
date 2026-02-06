# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/hooks/message.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Hook definitions for CDM Message evaluation.

This hook provides a unified entry point for policy evaluation on messages
flowing through the system. The Message itself serves as the payload,
and plugins can use MessageView to iterate over content for granular
policy checks.
"""

# Standard
from enum import Enum

# First-Party
from mcpgateway.plugins.framework.cdm.models import Message
from mcpgateway.plugins.framework.models import PluginResult


class MessageHookType(str, Enum):
    """Message hook points.

    Attributes:
        MESSAGE_EVALUATE: Evaluate a message for policy decisions.

    Examples:
        >>> MessageHookType.MESSAGE_EVALUATE
        <MessageHookType.MESSAGE_EVALUATE: 'message_evaluate'>
        >>> MessageHookType.MESSAGE_EVALUATE.value
        'message_evaluate'
    """

    MESSAGE_EVALUATE = "message_evaluate"


# Message IS the payload - it already inherits from BaseModel (PluginPayload)
MessagePayload = Message

# Result type for message evaluation
MessageResult = PluginResult[Message]


def _register_message_hooks() -> None:
    """Register message hooks in the global registry.

    This is called lazily to avoid circular import issues.
    """
    # Import here to avoid circular dependency at module load time
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    # Only register if not already registered (idempotent)
    if not registry.is_registered(MessageHookType.MESSAGE_EVALUATE):
        registry.register_hook(MessageHookType.MESSAGE_EVALUATE, MessagePayload, MessageResult)


_register_message_hooks()
