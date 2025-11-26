# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Mihai Criveti

Utility module for plugins layer.
This module implements the utility functions associated with
plugins.
"""

# Standard
from functools import cache
import importlib
from types import ModuleType
from typing import Any, Optional

# First-Party
from mcpgateway.plugins.framework.models import GlobalContext, PluginCondition

# from mcpgateway.plugins.mcp.entities import (
#     PromptPosthookPayload,
#     PromptPrehookPayload,
#     ResourcePostFetchPayload,
#     ResourcePreFetchPayload,
#     ToolPostInvokePayload,
#     ToolPreInvokePayload,
# )


@cache  # noqa
def import_module(mod_name: str) -> ModuleType:
    """Import a module.

    Args:
        mod_name: fully qualified module name

    Returns:
        A module.

    Examples:
        >>> import sys
        >>> mod = import_module('sys')
        >>> mod is sys
        True
        >>> os_mod = import_module('os')
        >>> hasattr(os_mod, 'path')
        True
    """
    return importlib.import_module(mod_name)


def parse_class_name(name: str) -> tuple[str, str]:
    """Parse a class name into its constituents.

    Args:
        name: the qualified class name

    Returns:
        A pair containing the qualified class prefix and the class name

    Examples:
        >>> parse_class_name('module.submodule.ClassName')
        ('module.submodule', 'ClassName')
        >>> parse_class_name('SimpleClass')
        ('', 'SimpleClass')
        >>> parse_class_name('package.Class')
        ('package', 'Class')
    """
    clslist = name.rsplit(".", 1)
    if len(clslist) == 2:
        return (clslist[0], clslist[1])
    return ("", name)


def matches(condition: PluginCondition, context: GlobalContext) -> bool:
    """Check if conditions match the current context.

    Args:
        condition: the conditions on the plugin that are required for execution.
        context: the global context.

    Returns:
        True if the plugin matches criteria.

    Examples:
        >>> from mcpgateway.plugins.framework import GlobalContext, PluginCondition
        >>> cond = PluginCondition(server_ids={"srv1", "srv2"})
        >>> ctx = GlobalContext(request_id="req1", server_id="srv1")
        >>> matches(cond, ctx)
        True
        >>> ctx2 = GlobalContext(request_id="req2", server_id="srv3")
        >>> matches(cond, ctx2)
        False
        >>> cond2 = PluginCondition(user_patterns=["admin"])
        >>> ctx3 = GlobalContext(request_id="req3", user="admin_user")
        >>> matches(cond2, ctx3)
        True
    """
    # Check server ID
    if condition.server_ids and context.server_id not in condition.server_ids:
        return False

    # Check tenant ID
    if condition.tenant_ids and context.tenant_id not in condition.tenant_ids:
        return False

    # Check user patterns (simple contains check, could be regex)
    if condition.user_patterns and context.user:
        if not any(pattern in context.user for pattern in condition.user_patterns):
            return False
    return True


def get_matchable_value(payload: Any, hook_type: str) -> Optional[str]:
    """Extract the matchable value from a payload based on hook type.

    This function maps hook types to their corresponding payload attributes
    that should be used for conditional matching.

    Args:
        payload: The payload object (e.g., ToolPreInvokePayload, AgentPreInvokePayload).
        hook_type: The hook type identifier.

    Returns:
        The matchable value (e.g., tool name, agent ID, resource URI) or None.

    Examples:
        >>> from mcpgateway.plugins.framework import GlobalContext
        >>> from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        >>> payload = ToolPreInvokePayload(name="calculator", args={})
        >>> get_matchable_value(payload, "tool_pre_invoke")
        'calculator'
        >>> get_matchable_value(payload, "unknown_hook")
    """
    # Mapping: hook_type -> payload attribute name
    field_map = {
        "tool_pre_invoke": "name",
        "tool_post_invoke": "name",
        "prompt_pre_fetch": "prompt_id",
        "prompt_post_fetch": "prompt_id",
        "resource_pre_fetch": "uri",
        "resource_post_fetch": "uri",
        "agent_pre_invoke": "agent_id",
        "agent_post_invoke": "agent_id",
    }

    field_name = field_map.get(hook_type)
    if field_name:
        return getattr(payload, field_name, None)
    return None


def payload_matches(
    payload: Any,
    hook_type: str,
    conditions: list[PluginCondition],
    context: GlobalContext,
) -> bool:
    """Check if a payload matches any of the plugin conditions.

    This function provides generic conditional matching for all hook types.
    It checks both GlobalContext conditions (via matches()) and payload-specific
    conditions (tools, prompts, resources, agents).

    Args:
        payload: The payload object.
        hook_type: The hook type identifier.
        conditions: List of conditions to check against.
        context: The global context.

    Returns:
        True if the payload matches any condition or if no conditions are specified.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginCondition, GlobalContext
        >>> from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        >>> payload = ToolPreInvokePayload(name="calculator", args={})
        >>> cond = PluginCondition(tools={"calculator"})
        >>> ctx = GlobalContext(request_id="req1")
        >>> payload_matches(payload, "tool_pre_invoke", [cond], ctx)
        True
        >>> cond2 = PluginCondition(tools={"other_tool"})
        >>> payload_matches(payload, "tool_pre_invoke", [cond2], ctx)
        False
        >>> payload_matches(payload, "tool_pre_invoke", [], ctx)
        True
    """
    # Mapping: hook_type -> PluginCondition attribute name
    condition_attr_map = {
        "tool_pre_invoke": "tools",
        "tool_post_invoke": "tools",
        "prompt_pre_fetch": "prompts",
        "prompt_post_fetch": "prompts",
        "resource_pre_fetch": "resources",
        "resource_post_fetch": "resources",
        "agent_pre_invoke": "agents",
        "agent_post_invoke": "agents",
    }

    # If no conditions, match everything
    if not conditions:
        return True

    # Check each condition (OR logic between conditions)
    for condition in conditions:
        # First check GlobalContext conditions
        if not matches(condition, context):
            continue

        # Then check payload-specific conditions
        condition_attr = condition_attr_map.get(hook_type)
        if condition_attr:
            condition_set = getattr(condition, condition_attr, None)
            if condition_set:
                # Extract the matchable value from the payload
                payload_value = get_matchable_value(payload, hook_type)
                if payload_value and payload_value not in condition_set:
                    # Payload value doesn't match this condition's set
                    continue

        # If we get here, this condition matched
        return True

    # No conditions matched
    return False


# def pre_prompt_matches(payload: PromptPrehookPayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
#     """Check for a match on pre-prompt hooks.

