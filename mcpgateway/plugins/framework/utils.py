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
import logging
from types import ModuleType
from typing import Any, Optional

# Third-Party
from fastapi.responses import JSONResponse
import orjson
from pydantic import BaseModel, ConfigDict

# First-Party
from mcpgateway.plugins.framework.models import GlobalContext, PluginCondition

logger = logging.getLogger(__name__)


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


def coerce_messages(v: Any) -> Any:
    """Convert nested dicts in a messages list to objects with attribute access.

    Shared validator logic for agent payload ``messages`` fields.
    When deserializing from JSON, messages arrive as plain dicts.  This
    converts each dict to a :class:`StructuredData` so plugin code like
    ``payload.messages[0].content.text`` works regardless of the transport.

    Args:
        v: The raw value for the ``messages`` field.

    Returns:
        The coerced list with attribute access on each element.
    """
    if isinstance(v, list):
        return [coerce_nested(item) if isinstance(item, dict) else item for item in v]
    return v


_COERCE_MAX_DEPTH = 20
_COERCE_MAX_BREADTH = 500


def coerce_nested(v: Any, *, _depth: int = 0) -> Any:
    """Recursively convert dicts to :class:`StructuredData` for attribute access.

    Already-constructed Pydantic models (e.g. a real ``PromptResult``
    passed by the gateway) are returned as-is.  Depth is capped at
    ``_COERCE_MAX_DEPTH`` and breadth (keys per dict / items per list)
    at ``_COERCE_MAX_BREADTH`` to guard against resource exhaustion.

    Args:
        v: Value to coerce — dict, list, or scalar.
        _depth: Internal recursion depth counter (do not set manually).

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
    if _depth >= _COERCE_MAX_DEPTH:
        return v
    if isinstance(v, BaseModel):
        return v
    if isinstance(v, dict):
        if len(v) > _COERCE_MAX_BREADTH:
            logger.warning("coerce_nested: dict has %d keys (limit %d); returning as plain dict", len(v), _COERCE_MAX_BREADTH)
            return v
        return StructuredData(**{k: coerce_nested(val, _depth=_depth + 1) for k, val in v.items()})
    if isinstance(v, list):
        if len(v) > _COERCE_MAX_BREADTH:
            logger.warning("coerce_nested: list has %d items (limit %d); skipping coercion", len(v), _COERCE_MAX_BREADTH)
            return v
        return [coerce_nested(item, _depth=_depth + 1) for item in v]
    return v


_BLOCKED_MODULE_PREFIXES = (
    "os",
    "sys",
    "subprocess",
    "shutil",
    "socket",
    "http.server",
    "ctypes",
    "importlib",
    "builtins",
    "code",
    "codeop",
    "compileall",
    "runpy",
)


@cache  # noqa
def import_module(mod_name: str) -> ModuleType:
    """Import a module after validating the name is safe for dynamic loading.

    Blocks dangerous stdlib modules that could enable arbitrary code
    execution if an attacker controls the plugin ``kind`` field.

    Args:
        mod_name: fully qualified module name

    Returns:
        A module.

    Raises:
        ImportError: If the module name is blocked or contains path traversal.

    Examples:
        >>> mod = import_module('mcpgateway.plugins.framework.utils')
        >>> hasattr(mod, 'import_module')
        True
    """
    # Block path-traversal-style names and names with dangerous characters
    if ".." in mod_name or "/" in mod_name or "\\" in mod_name:
        raise ImportError(f"Plugin module name '{mod_name}' contains invalid characters.")
    # Block dangerous stdlib modules
    for blocked in _BLOCKED_MODULE_PREFIXES:
        if mod_name == blocked or mod_name.startswith(blocked + "."):
            raise ImportError(f"Plugin module '{mod_name}' is blocked for security reasons.")
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


def normalize_content_type(content_type: str) -> str:
    """Extract base content type without parameters.

    Args:
        content_type: Raw content type string (e.g., 'application/json; charset=utf-8')

    Returns:
        Normalized content type (e.g., 'application/json')

    Examples:
        >>> normalize_content_type('application/json; charset=utf-8')
        'application/json'
        >>> normalize_content_type('text/html')
        'text/html'
        >>> normalize_content_type('TEXT/PLAIN')
        'text/plain'
        >>> normalize_content_type('application/json;charset=utf-8')
        'application/json'
        >>> normalize_content_type('')
        ''
        >>> normalize_content_type('   ')
        ''
    """
    if not isinstance(content_type, str):
        return ""
    return content_type.split(";", maxsplit=1)[0].strip().lower()


def matches(condition: PluginCondition, context: GlobalContext) -> bool:
    """Check if GlobalContext conditions match (AND logic).

    All specified fields in the condition must match for this function to return True.
    This function uses AND logic - if any field doesn't match, it returns False.

    Args:
        condition: the conditions on the plugin that are required for execution.
        context: the global context.

    Returns:
        True if all specified fields match, False otherwise.

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
        >>> cond3 = PluginCondition(content_types=["application/json"])
        >>> ctx4 = GlobalContext(request_id="req4", content_type="application/json")
        >>> matches(cond3, ctx4)
        True
        >>> ctx5 = GlobalContext(request_id="req5", content_type="application/json; charset=utf-8")
        >>> matches(cond3, ctx5)
        True
        >>> ctx6 = GlobalContext(request_id="req6", content_type="text/plain")
        >>> matches(cond3, ctx6)
        False
    """
    # Check server ID
    if condition.server_ids:
        if context.server_id not in condition.server_ids:
            logger.debug("Server ID mismatch: %s not in %s", context.server_id, condition.server_ids)
            return False
        logger.debug("Server ID matched: %s", context.server_id)

    # Check tenant ID
    if condition.tenant_ids:
        if context.tenant_id not in condition.tenant_ids:
            logger.debug("Tenant ID mismatch: %s not in %s", context.tenant_id, condition.tenant_ids)
            return False
        logger.debug("Tenant ID matched: %s", context.tenant_id)

    # Check content types (strict AND logic - fail if content_type is None but condition requires it)
    if condition.content_types:
        if not context.content_type:
            logger.debug("Content-type mismatch: content_type is None but condition requires: %s", condition.content_types)
            return False
        normalized_request = normalize_content_type(context.content_type)
        if normalized_request not in condition.content_types:
            return False
        logger.debug("Content-type matched: %s", context.content_type)

    # Check user patterns (simple contains check, could be regex)
    if condition.user_patterns:
        if not context.user:
            logger.debug("User pattern mismatch: user is None but patterns required: %s", condition.user_patterns)
            return False

        if not any(pattern in context.user for pattern in condition.user_patterns):
            logger.debug("User pattern mismatch: %s does not match any of %s", context.user, condition.user_patterns)
            return False
        logger.debug("User pattern matched: %s", context.user)

    logger.debug("All GlobalContext conditions matched")
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
    """Check if payload matches plugin conditions using hybrid AND/OR logic.

    Evaluation logic:
    - Within a condition object: ALL fields must match (AND logic)
    - Across condition objects: ANY can match (OR logic)

    This enables expressions like:
    - (tenant=X AND tool=Y) OR (server=Z AND user=W)

    Args:
        payload: The payload object.
        hook_type: The hook type identifier.
        conditions: List of conditions (any can match).
        context: The global context.

    Returns:
        True if any condition fully matches, False otherwise.

    Examples:
        >>> from mcpgateway.plugins.framework import PluginCondition, GlobalContext
        >>> from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload
        >>> # Single condition - all fields must match
        >>> payload = ToolPreInvokePayload(name="calculator", args={})
        >>> cond = PluginCondition(tools={"calculator"})
        >>> ctx = GlobalContext(request_id="req1")
        >>> payload_matches(payload, "tool_pre_invoke", [cond], ctx)
        True
        >>> # Multiple conditions - any can match
        >>> cond1 = PluginCondition(tenant_ids={"healthcare"}, tools={"tool1"})
        >>> cond2 = PluginCondition(server_ids={"prod"}, user_patterns={"admin_.*"})
        >>> # Matches if (healthcare AND tool1) OR (prod AND admin_*)
        >>> payload_matches(payload, "tool_pre_invoke", [cond1, cond2], ctx)
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
        logger.debug("No conditions specified - matching all requests")
        return True

    logger.debug("Evaluating %d condition object(s) for hook %s (OR logic across objects)", len(conditions), hook_type)

    # ANY condition object can match (OR logic across objects)
    for idx, condition in enumerate(conditions, 1):
        logger.debug("Evaluating condition object %d/%d", idx, len(conditions))

        # Within this condition object, ALL fields must match (AND logic)

        # Check GlobalContext conditions first (server_id, tenant_id, user_patterns)
        if not matches(condition, context):
            logger.debug("Condition object %d: GlobalContext mismatch (server_id=%s, tenant_id=%s, user=%s)", idx, context.server_id, context.tenant_id, context.user)
            continue  # Try next condition object (OR logic)

        # Check payload-specific conditions (tools, prompts, resources, agents)
        condition_attr = condition_attr_map.get(hook_type)
        if condition_attr:
            condition_set = getattr(condition, condition_attr, None)
            if condition_set:
                payload_value = get_matchable_value(payload, hook_type)
                if not payload_value or payload_value not in condition_set:
                    logger.debug("Condition object %d: Payload mismatch (%s='%s' not in %s)", idx, condition_attr, payload_value, condition_set)
                    continue  # Try next condition object (OR logic)

        # If we reach here, this condition object fully matched (all fields matched)
        logger.debug("Condition object %d MATCHED - plugin will execute (hook=%s)", idx, hook_type)
        return True  # OR logic - any condition object matching is sufficient

    # No condition objects matched
    logger.debug("No condition objects matched for hook %s - plugin will NOT execute", hook_type)
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


def apply_attribute_mapping(attributes: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Apply attribute name mapping (renaming) to a dictionary of attributes.

    This is a centralized helper to avoid duplicating the mapping logic across
    observability_service.py and manager.py.

    Args:
        attributes: Dictionary of attributes to rename.
        mapping: Dictionary mapping old attribute names to new names.

    Returns:
        New dictionary with renamed attributes.

    Example:
        >>> attrs = {"tool.name": "weather", "tool.version": "1.0"}
        >>> mapping = {"tool.name": "controls.artifact.name"}
        >>> apply_attribute_mapping(attrs, mapping)
        {'controls.artifact.name': 'weather', 'tool.version': '1.0'}
    """
    if not mapping:
        return attributes

    renamed_attributes = {}
    for old_name, value in attributes.items():
        new_name = mapping.get(old_name, old_name)
        renamed_attributes[new_name] = value

    logger.debug("Applied %d attribute name mappings", len(mapping))
    return renamed_attributes
