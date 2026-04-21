# -*- coding: utf-8 -*-
"""Configuration schema for Span Attribute Customizer plugin.

Location: ./plugins/span_attribute_customizer/config_schema.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class AttributeTransformation(BaseModel):
    """Attribute transformation configuration."""

    field: str = Field(..., description="Attribute field to transform")
    operation: str = Field(..., description="Transformation operation: hash, uppercase, lowercase, truncate")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Operation-specific parameters")


class ConditionalAttribute(BaseModel):
    """Conditional attribute configuration."""

    when: str = Field(..., description="Condition expression (e.g., 'tool.name == \"weather\"')")
    add: Dict[str, Any] = Field(..., description="Attributes to add when condition is true")


class ToolOverride(BaseModel):
    """Per-tool attribute override configuration."""

    attributes: Optional[Dict[str, Any]] = Field(default=None, description="Attributes to add/override")
    remove_attributes: Optional[List[str]] = Field(default=None, description="Attributes to remove")


class SpanAttributeCustomizerConfig(BaseModel):
    """Configuration for Span Attribute Customizer plugin."""

    # Global attributes
    global_attributes: Dict[str, Union[str, int, float, bool]] = Field(
        default_factory=dict, 
        description="Attributes to add to all spans (values must be str, int, float, or bool)"
    )

    # Per-tool overrides
    tool_overrides: Dict[str, ToolOverride] = Field(default_factory=dict, description="Per-tool attribute overrides")

    # Attribute transformations
    transformations: List[AttributeTransformation] = Field(default_factory=list, description="Attribute transformations to apply")

    # Conditional attributes
    conditions: List[ConditionalAttribute] = Field(default_factory=list, description="Conditional attributes based on context")

    # Global removal list
    remove_attributes: List[str] = Field(default_factory=list, description="Attributes to remove from all spans")

    # Attribute name mapping (renaming)
    attribute_mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="Map attribute names to new names (e.g., 'tool.name' -> 'controls.artifact.name')"
    )

    @field_validator("global_attributes")
    @classmethod
    def validate_global_attributes(cls, v: Dict[str, Any]) -> Dict[str, Union[str, int, float, bool]]:
        """Validate that global attributes only contain OTEL-compatible types.
        
        Args:
            v: Dictionary of attributes to validate.
            
        Returns:
            Validated dictionary.
            
        Raises:
            ValueError: If any attribute value is not str, int, float, or bool.
        """
        if len(v) > 100:
            raise ValueError("global_attributes cannot exceed 100 entries")
        
        for key, value in v.items():
            if len(key) > 255:
                raise ValueError(f"Attribute key '{key}' exceeds 255 characters")
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    f"Attribute '{key}' has invalid type {type(value).__name__}. "
                    "Only str, int, float, and bool are supported by OTEL SDKs."
                )
            if isinstance(value, str) and len(value) > 4096:
                raise ValueError(f"Attribute '{key}' string value exceeds 4096 characters")
        
        return v
