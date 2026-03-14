# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/hooks/a2a_gateway.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Pydantic models for A2A gateway plugin hooks.
Implements hook types and payloads for the native A2A protocol gateway.
"""

# Standard
from enum import Enum
from typing import Any, Dict, Optional

# Third-Party
from pydantic import Field

# First-Party
from mcpgateway.plugins.framework.hooks.http import HttpHeaderPayload
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class A2AGatewayHookType(str, Enum):
    """A2A gateway hook points.

    Attributes:
        A2A_GATEWAY_PRE_INVOKE: Before forwarding a JSON-RPC request to downstream agent.
        A2A_GATEWAY_POST_INVOKE: After receiving a response from downstream agent.

    Examples:
        >>> A2AGatewayHookType.A2A_GATEWAY_PRE_INVOKE
        <A2AGatewayHookType.A2A_GATEWAY_PRE_INVOKE: 'a2a_gateway_pre_invoke'>
        >>> A2AGatewayHookType.A2A_GATEWAY_POST_INVOKE.value
        'a2a_gateway_post_invoke'
    """

    A2A_GATEWAY_PRE_INVOKE = "a2a_gateway_pre_invoke"
    A2A_GATEWAY_POST_INVOKE = "a2a_gateway_post_invoke"


class A2AGatewayPreInvokePayload(PluginPayload):
    """Payload for A2A gateway pre-invoke hook.

    Attributes:
        agent_id: The target agent's ID.
        method: JSON-RPC method name (e.g., "message/send").
        params: JSON-RPC params from the request body.
        headers: Optional HTTP headers being sent to downstream agent.
        user_email: Email of the requesting user.
        user_id: ID of the requesting user.

    Examples:
        >>> payload = A2AGatewayPreInvokePayload(agent_id="echo", method="message/send", params={})
        >>> payload.agent_id
        'echo'
    """

    agent_id: str
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)
    headers: Optional[HttpHeaderPayload] = None
    user_email: Optional[str] = None
    user_id: Optional[str] = None


class A2AGatewayPostInvokePayload(PluginPayload):
    """Payload for A2A gateway post-invoke hook.

    Attributes:
        agent_id: The target agent's ID.
        method: JSON-RPC method name.
        result: The JSON-RPC response from downstream agent.
        duration_ms: Request duration in milliseconds.
        is_error: Whether the response contains a JSON-RPC error.

    Examples:
        >>> payload = A2AGatewayPostInvokePayload(agent_id="echo", method="message/send", result={})
        >>> payload.is_error
        False
    """

    agent_id: str
    method: str
    result: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[float] = None
    is_error: bool = False


A2AGatewayPreInvokeResult = PluginResult[A2AGatewayPreInvokePayload]
A2AGatewayPostInvokeResult = PluginResult[A2AGatewayPostInvokePayload]


def _register_a2a_gateway_hooks() -> None:
    """Register A2A gateway hooks in the global registry.

    Called lazily to avoid circular import issues.
    """
    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    if not registry.is_registered(A2AGatewayHookType.A2A_GATEWAY_PRE_INVOKE):
        registry.register_hook(A2AGatewayHookType.A2A_GATEWAY_PRE_INVOKE, A2AGatewayPreInvokePayload, A2AGatewayPreInvokeResult)
        registry.register_hook(A2AGatewayHookType.A2A_GATEWAY_POST_INVOKE, A2AGatewayPostInvokePayload, A2AGatewayPostInvokeResult)


_register_a2a_gateway_hooks()
