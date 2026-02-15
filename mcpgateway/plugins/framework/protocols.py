# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/protocols.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Protocol definitions for types that cross the gateway-framework boundary.

These replace concrete imports of Message and PromptResult from
mcpgateway.common.models, allowing the framework to express structural
contracts without creating a dependency on the outer package.

Examples:
    >>> from mcpgateway.plugins.framework.protocols import MessageLike, PromptResultLike
    >>> import typing
    >>> typing.runtime_checkable(MessageLike)  # Already decorated
    <class 'mcpgateway.plugins.framework.protocols.MessageLike'>
"""

# Standard
from typing import Any, Optional, Protocol, runtime_checkable, Sequence


@runtime_checkable
class MessageLike(Protocol):
    """Structural contract for message objects.

    The framework never instantiates Message directly -- it receives
    them from the service layer.  Any object with ``role`` and
    ``content`` attributes satisfies this protocol structurally.

    Attributes:
        role: str or Role enum indicating the message sender.
        content: TextContent, ImageContent, or other content type.

    Examples:
        >>> from types import SimpleNamespace
        >>> msg = SimpleNamespace(role="user", content="hello")
        >>> isinstance(msg, MessageLike)
        True
    """

    role: str
    content: Any


@runtime_checkable
class PromptResultLike(Protocol):
    """Structural contract for prompt result objects.

    The framework never instantiates PromptResult directly -- it
    receives them from the service layer.  Any object with
    ``messages`` and ``description`` attributes satisfies this
    protocol structurally.

    Attributes:
        messages: Sequence of MessageLike objects.
        description: Optional description of the rendered result.

    Examples:
        >>> from types import SimpleNamespace
        >>> result = SimpleNamespace(messages=[], description=None)
        >>> isinstance(result, PromptResultLike)
        True
    """

    messages: Sequence[MessageLike]
    description: Optional[str]
