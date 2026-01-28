# -*- coding: utf-8 -*-
"""Location: ./plugins/schema_guard/schema_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Schema Guard Plugin.
Validates tool args and results against a minimal JSONSchema-like subset.
Supported: type, properties, required. Types: object, string, number, integer, boolean, array.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, Dict, Optional

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)


class SchemaGuardConfig(BaseModel):
    """Configuration for schema validation guard.

    Attributes:
        arg_schemas: Map of tool names to argument schemas.
        result_schemas: Map of tool names to result schemas.
        block_on_violation: Whether to block on validation failures.
    """

    arg_schemas: Optional[Dict[str, Dict[str, Any]]] = None
    result_schemas: Optional[Dict[str, Dict[str, Any]]] = None
    block_on_violation: bool = True


def _is_type(value: Any, typ: str) -> bool:
    """Check if value matches the specified type.

    Args:
        value: Value to check.
        typ: Type name (object, string, number, integer, boolean, array).

    Returns:
        True if value matches the type.
    """
    match typ:
        case "object":
            return isinstance(value, dict)
        case "string":
            return isinstance(value, str)
        case "number":
            return isinstance(value, (int, float))
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "boolean":
            return isinstance(value, bool)
        case "array":
            return isinstance(value, list)
    return True


def _validate(data: Any, schema: Dict[str, Any]) -> list[str]:
    """Validate data against a schema.

    Args:
        data: Data to validate.
        schema: JSONSchema-like validation schema.

    Returns:
        List of validation error messages.
    """
    errors: list[str] = []
    s_type = schema.get("type")
    if s_type and not _is_type(data, s_type):
        errors.append(f"Type mismatch: expected {s_type}")
        return errors
    if s_type == "object":
        props = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if not isinstance(data, dict) or key not in data:
                errors.append(f"Missing required property: {key}")
        if isinstance(data, dict):
            for key, sub in props.items():
                if key in data:
                    errors.extend([f"{key}: {e}" for e in _validate(data[key], sub)])
    if s_type == "array":
        if isinstance(data, list) and "items" in schema:
            for idx, item in enumerate(data):
                errors.extend([f"[{idx}]: {e}" for e in _validate(item, schema["items"])])
    return errors


class SchemaGuardPlugin(Plugin):
    """Validate tool args and results using a simple schema subset."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the schema guard plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = SchemaGuardConfig(**(config.config or {}))

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Validate tool arguments before invocation.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result indicating whether arguments pass schema validation.
        """
        schema = (self._cfg.arg_schemas or {}).get(payload.name)
        if not schema:
            return ToolPreInvokeResult(continue_processing=True)
        errors = _validate(payload.args or {}, schema)
        if errors and self._cfg.block_on_violation:
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Schema validation failed",
                    description="Arguments do not conform to schema",
                    code="SCHEMA_GUARD_ARGS",
                    details={"errors": errors},
                ),
            )
        return ToolPreInvokeResult(metadata={"schema_errors": errors})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Validate tool result after invocation.

        Args:
            payload: Tool result payload.
            context: Plugin execution context.

        Returns:
            Result indicating whether tool result passes schema validation.
        """
        schema = (self._cfg.result_schemas or {}).get(payload.name)
        if not schema:
            return ToolPostInvokeResult(continue_processing=True)
        errors = _validate(payload.result, schema)
        if errors and self._cfg.block_on_violation:
            return ToolPostInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Schema validation failed",
                    description="Result does not conform to schema",
                    code="SCHEMA_GUARD_RESULT",
                    details={"errors": errors},
                ),
            )
        return ToolPostInvokeResult(metadata={"schema_errors": errors})
