# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/content_security.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Content Security Service for ContextForge.
Provides validation for user-submitted content including size limits,
MIME type restrictions, and malicious pattern detection.

This module implements (Content Size Limits) from issue #538.
"""

# Standard
import hashlib
import logging
import threading
from typing import Optional, Union

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


def _sanitize_pii_for_logging(user_email: Optional[str] = None, ip_address: Optional[str] = None) -> dict:
    """Sanitize PII data for secure logging.

    Args:
        user_email: User email to sanitize (returns first 8 chars of SHA256 hash)
        ip_address: IP address to sanitize (masks last octet)

    Returns:
        Dictionary with sanitized values suitable for logging

    Examples:
        >>> result = _sanitize_pii_for_logging("user@example.com", "192.168.1.100")
        >>> 'user_hash' in result and 'ip_subnet' in result
        True
        >>> result = _sanitize_pii_for_logging(None, None)
        >>> result
        {'user_hash': None, 'ip_subnet': None}
    """
    user_hash = None
    if user_email:
        user_hash = hashlib.sha256(user_email.encode()).hexdigest()[:8]

    ip_subnet = None
    if ip_address:
        # Mask last octet for IPv4, or last segment for IPv6
        if ":" in ip_address:  # IPv6
            parts = ip_address.split(":")
            ip_subnet = ":".join(parts[:-1]) + ":xxxx"
        else:  # IPv4
            ip_subnet = ip_address.rsplit(".", 1)[0] + ".xxx"

    return {"user_hash": user_hash, "ip_subnet": ip_subnet}


def _format_bytes(bytes_val: int) -> str:
    """Format bytes as human-readable size.

    Args:
        bytes_val: Size in bytes

    Returns:
        Human-readable size string (e.g., "195.3 KB")

    Examples:
        >>> _format_bytes(1024)
        '1.0 KB'
        >>> _format_bytes(1536)
        '1.5 KB'
        >>> _format_bytes(1048576)
        '1.0 MB'
        >>> _format_bytes(500)
        '500 B'
    """
    if bytes_val < 1024:
        return f"{bytes_val} B"

    size_kb = bytes_val / 1024.0
    if size_kb < 1024:
        return f"{size_kb:.1f} KB"

    size_mb = size_kb / 1024.0
    if size_mb < 1024:
        return f"{size_mb:.1f} MB"

    size_gb = size_mb / 1024.0
    return f"{size_gb:.1f} GB"


class ContentSizeError(Exception):
    """Raised when content exceeds size limits."""

    def __init__(self, content_type: str, actual_size: int, max_size: int):
        """Initialize ContentSizeError with size details.

        Args:
            content_type: Type of content (e.g., "Resource content", "Prompt template")
            actual_size: Actual size of the content in bytes
            max_size: Maximum allowed size in bytes
        """
        self.content_type = content_type
        self.actual_size = actual_size
        self.max_size = max_size

        # Format sizes for human readability
        actual_formatted = _format_bytes(actual_size)
        max_formatted = _format_bytes(max_size)

        super().__init__(f"{content_type} size ({actual_formatted}) exceeds " f"maximum allowed size ({max_formatted})")


class ContentSecurityService:
    """Service for validating content security constraints.

    This service provides validation for:
    - Content size limits
    - MIME type restrictions (US-2, future)
    - Malicious pattern detection (US-3, future)
    - Template syntax validation (US-4, future)

    Examples:
        >>> service = ContentSecurityService()
        >>> service.validate_resource_size("x" * 50000)  # 50KB - OK
        >>> try:
        ...     service.validate_resource_size("x" * 200000)  # 200KB - Too large
        ... except ContentSizeError as e:
        ...     print(f"Error: {e.actual_size} > {e.max_size}")
        Error: 200000 > 102400
    """

    def __init__(self):
        """Initialize the content security service."""
        self.max_resource_size = settings.content_max_resource_size
        self.max_prompt_size = settings.content_max_prompt_size
        logger.info("ContentSecurityService initialized: " f"max_resource_size={self.max_resource_size}, " f"max_prompt_size={self.max_prompt_size}")

    def validate_resource_size(self, content: Union[str, bytes], uri: Optional[str] = None, user_email: Optional[str] = None, ip_address: Optional[str] = None) -> None:
        """Validate resource content size.

        Args:
            content: The resource content to validate (string or bytes)
            uri: Optional resource URI for logging
            user_email: Optional user email for logging
            ip_address: Optional IP address for logging

        Raises:
            ContentSizeError: If content exceeds maximum size

        Examples:
            >>> service = ContentSecurityService()
            >>> service.validate_resource_size("small content")  # OK
            >>> try:
            ...     service.validate_resource_size("x" * 200000)
            ... except ContentSizeError:
            ...     print("Too large")
            Too large
        """
        content_bytes = content.encode("utf-8") if isinstance(content, str) else content
        actual_size = len(content_bytes)

        if actual_size > self.max_resource_size:
            # Log security violation with sanitized PII
            sanitized = _sanitize_pii_for_logging(user_email, ip_address)
            logger.warning(
                "Resource size limit exceeded", extra={"actual_size": actual_size, "max_size": self.max_resource_size, "content_type": "resource", "uri_provided": uri is not None, **sanitized}
            )
            raise ContentSizeError("Resource content", actual_size, self.max_resource_size)

        logger.debug(f"Resource size validation passed: {actual_size} bytes")

    def validate_prompt_size(self, template: str, name: Optional[str] = None, user_email: Optional[str] = None, ip_address: Optional[str] = None) -> None:
        """Validate prompt template size.

        Args:
            template: The prompt template to validate
            name: Optional prompt name for logging
            user_email: Optional user email for logging
            ip_address: Optional IP address for logging

        Raises:
            ContentSizeError: If template exceeds maximum size

        Examples:
            >>> service = ContentSecurityService()
            >>> service.validate_prompt_size("Hello {{user}}")  # OK
            >>> try:
            ...     service.validate_prompt_size("x" * 20000)
            ... except ContentSizeError:
            ...     print("Too large")
            Too large
        """
        template_bytes = template.encode("utf-8") if isinstance(template, str) else template
        actual_size = len(template_bytes)

        if actual_size > self.max_prompt_size:
            # Log security violation with sanitized PII
            sanitized = _sanitize_pii_for_logging(user_email, ip_address)
            logger.warning("Prompt size limit exceeded", extra={"actual_size": actual_size, "max_size": self.max_prompt_size, "content_type": "prompt", "name_provided": name is not None, **sanitized})
            raise ContentSizeError("Prompt template", actual_size, self.max_prompt_size)

        logger.debug(f"Prompt size validation passed: {actual_size} bytes")


# Singleton instance with thread-safe initialization
_content_security_service: Optional[ContentSecurityService] = None
_content_security_service_lock = threading.Lock()


def get_content_security_service() -> ContentSecurityService:
    """Get or create the singleton ContentSecurityService instance.

    Thread-safe singleton implementation using double-checked locking pattern
    to prevent race conditions (CWE-362).

    Returns:
        ContentSecurityService: The singleton instance

    Examples:
        >>> service1 = get_content_security_service()
        >>> service2 = get_content_security_service()
        >>> service1 is service2
        True
    """
    global _content_security_service  # pylint: disable=global-statement

    # First check (without lock for performance)
    if _content_security_service is None:
        # Acquire lock for thread-safe initialization
        with _content_security_service_lock:
            # Second check (with lock to prevent race condition)
            if _content_security_service is None:
                _content_security_service = ContentSecurityService()

    return _content_security_service


def reset_content_security_service() -> None:
    """Reset the singleton instance so it re-reads settings on next access.

    Intended for test teardown when monkeypatching size limits.
    """
    global _content_security_service  # pylint: disable=global-statement
    with _content_security_service_lock:
        _content_security_service = None
