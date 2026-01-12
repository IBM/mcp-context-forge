# -*- coding: utf-8 -*-
"""Location: ./plugins/sparc_static_validator/sparc_static_validator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Osher Elhadad

SPARC Static Validator Plugin.

This plugin provides static validation for tool call arguments using the SPARC
(Semantic Pre-execution Analysis for Reliable Calls) component from the
Agent Lifecycle Toolkit (ALTK). It performs comprehensive JSON Schema validation,
type checking, and required parameter verification.

Key Features:
    - JSON Schema validation against tool input_schema
    - Missing required parameter detection
    - Type mismatch detection with optional auto-correction
    - Non-existent parameter detection
    - Enum/allowed values validation

The plugin integrates with MCP Gateway's plugin framework and automatically
retrieves tool schemas from the global context metadata.
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Any, Dict, List, Optional

# Third-Party
import orjson
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.common.models import Tool
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.plugins.framework.constants import TOOL_METADATA

# ALTK imports - optional dependency
try:
    from altk.pre_tool.sparc.function_calling.pipeline.static_checker import (
        evaluate_static,
    )
    from altk.pre_tool.sparc.function_calling.pipeline.types import (
        StaticResult,
        ToolCall,
        ToolSpec,
    )

    ALTK_AVAILABLE = True
except ImportError:
    ALTK_AVAILABLE = False
    evaluate_static = None  # type: ignore[assignment, misc]
    StaticResult = None  # type: ignore[assignment, misc]
    ToolCall = None  # type: ignore[assignment, misc]
    ToolSpec = None  # type: ignore[assignment, misc]


logger = logging.getLogger(__name__)


# Error code mapping from SPARC static checks to plugin error codes
SPARC_ERROR_CODES: Dict[str, str] = {
    "non_existent_function": "SPARC_UNKNOWN_FUNCTION",
    "non_existent_parameter": "SPARC_UNKNOWN_PARAM",
    "incorrect_parameter_type": "SPARC_TYPE_ERROR",
    "missing_required_parameter": "SPARC_MISSING_REQUIRED",
    "allowed_values_violation": "SPARC_ENUM_VIOLATION",
    "json_schema_validation": "SPARC_SCHEMA_ERROR",
    "empty_api_spec": "SPARC_EMPTY_SPEC",
    "invalid_api_spec": "SPARC_INVALID_SPEC",
    "invalid_tool_call": "SPARC_INVALID_CALL",
}


class SPARCStaticConfig(BaseModel):
    """Configuration for SPARC static validation plugin.

    Attributes:
        block_on_violation: Whether to block tool execution when validation fails.
            When True, the tool invocation is stopped and an error is returned.
            When False, validation errors are logged and attached to metadata.
        enable_type_correction: Whether to attempt automatic type conversion for
            mismatched types (e.g., "123" -> 123 for integer fields).
        auto_apply_corrections: Whether to automatically apply type corrections
            to the tool call payload. Only takes effect when enable_type_correction
            is True and corrections are available.
        include_correction_in_response: Whether to include the corrected arguments
            in the response metadata when corrections are available.
        log_corrections: Whether to log when corrections are applied or suggested.
        tool_schemas: Optional map of tool names to their input schemas. If provided,
            these schemas take precedence over schemas from tool metadata.
            This allows overriding or defining schemas for tools that don't have
            input_schema in their metadata.

    Example:
        >>> config = SPARCStaticConfig(
        ...     block_on_violation=True,
        ...     enable_type_correction=True,
        ...     auto_apply_corrections=False,
        ... )
    """

    block_on_violation: bool = Field(
        default=True,
        description="Block tool execution when validation fails",
    )
    enable_type_correction: bool = Field(
        default=True,
        description="Attempt automatic type conversion for mismatched types",
    )
    auto_apply_corrections: bool = Field(
        default=False,
        description="Automatically apply type corrections to the payload",
    )
    include_correction_in_response: bool = Field(
        default=True,
        description="Include corrected arguments in response metadata",
    )
    log_corrections: bool = Field(
        default=True,
        description="Log when corrections are applied or suggested",
    )
    tool_schemas: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None,
        description="Optional per-tool input schemas (overrides tool metadata)",
    )


class SPARCStaticValidatorPlugin(Plugin):
    """SPARC Static Validator Plugin for tool call argument validation.

    This plugin validates tool call arguments before execution using SPARC's
    static analysis capabilities from the Agent Lifecycle Toolkit (ALTK).
    It performs JSON Schema validation, type checking, and required parameter
    verification without requiring an LLM.

    The plugin automatically retrieves the tool's input schema from the gateway's
    tool metadata (available in global_context.metadata["tool"]) and validates
    incoming arguments against it.

    Features:
        - Validates against JSON Schema (type, properties, required, enum, min/max)
        - Detects missing required parameters
        - Detects type mismatches with optional auto-correction
        - Detects non-existent parameters
        - Validates enum/allowed values
        - Graceful degradation when ALTK is not installed

    Example:
        >>> plugin = SPARCStaticValidatorPlugin(
        ...     PluginConfig(
        ...         name="sparc_static_validator",
        ...         kind="plugins.sparc_static_validator.sparc_static_validator.SPARCStaticValidatorPlugin",
        ...         hooks=["tool_pre_invoke"],
        ...         config={"block_on_violation": True},
        ...     )
        ... )

    Note:
        This plugin requires the `agent-lifecycle-toolkit` package to be installed.
        Install it with: pip install mcp-contextforge-gateway[altk]
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the SPARC static validator plugin.

        Args:
            config: Plugin configuration containing settings for validation behavior.

        Raises:
            No exceptions are raised during initialization. If ALTK is not available,
            a warning is logged and the plugin will pass through all requests.
        """
        super().__init__(config)
        self._cfg = SPARCStaticConfig(**(config.config or {}))
        self._altk_available = ALTK_AVAILABLE

        if not self._altk_available:
            logger.warning(
                "SPARC Static Validator: agent-lifecycle-toolkit (ALTK) is not installed. "
                "Plugin will pass through all requests without validation. "
                "Install with: pip install mcp-contextforge-gateway[altk]"
            )

    def _get_tool_schema(self, tool_name: str, context: PluginContext) -> Optional[Dict[str, Any]]:
        """Retrieve the input schema for a tool.

        First checks the plugin configuration for an override schema,
        then falls back to the tool's metadata input_schema.

        Args:
            tool_name: Name of the tool to get the schema for.
            context: Plugin context containing global metadata.

        Returns:
            The tool's input schema as a dict, or None if not available.
        """
        # Check plugin config first (allows overrides)
        if self._cfg.tool_schemas and tool_name in self._cfg.tool_schemas:
            return self._cfg.tool_schemas[tool_name]

        # Fall back to tool metadata from global context
        tool_metadata: Optional[Tool] = context.global_context.metadata.get(TOOL_METADATA)
        if tool_metadata and hasattr(tool_metadata, "input_schema"):
            return tool_metadata.input_schema

        return None

    def _convert_to_tool_spec(self, tool_name: str, input_schema: Dict[str, Any], description: str = "") -> "ToolSpec":
        """Convert MCP Gateway tool schema to SPARC ToolSpec format.

        The SPARC static checker expects an OpenAI-style ToolSpec format.
        This method converts the MCP Gateway's JSON Schema input_schema
        to the expected format.

        Args:
            tool_name: Name of the tool.
            input_schema: JSON Schema for the tool's input parameters.
            description: Optional description of the tool.

        Returns:
            A ToolSpec instance in OpenAI function calling format.
        """
        return ToolSpec.model_validate(
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": description,
                    "parameters": input_schema,
                },
            }
        )

    def _convert_to_tool_call(self, tool_name: str, args: Dict[str, Any], call_id: str = "1") -> "ToolCall":
        """Convert MCP Gateway tool call to SPARC ToolCall format.

        The SPARC static checker expects an OpenAI-style ToolCall format
        with arguments as a JSON-encoded string.

        Args:
            tool_name: Name of the tool being called.
            args: Dictionary of tool arguments.
            call_id: Optional unique identifier for the call.

        Returns:
            A ToolCall instance in OpenAI function calling format.
        """
        return ToolCall.model_validate(
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": orjson.dumps(args).decode(),
                },
            }
        )

    def _extract_errors(self, result: "StaticResult") -> List[Dict[str, Any]]:
        """Extract error details from SPARC validation result.

        Args:
            result: The StaticResult from SPARC validation.

        Returns:
            List of error dictionaries with code, description, and explanation.
        """
        errors: List[Dict[str, Any]] = []
        for check_name, metric in result.metrics.items():
            if not metric.valid:
                errors.append(
                    {
                        "code": SPARC_ERROR_CODES.get(check_name, f"SPARC_{check_name.upper()}"),
                        "check": check_name,
                        "description": metric.description,
                        "explanation": metric.explanation,
                    }
                )
        return errors

    def _extract_correction(self, result: "StaticResult") -> Optional[Dict[str, Any]]:
        """Extract type corrections from SPARC validation result.

        The correction format from SPARC is:
        {
            "corrected_arguments": {<corrected args dict>},
            "tool_call": {<full corrected tool call>}
        }

        This method extracts the corrected_arguments for easy use.

        Args:
            result: The StaticResult from SPARC validation.

        Returns:
            Corrected arguments dictionary, or None if no corrections available.
        """
        for metric in result.metrics.values():
            if metric.correction is not None:
                # Extract corrected_arguments from the correction format
                if isinstance(metric.correction, dict):
                    return metric.correction.get("corrected_arguments", metric.correction)
                return metric.correction
        return None

    def _format_error_description(self, errors: List[Dict[str, Any]]) -> str:
        """Format error list into a human-readable description.

        Args:
            errors: List of error dictionaries.

        Returns:
            Formatted string describing all validation errors.
        """
        if not errors:
            return "Unknown validation error"

        descriptions = []
        for error in errors:
            explanation = error.get("explanation", "")
            if explanation:
                descriptions.append(f"• {explanation}")
            else:
                descriptions.append(f"• {error.get('description', 'Validation failed')}")

        return "Tool call validation failed:\n" + "\n".join(descriptions)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Validate tool arguments before invocation using SPARC static analysis.

        This method is called before each tool invocation. It retrieves the tool's
        schema, converts the call to SPARC format, runs static validation, and
        returns the appropriate result based on configuration.

        Args:
            payload: Tool invocation payload containing tool name and arguments.
            context: Plugin execution context containing tool metadata.

        Returns:
            ToolPreInvokeResult indicating whether to proceed with tool execution.
            May include modified payload if auto_apply_corrections is enabled.
        """
        # If ALTK is not available, pass through
        if not self._altk_available:
            return ToolPreInvokeResult(
                continue_processing=True,
                metadata={"sparc_validation": "skipped", "reason": "ALTK not installed"},
            )

        # Get tool schema
        tool_schema = self._get_tool_schema(payload.name, context)
        if not tool_schema:
            logger.debug(f"SPARC Static Validator: No schema found for tool '{payload.name}', skipping validation")
            return ToolPreInvokeResult(
                continue_processing=True,
                metadata={"sparc_validation": "skipped", "reason": "no_schema"},
            )

        # Get tool description if available
        tool_metadata: Optional[Tool] = context.global_context.metadata.get(TOOL_METADATA)
        tool_description = ""
        if tool_metadata and hasattr(tool_metadata, "description"):
            tool_description = tool_metadata.description or ""

        try:
            # Convert to SPARC format
            tool_spec = self._convert_to_tool_spec(payload.name, tool_schema, tool_description)
            tool_call = self._convert_to_tool_call(payload.name, payload.args or {})

            # Run SPARC static validation
            result: StaticResult = evaluate_static([tool_spec], tool_call)

            # Process validation result
            if result.final_decision:
                # Validation passed
                return ToolPreInvokeResult(
                    continue_processing=True,
                    metadata={"sparc_validation": "passed"},
                )

            # Validation failed - extract errors and corrections
            errors = self._extract_errors(result)
            correction = None

            if self._cfg.enable_type_correction:
                correction = self._extract_correction(result)
                if correction and self._cfg.log_corrections:
                    logger.info(f"SPARC Static Validator: Type corrections available for tool '{payload.name}': {correction}")

            # Build metadata
            metadata: Dict[str, Any] = {
                "sparc_validation": "failed",
                "sparc_errors": errors,
            }

            if self._cfg.include_correction_in_response and correction:
                metadata["sparc_correction"] = correction

            # Handle auto-apply corrections
            if self._cfg.auto_apply_corrections and correction and self._cfg.enable_type_correction:
                if self._cfg.log_corrections:
                    logger.info(f"SPARC Static Validator: Auto-applying corrections for tool '{payload.name}'")
                # Create modified payload with corrected arguments
                modified_payload = ToolPreInvokePayload(
                    name=payload.name,
                    args=correction,
                    headers=payload.headers,
                )
                return ToolPreInvokeResult(
                    continue_processing=True,
                    modified_payload=modified_payload,
                    metadata={
                        "sparc_validation": "corrected",
                        "sparc_original_errors": errors,
                        "sparc_applied_correction": correction,
                    },
                )

            # Block or pass based on configuration
            if self._cfg.block_on_violation:
                # Determine primary error code
                primary_code = "SPARC_VALIDATION_FAILED"
                if errors:
                    primary_code = errors[0].get("code", primary_code)

                return ToolPreInvokeResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="SPARC static validation failed",
                        description=self._format_error_description(errors),
                        code=primary_code,
                        details={
                            "errors": errors,
                            "correction": correction,
                            "tool_name": payload.name,
                            "arguments": payload.args,
                        },
                    ),
                    metadata=metadata,
                )

            # Permissive mode - log and continue
            logger.warning(f"SPARC Static Validator: Validation failed for tool '{payload.name}' " f"(permissive mode, continuing): {errors}")
            return ToolPreInvokeResult(
                continue_processing=True,
                metadata=metadata,
            )

        except Exception as e:
            # Handle unexpected errors gracefully
            logger.error(
                f"SPARC Static Validator: Unexpected error during validation " f"for tool '{payload.name}': {e}",
                exc_info=True,
            )
            return ToolPreInvokeResult(
                continue_processing=True,
                metadata={
                    "sparc_validation": "error",
                    "sparc_error": str(e),
                },
            )