#     Args:
#         payload: the prompt prehook payload.
#         conditions: the conditions on the plugin that are required for execution.
#         context: the global context.

#     Returns:
#         True if the plugin matches criteria.

#     Examples:
#         >>> from mcpgateway.plugins.framework import PluginCondition, GlobalContext
#         >>> from mcpgateway.plugins.mcp.entities import PromptPrehookPayload
#         >>> payload = PromptPrehookPayload(name="greeting", args={})
#         >>> cond = PluginCondition(prompts={"greeting"})
#         >>> ctx = GlobalContext(request_id="req1")
#         >>> pre_prompt_matches(payload, [cond], ctx)
#         True
#         >>> payload2 = PromptPrehookPayload(name="other", args={})
#         >>> pre_prompt_matches(payload2, [cond], ctx)
#         False
#     """
#     current_result = True
#     for index, condition in enumerate(conditions):
#         if not matches(condition, context):
#             current_result = False

#         if condition.prompts and payload.name not in condition.prompts:
#             current_result = False
#         if current_result:
#             return True
#         if index < len(conditions) - 1:
#             current_result = True
#     return current_result


# def post_prompt_matches(payload: PromptPosthookPayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
#     """Check for a match on pre-prompt hooks.

#     Args:
#         payload: the prompt posthook payload.
#         conditions: the conditions on the plugin that are required for execution.
#         context: the global context.

#     Returns:
#         True if the plugin matches criteria.
#     """
#     current_result = True
#     for index, condition in enumerate(conditions):
#         if not matches(condition, context):
#             current_result = False

#         if condition.prompts and payload.name not in condition.prompts:
#             current_result = False
#         if current_result:
#             return True
#         if index < len(conditions) - 1:
#             current_result = True
#     return current_result


# def pre_tool_matches(payload: ToolPreInvokePayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
#     """Check for a match on pre-tool hooks.

#     Args:
#         payload: the tool pre-invoke payload.
#         conditions: the conditions on the plugin that are required for execution.
#         context: the global context.

#     Returns:
#         True if the plugin matches criteria.

