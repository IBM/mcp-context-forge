# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/log_sanitizer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Log Sanitization Utility.

This module provides utilities to sanitize untrusted input before logging to prevent
log injection attacks. Control characters like newlines (\n, \r) can be used to inject
fabricated log entries when logging unauthenticated user input.

Security Context:
    Log injection occurs when an attacker includes control characters (especially newlines)
    in query parameters, headers, or other user-controlled input that gets logged. When
    URL-decoded by the ASGI framework, these characters are passed to Python's logging
    module which does not sanitize them, allowing injection of fake log lines.

    Example attack:
        GET /oauth/callback?error=foo&error_description=bar%0ACRITICAL:root:SECURITY+BREACH

    This produces two log lines:
        WARNING:oauth:OAuth error: bar
        CRITICAL:root:SECURITY BREACH

    The second line is entirely fabricated by the attacker.

Mitigation:
    This utility strips or replaces control characters before logging. Structured logging
    (JSON format) also mitigates this by encapsulating the full message as a single field.

Examples:
    >>> from mcpgateway.utils.log_sanitizer import sanitize_for_log
    >>> sanitize_for_log("normal text")
    'normal text'
    >>> sanitize_for_log("text with\\nnewline")
    'text with newline'
    >>> sanitize_for_log("text with\\r\\nCRLF")
    'text with  CRLF'
    >>> sanitize_for_log("tab\\there")
    'tab here'
    >>> sanitize_for_log(None)
    'None'
    >>> sanitize_for_log(123)
    '123'
"""

# Standard
import re
from typing import Any, Optional

# Regex pattern to match control characters that could be used for log injection
# Includes: \n (LF), \r (CR), \t (TAB), \v (VT), \f (FF), and other C0/C1 control chars
# We preserve space (0x20) as it's safe and commonly used
CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize_for_log(value: Any, replacement: str = " ") -> str:
    """
    Sanitize a value for safe logging by removing control characters.

    This function converts the input to a string and removes all control characters
    that could be used for log injection attacks. Control characters include newlines,
    carriage returns, tabs, and other non-printable characters.

    Args:
        value: The value to sanitize. Can be any type; will be converted to string.
        replacement: The string to replace control characters with. Defaults to a space.
                    Use empty string '' to remove control characters entirely.

    Returns:
        A sanitized string safe for logging, with control characters replaced.

    Security Notes:
        - Always use this function when logging unauthenticated user input
        - Particularly important for query parameters, headers, and form data
        - Does not protect against other injection types (SQL, XSS, etc.)
        - Structured logging (JSON) provides additional protection

    Examples:
        >>> sanitize_for_log("error: bad scope\\nCRITICAL:root:FAKE LOG")
        'error: bad scope CRITICAL:root:FAKE LOG'
        >>> sanitize_for_log("path/to/file\\x00null")
        'path/to/file null'
        >>> sanitize_for_log("normal text")
        'normal text'
        >>> sanitize_for_log(None)
        'None'
        >>> sanitize_for_log({"key": "value"})
        "{'key': 'value'}"
    """
    # Convert to string first (handles None, numbers, objects, etc.)
    str_value = str(value)

    # Replace all control characters with the replacement string
    sanitized = CONTROL_CHARS_PATTERN.sub(replacement, str_value)

    return sanitized


def sanitize_dict_for_log(data: dict[str, Any], replacement: str = " ") -> dict[str, str]:
    """
    Sanitize all values in a dictionary for safe logging.

    This is useful when logging multiple related values, such as query parameters
    or form data. Each value is sanitized individually.

    Args:
        data: Dictionary with string keys and any values
        replacement: The string to replace control characters with

    Returns:
        A new dictionary with all values sanitized as strings

    Examples:
        >>> sanitize_dict_for_log({"error": "foo", "desc": "bar\\nFAKE"})
        {'error': 'foo', 'desc': 'bar FAKE'}
        >>> sanitize_dict_for_log({"count": 42, "name": "test\\ttab"})
        {'count': '42', 'name': 'test tab'}
    """
    return {key: sanitize_for_log(value, replacement) for key, value in data.items()}


def sanitize_optional(value: Optional[Any], replacement: str = " ") -> Optional[str]:
    """
    Sanitize an optional value, preserving None.

    This is useful when you want to maintain None as None rather than converting
    it to the string "None".

    Args:
        value: The value to sanitize, or None
        replacement: The string to replace control characters with

    Returns:
        Sanitized string if value is not None, otherwise None

    Examples:
        >>> sanitize_optional("text\\nwith newline")
        'text with newline'
        >>> sanitize_optional(None)
        >>> sanitize_optional(None) is None
        True
    """
    if value is None:
        return None
    return sanitize_for_log(value, replacement)
