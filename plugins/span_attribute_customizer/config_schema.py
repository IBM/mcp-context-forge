# -*- coding: utf-8 -*-
"""Configuration schema for Span Attribute Customizer plugin.

Location: ./plugins/span_attribute_customizer/config_schema.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    global_attributes: Dict[str, Any] = Field(default_factory=dict, description="Attributes to add to all spans")

    # Per-tool overrides
    tool_overrides: Dict[str, ToolOverride] = Field(default_factory=dict, description="Per-tool attribute overrides")

    # Attribute transformations
    transformations: List[AttributeTransformation] = Field(default_factory=list, description="Attribute transformations to apply")

    # Conditional attributes
    conditions: List[ConditionalAttribute] = Field(default_factory=list, description="Conditional attributes based on context")

    # Global removal list
    remove_attributes: List[str] = Field(default_factory=list, description="Attributes to remove from all spans")