#     Examples:
#         >>> from mcpgateway.plugins.framework import PluginCondition, GlobalContext
#         >>> from mcpgateway.plugins.mcp.entities import ToolPreInvokePayload
#         >>> payload = ToolPreInvokePayload(name="calculator", args={})
#         >>> cond = PluginCondition(tools={"calculator"})
#         >>> ctx = GlobalContext(request_id="req1")
#         >>> pre_tool_matches(payload, [cond], ctx)
#         True
#         >>> payload2 = ToolPreInvokePayload(name="other", args={})
#         >>> pre_tool_matches(payload2, [cond], ctx)
#         False
#     """
#     current_result = True
#     for index, condition in enumerate(conditions):
#         if not matches(condition, context):
#             current_result = False

#         if condition.tools and payload.name not in condition.tools:
#             current_result = False
#         if current_result:
#             return True
#         if index < len(conditions) - 1:
#             current_result = True
#     return current_result


# def post_tool_matches(payload: ToolPostInvokePayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
#     """Check for a match on post-tool hooks.

#     Args:
#         payload: the tool post-invoke payload.
#         conditions: the conditions on the plugin that are required for execution.
#         context: the global context.

#     Returns:
#         True if the plugin matches criteria.

#     Examples:
#         >>> from mcpgateway.plugins.framework import PluginCondition, GlobalContext
#         >>> from mcpgateway.plugins.mcp.entities import ToolPostInvokePayload
#         >>> payload = ToolPostInvokePayload(name="calculator", result={"result": 8})
#         >>> cond = PluginCondition(tools={"calculator"})
#         >>> ctx = GlobalContext(request_id="req1")
#         >>> post_tool_matches(payload, [cond], ctx)
#         True
#         >>> payload2 = ToolPostInvokePayload(name="other", result={"result": 8})
#         >>> post_tool_matches(payload2, [cond], ctx)
#         False
#     """
#     current_result = True
#     for index, condition in enumerate(conditions):
#         if not matches(condition, context):
#             current_result = False

#         if condition.tools and payload.name not in condition.tools:
#             current_result = False
#         if current_result:
#             return True
#         if index < len(conditions) - 1:
#             current_result = True
#     return current_result


# def pre_resource_matches(payload: ResourcePreFetchPayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
#     """Check for a match on pre-resource hooks.

#     Args:
#         payload: the resource pre-fetch payload.
#         conditions: the conditions on the plugin that are required for execution.
#         context: the global context.

#     Returns:
#         True if the plugin matches criteria.

#     Examples:
#         >>> from mcpgateway.plugins.framework import PluginCondition, GlobalContext
#         >>> from mcpgateway.plugins.mcp.entities import ResourcePreFetchPayload
#         >>> payload = ResourcePreFetchPayload(uri="file:///data.txt")
#         >>> cond = PluginCondition(resources={"file:///data.txt"})
#         >>> ctx = GlobalContext(request_id="req1")
#         >>> pre_resource_matches(payload, [cond], ctx)
#         True
#         >>> payload2 = ResourcePreFetchPayload(uri="http://api/other")
#         >>> pre_resource_matches(payload2, [cond], ctx)
#         False
#     """
#     current_result = True
#     for index, condition in enumerate(conditions):
#         if not matches(condition, context):
#             current_result = False

#         if condition.resources and payload.uri not in condition.resources:
#             current_result = False
#         if current_result:
#             return True
#         if index < len(conditions) - 1:
#             current_result = True
#     return current_result


# def post_resource_matches(payload: ResourcePostFetchPayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
#     """Check for a match on post-resource hooks.

#     Args:
#         payload: the resource post-fetch payload.
#         conditions: the conditions on the plugin that are required for execution.
#         context: the global context.

#     Returns:
#         True if the plugin matches criteria.

#     Examples:
#         >>> from mcpgateway.plugins.framework import PluginCondition, GlobalContext
#         >>> from mcpgateway.plugins.mcp.entities import ResourcePostFetchPayload, ResourceContent
#         >>> content = ResourceContent(type="resource", uri="file:///data.txt", text="Test")
#         >>> payload = ResourcePostFetchPayload(uri="file:///data.txt", content=content)
#         >>> cond = PluginCondition(resources={"file:///data.txt"})
#         >>> ctx = GlobalContext(request_id="req1")
#         >>> post_resource_matches(payload, [cond], ctx)
#         True
#         >>> payload2 = ResourcePostFetchPayload(uri="http://api/other", content=content)
#         >>> post_resource_matches(payload2, [cond], ctx)
#         False
#     """
#     current_result = True
#     for index, condition in enumerate(conditions):
#         if not matches(condition, context):
#             current_result = False

#         if condition.resources and payload.uri not in condition.resources:
#             current_result = False
#         if current_result:
#             return True
#         if index < len(conditions) - 1:
#             current_result = True
#     return current_result
