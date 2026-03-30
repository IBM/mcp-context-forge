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
import re
import threading
from typing import Dict, List, Optional, Union

# First-Party
from mcpgateway.config import settings

# Import metrics with error handling for test environments
try:
    # First-Party
    from mcpgateway.services.metrics import (
        content_pattern_violations_counter,
        content_size_violations_counter,
        content_type_violations_counter,
    )
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
    content_pattern_violations_counter = NoOpCounter()

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


class ContentPatternError(Exception):
    """Raised when content contains malicious patterns.

    This exception is raised when the content security service detects
    patterns that match known malicious content signatures such as XSS,
    template injection, or command injection attempts.

    Attributes:
        pattern_matched: The regex pattern that matched the malicious content
        content_snippet: A snippet of the content around the match location
        violation_type: Type of security violation (xss, template_injection, command_injection, etc.)
        content_type: Type of content being validated (resource, prompt)

    Examples:
        >>> try:
        ...     raise ContentPatternError(
        ...         pattern_matched="<script[^>]*>",
        ...         content_snippet="<script>alert(1)</script>",
        ...         violation_type="xss",
        ...         content_type="resource"
        ...     )
        ... except ContentPatternError as e:
        ...     print(e.violation_type)
        xss
        >>> err = ContentPatternError("<script>", "<script>alert(1)</script>", "xss", "resource")
        >>> err.pattern_matched
        '<script>'
        >>> err.violation_type
        'xss'
        >>> "Malicious pattern detected" in str(err)
        True
    """

    def __init__(self, pattern_matched: str, content_snippet: str, violation_type: str, content_type: str = "content"):
        """Initialize ContentPatternError with pattern details.

        Args:
            pattern_matched: The regex pattern that matched
            content_snippet: Snippet of content around the match
            violation_type: Type of violation (xss, template_injection, command_injection, sql_injection, unknown)
            content_type: Type of content (resource, prompt)
        """
        self.pattern_matched = pattern_matched
        self.content_snippet = content_snippet
        self.violation_type = violation_type
        self.content_type = content_type

        # Truncate snippet if too long for error message
        max_snippet = 50
        display_snippet = content_snippet[:max_snippet]
        if len(content_snippet) > max_snippet:
            display_snippet += "..."

        super().__init__(f"Malicious pattern detected in {content_type}: " f"{violation_type} pattern matched. " f"Content snippet: '{display_snippet}'")


