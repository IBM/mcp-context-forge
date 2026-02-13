# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Mihai Criveti, Fred Araujo

Utility module for plugins layer.
This module implements the utility functions associated with
plugins.
"""

# Standard
from functools import cache
import importlib
from types import ModuleType
from typing import Any, Optional

# Third-Party
from fastapi.responses import JSONResponse
import orjson
from pydantic import BaseModel, ConfigDict

# First-Party
from mcpgateway.plugins.framework.models import GlobalContext, PluginCondition


class StructuredData(BaseModel):
    """Dynamic model that provides attribute access on deserialized dicts.

    When framework payload fields are typed as ``Any``, Pydantic keeps
    nested dicts as plain dicts during ``model_validate``.  This class
    is used by :func:`coerce_nested` to convert those dicts into objects
    with attribute-style access, preserving compatibility with plugin
    code that expects ``payload.result.messages[0].content.text``.

    Examples:
        >>> sd = StructuredData(name="test", value=42)
        >>> sd.name
        'test'
        >>> sd.model_dump()
        {'name': 'test', 'value': 42}
    """

    model_config = ConfigDict(extra="allow")


def coerce_nested(v: Any) -> Any:
    """Recursively convert dicts to :class:`StructuredData` for attribute access.

    Already-constructed Pydantic models (e.g. a real ``PromptResult``
    passed by the gateway) are returned as-is.

    Args:
        v: Value to coerce — dict, list, or scalar.

    Returns:
        A ``StructuredData`` (for dicts), a list of coerced items, or
        the original value unchanged.

    Examples:
        >>> from pydantic import BaseModel
        >>> result = coerce_nested({"messages": [{"role": "user", "content": {"type": "text", "text": "hi"}}]})
        >>> result.messages[0].content.text
        'hi'
        >>> class Existing(BaseModel):
        ...     x: int = 1
        >>> coerce_nested(Existing()) is not None
        True
    """
    if isinstance(v, BaseModel):
        return v
    if isinstance(v, dict):
        return StructuredData(**{k: coerce_nested(val) for k, val in v.items()})
    if isinstance(v, list):
        return [coerce_nested(item) for item in v]
    return v


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


def get_attr(obj: Any, attr: str, default: Any = "") -> Any:
    """Get attribute from object or dictionary with defensive access.

    This utility function provides a consistent way to access attributes
    on objects that may be either ORM model instances or plain dictionaries.

    Args:
        obj: The object or dictionary to get the attribute from.
        attr: The attribute name to retrieve.
        default: The default value to return if attribute is not found.

    Returns:
        The attribute value, or the default if not found or obj is None.

    Examples:
        >>> get_attr({"name": "test"}, "name")
        'test'
        >>> get_attr({"name": "test"}, "missing", "default")
        'default'
        >>> get_attr(None, "name", "fallback")
        'fallback'
        >>> class Obj:
        ...     name = "obj_name"
        >>> get_attr(Obj(), "name")
        'obj_name'
    """
    if obj is None:
        return default
    if hasattr(obj, attr):
        return getattr(obj, attr, default) or default
    if isinstance(obj, dict):
        return obj.get(attr, default) or default
    return default


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


class ORJSONResponse(JSONResponse):
    """JSON response using orjson for faster serialization.

    Drop-in replacement for FastAPI's default JSONResponse.
    The framework already depends on both fastapi and orjson.

    Example:
        >>> response = ORJSONResponse(content={"status": "healthy"})
        >>> response.media_type
        'application/json'
    """

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        """Render content to JSON bytes using orjson.

        Args:
            content: The content to serialize to JSON.

        Returns:
            JSON bytes ready for HTTP response.
        """
        return orjson.dumps(
            content,
            option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY,
        )
