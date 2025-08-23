# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/display_name.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Display Name Utilities.
This module provides utilities for converting technical tool names to user-friendly display names.

Examples:
    >>> from mcpgateway.utils.display_name import generate_display_name
    >>> generate_display_name("duckduckgo_search")
    'Duckduckgo Search'
    >>> generate_display_name("weather-api")
    'Weather Api'
    >>> generate_display_name("get_user.profile")
    'Get User Profile'
"""

# Standard
import re


def generate_display_name(technical_name: str) -> str:
    """Convert technical tool name to human-readable display name.

    Converts underscores, hyphens, and dots to spaces, then capitalizes the first letter.

    Args:
        technical_name: The technical tool name (e.g., "duckduckgo_search")

    Returns:
        str: Human-readable display name (e.g., "Duckduckgo Search")

    Examples:
        >>> generate_display_name("duckduckgo_search")
        'Duckduckgo Search'
        >>> generate_display_name("weather-api")
        'Weather Api'
        >>> generate_display_name("get_user.profile")
        'Get User Profile'
        >>> generate_display_name("simple_tool")
        'Simple Tool'
        >>> generate_display_name("UPPER_CASE")
        'Upper Case'
        >>> generate_display_name("mixed_Case-Name.test")
        'Mixed Case Name Test'
        >>> generate_display_name("")
        ''
        >>> generate_display_name("single")
        'Single'
        >>> generate_display_name("multiple___underscores")
        'Multiple Underscores'
        >>> generate_display_name("tool_with-mixed.separators")
        'Tool With Mixed Separators'
    """
    if not technical_name:
        return ""

    # Replace underscores, hyphens, and dots with spaces
    display_name = re.sub(r"[_\-\.]+", " ", technical_name)

    # Remove extra whitespace and capitalize first letter
    display_name = " ".join(display_name.split())  # Normalize whitespace

    if display_name:
        # Capitalize each word (title case)
        display_name = display_name.title()

    return display_name
