# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/hooks/tools.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic models for tool hooks.
"""

# Standard
from enum import Enum
from typing import Any, Optional

# Third-Party
from pydantic import Field

# First-Party
from mcpgateway.plugins.framework.hooks.http import HttpHeaderPayload
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class ToolHookType(str, Enum):
    """MCP Forge Gateway hook points.

    Attributes:
        tool_pre_invoke: The tool pre invoke hook.
        tool_post_invoke: The tool post invoke hook.

    Examples:
        >>> ToolHookType.TOOL_PRE_INVOKE
        <ToolHookType.TOOL_PRE_INVOKE: 'tool_pre_invoke'>
        >>> ToolHookType.TOOL_PRE_INVOKE.value
        'tool_pre_invoke'
        >>> ToolHookType('tool_post_invoke')
        <ToolHookType.TOOL_POST_INVOKE: 'tool_post_invoke'>
        >>> list(ToolHookType)
        [<ToolHookType.TOOL_PRE_INVOKE: 'tool_pre_invoke'>, <ToolHookType.TOOL_POST_INVOKE: 'tool_post_invoke'>]
    """

    TOOL_PRE_INVOKE = "tool_pre_invoke"
    TOOL_POST_INVOKE = "tool_post_invoke"


class ToolPreInvokePayload(PluginPayload):
    """A tool payload for a tool pre-invoke hook.

    Args:
        name: The tool name.
        args: The tool arguments for invocation.
        headers: The http pass through headers.

    Examples:
        >>> payload = ToolPreInvokePayload(name="test_tool", args={"input": "data"})
        >>> payload.name
        'test_tool'
        >>> payload.args
        {'input': 'data'}
        >>> payload2 = ToolPreInvokePayload(name="empty")
        >>> payload2.args
        {}
        >>> p = ToolPreInvokePayload(name="calculator", args={"operation": "add", "a": 5, "b": 3})
        >>> p.name
        'calculator'
        >>> p.args["operation"]
        'add'

    """

    name: str
    args: Optional[dict[str, Any]] = Field(default_factory=dict)
    headers: Optional[HttpHeaderPayload] = None


class ToolPostInvokePayload(PluginPayload):
    """A tool payload for a tool post-invoke hook.

    Args:
        name: The tool name.
        result: The tool invocation result.

    Examples:
        >>> payload = ToolPostInvokePayload(name="calculator", result={"result": 8, "status": "success"})
        >>> payload.name
        'calculator'
        >>> payload.result
        {'result': 8, 'status': 'success'}
        >>> p = ToolPostInvokePayload(name="analyzer", result={"confidence": 0.95, "sentiment": "positive"})
        >>> p.name
        'analyzer'
        >>> p.result["confidence"]
        0.95
    """

    name: str
    result: Any


ToolPreInvokeResult = PluginResult[ToolPreInvokePayload]
ToolPostInvokeResult = PluginResult[ToolPostInvokePayload]


def _register_tool_hooks() -> None:
    """Register Tool hooks in the global registry.

    This is called lazily to avoid circular import issues.
    """
    # Import here to avoid circular dependency at module load time
    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    # Only register if not already registered (idempotent)
    if not registry.is_registered(ToolHookType.TOOL_PRE_INVOKE):
        registry.register_hook(ToolHookType.TOOL_PRE_INVOKE, ToolPreInvokePayload, ToolPreInvokeResult)
        registry.register_hook(ToolHookType.TOOL_POST_INVOKE, ToolPostInvokePayload, ToolPostInvokeResult)


_register_tool_hooks()
