# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/common/validators.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Madhav Kandukuri

SecurityValidator for MCP Gateway
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

Examples:
    >>> from mcpgateway.common.validators import SecurityValidator
    >>> SecurityValidator.sanitize_display_text('<b>Test</b>', 'test')
    '&lt;b&gt;Test&lt;/b&gt;'
    >>> SecurityValidator.validate_name('valid_name-123', 'test')
    'valid_name-123'
    >>> SecurityValidator.validate_identifier('my.test.id_123', 'test')
    'my.test.id_123'
    >>> SecurityValidator.validate_json_depth({'a': {'b': 1}})
    >>> SecurityValidator.validate_json_depth({'a': 1})
"""

# Standard
import html
import logging
from pathlib import Path
import re
import shlex
from typing import Any, List, Optional
from urllib.parse import urlparse
import uuid

# First-Party
from mcpgateway.common.config import settings
from mcpgateway.config import settings as config_settings

logger = logging.getLogger(__name__)


class SecurityValidator:
    """Configurable validation with MCP-compliant limits"""

    # Configurable patterns (from settings)
    DANGEROUS_HTML_PATTERN = (
        settings.validation_dangerous_html_pattern
    )  # Default: '<(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)\b|</*(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)>'
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
    MAX_DESCRIPTION_LENGTH = settings.validation_max_description_length  # Default: 8192 (8KB)
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

        Examples:
            Basic HTML escaping:

            >>> SecurityValidator.sanitize_display_text('Hello World', 'test')
            'Hello World'
            >>> SecurityValidator.sanitize_display_text('Hello <b>World</b>', 'test')
            'Hello &lt;b&gt;World&lt;/b&gt;'

            Empty/None handling:

            >>> SecurityValidator.sanitize_display_text('', 'test')
            ''
            >>> SecurityValidator.sanitize_display_text(None, 'test') #doctest: +SKIP

            Dangerous script patterns:

            >>> SecurityValidator.sanitize_display_text('alert();', 'test')
            'alert();'
            >>> SecurityValidator.sanitize_display_text('javascript:alert(1)', 'test')
            Traceback (most recent call last):
                ...
            ValueError: test contains script patterns that may cause display issues

            Polyglot attack patterns:

            >>> SecurityValidator.sanitize_display_text('"; alert()', 'test')
            Traceback (most recent call last):
                ...
            ValueError: test contains potentially dangerous character sequences
            >>> SecurityValidator.sanitize_display_text('-->test', 'test')
            '--&gt;test'
            >>> SecurityValidator.sanitize_display_text('--><script>', 'test')
            Traceback (most recent call last):
                ...
            ValueError: test contains HTML tags that may cause display issues
            >>> SecurityValidator.sanitize_display_text('String.fromCharCode(65)', 'test')
            Traceback (most recent call last):
                ...
            ValueError: test contains potentially dangerous character sequences

            Safe character escaping:

            >>> SecurityValidator.sanitize_display_text('User & Admin', 'test')
            'User &amp; Admin'
            >>> SecurityValidator.sanitize_display_text('Quote: "Hello"', 'test')
            'Quote: &quot;Hello&quot;'
            >>> SecurityValidator.sanitize_display_text("Quote: 'Hello'", 'test')
            'Quote: &#x27;Hello&#x27;'
        """
        if not value:
            return value

        # Check for patterns that could cause display issues
        if re.search(cls.DANGEROUS_HTML_PATTERN, value, re.IGNORECASE):
            raise ValueError(f"{field_name} contains HTML tags that may cause display issues")

        if re.search(cls.DANGEROUS_JS_PATTERN, value, re.IGNORECASE):
            raise ValueError(f"{field_name} contains script patterns that may cause display issues")

        # Check for polyglot patterns - combinations of quotes, semicolons, and parentheses
        # that could work in multiple contexts
        polyglot_patterns = [
            r"['\"];.*alert\s*\(",  # Quotes followed by alert
            r"-->\s*<[^>]+>",  # HTML comment closers followed by tags
            r"['\"].*//['\"]",  # Quote, content, comment, quote
            r"<<[A-Z]+>",  # Double angle brackets (like <<SCRIPT>)
            r"String\.fromCharCode",  # Character code manipulation
            r"javascript:.*\(",  # javascript: protocol with function call
        ]

        for pattern in polyglot_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise ValueError(f"{field_name} contains potentially dangerous character sequences")

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
            >>> SecurityValidator.validate_name('valid_name-123')
            'valid_name-123'
            >>> SecurityValidator.validate_name('valid_name_test')
            'valid_name_test'
            >>> SecurityValidator.validate_name('Test Name')
            'Test Name'
            >>> try:
            ...     SecurityValidator.validate_name('Invalid Name!')
            ... except ValueError as e:
            ...     'can only contain' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_name('')
            ... except ValueError as e:
            ...     'cannot be empty' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_name('name<script>')
            ... except ValueError as e:
            ...     'HTML special characters' in str(e) or 'can only contain' in str(e)
            True

            Test length limit (line 181):

            >>> long_name = 'a' * 256
            >>> try:
            ...     SecurityValidator.validate_name(long_name)
            ... except ValueError as e:
            ...     'exceeds maximum length' in str(e)
            True

            Test HTML special characters (line 178):

            >>> try:
            ...     SecurityValidator.validate_name('name"test')
            ... except ValueError as e:
            ...     'can only contain' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_name("name'test")
            ... except ValueError as e:
            ...     'can only contain' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_name('name/test')
            ... except ValueError as e:
            ...     'can only contain' in str(e)
            True
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
            >>> SecurityValidator.validate_identifier('valid.id.123', 'ID')
            'valid.id.123'
            >>> SecurityValidator.validate_identifier('valid-id_test', 'ID')
            'valid-id_test'
            >>> SecurityValidator.validate_identifier('test123', 'ID')
            'test123'
            >>> try:
            ...     SecurityValidator.validate_identifier('Invalid/ID', 'ID')
            ... except ValueError as e:
            ...     'can only contain' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_identifier('', 'ID')
            ... except ValueError as e:
            ...     'cannot be empty' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_identifier('id<script>', 'ID')
            ... except ValueError as e:
            ...     'HTML special characters' in str(e) or 'can only contain' in str(e)
            True

            Test HTML special characters (line 233):

            >>> try:
            ...     SecurityValidator.validate_identifier('id"test', 'ID')
            ... except ValueError as e:
            ...     'can only contain' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_identifier("id'test", 'ID')
            ... except ValueError as e:
            ...     'can only contain' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_identifier('id/test', 'ID')
            ... except ValueError as e:
            ...     'can only contain' in str(e)
            True

            Test length limit (line 236):

            >>> long_id = 'a' * 256
            >>> try:
            ...     SecurityValidator.validate_identifier(long_id, 'ID')
            ... except ValueError as e:
            ...     'exceeds maximum length' in str(e)
            True
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
            ValueError: URI cannot contain directory traversal sequences ('..')
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
            ValueError: Tool name must start with a letter and contain only letters, numbers, and underscore

            Test HTML special characters (line 310):

            >>> try:
            ...     SecurityValidator.validate_tool_name('tool<script>')
            ... except ValueError as e:
            ...     'must start with a letter' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_tool_name('tool"test')
            ... except ValueError as e:
            ...     'must start with a letter' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_tool_name("tool'test")
            ... except ValueError as e:
            ...     'must start with a letter' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_tool_name('tool/test')
            ... except ValueError as e:
            ...     'must start with a letter' in str(e)
            True

            Test length limit (line 313):

            >>> long_tool_name = 'a' * 256
            >>> try:
            ...     SecurityValidator.validate_tool_name(long_tool_name)
            ... except ValueError as e:
            ...     'exceeds maximum length' in str(e)
            True
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
    def validate_uuid(cls, value: str, field_name: str = "UUID") -> str:
        """Validate UUID format

        Args:
            value (str): Value to validate
            field_name (str): Name of field being validated

        Returns:
            str: Value if validated as safe

        Raises:
            ValueError: When value is not a valid UUID

        Examples:
            >>> SecurityValidator.validate_uuid('550e8400-e29b-41d4-a716-446655440000')
            '550e8400e29b41d4a716446655440000'
            >>> SecurityValidator.validate_uuid('invalid-uuid')
            Traceback (most recent call last):
                ...
            ValueError: UUID must be a valid UUID format

            Test empty UUID (line 340):

            >>> SecurityValidator.validate_uuid('')
            ''

            Test normalized UUID format (lines 344-346):

            >>> SecurityValidator.validate_uuid('550E8400-E29B-41D4-A716-446655440000')
            '550e8400e29b41d4a716446655440000'
            >>> SecurityValidator.validate_uuid('550e8400e29b41d4a716446655440000')
            '550e8400e29b41d4a716446655440000'

            Test various invalid UUID formats (line 347-348):

            >>> try:
            ...     SecurityValidator.validate_uuid('not-a-uuid')
            ... except ValueError as e:
            ...     'valid UUID format' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_uuid('550e8400-e29b-41d4-a716')
            ... except ValueError as e:
            ...     'valid UUID format' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_uuid('550e8400-e29b-41d4-a716-446655440000-extra')
            ... except ValueError as e:
            ...     'valid UUID format' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_uuid('gggggggg-gggg-gggg-gggg-gggggggggggg')
            ... except ValueError as e:
            ...     'valid UUID format' in str(e)
            True
        """
        if not value:
            return value

        try:
            # Validate UUID format by attempting to parse it
            uuid_obj = uuid.UUID(value)
            # Return the normalized string representation
            return str(uuid_obj).replace("-", "")
        except ValueError:
            logger.error(f"Invalid UUID format for {field_name}: {value}")
            raise ValueError(f"{field_name} must be a valid UUID format")

    @classmethod
    def validate_template(cls, value: str) -> str:
        """Special validation for templates - allow safe Jinja2 but prevent SSTI

        Args:
            value (str): Value to validate

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable

        Examples:
            Empty template handling:

            >>> SecurityValidator.validate_template('')
            ''
            >>> SecurityValidator.validate_template(None) #doctest: +SKIP

            Safe Jinja2 templates:

            >>> SecurityValidator.validate_template('Hello {{ name }}')
            'Hello {{ name }}'
            >>> SecurityValidator.validate_template('{% if condition %}text{% endif %}')
            '{% if condition %}text{% endif %}'
            >>> SecurityValidator.validate_template('{{ username }}')
            '{{ username }}'

            Dangerous HTML tags blocked:

            >>> SecurityValidator.validate_template('Hello <script>alert(1)</script>')
            Traceback (most recent call last):
                ...
            ValueError: Template contains HTML tags that may interfere with proper display
            >>> SecurityValidator.validate_template('Test <iframe src="evil.com"></iframe>')
            Traceback (most recent call last):
                ...
            ValueError: Template contains HTML tags that may interfere with proper display
            >>> SecurityValidator.validate_template('<form action="/evil"></form>')
            Traceback (most recent call last):
                ...
            ValueError: Template contains HTML tags that may interfere with proper display

            Event handlers blocked:

            >>> SecurityValidator.validate_template('<div onclick="evil()">Test</div>')
            Traceback (most recent call last):
                ...
            ValueError: Template contains event handlers that may cause display issues
            >>> SecurityValidator.validate_template('onload = "alert(1)"')
            Traceback (most recent call last):
                ...
            ValueError: Template contains event handlers that may cause display issues

            SSTI prevention patterns:

            >>> SecurityValidator.validate_template('{{ __import__ }}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions
            >>> SecurityValidator.validate_template('{{ config }}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions
            >>> SecurityValidator.validate_template('{% import os %}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions
            >>> SecurityValidator.validate_template('{{ 7*7 }}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions
            >>> SecurityValidator.validate_template('{{ 10/2 }}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions
            >>> SecurityValidator.validate_template('{{ 5+5 }}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions
            >>> SecurityValidator.validate_template('{{ 10-5 }}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions

            Other template injection patterns:

            >>> SecurityValidator.validate_template('${evil}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions
            >>> SecurityValidator.validate_template('#{evil}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions
            >>> SecurityValidator.validate_template('%{evil}')
            Traceback (most recent call last):
                ...
            ValueError: Template contains potentially dangerous expressions

            Length limit testing:

            >>> long_template = 'a' * 65537
            >>> SecurityValidator.validate_template(long_template)
            Traceback (most recent call last):
                ...
            ValueError: Template exceeds maximum length of 65536
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

        # SSTI Prevention - block dangerous template expressions
        ssti_patterns = [
            r"\{\{.*(__|\.|config|self|request|application|globals|builtins|import).*\}\}",  # Jinja2 dangerous patterns
            r"\{%.*(__|\.|config|self|request|application|globals|builtins|import).*%\}",  # Jinja2 tags
            r"\$\{.*\}",  # ${} expressions
            r"#\{.*\}",  # #{} expressions
            r"%\{.*\}",  # %{} expressions
            r"\{\{.*\*.*\}\}",  # Math operations in templates (like {{7*7}})
            r"\{\{.*\/.*\}\}",  # Division operations
            r"\{\{.*\+.*\}\}",  # Addition operations
            r"\{\{.*\-.*\}\}",  # Subtraction operations
        ]

        for pattern in ssti_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise ValueError("Template contains potentially dangerous expressions")

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
            Valid URLs:

            >>> SecurityValidator.validate_url('https://example.com')
            'https://example.com'
            >>> SecurityValidator.validate_url('http://example.com')
            'http://example.com'
            >>> SecurityValidator.validate_url('ws://example.com')
            'ws://example.com'
            >>> SecurityValidator.validate_url('wss://example.com')
            'wss://example.com'
            >>> SecurityValidator.validate_url('https://example.com:8080/path')
            'https://example.com:8080/path'
            >>> SecurityValidator.validate_url('https://example.com/path?query=value')
            'https://example.com/path?query=value'

            Empty URL handling:

            >>> SecurityValidator.validate_url('')
            Traceback (most recent call last):
                ...
            ValueError: URL cannot be empty

            Length validation:

            >>> long_url = 'https://example.com/' + 'a' * 2100
            >>> SecurityValidator.validate_url(long_url)
            Traceback (most recent call last):
                ...
            ValueError: URL exceeds maximum length of 2048

            Scheme validation:

            >>> SecurityValidator.validate_url('ftp://example.com')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
            >>> SecurityValidator.validate_url('file:///etc/passwd')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
            >>> SecurityValidator.validate_url('javascript:alert(1)')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
            >>> SecurityValidator.validate_url('data:text/plain,hello')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
            >>> SecurityValidator.validate_url('vbscript:alert(1)')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
            >>> SecurityValidator.validate_url('about:blank')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
            >>> SecurityValidator.validate_url('chrome://settings')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
            >>> SecurityValidator.validate_url('mailto:test@example.com')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://

            IPv6 URL blocking:

            >>> SecurityValidator.validate_url('https://[::1]:8080/')
            Traceback (most recent call last):
                ...
            ValueError: URL contains IPv6 address which is not supported
            >>> SecurityValidator.validate_url('https://[2001:db8::1]/')
            Traceback (most recent call last):
                ...
            ValueError: URL contains IPv6 address which is not supported

            Protocol-relative URL blocking:

            >>> SecurityValidator.validate_url('//example.com/path')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://

            Line break injection:

            >>> SecurityValidator.validate_url('https://example.com\\rHost: evil.com')
            Traceback (most recent call last):
                ...
            ValueError: URL contains line breaks which are not allowed
            >>> SecurityValidator.validate_url('https://example.com\\nHost: evil.com')
            Traceback (most recent call last):
                ...
            ValueError: URL contains line breaks which are not allowed

            Space validation:

            >>> SecurityValidator.validate_url('https://exam ple.com')
            Traceback (most recent call last):
                ...
            ValueError: URL contains spaces which are not allowed in URLs
            >>> SecurityValidator.validate_url('https://example.com/path?query=hello world')
            'https://example.com/path?query=hello world'

            Malformed URLs:

            >>> SecurityValidator.validate_url('https://')
            Traceback (most recent call last):
                ...
            ValueError: URL is not a valid URL
            >>> SecurityValidator.validate_url('not-a-url')
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://

            Restricted IP addresses:

            >>> SecurityValidator.validate_url('https://0.0.0.0/')
            Traceback (most recent call last):
                ...
            ValueError: URL contains invalid IP address (0.0.0.0)
            >>> SecurityValidator.validate_url('https://169.254.169.254/')
            Traceback (most recent call last):
                ...
            ValueError: URL contains restricted IP address

            Invalid port numbers:

            >>> SecurityValidator.validate_url('https://example.com:0/')
            Traceback (most recent call last):
                ...
            ValueError: URL contains invalid port number
            >>> try:
            ...     SecurityValidator.validate_url('https://example.com:65536/')
            ... except ValueError as e:
            ...     'Port out of range' in str(e) or 'invalid port' in str(e)
            True

            Credentials in URL:

            >>> SecurityValidator.validate_url('https://user:pass@example.com/')
            Traceback (most recent call last):
                ...
            ValueError: URL contains credentials which are not allowed
            >>> SecurityValidator.validate_url('https://user@example.com/')
            Traceback (most recent call last):
                ...
            ValueError: URL contains credentials which are not allowed

            XSS patterns in URLs:

            >>> SecurityValidator.validate_url('https://example.com/<script>')
            Traceback (most recent call last):
                ...
            ValueError: URL contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_url('https://example.com?param=javascript:alert(1)')
            Traceback (most recent call last):
                ...
            ValueError: URL contains unsupported or potentially dangerous protocol
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

        # Block IPv6 URLs (URLs with square brackets)
        if "[" in value or "]" in value:
            raise ValueError(f"{field_name} contains IPv6 address which is not supported")

        # Block protocol-relative URLs
        if value.startswith("//"):
            raise ValueError(f"{field_name} contains protocol-relative URL which is not supported")

        # Check for CRLF injection
        if "\r" in value or "\n" in value:
            raise ValueError(f"{field_name} contains line breaks which are not allowed")

        # Check for spaces in domain
        if " " in value.split("?")[0]:  # Check only in the URL part, not query string
            raise ValueError(f"{field_name} contains spaces which are not allowed in URLs")

        # Basic URL structure validation
        try:
            result = urlparse(value)
            if not all([result.scheme, result.netloc]):
                raise ValueError(f"{field_name} is not a valid URL")

            # Additional validation: ensure netloc doesn't contain brackets (double-check)
            if "[" in result.netloc or "]" in result.netloc:
                raise ValueError(f"{field_name} contains IPv6 address which is not supported")

            # Block dangerous IP addresses
            hostname = result.hostname
            if hostname:
                # Block 0.0.0.0 (all interfaces)
                if hostname == "0.0.0.0":  # nosec B104 - we're blocking this for security
                    raise ValueError(f"{field_name} contains invalid IP address (0.0.0.0)")

                # Block AWS metadata service
                if hostname == "169.254.169.254":
                    raise ValueError(f"{field_name} contains restricted IP address")

                # Optional: Block localhost/loopback (uncomment if needed)
                # if hostname in ["127.0.0.1", "localhost"]:
                #     raise ValueError(f"{field_name} contains localhost address")

            # Validate port number
            if result.port is not None:
                if result.port < 1 or result.port > 65535:
                    raise ValueError(f"{field_name} contains invalid port number")

            # Check for credentials in URL
            if result.username or result.password:
                raise ValueError(f"{field_name} contains credentials which are not allowed")

            # Check for XSS patterns in the entire URL (including query parameters)
            if re.search(cls.DANGEROUS_HTML_PATTERN, value, re.IGNORECASE):
                raise ValueError(f"{field_name} contains HTML tags that may cause security issues")

            if re.search(cls.DANGEROUS_JS_PATTERN, value, re.IGNORECASE):
                raise ValueError(f"{field_name} contains script patterns that may cause security issues")

        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception:
            raise ValueError(f"{field_name} is not a valid URL")

        return value

    @classmethod
    def validate_no_xss(cls, value: str, field_name: str) -> None:
        """
        Validate that a string does not contain XSS patterns.

        Args:
            value (str): Value to validate.
            field_name (str): Name of the field being validated.

        Raises:
            ValueError: If the value contains XSS patterns.

        Examples:
            Safe strings pass validation:

            >>> SecurityValidator.validate_no_xss('Hello World', 'test_field')
            >>> SecurityValidator.validate_no_xss('User: admin@example.com', 'email')
            >>> SecurityValidator.validate_no_xss('Price: $10.99', 'price')

            Empty/None strings are considered safe:

            >>> SecurityValidator.validate_no_xss('', 'empty_field')
            >>> SecurityValidator.validate_no_xss(None, 'none_field') #doctest: +SKIP

            Dangerous HTML tags trigger validation errors:

            >>> SecurityValidator.validate_no_xss('<script>alert(1)</script>', 'test_field')
            Traceback (most recent call last):
                ...
            ValueError: test_field contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<iframe src="evil.com"></iframe>', 'content')
            Traceback (most recent call last):
                ...
            ValueError: content contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<object data="malware.swf"></object>', 'data')
            Traceback (most recent call last):
                ...
            ValueError: data contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<embed src="evil.swf">', 'embed')
            Traceback (most recent call last):
                ...
            ValueError: embed contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<link rel="stylesheet" href="evil.css">', 'style')
            Traceback (most recent call last):
                ...
            ValueError: style contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<meta http-equiv="refresh" content="0;url=evil.com">', 'meta')
            Traceback (most recent call last):
                ...
            ValueError: meta contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<base href="http://evil.com">', 'base')
            Traceback (most recent call last):
                ...
            ValueError: base contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<form action="evil.php">', 'form')
            Traceback (most recent call last):
                ...
            ValueError: form contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<img src="x" onerror="alert(1)">', 'image')
            Traceback (most recent call last):
                ...
            ValueError: image contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<svg onload="alert(1)"></svg>', 'svg')
            Traceback (most recent call last):
                ...
            ValueError: svg contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<video src="x" onerror="alert(1)"></video>', 'video')
            Traceback (most recent call last):
                ...
            ValueError: video contains HTML tags that may cause security issues
            >>> SecurityValidator.validate_no_xss('<audio src="x" onerror="alert(1)"></audio>', 'audio')
            Traceback (most recent call last):
                ...
            ValueError: audio contains HTML tags that may cause security issues
        """
        if not value:
            return  # Empty values are considered safe
        # Check for dangerous HTML tags
        if re.search(cls.DANGEROUS_HTML_PATTERN, value, re.IGNORECASE):
            raise ValueError(f"{field_name} contains HTML tags that may cause security issues")

    @classmethod
    def validate_json_depth(
        cls,
        obj: object,
        max_depth: int | None = None,
        current_depth: int = 0,
    ) -> None:
        """Validate that a JSON‑like structure does not exceed a depth limit.

        A *depth* is counted **only** when we enter a container (`dict` or
        `list`). Primitive values (`str`, `int`, `bool`, `None`, etc.) do not
        increase the depth, but an *empty* container still counts as one level.

        Args:
            obj: Any Python object to inspect recursively.
            max_depth: Maximum allowed depth (defaults to
                :pyattr:`SecurityValidator.MAX_JSON_DEPTH`).
            current_depth: Internal recursion counter. **Do not** set this
                from user code.

        Raises:
            ValueError: If the nesting level exceeds *max_depth*.

        Examples:
            Simple flat dictionary – depth 1: ::

                >>> SecurityValidator.validate_json_depth({'name': 'Alice'})

            Nested dict – depth 2: ::

                >>> SecurityValidator.validate_json_depth(
                ...     {'user': {'name': 'Alice'}}
                ... )

            Mixed dict/list – depth 3: ::

                >>> SecurityValidator.validate_json_depth(
                ...     {'users': [{'name': 'Alice', 'meta': {'age': 30}}]}
                ... )

            Exactly at the default limit (10) – allowed: ::

                >>> deep_10 = {'1': {'2': {'3': {'4': {'5': {'6': {'7': {'8':
                ...     {'9': {'10': 'end'}}}}}}}}}}
                >>> SecurityValidator.validate_json_depth(deep_10)

            One level deeper – rejected: ::

                >>> deep_11 = {'1': {'2': {'3': {'4': {'5': {'6': {'7': {'8':
                ...     {'9': {'10': {'11': 'end'}}}}}}}}}}}
                >>> SecurityValidator.validate_json_depth(deep_11)
                Traceback (most recent call last):
                    ...
                ValueError: JSON structure exceeds maximum depth of 10
        """
        if max_depth is None:
            max_depth = cls.MAX_JSON_DEPTH

        # Only containers count toward depth; primitives are ignored
        if not isinstance(obj, (dict, list)):
            return

        next_depth = current_depth + 1
        if next_depth > max_depth:
            raise ValueError(f"JSON structure exceeds maximum depth of {max_depth}")

        if isinstance(obj, dict):
            for value in obj.values():
                cls.validate_json_depth(value, max_depth, next_depth)
        else:  # obj is a list
            for item in obj:
                cls.validate_json_depth(item, max_depth, next_depth)

    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        """Validate MIME type format

        Args:
            value (str): Value to validate

        Returns:
            str: Value if acceptable

        Raises:
            ValueError: When input is not acceptable

        Examples:
            Empty/None handling:

            >>> SecurityValidator.validate_mime_type('')
            ''
            >>> SecurityValidator.validate_mime_type(None) #doctest: +SKIP

            Valid standard MIME types:

            >>> SecurityValidator.validate_mime_type('text/plain')
            'text/plain'
            >>> SecurityValidator.validate_mime_type('application/json')
            'application/json'
            >>> SecurityValidator.validate_mime_type('image/jpeg')
            'image/jpeg'
            >>> SecurityValidator.validate_mime_type('text/html')
            'text/html'
            >>> SecurityValidator.validate_mime_type('application/pdf')
            'application/pdf'

            Valid vendor-specific MIME types:

            >>> SecurityValidator.validate_mime_type('application/x-custom')
            'application/x-custom'
            >>> SecurityValidator.validate_mime_type('text/x-log')
            'text/x-log'

            Valid MIME types with suffixes:

            >>> SecurityValidator.validate_mime_type('application/vnd.api+json')
            'application/vnd.api+json'
            >>> SecurityValidator.validate_mime_type('image/svg+xml')
            'image/svg+xml'

            Invalid MIME type formats:

            >>> SecurityValidator.validate_mime_type('invalid')
            Traceback (most recent call last):
                ...
            ValueError: Invalid MIME type format
            >>> SecurityValidator.validate_mime_type('text/')
            Traceback (most recent call last):
                ...
            ValueError: Invalid MIME type format
            >>> SecurityValidator.validate_mime_type('/plain')
            Traceback (most recent call last):
                ...
            ValueError: Invalid MIME type format
            >>> SecurityValidator.validate_mime_type('text//plain')
            Traceback (most recent call last):
                ...
            ValueError: Invalid MIME type format
            >>> SecurityValidator.validate_mime_type('text/plain/extra')
            Traceback (most recent call last):
                ...
            ValueError: Invalid MIME type format
            >>> SecurityValidator.validate_mime_type('text plain')
            Traceback (most recent call last):
                ...
            ValueError: Invalid MIME type format
            >>> SecurityValidator.validate_mime_type('<text/plain>')
            Traceback (most recent call last):
                ...
            ValueError: Invalid MIME type format

            Disallowed MIME types (not in whitelist - line 620):

            >>> try:
            ...     SecurityValidator.validate_mime_type('application/evil')
            ... except ValueError as e:
            ...     'not in the allowed list' in str(e)
            True
            >>> try:
            ...     SecurityValidator.validate_mime_type('text/evil')
            ... except ValueError as e:
            ...     'not in the allowed list' in str(e)
            True

            Test MIME type with parameters (line 618):

            >>> try:
            ...     SecurityValidator.validate_mime_type('application/evil; charset=utf-8')
            ... except ValueError as e:
            ...     'Invalid MIME type format' in str(e)
            True
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

    @classmethod
    def validate_shell_parameter(cls, value: str) -> str:
        """Validate and escape shell parameters to prevent command injection.

        Args:
            value (str): Shell parameter to validate

        Returns:
            str: Validated/escaped parameter

        Raises:
            ValueError: If parameter contains dangerous characters in strict mode

        Examples:
            >>> SecurityValidator.validate_shell_parameter('safe_param')
            'safe_param'
            >>> SecurityValidator.validate_shell_parameter('param with spaces')
            'param with spaces'
        """
        if not isinstance(value, str):
            raise ValueError("Parameter must be string")

        # Check for dangerous patterns
        dangerous_chars = re.compile(r"[;&|`$(){}\[\]<>]")
        if dangerous_chars.search(value):
            # Check if validation is strict
            strict_mode = getattr(settings, "validation_strict", True)
            if strict_mode:
                raise ValueError("Parameter contains shell metacharacters")
            # In non-strict mode, escape using shlex
            return shlex.quote(value)

        return value

    @classmethod
    def validate_path(cls, path: str, allowed_roots: Optional[List[str]] = None) -> str:
        """Validate and normalize file paths to prevent directory traversal.

        Args:
            path (str): File path to validate
            allowed_roots (Optional[List[str]]): List of allowed root directories

        Returns:
            str: Validated and normalized path

        Raises:
            ValueError: If path contains traversal attempts or is outside allowed roots

        Examples:
            >>> SecurityValidator.validate_path('/safe/path')
            '/safe/path'
            >>> SecurityValidator.validate_path('http://example.com/file')
            'http://example.com/file'
        """
        if not isinstance(path, str):
            raise ValueError("Path must be string")

        # Skip validation for URI schemes (http://, plugin://, etc.)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", path):
            return path

        try:
            p = Path(path)
            # Check for path traversal
            if ".." in p.parts:
                raise ValueError("Path traversal detected")

            resolved_path = p.resolve()

            # Check against allowed roots
            if allowed_roots:
                allowed = any(str(resolved_path).startswith(str(Path(root).resolve())) for root in allowed_roots)
                if not allowed:
                    raise ValueError("Path outside allowed roots")

            return str(resolved_path)
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid path: {e}")

    @classmethod
    def validate_sql_parameter(cls, value: str) -> str:
        """Validate SQL parameters to prevent SQL injection attacks.

        Args:
            value (str): SQL parameter to validate

        Returns:
            str: Validated/escaped parameter

        Raises:
            ValueError: If parameter contains SQL injection patterns in strict mode

        Examples:
            >>> SecurityValidator.validate_sql_parameter('safe_value')
            'safe_value'
            >>> SecurityValidator.validate_sql_parameter('123')
            '123'
        """
        if not isinstance(value, str):
            return value

        # Check for SQL injection patterns
        sql_patterns = [
            r"[';\"\\]",  # Quote characters
            r"--",  # SQL comments
            r"/\\*.*?\\*/",  # Block comments
            r"\\b(union|select|insert|update|delete|drop|exec|execute)\\b",  # SQL keywords
        ]

        for pattern in sql_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                if getattr(config_settings, "validation_strict", True):
                    raise ValueError("Parameter contains SQL injection patterns")
                # Basic escaping
                value = value.replace("'", "''").replace('"', '""')

        return value

    @classmethod
    def validate_parameter_length(cls, value: str, max_length: int = None) -> str:
        """Validate parameter length against configured limits.

        Args:
            value (str): Parameter to validate
            max_length (int): Maximum allowed length

        Returns:
            str: Parameter if within length limits

        Raises:
            ValueError: If parameter exceeds maximum length

        Examples:
            >>> SecurityValidator.validate_parameter_length('short', 10)
            'short'
        """
        max_len = max_length or getattr(config_settings, "max_param_length", 10000)
        if len(value) > max_len:
            raise ValueError(f"Parameter exceeds maximum length of {max_len}")
        return value

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """Remove control characters and ANSI escape sequences from text.

        Args:
            text (str): Text to sanitize

        Returns:
            str: Sanitized text with control characters removed

        Examples:
            >>> SecurityValidator.sanitize_text('Hello World')
            'Hello World'
            >>> SecurityValidator.sanitize_text('Text\x1b[31mwith\x1b[0mcolors')
            'Textwithcolors'
        """
        if not isinstance(text, str):
            return text

        # Remove ANSI escape sequences
        text = re.sub(r"\x1B\[[0-9;]*[A-Za-z]", "", text)
        # Remove control characters except newlines and tabs
        sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
        return sanitized

    @classmethod
    def sanitize_json_response(cls, data: Any) -> Any:
        """Recursively sanitize JSON response data by removing control characters.

        Args:
            data (Any): JSON data structure to sanitize

        Returns:
            Any: Sanitized data structure with same type as input

        Examples:
            >>> SecurityValidator.sanitize_json_response('clean text')
            'clean text'
            >>> SecurityValidator.sanitize_json_response({'key': 'value'})
            {'key': 'value'}
            >>> SecurityValidator.sanitize_json_response(['item1', 'item2'])
            ['item1', 'item2']
        """
        if isinstance(data, str):
            return cls.sanitize_text(data)
        if isinstance(data, dict):
            return {k: cls.sanitize_json_response(v) for k, v in data.items()}
        if isinstance(data, list):
            return [cls.sanitize_json_response(item) for item in data]
        return data
