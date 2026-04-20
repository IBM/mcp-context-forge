# -*- coding: utf-8 -*-
"""Span Attribute Customizer Plugin for ContextForge.

Location: ./plugins/span_attribute_customizer/span_attribute_customizer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import hashlib
import logging
from typing import Any, Dict, Optional

from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

from .config_schema import SpanAttributeCustomizerConfig

logger = logging.getLogger(__name__)


class SpanAttributeCustomizerPlugin(Plugin):
    """Customizes OpenTelemetry span attributes at various lifecycle points."""

    def __init__(self, config: PluginConfig):
        """Initialize the span attribute customizer plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self.cfg = SpanAttributeCustomizerConfig.model_validate(self._config.config)
        logger.info(f"SpanAttributeCustomizer initialized with {len(self.cfg.global_attributes)} global attributes")

    def _compute_attributes(self, tool_name: Optional[str], context: PluginContext, base_attributes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Compute final attributes by merging global, tool-specific, and conditional attributes.

        Args:
            tool_name: Name of the tool being invoked.
            context: Plugin execution context.
            base_attributes: Base attributes to merge with.

        Returns:
            Computed attributes dictionary.
        """
        attributes = {}

        # Start with global attributes
        attributes.update(self.cfg.global_attributes)

        # Apply tool-specific overrides
        if tool_name and tool_name in self.cfg.tool_overrides:
            override = self.cfg.tool_overrides[tool_name]
            if override.attributes:
                attributes.update(override.attributes)

        # Apply conditional attributes
        for condition in self.cfg.conditions:
            if self._evaluate_condition(condition.when, tool_name, context):
                attributes.update(condition.add)

        # Apply transformations
        if base_attributes:
            attributes.update(base_attributes)

        for transform in self.cfg.transformations:
            if transform.field in attributes:
                attributes[transform.field] = self._apply_transformation(attributes[transform.field], transform.operation, transform.params)

        return attributes

    def _get_attribute_mapping(self) -> Dict[str, str]:
        """Get attribute name mapping for renaming.

        Returns:
            Dictionary mapping old attribute names to new names.
        """
        return dict(self.cfg.attribute_mapping)

    def _evaluate_condition(self, condition: str, tool_name: Optional[str], context: PluginContext) -> bool:
        """Evaluate a condition expression.

        Args:
            condition: Condition string to evaluate.
            tool_name: Name of the tool being invoked.
            context: Plugin execution context.

        Returns:
            True if condition is met, False otherwise.
        """
        # Simple condition evaluation (can be enhanced with safe eval)
        # For now, support basic equality checks
        try:
            if "==" in condition:
                left, right = condition.split("==")
                left = left.strip()
                right = right.strip().strip('"').strip("'")

                if left == "tool.name":
                    return tool_name == right

            return False
        except Exception as e:
            logger.warning(f"Failed to evaluate condition '{condition}': {e}")
            return False

    def _apply_transformation(self, value: Any, operation: str, params: Optional[Dict[str, Any]]) -> Any:
        """Apply a transformation to an attribute value.

        Args:
            value: Value to transform.
            operation: Transformation operation to apply.
            params: Operation-specific parameters.

        Returns:
            Transformed value.
        """
        try:
            if operation == "hash":
                return hashlib.sha256(str(value).encode()).hexdigest()[:16]
            if operation == "uppercase":
                return str(value).upper()
            if operation == "lowercase":
                return str(value).lower()
            if operation == "truncate":
                max_len = params.get("max_length", 50) if params else 50
                return str(value)[:max_len]
            logger.warning(f"Unknown transformation operation: {operation}")
            return value
        except Exception as e:
            logger.warning(f"Failed to apply transformation '{operation}': {e}")
            return value

    def _get_removal_list(self, tool_name: Optional[str]) -> list[str]:
        """Get list of attributes to remove.

        Args:
            tool_name: Name of the tool being invoked.

        Returns:
            List of attribute names to remove.
        """
        removal_list = list(self.cfg.remove_attributes)

        # Add tool-specific removals
        if tool_name and tool_name in self.cfg.tool_overrides:
            override = self.cfg.tool_overrides[tool_name]
            if override.remove_attributes:
                removal_list.extend(override.remove_attributes)

        return removal_list

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Add custom attributes before tool invocation.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result with metadata about attributes added.
        """
        custom_attrs = self._compute_attributes(payload.name, context)
        removal_list = self._get_removal_list(payload.name)
        attribute_mapping = self._get_attribute_mapping()

        # Store in context for observability service
        context.global_context.state["custom_span_attributes"] = custom_attrs
        context.global_context.state["remove_span_attributes"] = removal_list
        context.global_context.state["span_attribute_mapping"] = attribute_mapping

        logger.debug(f"Added {len(custom_attrs)} custom attributes for tool '{payload.name}'")
        if attribute_mapping:
            logger.debug(f"Configured {len(attribute_mapping)} attribute name mappings")

        return ToolPreInvokeResult(metadata={"span_customizer": {"attributes_added": len(custom_attrs), "mappings_configured": len(attribute_mapping)}})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Add result-based attributes after tool execution.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result indicating post-processing completion.
        """
        # Can add attributes based on tool results
        return ToolPostInvokeResult()

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Add custom attributes before resource fetch.

        Args:
            payload: Resource fetch payload.
            context: Plugin execution context.

        Returns:
            Result indicating pre-processing completion.
        """
        custom_attrs = self._compute_attributes(None, context)
        context.global_context.state["custom_span_attributes"] = custom_attrs
        return ResourcePreFetchResult()

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Add result-based attributes after resource fetch.

        Args:
            payload: Resource fetch result payload.
            context: Plugin execution context.

        Returns:
            Result indicating post-processing completion.
        """
        return ResourcePostFetchResult()

    async def shutdown(self) -> None:
        """Shutdown the plugin and clean up resources."""
        logger.info("SpanAttributeCustomizer plugin shutting down")
