# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/create_slug.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

Slug generation utilities for MCP Gateway.
This module provides utilities for creating URL-friendly slugs from text.
It handles Unicode normalization, special character replacement, and
contraction processing to generate clean, readable slugs.
"""

# Standard
import re
from unicodedata import normalize

# First-Party
from mcpgateway.config import settings

# Helper regex patterns
CONTRACTION_PATTERN = re.compile(r"(\w)[''](\w)")
NON_ALPHANUMERIC_PATTERN = re.compile(r"[\W_]+")

# Special character replacements that normalize() doesn't handle well
SPECIAL_CHAR_MAP = {
    "æ": "ae",
    "ß": "ss",
    "ø": "o",
}


def slugify(text):
    """Make an ASCII slug of text.

    Args:
        text(str): Input text

    Returns:
        str: Slugified text

    Examples:
        Basic slugification:
        >>> slugify("Hello World")
        'hello-world'
        >>> slugify("Test-Case_123")
        'test-case-123'

        Handle special characters:
        >>> slugify("Café & Restaurant")
        'cafe-restaurant'
        >>> slugify("user@example.com")
        'user-example-com'

        Handle contractions:
        >>> slugify("Don't Stop")
        'dont-stop'
        >>> slugify("It's Working")
        'its-working'

        Edge cases:
        >>> slugify("")
        ''
        >>> slugify("   ")
        ''
        >>> slugify("---test---")
        'test'
        >>> slugify("Multiple   Spaces")
        'multiple-spaces'

        Unicode normalization:
        >>> slugify("Naïve résumé")
        'naive-resume'
        >>> slugify("Zürich")
        'zurich'
    """
    # Make lower case and delete apostrophes from contractions
    slug = CONTRACTION_PATTERN.sub(r"\1\2", text.lower())
    # Convert runs of non-alphanumeric characters to single hyphens, strip ends
    slug = NON_ALPHANUMERIC_PATTERN.sub(settings.gateway_tool_name_separator, slug).strip(settings.gateway_tool_name_separator)
    # Replace special characters from the map
    for special_char, replacement in SPECIAL_CHAR_MAP.items():
        slug = slug.replace(special_char, replacement)
    # Normalize the non-ASCII text to ASCII
    slug = normalize("NFKD", slug).encode("ascii", "ignore").decode()
    return slug
