# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

Common MCP Gateway Configuration settings used across subpackages.
This module defines configuration settings for the MCP Gateway using Pydantic.
It loads configuration from environment variables with sensible defaults.
"""

# Standard
from functools import lru_cache

# Third-Party
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Validation settings for the security validator."""

    # Validation patterns for safe display (configurable)
    validation_dangerous_html_pattern: str = (
        r"<(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)\b|</*(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)>"
    )

    validation_dangerous_js_pattern: str = r"(?i)(?:^|\s|[\"'`<>=])(javascript:|vbscript:|data:\s*[^,]*[;\s]*(javascript|vbscript)|\bon[a-z]+\s*=|<\s*script\b)"

    validation_allowed_url_schemes: list[str] = ["http://", "https://", "ws://", "wss://"]

    # Character validation patterns
    validation_name_pattern: str = r"^[a-zA-Z0-9_.\-\s]+$"  # Allow spaces for names
    validation_identifier_pattern: str = r"^[a-zA-Z0-9_\-\.]+$"  # No spaces for IDs
    validation_safe_uri_pattern: str = r"^[a-zA-Z0-9_\-.:/?=&%{}]+$"
    validation_unsafe_uri_pattern: str = r'[<>"\'\\]'
    validation_tool_name_pattern: str = r"^[a-zA-Z][a-zA-Z0-9._-]*$"  # MCP tool naming
    validation_tool_method_pattern: str = r"^[a-zA-Z][a-zA-Z0-9_\./-]*$"

    # MCP-compliant size limits (configurable via env)
    validation_max_name_length: int = 255
    validation_max_description_length: int = 8192  # 8KB
    validation_max_template_length: int = 65536  # 64KB
    validation_max_content_length: int = 1048576  # 1MB
    validation_max_json_depth: int = 10
    validation_max_url_length: int = 2048
    validation_max_rpc_param_size: int = 262144  # 256KB

    validation_max_method_length: int = 128

    # Allowed MIME types
    validation_allowed_mime_types: list[str] = [
        "text/plain",
        "text/html",
        "text/css",
        "text/markdown",
        "text/javascript",
        "application/json",
        "application/xml",
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/svg+xml",
        "application/octet-stream",
    ]

    # Rate limiting
    validation_max_requests_per_minute: int = 60

    # CLI settings
    plugins_cli_markup_mode: str | None = None
    plugins_cli_completion: bool = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: A cached instance of the Settings class.

    Examples:
        >>> settings = get_settings()
        >>> isinstance(settings, Settings)
        True
        >>> # Second call returns the same cached instance
        >>> settings2 = get_settings()
        >>> settings is settings2
        True
    """
    # Instantiate a fresh Pydantic Settings object,
    # loading from env vars or .env exactly once.
    cfg = Settings()
    # Validate that transport_type is correct; will
    # raise if mis-configured.
    # cfg.validate_transport()
    # Ensure sqlite DB directories exist if needed.
    # cfg.validate_database()
    # Return the one-and-only Settings instance (cached).
    return cfg


# Create settings instance
settings = get_settings()
