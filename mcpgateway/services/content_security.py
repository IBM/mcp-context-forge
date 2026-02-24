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
import logging
from typing import Optional, Union

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


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
        super().__init__(f"{content_type} size ({actual_size} bytes) exceeds maximum allowed size ({max_size} bytes)")


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
            # Log security violation
            logger.warning(f"Resource size limit exceeded: " f"size={actual_size}, limit={self.max_resource_size}, " f"uri={uri}, user={user_email}, ip={ip_address}")
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
            # Log security violation
            logger.warning(f"Prompt size limit exceeded: " f"size={actual_size}, limit={self.max_prompt_size}, " f"name={name}, user={user_email}, ip={ip_address}")
            raise ContentSizeError("Prompt template", actual_size, self.max_prompt_size)

        logger.debug(f"Prompt size validation passed: {actual_size} bytes")


# Singleton instance
_content_security_service: Optional[ContentSecurityService] = None


def get_content_security_service() -> ContentSecurityService:
    """Get or create the singleton ContentSecurityService instance.

    Returns:
        ContentSecurityService: The singleton instance

    Examples:
        >>> service1 = get_content_security_service()
        >>> service2 = get_content_security_service()
        >>> service1 is service2
        True
    """
    global _content_security_service  # pylint: disable=global-statement
    if _content_security_service is None:
        _content_security_service = ContentSecurityService()
    return _content_security_service
