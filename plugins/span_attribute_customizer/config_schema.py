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

    @field_validator("add")
    @classmethod
    def validate_add_attributes(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that conditional attributes only contain OTEL-compatible types.

        Args:
            v: Dictionary of attributes to validate.

        Returns:
            Validated dictionary.

        Raises:
            ValueError: If any attribute value is not str, int, float, or bool.
        """
        for key, value in v.items():
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    f"Conditional attribute '{key}' has invalid type {type(value).__name__}. "
                    "Only str, int, float, and bool are supported by OTEL SDKs."
                )
        return v


class ToolOverride(BaseModel):
    """Per-tool attribute override configuration."""

    attributes: Optional[Dict[str, Any]] = Field(default=None, description="Attributes to add/override")
    remove_attributes: Optional[List[str]] = Field(default=None, description="Attributes to remove")

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Validate that tool override attributes only contain OTEL-compatible types.

        Args:
            v: Dictionary of attributes to validate.

        Returns:
            Validated dictionary.

        Raises:
            ValueError: If any attribute value is not str, int, float, or bool.
        """
        if v is None:
            return v
        for key, value in v.items():
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    f"Tool override attribute '{key}' has invalid type {type(value).__name__}. "
                    "Only str, int, float, and bool are supported by OTEL SDKs."
                )
        return v


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

    @field_validator("tool_overrides")
    @classmethod
    def validate_tool_overrides_count(cls, v: Dict[str, ToolOverride]) -> Dict[str, ToolOverride]:
        """Validate tool_overrides count to prevent resource exhaustion.

        Args:
            v: Dictionary of tool overrides to validate.

        Returns:
            Validated dictionary.

        Raises:
            ValueError: If count exceeds limit.
        """
        if len(v) > 200:
            raise ValueError("tool_overrides cannot exceed 200 entries (Finding 4: CWE-400)")
        return v

    @field_validator("conditions")
    @classmethod
    def validate_conditions_count(cls, v: List[ConditionalAttribute]) -> List[ConditionalAttribute]:
        """Validate conditions count to prevent resource exhaustion.

        Args:
            v: List of conditions to validate.

        Returns:
            Validated list.

        Raises:
            ValueError: If count exceeds limit.
        """
        if len(v) > 50:
            raise ValueError("conditions cannot exceed 50 entries (Finding 4: CWE-400)")
        return v

    @field_validator("transformations")
    @classmethod
    def validate_transformations_count(cls, v: List[AttributeTransformation]) -> List[AttributeTransformation]:
        """Validate transformations count to prevent resource exhaustion.

        Args:
            v: List of transformations to validate.

        Returns:
            Validated list.

        Raises:
            ValueError: If count exceeds limit.
        """
        if len(v) > 50:
            raise ValueError("transformations cannot exceed 50 entries (Finding 4: CWE-400)")
        return v

    @field_validator("attribute_mapping")
    @classmethod
    def validate_attribute_mapping_count(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate attribute_mapping count to prevent resource exhaustion.

        Args:
            v: Dictionary of attribute mappings to validate.

        Returns:
            Validated dictionary.

        Raises:
            ValueError: If count exceeds limit.
        """
        if len(v) > 100:
            raise ValueError("attribute_mapping cannot exceed 100 entries (Finding 4: CWE-400)")
        return v

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
