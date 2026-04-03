# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/content_security.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Content Security Service for ContextForge.
Provides validation for user-submitted content including size limits,
MIME type restrictions, and malicious pattern detection.

This module implements Content Size Limits and MIME Type Restrictions (US-2)
from issue #538.
"""

# Standard
import hashlib
import logging
import threading
from typing import List, Optional, Union

# First-Party
from mcpgateway.config import settings

# Import metrics with error handling for test environments
try:
    # First-Party
    from mcpgateway.services.metrics import content_size_violations_counter, content_type_violations_counter
except ImportError:
    # Metrics not available in test environment - create no-op counters
    class NoOpCounter:
        """No-op counter for test environments where metrics are unavailable."""

        def labels(self, **_kwargs):
            """Return self to allow method chaining.

            Args:
                **_kwargs: Arbitrary keyword arguments (ignored)

            Returns:
                self: Returns self for method chaining
            """
            return self

        def inc(self, _amount=1):
            """No-op increment method."""

    content_size_violations_counter = NoOpCounter()
    content_type_violations_counter = NoOpCounter()

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


class ContentTypeError(Exception):
    """Raised when a resource MIME type is not in the allowed list."""

    def __init__(self, mime_type: str, allowed_types: List[str]):
        """Initialize ContentTypeError with MIME type details.

        Args:
            mime_type: The disallowed MIME type that was submitted
            allowed_types: List of allowed MIME types from configuration

        Examples:
            >>> err = ContentTypeError("application/evil", ["text/plain", "text/markdown"])
            >>> err.mime_type
            'application/evil'
            >>> err.allowed_types
            ['text/plain', 'text/markdown']
            >>> "application/evil" in str(err)
            True
        """
        self.mime_type = mime_type
        self.allowed_types = allowed_types

        # Show up to 5 allowed types in the message for readability
        display = ", ".join(allowed_types[:5])
        if len(allowed_types) > 5:
            display += f", ... ({len(allowed_types)} total)"

        super().__init__(f"MIME type '{mime_type}' is not allowed. Allowed types: {display}")


class ContentSecurityService:
    """Service for validating content security constraints.

    This service provides validation for:
    - Content size limits (US-1)
    - MIME type restrictions (US-2)
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
        logger.info(
            "ContentSecurityService initialized",
            extra={
                "max_resource_size": self.max_resource_size,
                "max_prompt_size": self.max_prompt_size,
                "strict_mime_validation": settings.content_strict_mime_validation,
                "allowed_resource_mimetypes_count": len(settings.content_allowed_resource_mimetypes),
            },
        )

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
            # Increment Prometheus metric
            content_size_violations_counter.labels(content_type="resource").inc()

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
            # Increment Prometheus metric
            content_size_violations_counter.labels(content_type="prompt").inc()

            # Log security violation with sanitized PII
            sanitized = _sanitize_pii_for_logging(user_email, ip_address)
            logger.warning("Prompt size limit exceeded", extra={"actual_size": actual_size, "max_size": self.max_prompt_size, "content_type": "prompt", "name_provided": name is not None, **sanitized})
            raise ContentSizeError("Prompt template", actual_size, self.max_prompt_size)

        logger.debug(f"Prompt size validation passed: {actual_size} bytes")

    def validate_resource_mime_type(
        self,
        mime_type: Optional[str],
        uri: Optional[str] = None,
        user_email: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Validate a resource MIME type against the configured allowlist.

        When :attr:`~mcpgateway.config.Settings.content_strict_mime_validation`
        is ``True``, only MIME types explicitly listed in the allowlist are accepted.
        This includes vendor types (``application/x-*``, ``text/x-*``) and
        structured-syntax suffix types (e.g. ``application/vnd.api+json``) which
        must be explicitly added to the allowlist if needed.

        When :attr:`~mcpgateway.config.Settings.content_strict_mime_validation`
        is ``False`` the method logs a warning but does **not** raise, enabling
        a log-only migration mode.

        Args:
            mime_type: The MIME type declared by the caller.  ``None`` or empty
                string is accepted without validation.
            uri: Optional resource URI included in log output (not logged raw).
            user_email: Optional user e-mail for PII-safe audit logging.
            ip_address: Optional client IP for PII-safe audit logging.

        Raises:
            ContentTypeError: If ``mime_type`` is not in the allowlist and
                ``content_strict_mime_validation`` is ``True``.

        Examples:
            >>> service = ContentSecurityService()
            >>> service.validate_resource_mime_type("text/plain")  # OK if in allowlist
            >>> service.validate_resource_mime_type(None)          # OK - no type declared
            >>> from unittest.mock import patch
            >>> with patch("mcpgateway.services.content_security.settings") as mock_settings:
            ...     mock_settings.content_strict_mime_validation = True
            ...     mock_settings.content_allowed_resource_mimetypes = ["text/plain"]
            ...     try:
            ...         service.validate_resource_mime_type("application/evil")
            ...     except ContentTypeError as e:
            ...         print("blocked:", e.mime_type)
            blocked: application/evil
            >>> # Vendor types must be explicitly in allowlist
            >>> with patch("mcpgateway.services.content_security.settings") as mock_settings:
            ...     mock_settings.content_strict_mime_validation = True
            ...     mock_settings.content_allowed_resource_mimetypes = ["text/plain"]
            ...     try:
            ...         service.validate_resource_mime_type("application/x-custom")
            ...     except ContentTypeError as e:
            ...         print("vendor type blocked:", e.mime_type)
            vendor type blocked: application/x-custom
        """
        # Allow absent MIME types - callers may omit the field legitimately
        if not mime_type:
            return

        allowed_types: List[str] = settings.content_allowed_resource_mimetypes
        strict = settings.content_strict_mime_validation

        # Strip parameters from MIME type for comparison (e.g., "text/plain; charset=utf-8" -> "text/plain")
        base_mime_type = mime_type.split(";")[0].strip()

        # Fast path: exact match in allowlist (check both full and base MIME type)
        if mime_type in allowed_types or base_mime_type in allowed_types:
            logger.debug("Resource MIME type validation passed: %s", mime_type)
            return

        # Violation detected — always increment metric and log regardless of mode.
        # In strict mode, also raise to block the request.
        content_type_violations_counter.labels(content_type="resource").inc()

        sanitized = _sanitize_pii_for_logging(user_email, ip_address)
        logger.warning(
            "Resource MIME type not in allowlist%s",
            " (log-only mode, not blocking)" if not strict else "",
            extra={
                "mime_type": mime_type,
                "allowed_count": len(allowed_types),
                "uri_provided": uri is not None,
                "strict": strict,
                **sanitized,
            },
        )

        if strict:
            raise ContentTypeError(mime_type, allowed_types)


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
