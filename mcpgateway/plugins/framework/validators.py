# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/validators.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Self-contained security validation for the plugin framework.

Contains only the validation methods actually used by framework models
(MCPClientConfig), with hardcoded defaults to avoid any dependency on
mcpgateway.config.settings.

Examples:
    >>> SecurityValidator.validate_url("https://example.com")
    'https://example.com'
"""

# Standard
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Defaults matching the gateway's SecurityValidator
_ALLOWED_URL_SCHEMES = ("http://", "https://", "ws://", "wss://")
_MAX_URL_LENGTH = 2048


class SecurityValidator:
    """Minimal security validator for the plugin framework.

    Only includes methods used by MCPClientConfig validation.

    Examples:
        >>> SecurityValidator.validate_url("https://example.com")
        'https://example.com'
        >>> SecurityValidator.validate_url("http://localhost:8080/mcp")
        'http://localhost:8080/mcp'
    """

    @staticmethod
    def validate_url(value: str, field_name: str = "URL") -> str:
        """Validate URLs for allowed schemes and basic structure.

        Args:
            value: URL string to validate.
            field_name: Name of the field being validated (for error messages).

        Returns:
            The validated URL string.

        Raises:
            ValueError: If the URL is empty, too long, uses a disallowed
                scheme, or is structurally invalid.

        Examples:
            >>> SecurityValidator.validate_url("https://example.com")
            'https://example.com'
            >>> SecurityValidator.validate_url("http://localhost:9000/sse")
            'http://localhost:9000/sse'
            >>> SecurityValidator.validate_url("")
            Traceback (most recent call last):
                ...
            ValueError: URL cannot be empty
            >>> SecurityValidator.validate_url("ftp://example.com")
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
        """
        if not value:
            raise ValueError(f"{field_name} cannot be empty")

        if len(value) > _MAX_URL_LENGTH:
            raise ValueError(f"{field_name} exceeds maximum length of {_MAX_URL_LENGTH}")

        if not any(value.lower().startswith(scheme) for scheme in _ALLOWED_URL_SCHEMES):
            raise ValueError(f"{field_name} must start with one of: {', '.join(_ALLOWED_URL_SCHEMES)}")

        if "\r" in value or "\n" in value:
            raise ValueError(f"{field_name} contains line breaks which are not allowed")

        try:
            result = urlparse(value)
            if not all([result.scheme, result.netloc]):
                raise ValueError(f"{field_name} is not a valid URL")
        except ValueError:
            raise
        except Exception:
            raise ValueError(f"{field_name} is not a valid URL")

        return value
