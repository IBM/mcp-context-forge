# -*- coding: utf-8 -*-
"""Span Attribute Customizer Plugin for ContextForge.

Location: ./plugins/span_attribute_customizer/span_attribute_customizer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import hashlib
import hmac
import logging
import threading
from typing import Any, Dict, Optional

from mcpgateway.config import settings
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
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
        self._state_lock = threading.Lock()
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
        # Simple condition evaluation supporting basic equality checks
        try:
            if "==" in condition:
                # Split only on first occurrence to handle values containing ==
                left, right = condition.split("==", 1)
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
                # Use HMAC-SHA-256 with auth_encryption_secret for secure pseudonymization
                secret = settings.auth_encryption_secret.get_secret_value().encode()
                return hmac.new(secret, str(value).encode(), hashlib.sha256).hexdigest()[:32]
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
        # Compute attributes outside lock (read-only operations)
        custom_attrs = self._compute_attributes(payload.name, context)
        removal_list = self._get_removal_list(payload.name)
        attribute_mapping = self._get_attribute_mapping()

        # Store in context for observability service with thread-safe access
        # Snapshot all state under lock to prevent race conditions (Finding 1: CWE-362)
        with self._state_lock:
            context.global_context.state["custom_span_attributes"] = custom_attrs
            context.global_context.state["remove_span_attributes"] = removal_list
            context.global_context.state["span_attribute_mapping"] = attribute_mapping

        logger.debug(f"Added {len(custom_attrs)} custom attributes for tool '{payload.name}'")
        if attribute_mapping:
            logger.debug(f"Configured {len(attribute_mapping)} attribute name mappings")

        return ToolPreInvokeResult(metadata={"span_customizer": {"attributes_added": len(custom_attrs), "mappings_configured": len(attribute_mapping)}})

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Add custom attributes before resource fetch.

        Args:
            payload: Resource fetch payload.
            context: Plugin execution context.

        Returns:
            Result indicating pre-processing completion.
        """
        custom_attrs = self._compute_attributes(None, context)
        attribute_mapping = self._get_attribute_mapping()

        # Apply attribute mapping to resource spans (Finding 3: CWE-840)
        # Reset tool-specific state but preserve global attribute mapping for compliance/privacy
        with self._state_lock:
            context.global_context.state["custom_span_attributes"] = custom_attrs
            context.global_context.state["remove_span_attributes"] = []
            context.global_context.state["span_attribute_mapping"] = attribute_mapping

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
