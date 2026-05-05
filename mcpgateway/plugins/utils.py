# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Gateway-side plugin utilities.
"""

# Standard
import logging
from typing import Any

logger = logging.getLogger(__name__)


def apply_attribute_mapping(attributes: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Apply attribute name mapping (renaming) to a dictionary of attributes.

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
        return dict(attributes)

    renamed_attributes = {}
    for old_name, value in attributes.items():
        new_name = mapping.get(old_name, old_name)
        renamed_attributes[new_name] = value

    logger.debug("Applied %d attribute name mappings", len(mapping))
    return renamed_attributes
