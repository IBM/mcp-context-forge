# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/correlation_id.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: MCP Gateway Contributors

Correlation ID (Request ID) Utilities.

This module provides async-safe utilities for managing correlation IDs (also known as
request IDs) throughout the request lifecycle using Python's contextvars.

The correlation ID is a unique identifier that tracks a single request as it flows
through all components of the system (HTTP → Middleware → Services → Plugins → Logs).

Key concepts:
- ContextVar provides per-request isolation in async environments
- Correlation IDs can be client-provided (X-Correlation-ID header) or auto-generated
- The same ID is used as request_id throughout logs, services, and plugin contexts
- Thread-safe and async-safe (no cross-contamination between concurrent requests)
"""

# Standard
from contextvars import ContextVar
import logging
from typing import Dict, Optional
import uuid

logger = logging.getLogger(__name__)

# Context variable for storing correlation ID (request ID) per-request
# This is async-safe and provides automatic isolation between concurrent requests
_correlation_id_context: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID (request ID) from context.

    Returns the correlation ID for the current async task/request. Each request
    has its own isolated context, so concurrent requests won't interfere.

    Returns:
        Optional[str]: The correlation ID if set, None otherwise

    Example:
        >>> clear_correlation_id()  # Start fresh
        >>> get_correlation_id() is None
        True
        >>> set_correlation_id("test-123")
        >>> get_correlation_id()
        'test-123'
        >>> clear_correlation_id()
    """
    return _correlation_id_context.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID (request ID) for the current context.

    Stores the correlation ID in a context variable that's automatically isolated
    per async task. This ID will be used as request_id throughout the system.

    Args:
        correlation_id: The correlation ID to set (typically a UUID or client-provided ID)

    Example:
        >>> set_correlation_id("my-request-id")
        >>> get_correlation_id()
        'my-request-id'
        >>> clear_correlation_id()
    """
    _correlation_id_context.set(correlation_id)


def clear_correlation_id() -> None:
    """Clear the correlation ID (request ID) from the current context.

    Should be called at the end of request processing to clean up context.
    In practice, FastAPI middleware automatically handles context cleanup.

    Note: This is optional as ContextVar automatically cleans up when the
    async task completes.

    Example:
        >>> set_correlation_id("temp-id")
        >>> get_correlation_id() is not None
        True
        >>> clear_correlation_id()
        >>> get_correlation_id() is None
        True
    """
    _correlation_id_context.set(None)


def generate_correlation_id() -> str:
    """Generate a new correlation ID (UUID4 hex format).

    Creates a new random UUID suitable for use as a correlation ID.
    Uses UUID4 which provides 122 bits of randomness.

    Returns:
        str: A new UUID in hex format (32 characters, no hyphens)

    Example:
        >>> cid = generate_correlation_id()
        >>> len(cid) == 32
        True
        >>> cid.isalnum()
        True
    """
    return uuid.uuid4().hex


def extract_correlation_id_from_headers(headers: Dict[str, str], header_name: str = "X-Correlation-ID") -> Optional[str]:
    """Extract correlation ID from HTTP headers.

    Searches for the correlation ID header (case-insensitive) and returns its value.
    Validates that the value is non-empty after stripping whitespace.

    Args:
        headers: Dictionary of HTTP headers
        header_name: Name of the correlation ID header (default: X-Correlation-ID)

    Returns:
        Optional[str]: The correlation ID if found and valid, None otherwise

    Example:
        >>> headers = {"X-Correlation-ID": "abc-123"}
        >>> extract_correlation_id_from_headers(headers)
        'abc-123'

        >>> headers = {"x-correlation-id": "def-456"}  # Case insensitive
        >>> extract_correlation_id_from_headers(headers)
        'def-456'
    """
    # Headers can be accessed case-insensitively in FastAPI/Starlette
    for key, value in headers.items():
        if key.lower() == header_name.lower():
            correlation_id = value.strip()
            if correlation_id:
                return correlation_id
    return None


def get_or_generate_correlation_id() -> str:
    """Get the current correlation ID or generate a new one if not set.

    This is a convenience function that ensures you always have a correlation ID.
    If the current context doesn't have a correlation ID, it generates and sets
    a new one.

    Returns:
        str: The correlation ID (either existing or newly generated)

    Example:
        >>> # First call generates new ID
        >>> id1 = get_or_generate_correlation_id()
        >>> # Second call returns same ID
        >>> id2 = get_or_generate_correlation_id()
        >>> assert id1 == id2
    """
    correlation_id = get_correlation_id()
    if not correlation_id:
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)
    return correlation_id


def validate_correlation_id(correlation_id: Optional[str], max_length: int = 255) -> bool:
    """Validate a correlation ID for safety and length.

    Checks that the correlation ID is:
    - Non-empty after stripping whitespace
    - Within the maximum length limit
    - Contains only safe characters (alphanumeric, hyphens, underscores)

    Args:
        correlation_id: The correlation ID to validate
        max_length: Maximum allowed length (default: 255)

    Returns:
        bool: True if valid, False otherwise

    Example:
        >>> validate_correlation_id("abc-123")
        True
        >>> validate_correlation_id("abc 123")  # Spaces not allowed
        False
        >>> validate_correlation_id("a" * 300)  # Too long
        False
    """
    if not correlation_id or not correlation_id.strip():
        return False

    correlation_id = correlation_id.strip()

    if len(correlation_id) > max_length:
        logger.warning(f"Correlation ID too long: {len(correlation_id)} > {max_length}")
        return False

    # Allow alphanumeric, hyphens, and underscores only
    if not all(c.isalnum() or c in ("-", "_") for c in correlation_id):
        logger.warning(f"Correlation ID contains invalid characters: {correlation_id}")
        return False

    return True
