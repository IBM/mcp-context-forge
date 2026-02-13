# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/policy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Concrete hook payload policies for the gateway.

This module defines which payload fields plugins are allowed to modify
for each hook type.  The policies are injected into the PluginManager
at initialization time.

Examples:
    >>> from mcpgateway.plugins.policy import HOOK_PAYLOAD_POLICIES
    >>> "name" in HOOK_PAYLOAD_POLICIES["tool_pre_invoke"].writable_fields
    True
    >>> "result" in HOOK_PAYLOAD_POLICIES["tool_post_invoke"].writable_fields
    True
"""

# First-Party
from mcpgateway.plugins.framework.hooks.policies import HookPayloadPolicy

HOOK_PAYLOAD_POLICIES: dict[str, HookPayloadPolicy] = {
    # Tools
    "tool_pre_invoke": HookPayloadPolicy(writable_fields=frozenset({"name", "args", "headers"})),
    "tool_post_invoke": HookPayloadPolicy(writable_fields=frozenset({"result"})),
    # Prompts
    "prompt_pre_fetch": HookPayloadPolicy(writable_fields=frozenset({"args"})),
    "prompt_post_fetch": HookPayloadPolicy(writable_fields=frozenset({"result"})),
    # Resources
    "resource_pre_fetch": HookPayloadPolicy(writable_fields=frozenset({"uri", "metadata"})),
    "resource_post_fetch": HookPayloadPolicy(writable_fields=frozenset({"content"})),
    # Agents
    "agent_pre_invoke": HookPayloadPolicy(writable_fields=frozenset({"messages", "tools", "model", "system_prompt", "parameters", "headers"})),
    "agent_post_invoke": HookPayloadPolicy(writable_fields=frozenset({"messages", "tool_calls"})),
}
