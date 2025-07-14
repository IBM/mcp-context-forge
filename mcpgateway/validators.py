# -*- coding: utf-8 -*-
"""SecurityValidator for MCP Gateway

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Madhav Kandukuri

This module defines the `SecurityValidator` class, which provides centralized, configurable
validation logic for user-generated content in MCP-based applications.

The validator enforces strict security and structural rules across common input types such as:
- Display text (e.g., names, descriptions)
- Identifiers and tool names
- URIs and URLs
- JSON object depth
- Templates (including limited HTML/Jinja2)
- MIME types

Key Features:
- Pattern-based validation using settings-defined regex for HTML/script safety
- Configurable max lengths and depth limits
- Whitelist-based URL scheme and MIME type validation
- Safe escaping of user-visible text fields
- Reusable static/class methods for field-level and form-level validation

Intended to be used with Pydantic or similar schema-driven systems to validate and sanitize
user input in a consistent, centralized way.

Dependencies:
- Standard Library: re, html, logging, urllib.parse
- First-party: `settings` from `mcpgateway.config`

Example usage:
    SecurityValidator.validate_name("my_tool", field_name="Tool Name")
    SecurityValidator.validate_url("https://example.com")
    SecurityValidator.validate_json_depth({...})
"""

# Standard
import html
import logging
import re
from typing import Any
from urllib.parse import urlparse

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class SecurityValidator:
    """Configurable validation with MCP-compliant limits"""

    # Configurable patterns (from settings)
    DANGEROUS_HTML_PATTERN = settings.validation_dangerous_html_pattern  # Default: <(script|iframe|object|embed|link|meta|base|form)\b|</*(script|iframe|object|embed|link|meta|base|form)>
    DANGEROUS_JS_PATTERN = settings.validation_dangerous_js_pattern  # Default: javascript:|vbscript:|on\w+\s*=|data:.*script
    ALLOWED_URL_SCHEMES = settings.validation_allowed_url_schemes  # Default: ["http://", "https://", "ws://", "wss://"]

    # Character type patterns
    NAME_PATTERN = settings.validation_name_pattern  # Default: ^[a-zA-Z0-9_\-\s]+$
    IDENTIFIER_PATTERN = settings.validation_identifier_pattern  # Default: ^[a-zA-Z0-9_\-\.]+$
    VALIDATION_SAFE_URI_PATTERN = settings.validation_safe_uri_pattern  # Default: ^[a-zA-Z0-9_\-.:/?=&%]+$
    VALIDATION_UNSAFE_URI_PATTERN = settings.validation_unsafe_uri_pattern  # Default: [<>"\'\\]
    TOOL_NAME_PATTERN = settings.validation_tool_name_pattern  # Default: ^[a-zA-Z][a-zA-Z0-9_-]*$

    # MCP-compliant limits (configurable)
    MAX_NAME_LENGTH = settings.validation_max_name_length  # Default: 255
    MAX_DESCRIPTION_LENGTH = settings.validation_max_description_length  # Default: 4096
    MAX_TEMPLATE_LENGTH = settings.validation_max_template_length  # Default: 65536
    MAX_CONTENT_LENGTH = settings.validation_max_content_length  # Default: 1048576 (1MB)
    MAX_JSON_DEPTH = settings.validation_max_json_depth  # Default: 10
    MAX_URL_LENGTH = settings.validation_max_url_length  # Default: 2048

    @classmethod
    def sanitize_display_text(cls, value: str, field_name: str) -> str:
        """Ensure text is safe for display in UI by escaping special characters

        Args:
            value (str): Value to validate
            field_name (str): Name of field being validated

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable
        """
        if not value:
            return value

        # Check for patterns that could cause display issues
        if re.search(cls.DANGEROUS_HTML_PATTERN, value, re.IGNORECASE):
            raise ValueError(f"{field_name} contains HTML tags that may cause display issues")

        if re.search(cls.DANGEROUS_JS_PATTERN, value, re.IGNORECASE):
            raise ValueError(f"{field_name} contains script patterns that may cause display issues")

        # Escape HTML entities to ensure proper display
        return html.escape(value, quote=True)

    @classmethod
    def validate_name(cls, value: str, field_name: str = "Name") -> str:
        """Validate names with strict character requirements

        Args:
            value (str): Value to validate
            field_name (str): Name of field being validated

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable

        Examples:
            >>> SecurityValidator.validate_name('valid_name')
            'valid_name'
            >>> SecurityValidator.validate_name('Invalid Name!')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if not value:
            raise ValueError(f"{field_name} cannot be empty")

        # Check against allowed pattern
        if not re.match(cls.NAME_PATTERN, value):
            raise ValueError(f"{field_name} can only contain letters, numbers, underscore, and hyphen. Special characters like <, >, quotes are not allowed.")

        # Additional check for HTML-like patterns
        if re.search(r'[<>"\'/]', value):
            raise ValueError(f"{field_name} cannot contain HTML special characters")

        if len(value) > cls.MAX_NAME_LENGTH:
            raise ValueError(f"{field_name} exceeds maximum length of {cls.MAX_NAME_LENGTH}")

        return value

    @classmethod
    def validate_identifier(cls, value: str, field_name: str) -> str:
        """Validate identifiers (IDs) - MCP compliant

        Args:
            value (str): Value to validate
            field_name (str): Name of field being validated

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable

        Examples:
            >>> SecurityValidator.validate_identifier('valid_id', 'ID')
            'valid_id'
            >>> SecurityValidator.validate_identifier('Invalid/ID', 'ID')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if not value:
            raise ValueError(f"{field_name} cannot be empty")

        # MCP spec: identifiers should be alphanumeric + limited special chars
        if not re.match(cls.IDENTIFIER_PATTERN, value):
            raise ValueError(f"{field_name} can only contain letters, numbers, underscore, hyphen, and dots")

        # Block HTML-like patterns
        if re.search(r'[<>"\'/]', value):
            raise ValueError(f"{field_name} cannot contain HTML special characters")

        if len(value) > cls.MAX_NAME_LENGTH:
            raise ValueError(f"{field_name} exceeds maximum length of {cls.MAX_NAME_LENGTH}")

        return value

    @classmethod
    def validate_uri(cls, value: str, field_name: str = "URI") -> str:
        """Validate URIs - MCP compliant

        Args:
            value (str): Value to validate
            field_name (str): Name of field being validated

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable

        Examples:
            >>> SecurityValidator.validate_uri('/valid/uri', 'URI')
            '/valid/uri'
            >>> SecurityValidator.validate_uri('..', 'URI')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if not value:
            raise ValueError(f"{field_name} cannot be empty")

        # Block HTML-like patterns
        if re.search(cls.VALIDATION_UNSAFE_URI_PATTERN, value):
            raise ValueError(f"{field_name} cannot contain HTML special characters")

        if ".." in value:
            raise ValueError(f"{field_name} cannot contain directory traversal sequences ('..')")

        if not re.search(cls.VALIDATION_SAFE_URI_PATTERN, value):
            raise ValueError(f"{field_name} contains invalid characters")

        if len(value) > cls.MAX_NAME_LENGTH:
            raise ValueError(f"{field_name} exceeds maximum length of {cls.MAX_NAME_LENGTH}")

        return value

    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        """Special validation for MCP tool names

        Args:
            value (str): Value to validate

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable

        Examples:
            >>> SecurityValidator.validate_tool_name('tool_1')
            'tool_1'
            >>> SecurityValidator.validate_tool_name('1tool')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if not value:
            raise ValueError("Tool name cannot be empty")

        # MCP tools have specific naming requirements
        if not re.match(cls.TOOL_NAME_PATTERN, value):
            raise ValueError("Tool name must start with a letter and contain only letters, numbers, and underscore")

        # Ensure no HTML-like content
        if re.search(r'[<>"\'/]', value):
            raise ValueError("Tool name cannot contain HTML special characters")

        if len(value) > cls.MAX_NAME_LENGTH:
            raise ValueError(f"Tool name exceeds maximum length of {cls.MAX_NAME_LENGTH}")

        return value

    @classmethod
    def validate_template(cls, value: str) -> str:
        """Special validation for templates - allow Jinja2 but ensure safe display

        Args:
            value (str): Value to validate

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable
        """
        if not value:
            return value

        if len(value) > cls.MAX_TEMPLATE_LENGTH:
            raise ValueError(f"Template exceeds maximum length of {cls.MAX_TEMPLATE_LENGTH}")

        # Block dangerous tags but allow Jinja2 syntax {{ }} and {% %}
        dangerous_tags = r"<(script|iframe|object|embed|link|meta|base|form)\b"
        if re.search(dangerous_tags, value, re.IGNORECASE):
            raise ValueError("Template contains HTML tags that may interfere with proper display")

        # Check for event handlers that could cause issues
        if re.search(r"on\w+\s*=", value, re.IGNORECASE):
            raise ValueError("Template contains event handlers that may cause display issues")

        return value

    @classmethod
    def validate_url(cls, value: str, field_name: str = "URL") -> str:
        """Validate URLs for allowed schemes and safe display

        Args:
            value (str): Value to validate
            field_name (str): Name of field being validated

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable

        Examples:
            >>> SecurityValidator.validate_url('https://example.com')
            'https://example.com'
            >>> SecurityValidator.validate_url('ftp://example.com')
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if not value:
            raise ValueError(f"{field_name} cannot be empty")

        # Length check
        if len(value) > cls.MAX_URL_LENGTH:
            raise ValueError(f"{field_name} exceeds maximum length of {cls.MAX_URL_LENGTH}")

        # Check allowed schemes
        allowed_schemes = cls.ALLOWED_URL_SCHEMES
        if not any(value.lower().startswith(scheme.lower()) for scheme in allowed_schemes):
            raise ValueError(f"{field_name} must start with one of: {', '.join(allowed_schemes)}")

        # Block dangerous URL patterns
        dangerous_patterns = [r"javascript:", r"data:", r"vbscript:", r"about:", r"chrome:", r"file:", r"ftp:", r"mailto:"]
        for pattern in dangerous_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise ValueError(f"{field_name} contains unsupported or potentially dangerous protocol")

        # Basic URL structure validation
        try:
            result = urlparse(value)
            if not all([result.scheme, result.netloc]):
                raise ValueError(f"{field_name} is not a valid URL")
        except Exception:
            raise ValueError(f"{field_name} is not a valid URL")

        return value

    @classmethod
    def validate_json_depth(cls, obj: Any, max_depth: int = None, current_depth: int = 0) -> None:
        """Validate the maximum depth of a JSON object

        Args:
            obj (Any): The JSON object to check
            max_depth (int): Maximum allowed depth. Defaults to class setting.
            current_depth (int): Current depth for recursion. Used internally.


        Raises:
            ValueError: If the object exceeds the maximum allowed depth

        Examples:
            >>> SecurityValidator.validate_json_depth({'a': {'b': {'c': 1}}}, max_depth=3)
            >>> SecurityValidator.validate_json_depth({'a': {'b': {'c': {'d': 1}}}}, max_depth=3)
            Traceback (most recent call last):
                ...
            ValueError: ...
        """
        if max_depth is None:
            max_depth = cls.MAX_JSON_DEPTH

        if current_depth > max_depth:
            raise ValueError(f"JSON structure exceeds maximum depth of {max_depth}")

        if isinstance(obj, dict):
            for value in obj.values():
                cls.validate_json_depth(value, max_depth, current_depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                cls.validate_json_depth(item, max_depth, current_depth + 1)

    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        """Validate MIME type format

        Args:
            value (str): Value to validate

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable
        """
        if not value:
            return value

        # Basic MIME type pattern
        mime_pattern = r"^[a-zA-Z0-9][a-zA-Z0-9!#$&\-\^_+\.]*\/[a-zA-Z0-9][a-zA-Z0-9!#$&\-\^_+\.]*$"
        if not re.match(mime_pattern, value):
            raise ValueError("Invalid MIME type format")

        # Common safe MIME types
        safe_mime_types = settings.validation_allowed_mime_types
        if value not in safe_mime_types:
            # Allow x- vendor types and + suffixes
            base_type = value.split(";")[0].strip()
            if not (base_type.startswith("application/x-") or base_type.startswith("text/x-") or "+" in base_type):
                raise ValueError(f"MIME type '{value}' is not in the allowed list")

        return value