class ContentSecurityService:
    """Service for validating content security constraints.

    This service provides validation for:
    - Content size limits
    - MIME type restrictions (US-2)
    - Malicious pattern detection (future)
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

        # Pattern detection - compile patterns once at startup for performance
        self._pattern_cache: Dict[str, re.Pattern] = {}
        self._compile_patterns()

        logger.info(
            "ContentSecurityService initialized",
            extra={
                "max_resource_size": self.max_resource_size,
                "max_prompt_size": self.max_prompt_size,
                "strict_mime_validation": settings.content_strict_mime_validation,
                "allowed_resource_mimetypes_count": len(settings.content_allowed_resource_mimetypes),
                "pattern_detection_enabled": settings.content_pattern_detection_enabled,
                "pattern_validation_mode": settings.content_pattern_validation_mode,
                "compiled_patterns_count": len(self._pattern_cache),
            },
        )

    def _compile_patterns(self) -> None:
        """Compile regex patterns once at startup for performance.

        This method compiles all configured malicious patterns into regex objects
        and caches them for reuse. Pattern compilation is expensive, so doing it
        once at startup provides ~10x performance improvement over compiling on
        each validation.

        The patterns are compiled with IGNORECASE and MULTILINE flags to catch
        variations in casing and patterns that span multiple lines.

        Raises:
            re.error: If any pattern has invalid regex syntax
        """
        if not settings.content_pattern_detection_enabled:
            logger.info("Pattern detection disabled - skipping pattern compilation")
            return

        patterns = settings.content_blocked_patterns
        logger.info(f"Compiling {len(patterns)} malicious patterns for detection")

        for pattern_str in patterns:
            try:
                # Compile with IGNORECASE and MULTILINE for comprehensive detection
                compiled = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
                self._pattern_cache[pattern_str] = compiled
                logger.debug(f"Compiled pattern: {pattern_str[:50]}...")
            except re.error as e:
                logger.error(
                    f"Failed to compile pattern: {pattern_str[:50]}...",
                    extra={"error": str(e), "pattern": pattern_str},
                )
                # Continue with other patterns even if one fails
                continue

        logger.info(f"Pattern compilation complete: {len(self._pattern_cache)}/{len(patterns)} patterns compiled successfully")

    def _classify_violation(self, pattern: str) -> str:
        """Classify a matched pattern into a violation type.

        This method analyzes the matched pattern to determine what type of
        security violation it represents. This classification is used for:
        - Detailed logging and metrics
        - Security incident categorization
        - Targeted remediation guidance

        Args:
            pattern: The regex pattern that matched the content

        Returns:
            str: Violation type - one of:
                - "xss": Cross-site scripting patterns
                - "template_injection": Template injection patterns
                - "command_injection": Command injection patterns
                - "sql_injection": SQL injection patterns
                - "unknown": Pattern doesn't match known categories

        Examples:
            >>> service = ContentSecurityService()
            >>> service._classify_violation("<script>")
            'xss'
            >>> service._classify_violation("{{.*}}")
            'template_injection'
            >>> service._classify_violation("$(.*)")
            'command_injection'
        """
        pattern_lower = pattern.lower()

        # XSS patterns - HTML/JavaScript injection
        xss_indicators = [
            "<script",
            "javascript:",
            "onerror",
            "onload",
            "onclick",
            "<iframe",
            "<object",
            "<embed",
            "eval(",
            "alert(",
        ]
        if any(indicator in pattern_lower for indicator in xss_indicators):
            return "xss"

        # Template injection patterns - Jinja2, Mustache, etc.
        # Check for both literal and escaped versions (patterns use escaped regex)
        template_indicators = [
            "{{",
            "\\{\\{",  # Jinja2/Django - literal and escaped
            "}}",
            "\\}\\}",
            "{%",
            "\\{%",  # Django template tags
            "%}",
            "%\\}",
            "<%",
            "<%",  # ERB templates
            "%>",
            "%>",
            "${",
            "\\$\\{",  # Expression evaluation
            "[[",
            "\\[\\[",  # Other template engines
            "]]",
            "\\]\\]",
        ]
        if any(indicator in pattern_lower for indicator in template_indicators):
            return "template_injection"

        # Command injection patterns - Shell commands
        # Check for both literal and escaped versions
        command_indicators = [
            "$(",
            "\\$\\(",  # Command substitution
            "`",
            "\\`",  # Backtick execution
            ";",
            ";",  # Command separator
            "&&",
            "&&",  # AND operator
            "||",
            "\\|\\|",  # OR operator (escaped pipes)
            "|",
            "\\|",  # Pipe operator
            "exec",
            "system",
            "popen",
            "subprocess",
            "os.",
            "shell",
        ]
        if any(indicator in pattern_lower for indicator in command_indicators):
            return "command_injection"

        # SQL injection patterns
        sql_indicators = [
            "union",
            "select",
            "insert",
            "update",
            "delete",
            "drop",
            "exec",
            "--",
            "/*",
            "*/",
            "xp_",
            "sp_",
        ]
        if any(indicator in pattern_lower for indicator in sql_indicators):
            return "sql_injection"

        # Unknown pattern type
        return "unknown"

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

        # Honour the feature flag: log-only mode for safe migration
        if not settings.content_strict_mime_validation:
            logger.debug("MIME type validation disabled via CONTENT_STRICT_MIME_VALIDATION")
            return

        allowed_types: List[str] = settings.content_allowed_resource_mimetypes

        # Strip parameters from MIME type for comparison (e.g., "text/plain; charset=utf-8" -> "text/plain")
        base_mime_type = mime_type.split(";")[0].strip()

        # Fast path: exact match in allowlist (check both full and base MIME type)
        if mime_type in allowed_types or base_mime_type in allowed_types:
            logger.debug("Resource MIME type validation passed: %s", mime_type)
            return

        # In strict mode, ALL types must be explicitly in the allowlist.
        # Vendor types (application/x-*, text/x-*) and suffix types (+json, +xml)
        # are NOT automatically allowed for security reasons.
        # If you need these types, add them explicitly to CONTENT_ALLOWED_RESOURCE_MIMETYPES.

        # Validation failed - increment metric, log with sanitized PII, and raise
        content_type_violations_counter.labels(content_type="resource", mime_type=mime_type).inc()

        sanitized = _sanitize_pii_for_logging(user_email, ip_address)
        logger.warning(
            "Resource MIME type validation failed",
            extra={
                "mime_type": mime_type,
                "allowed_count": len(allowed_types),
                "uri_provided": uri is not None,
                **sanitized,
            },
        )
        raise ContentTypeError(mime_type, allowed_types)

    def validate_content_patterns(
        self,
        content: str,
        content_type: str,
        name: Optional[str] = None,
        user_email: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Validate content against malicious pattern detection rules.

        This method scans user-submitted content for malicious patterns including:
        - Cross-site scripting (XSS) attacks
        - Template injection attempts
        - Command injection attempts
        - SQL injection attempts

        The validation behavior depends on the configured mode:
        - **strict**: Block all matches, raise ContentPatternError
        - **moderate**: Context-aware validation (future: allow safe contexts)
        - **lenient**: Log violations but don't block

        Performance: Uses pre-compiled regex patterns (10x faster than runtime compilation)
        and fail-fast algorithm (stops at first match in strict mode).

        Args:
            content: The content to validate (resource content or prompt template)
            content_type: Type of content being validated ("resource" or "prompt")
            name: Optional name/identifier for the content (for logging)
            user_email: Optional user email for PII-safe audit logging
            ip_address: Optional client IP for PII-safe audit logging

        Raises:
            ContentPatternError: If malicious pattern detected and validation mode
                is "strict" or "moderate"

        Examples:
            Safe content passes validation:

            >>> service = ContentSecurityService()
            >>> service.validate_content_patterns("Hello world", "resource")

            XSS patterns are detected in resources:

            >>> service = ContentSecurityService()
            >>> try:  # doctest: +ELLIPSIS
            ...     service.validate_content_patterns("<script>alert('xss')</script>", "resource")
            ... except ContentPatternError as e:
            ...     print(f"Blocked: {e.violation_type}")
            Blocked: xss

            Template syntax is allowed in prompts (context-aware):

            >>> service = ContentSecurityService()
            >>> service.validate_content_patterns("Hello {{name}}", "prompt")
        """
        # Skip validation if pattern detection is disabled
        if not settings.content_pattern_detection_enabled:
            logger.debug("Pattern detection disabled - skipping validation")
            return

        # Skip validation if no patterns are configured
        if not self._pattern_cache:
            logger.debug("No patterns configured - skipping validation")
            return

        validation_mode = settings.content_pattern_validation_mode
        logger.debug(
            f"Validating {content_type} content for malicious patterns",
            extra={
                "content_length": len(content),
                "validation_mode": validation_mode,
                "pattern_count": len(self._pattern_cache),
                "name_provided": name is not None,
            },
        )

        # Scan content against all compiled patterns (fail-fast in strict mode)
        for pattern_str, compiled_pattern in self._pattern_cache.items():
            match = compiled_pattern.search(content)

            if match:
                # Pattern matched - classify the violation type
                violation_type = self._classify_violation(pattern_str)

                # Context-aware validation: Allow template patterns in prompts
                # Prompts legitimately use {{ }}, {% %}, and ${ } for template variables
                if content_type == "prompt" and violation_type == "template_injection":
                    logger.debug(
                        f"Allowing template syntax in {content_type} (legitimate use)",
                        extra={
                            "pattern": pattern_str[:50] + "..." if len(pattern_str) > 50 else pattern_str,
                            "content_type": content_type,
                            "violation_type": violation_type,
                        },
                    )
                    continue  # Skip this match - it's legitimate template syntax

                # Extract a safe snippet around the match for logging (max 100 chars)
                match_start = max(0, match.start() - 20)
                match_end = min(len(content), match.end() + 20)
                content_snippet = content[match_start:match_end]

                # Sanitize PII for logging
                sanitized = _sanitize_pii_for_logging(user_email, ip_address)

                # Log the violation with full context
                logger.warning(
                    f"Malicious pattern detected in {content_type}",
                    extra={
                        "violation_type": violation_type,
                        "content_type": content_type,
                        "validation_mode": validation_mode,
                        "pattern_matched": pattern_str[:50] + "..." if len(pattern_str) > 50 else pattern_str,
                        "match_position": match.start(),
                        "content_snippet": content_snippet[:100] + "..." if len(content_snippet) > 100 else content_snippet,
                        "content_length": len(content),
                        "name_provided": name is not None,
                        **sanitized,
                    },
                )

                # Increment metrics counter for pattern violation
                content_pattern_violations_counter.labels(content_type=content_type, violation_type=violation_type, validation_mode=validation_mode).inc()

                # Handle based on validation mode
                if validation_mode == "strict":
                    # Strict mode: block immediately (fail-fast)
                    logger.error(
                        f"Blocking {content_type} due to malicious pattern (strict mode)",
                        extra={
                            "violation_type": violation_type,
                            "content_type": content_type,
                            **sanitized,
                        },
                    )
                    raise ContentPatternError(
                        pattern_matched=pattern_str,
                        content_snippet=content_snippet,
                        violation_type=violation_type,
                        content_type=content_type,
                    )

                if validation_mode == "moderate":
                    # Moderate mode: context-aware validation
                    # For now, block all matches (future: allow safe contexts)
                    logger.error(
                        f"Blocking {content_type} due to malicious pattern (moderate mode)",
                        extra={
                            "violation_type": violation_type,
                            "content_type": content_type,
                            **sanitized,
                        },
                    )
                    raise ContentPatternError(
                        pattern_matched=pattern_str,
                        content_snippet=content_snippet,
                        violation_type=violation_type,
                        content_type=content_type,
                    )

                if validation_mode == "lenient":
                    # Lenient mode: log only, don't block
                    logger.warning(
                        "Malicious pattern detected but not blocking (lenient mode)",
                        extra={
                            "violation_type": violation_type,
                            "content_type": content_type,
                            **sanitized,
                        },
                    )
                    # Continue scanning to log all violations
                    continue

                # Unknown mode - default to strict for security
                if validation_mode not in ("strict", "moderate", "lenient"):
                    logger.error(
                        f"Unknown validation mode '{validation_mode}' - defaulting to strict",
                        extra={
                            "violation_type": violation_type,
                            "content_type": content_type,
                            **sanitized,
                        },
                    )
                    raise ContentPatternError(
                        pattern_matched=pattern_str,
                        content_snippet=content_snippet,
                        violation_type=violation_type,
                        content_type=content_type,
                    )

        # No patterns matched - content is safe
        logger.debug(
            f"{content_type.capitalize()} content passed pattern validation",
            extra={
                "content_length": len(content),
                "patterns_checked": len(self._pattern_cache),
            },
        )


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
