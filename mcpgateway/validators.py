# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/validators.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Madhav Kandukuri

SecurityValidator for MCP Gateway
This module re-exports the SecurityValidator class from mcpgateway.common.validators
for backward compatibility.

The canonical location for SecurityValidator is mcpgateway.common.validators.
This module exists to maintain backward compatibility with code that imports from
mcpgateway.validators.

Example usage:
    >>> from mcpgateway.validators import SecurityValidator
    >>> SecurityValidator.sanitize_display_text('<b>Test</b>', 'test')
    '&lt;b&gt;Test&lt;/b&gt;'
    >>> SecurityValidator.validate_name('valid_name-123', 'test')
    'valid_name-123'
    >>> SecurityValidator.validate_identifier('my.test.id_123', 'test')
    'my.test.id_123'
    >>> SecurityValidator.validate_json_depth({'a': {'b': 1}})
    >>> SecurityValidator.validate_json_depth({'a': 1})
"""

# First-Party
# Re-export SecurityValidator from canonical location
# pylint: disable=unused-import
from mcpgateway.common.validators import SecurityValidator  # noqa: F401

__all__ = ["SecurityValidator"]

import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcpgateway.config import settings


class SecurityInputValidator:
    """Security input validation utilities for preventing attacks."""

    @staticmethod
    def validate_shell_parameter(value: str) -> str:
        """Validate and escape shell parameters."""
        if not isinstance(value, str):
            raise ValueError("Parameter must be string")
        
        # Check for dangerous patterns
        dangerous_chars = re.compile(r"[;&|`$(){}\[\]<>]")
        if dangerous_chars.search(value):
            if getattr(settings, 'validation_strict', True):
                raise ValueError("Parameter contains shell metacharacters")
            # Escape using shlex
            return shlex.quote(value)
        
        return value

    @staticmethod
    def validate_path(path: str, allowed_roots: Optional[List[str]] = None) -> str:
        """Validate and normalize file paths."""
        if not isinstance(path, str):
            raise ValueError("Path must be string")
        
        try:
            resolved_path = Path(path).resolve()
            
            # Check for path traversal
            if ".." in Path(path).parts:
                raise ValueError("Path traversal detected")
            
            # Check against allowed roots
            if allowed_roots:
                allowed = any(
                    str(resolved_path).startswith(str(Path(root).resolve()))
                    for root in allowed_roots
                )
                if not allowed:
                    raise ValueError("Path outside allowed roots")
            
            return str(resolved_path)
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid path: {e}")

    @staticmethod
    def validate_sql_parameter(value: str) -> str:
        """Validate SQL parameters for injection attempts."""
        if not isinstance(value, str):
            return value
        
        # Check for SQL injection patterns
        sql_patterns = [
            r"[';\"\\]",  # Quote characters
            r"--",        # SQL comments
            r"/\\*.*?\\*/",  # Block comments
            r"\\b(union|select|insert|update|delete|drop|exec|execute)\\b",  # SQL keywords
        ]
        
        for pattern in sql_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                if getattr(settings, 'validation_strict', True):
                    raise ValueError("Parameter contains SQL injection patterns")
                # Basic escaping
                value = value.replace("'", "''").replace('"', '""')
        
        return value

    @staticmethod
    def validate_parameter_length(value: str, max_length: int = None) -> str:
        """Validate parameter length."""
        max_len = max_length or getattr(settings, 'max_param_length', 10000)
        if len(value) > max_len:
            raise ValueError(f"Parameter exceeds maximum length of {max_len}")
        return value


class OutputSanitizer:
    """Output sanitization utilities."""

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Remove control characters from text output."""
        if not isinstance(text, str):
            return text
        
        # Remove ANSI escape sequences
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        # Remove control characters except newlines and tabs
        sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
        return sanitized

    @staticmethod
    def sanitize_json_response(data: Any) -> Any:
        """Recursively sanitize JSON response data."""
        if isinstance(data, str):
            return OutputSanitizer.sanitize_text(data)
        elif isinstance(data, dict):
            return {k: OutputSanitizer.sanitize_json_response(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [OutputSanitizer.sanitize_json_response(item) for item in data]
        return data