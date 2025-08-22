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

# First-Party
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    PluginCondition,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)


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


def pre_prompt_matches(payload: PromptPrehookPayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
    """Check for a match on pre-prompt hooks.

    Args:
        payload: the prompt prehook payload.
        conditions: the conditions on the plugin that are required for execution.
        context: the global context.

    Returns:
        True if the plugin matches criteria.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginCondition, PromptPrehookPayload, GlobalContext
        >>> payload = PromptPrehookPayload(name="greeting", args={})
        >>> cond = PluginCondition(prompts={"greeting"})
        >>> ctx = GlobalContext(request_id="req1")
        >>> pre_prompt_matches(payload, [cond], ctx)
        True
        >>> payload2 = PromptPrehookPayload(name="other", args={})
        >>> pre_prompt_matches(payload2, [cond], ctx)
        False
    """
    current_result = True
    for index, condition in enumerate(conditions):
        if not matches(condition, context):
            current_result = False

        if condition.prompts and payload.name not in condition.prompts:
            current_result = False
        if current_result:
            return True
        if index < len(conditions) - 1:
            current_result = True
    return current_result


def post_prompt_matches(payload: PromptPosthookPayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
    """Check for a match on pre-prompt hooks.

    Args:
        payload: the prompt posthook payload.
        conditions: the conditions on the plugin that are required for execution.
        context: the global context.

    Returns:
        True if the plugin matches criteria.
    """
    current_result = True
    for index, condition in enumerate(conditions):
        if not matches(condition, context):
            current_result = False

        if condition.prompts and payload.name not in condition.prompts:
            current_result = False
        if current_result:
            return True
        if index < len(conditions) - 1:
            current_result = True
    return current_result


def pre_tool_matches(payload: ToolPreInvokePayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
    """Check for a match on pre-tool hooks.

    Args:
        payload: the tool pre-invoke payload.
        conditions: the conditions on the plugin that are required for execution.
        context: the global context.

    Returns:
        True if the plugin matches criteria.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginCondition, ToolPreInvokePayload, GlobalContext
        >>> payload = ToolPreInvokePayload(name="calculator", args={})
        >>> cond = PluginCondition(tools={"calculator"})
        >>> ctx = GlobalContext(request_id="req1")
        >>> pre_tool_matches(payload, [cond], ctx)
        True
        >>> payload2 = ToolPreInvokePayload(name="other", args={})
        >>> pre_tool_matches(payload2, [cond], ctx)
        False
    """
    current_result = True
    for index, condition in enumerate(conditions):
        if not matches(condition, context):
            current_result = False

        if condition.tools and payload.name not in condition.tools:
            current_result = False
        if current_result:
            return True
        if index < len(conditions) - 1:
            current_result = True
    return current_result


def post_tool_matches(payload: ToolPostInvokePayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
    """Check for a match on post-tool hooks.

    Args:
        payload: the tool post-invoke payload.
        conditions: the conditions on the plugin that are required for execution.
        context: the global context.

    Returns:
        True if the plugin matches criteria.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginCondition, ToolPostInvokePayload, GlobalContext
        >>> payload = ToolPostInvokePayload(name="calculator", result={"result": 8})
        >>> cond = PluginCondition(tools={"calculator"})
        >>> ctx = GlobalContext(request_id="req1")
        >>> post_tool_matches(payload, [cond], ctx)
        True
        >>> payload2 = ToolPostInvokePayload(name="other", result={"result": 8})
        >>> post_tool_matches(payload2, [cond], ctx)
        False
    """
    current_result = True
    for index, condition in enumerate(conditions):
        if not matches(condition, context):
            current_result = False

        if condition.tools and payload.name not in condition.tools:
            current_result = False
        if current_result:
            return True
        if index < len(conditions) - 1:
            current_result = True
    return current_result


def pre_resource_matches(payload: ResourcePreFetchPayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
    """Check for a match on pre-resource hooks.

    Args:
        payload: the resource pre-fetch payload.
        conditions: the conditions on the plugin that are required for execution.
        context: the global context.

    Returns:
        True if the plugin matches criteria.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginCondition, ResourcePreFetchPayload, GlobalContext
        >>> payload = ResourcePreFetchPayload(uri="file:///data.txt")
        >>> cond = PluginCondition(resources={"file:///data.txt"})
        >>> ctx = GlobalContext(request_id="req1")
        >>> pre_resource_matches(payload, [cond], ctx)
        True
        >>> payload2 = ResourcePreFetchPayload(uri="http://api/other")
        >>> pre_resource_matches(payload2, [cond], ctx)
        False
    """
    current_result = True
    for index, condition in enumerate(conditions):
        if not matches(condition, context):
            current_result = False

        if condition.resources and payload.uri not in condition.resources:
            current_result = False
        if current_result:
            return True
        if index < len(conditions) - 1:
            current_result = True
    return current_result


def post_resource_matches(payload: ResourcePostFetchPayload, conditions: list[PluginCondition], context: GlobalContext) -> bool:
    """Check for a match on post-resource hooks.

    Args:
        payload: the resource post-fetch payload.
        conditions: the conditions on the plugin that are required for execution.
        context: the global context.

    Returns:
        True if the plugin matches criteria.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginCondition, ResourcePostFetchPayload, GlobalContext
        >>> from mcpgateway.models import ResourceContent
        >>> content = ResourceContent(type="resource", uri="file:///data.txt", text="Test")
        >>> payload = ResourcePostFetchPayload(uri="file:///data.txt", content=content)
        >>> cond = PluginCondition(resources={"file:///data.txt"})
        >>> ctx = GlobalContext(request_id="req1")
        >>> post_resource_matches(payload, [cond], ctx)
        True
        >>> payload2 = ResourcePostFetchPayload(uri="http://api/other", content=content)
        >>> post_resource_matches(payload2, [cond], ctx)
        False
    """
    current_result = True
    for index, condition in enumerate(conditions):
        if not matches(condition, context):
            current_result = False

        if condition.resources and payload.uri not in condition.resources:
            current_result = False
        if current_result:
            return True
        if index < len(conditions) - 1:
            current_result = True
    return current_result
