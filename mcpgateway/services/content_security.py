# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/content_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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
import sys
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

# re.search() gained a `timeout` keyword in Python 3.13 that actually aborts
# pathological regex execution. Older versions only have the thread.join
# fallback, which is a soft timeout (see _regex_search_with_timeout).
_HAS_NATIVE_REGEX_TIMEOUT: bool = sys.version_info >= (3, 13)

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
    """Raised when content contains malicious or blocked patterns.

    This exception is raised when content validation detects:
    - Script injection attempts (<script>, javascript:, etc.)
    - Event handler attributes (onclick, onerror, etc.)
    - Command injection patterns (;, &&, ||, etc.)
    - Other dangerous patterns configured in CONTENT_BLOCKED_PATTERNS

    Attributes:
        pattern_matched: The specific pattern that was detected
        content_type: Type of content being validated (e.g., "Resource content", "Prompt template")
        content_snippet: Optional snippet of the content showing the violation
        violation_type: Optional type of violation (e.g., "command_injection", "xss")

    Examples:
        >>> err = ContentPatternError("<script>", "Resource content")
        >>> str(err)
        'Malicious pattern detected in Resource content: <script>'
        >>> err.pattern_matched
        '<script>'
        >>> err = ContentPatternError(";", "prompt", "ls; rm -rf /", "command_injection")
        >>> err.violation_type
        'command_injection'
    """

    def __init__(
        self,
        pattern_matched: str,
        content_type: str = "content",
        content_snippet: Optional[str] = None,
        violation_type: Optional[str] = None,
    ):
        """Initialize ContentPatternError.

        Args:
            pattern_matched: The pattern that was detected in the content
            content_type: Type of content (e.g., "Resource content", "Prompt template")
            content_snippet: Optional snippet of content showing the violation
            violation_type: Optional type of violation (e.g., "command_injection", "xss")
        """
        self.pattern_matched = pattern_matched
        self.content_type = content_type
        self.content_snippet = content_snippet
        self.violation_type = violation_type

        message = f"Malicious pattern detected in {content_type}: {pattern_matched}"
        if violation_type:
            message += f" (type: {violation_type})"
        if content_snippet:
            # Truncate snippet for readability
            snippet_preview = content_snippet[:50] + "..." if len(content_snippet) > 50 else content_snippet
            message += f" in content: {snippet_preview}"

        super().__init__(message)


class TemplateValidationError(Exception):
    """Raised when prompt template validation fails.

    This exception is raised when a prompt template contains:
    - Unbalanced Jinja2 delimiters ({{, }}, {%, %}, {#, #})
    - Dangerous Python patterns (eval, exec, __import__, dunder methods)
    - Invalid Jinja2 syntax

    Attributes:
        template_name: Name of the template that failed validation
        reason: Human-readable reason for validation failure
        pattern: Optional regex pattern that was matched (for dangerous patterns)

    Examples:
        >>> err = TemplateValidationError("my-prompt", "Unbalanced braces")
        >>> str(err)
        "Template validation failed for 'my-prompt': Unbalanced braces"

        >>> err = TemplateValidationError("evil", "Dangerous pattern", "__import__")
        >>> err.pattern
        '__import__'
    """

    def __init__(self, template_name: str, reason: str, pattern: Optional[str] = None):
        """Initialize TemplateValidationError.

        Args:
            template_name: Name of the template (for logging/debugging)
            reason: Description of why validation failed
            pattern: Optional pattern that triggered the failure
        """
        self.template_name = template_name
        self.reason = reason
        self.pattern = pattern

        message = f"Template validation failed for '{template_name}': {reason}"
        if pattern:
            message += f" (matched pattern: {pattern})"
        super().__init__(message)


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
        """Initialize the content security service.

        Patterns are compiled once here instead of on every request because
        this service is a singleton (see get_content_security_service below)
        and re.compile on a hot path is measurable overhead.
        """
        self.max_resource_size = settings.content_max_resource_size
        self.max_prompt_size = settings.content_max_prompt_size
        self._compiled_blocked_patterns: List[tuple[str, re.Pattern]] = self._compile_patterns(
            settings.content_blocked_patterns,
            pattern_kind="content_blocked_patterns",
        )
        self._compiled_template_patterns: List[tuple[str, re.Pattern]] = self._compile_patterns(
            settings.content_blocked_template_patterns,
            pattern_kind="content_blocked_template_patterns",
        )
        logger.info(
            "ContentSecurityService initialized",
            extra={
                "max_resource_size": self.max_resource_size,
                "max_prompt_size": self.max_prompt_size,
                "strict_mime_validation": settings.content_strict_mime_validation,
                "allowed_resource_mimetypes_count": len(settings.content_allowed_resource_mimetypes),
                "compiled_blocked_patterns": len(self._compiled_blocked_patterns),
                "compiled_template_patterns": len(self._compiled_template_patterns),
                "pattern_max_scan_size": settings.content_pattern_max_scan_size,
            },
        )

    @staticmethod
    def _compile_patterns(raw_patterns: List[str], pattern_kind: str) -> List[tuple[str, re.Pattern]]:
        """Compile a list of regex strings once, skipping any that fail to compile.

        Args:
            raw_patterns: Raw regex pattern strings from config.
            pattern_kind: Human-readable tag used when logging compile errors.

        Returns:
            List of (original_pattern_string, compiled_pattern) tuples. Patterns that
            fail to compile are logged and omitted so a single bad config entry does
            not disable the whole validator.
        """
        compiled: List[tuple[str, re.Pattern]] = []
        for raw in raw_patterns:
            try:
                compiled.append((raw, re.compile(raw, re.IGNORECASE | re.DOTALL)))
            except re.error as exc:
                logger.error("Skipping invalid regex in %s: %r (%s)", pattern_kind, raw, exc)
        return compiled

    def _regex_search_with_timeout(self, pattern, content: str, timeout: float = 1.0):
        """Execute regex search with timeout protection for Python < 3.13.

        Uses threading to implement timeout for regex operations that don't
        natively support it. This prevents ReDoS attacks on Python 3.11/3.12.

        Args:
            pattern: Regex pattern to search for. Accepts either a raw source
                string (compiled on the fly with IGNORECASE | DOTALL to match
                the detect_malicious_patterns hot path) or a pre-compiled
                re.Pattern for callers that already compiled once.
            content: Content to search in.
            timeout: Maximum time in seconds to allow for regex execution.

        Returns:
            Match object if pattern found, None otherwise.

        Raises:
            TimeoutError: If regex execution exceeds timeout.
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern, re.IGNORECASE | re.DOTALL)

        result = [None]
        exception = [None]

        def search_thread():
            """Run the regex search in a worker thread, capturing result or exception.

            Writes the match object (or ``None``) into the enclosing ``result`` list,
            and any raised exception into the enclosing ``exception`` list, so the
            caller can inspect them after ``thread.join(timeout)`` returns.
            """
            try:
                result[0] = pattern.search(content)
            except Exception as e:
                exception[0] = e

        thread = threading.Thread(target=search_thread, daemon=True)
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            # thread.join(timeout) only controls the wait here; the daemon thread
            # itself cannot be killed and continues until the regex returns naturally.
            # Primary ReDoS defense is the content_pattern_max_scan_size cap enforced
            # in detect_malicious_patterns() before this helper is called.
            logger.warning(
                "Regex search timeout exceeded",
                extra={
                    "pattern_length": len(pattern.pattern),
                    "content_length": len(content),
                    "timeout": timeout,
                },
            )
            raise TimeoutError(f"Regex search exceeded {timeout}s timeout - possible ReDoS attack")

        captured_exception = exception[0]
        if captured_exception is not None:
            raise captured_exception

        return result[0]

    def _normalize_input(self, content: str) -> str:
        """Normalize input to prevent encoding bypass attacks (CWE-116).

        Applies multiple normalization techniques to catch obfuscated malicious patterns:
        - HTML entity decoding (&#60;script -> <script)
        - URL percent decoding (%3Cscript -> <script)
        - Null byte removal (<scr\x00ipt -> <script)
        - Unicode normalization (NFKC form)

        Args:
            content: Raw input content to normalize

        Returns:
            Normalized content string

        Examples:
            >>> service = ContentSecurityService()
            >>> service._normalize_input("&#60;script&#62;")
            '<script>'
            >>> service._normalize_input("%3Cscript%3E")
            '<script>'
        """
        # Standard
        import html
        import unicodedata
        from urllib.parse import unquote

        # Remove null bytes
        normalized = content.replace("\x00", "")

        # HTML entity decoding (&#60; -> <, &lt; -> <)
        normalized = html.unescape(normalized)

        # URL percent decoding (%3C -> <)
        url_decoded = normalized
        try:
            url_decoded = unquote(normalized)
        except Exception:
            # If URL decoding fails, continue with the pre-decoded value
            logger.debug("URL decoding failed during content normalization", exc_info=True)
        normalized = url_decoded

        # Unicode normalization (NFKC - compatibility decomposition + canonical composition)
        # This catches various Unicode tricks like fullwidth characters
        unicode_normalized = normalized
        try:
            unicode_normalized = unicodedata.normalize("NFKC", normalized)
        except Exception:
            # If normalization fails, continue with the pre-normalized value
            logger.debug("Unicode normalization failed during content normalization", exc_info=True)
        normalized = unicode_normalized

        return normalized

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

    def detect_malicious_patterns(
        self,
        content: str,
        content_type: str = "content",
        user_email: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Detect malicious patterns in content (US-3).

        Scans content for XSS, command injection, SQL injection, and template injection patterns.
        Behavior depends on content_pattern_validation_mode:
        - strict: Raises ContentPatternError on detection
        - moderate: Logs warning and raises ContentPatternError
        - lenient: Logs warning only, allows content

        Args:
            content: Content to scan for malicious patterns
            content_type: Type of content (e.g., "Resource content", "Prompt template")
            user_email: Optional user email for audit logging (sanitized)
            ip_address: Optional IP address for audit logging (sanitized)

        Raises:
            ContentPatternError: If malicious pattern is detected (strict/moderate modes)

        Examples:
            >>> service = ContentSecurityService()
            >>> service.detect_malicious_patterns("Hello world")  # OK
            >>> try:
            ...     service.detect_malicious_patterns("<script>alert('XSS')</script>")
            ... except ContentPatternError as e:
            ...     print(f"Blocked: {e.violation_type}")
            Blocked: xss
        """
        if not settings.content_pattern_detection_enabled:
            logger.debug("Pattern detection disabled via CONTENT_PATTERN_DETECTION_ENABLED")
            return

        validation_mode = settings.content_pattern_validation_mode
        max_scan_size = settings.content_pattern_max_scan_size
        regex_timeout = settings.content_pattern_regex_timeout

        # Normalize input to prevent encoding bypasses (CWE-116 fix)
        # - HTML entity decoding: &#60;script -> <script
        # - URL decoding: %3Cscript -> <script
        # - Null byte removal: <scr\x00ipt -> <script
        # - Unicode normalization: various Unicode tricks
        normalized_content = self._normalize_input(content)

        # Hard ReDoS guard (CWE-400): reject content too large to scan in bounded time.
        # This is the primary defense; the per-pattern timeout below is defense-in-depth.
        if len(normalized_content) > max_scan_size:
            sanitized = _sanitize_pii_for_logging(user_email, ip_address)
            logger.warning(
                "Content rejected - exceeds pattern scan size limit",
                extra={
                    "content_type": content_type,
                    "content_length": len(normalized_content),
                    "max_scan_size": max_scan_size,
                    **sanitized,
                },
            )
            raise ContentPatternError(
                pattern_matched="[oversize]",
                content_type=content_type,
                violation_type="content_too_large_to_scan",
            )

        for raw_pattern, compiled in self._compiled_blocked_patterns:
            try:
                if _HAS_NATIVE_REGEX_TIMEOUT:
                    match = compiled.search(normalized_content, timeout=regex_timeout)  # pylint: disable=unexpected-keyword-arg
                else:
                    match = self._regex_search_with_timeout(compiled, normalized_content, timeout=regex_timeout)

                if match:
                    # Determine violation type from pattern
                    violation_type = self._classify_violation(raw_pattern, match.group(0))

                    # Log with sanitized PII
                    sanitized = _sanitize_pii_for_logging(user_email, ip_address)
                    logger.warning(
                        "Malicious pattern detected",
                        extra={
                            "content_type": content_type,
                            "violation_type": violation_type,
                            "pattern_length": len(raw_pattern),  # Don't log full pattern for security
                            "validation_mode": validation_mode,
                            **sanitized,
                        },
                    )

                    # Lenient mode must `continue`, not `return`: keep scanning so
                    # co-occurring violations (e.g. XSS+SQLi in one payload) all land in the audit log.
                    if validation_mode == "lenient":
                        logger.info(f"Lenient mode: allowing {content_type} with {violation_type} pattern")
                        continue

                    # In strict or moderate mode, raise exception
                    raise ContentPatternError(
                        pattern_matched=match.group(0)[:50],  # Truncate for security
                        content_type=content_type,
                        content_snippet=content[max(0, match.start() - 20) : match.end() + 20],
                        violation_type=violation_type,
                    )

            except TimeoutError:
                # ReDoS protection (CWE-400)
                sanitized = _sanitize_pii_for_logging(user_email, ip_address)
                logger.error(
                    "Pattern matching timeout - possible ReDoS",
                    extra={
                        "pattern_length": len(raw_pattern),
                        "content_type": content_type,
                        **sanitized,
                    },
                )
                raise ContentPatternError(
                    pattern_matched="[timeout]",
                    content_type=content_type,
                    violation_type="redos_timeout",
                )

    def _classify_violation(self, pattern: str, matched_text: str) -> str:
        """Classify violation type based on pattern and matched text.

        Args:
            pattern: The regex pattern that matched
            matched_text: The actual text that was matched

        Returns:
            Violation type string (xss, command_injection, sql_injection, template_injection, unknown)
        """
        matched_lower = matched_text.lower()

        # Check in order of specificity to avoid misclassification
        # Template injection patterns
        if "{{" in matched_text or "{%" in matched_text or "${" in matched_text:
            return "template_injection"
        # SQL injection patterns
        if any(sql in matched_lower for sql in ["select", "union", "insert", "delete", "drop", "update"]) or matched_text.strip().endswith("--"):
            return "sql_injection"
        # Command injection patterns
        if any(cmd in matched_lower for cmd in ["rm -rf", "&&", "||"]) or "`" in matched_text or "$(" in matched_text:
            return "command_injection"
        # XSS patterns (check last to avoid false positives)
        if "<script" in matched_lower or "javascript:" in matched_lower or "<iframe" in matched_lower or (r"on\w+\s*=" in pattern):
            return "xss"
        return "unknown"

    def validate_prompt_template(
        self,
        template: str,
        name: Optional[str] = None,
        user_email: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Validate prompt template for safe syntax and patterns (US-4).

        Performs three levels of validation:
        1. Balanced Jinja2 braces ({{, }}, {%, %}, {#, #})
        2. Dangerous Python pattern detection (eval, exec, __import__, etc.)
        3. Valid Jinja2 syntax via parsing

        Args:
            template: The prompt template string to validate
            name: Optional prompt name for logging context
            user_email: Optional user email for audit logging (sanitized)
            ip_address: Optional IP address for audit logging (sanitized)

        Raises:
            TemplateValidationError: If template validation fails
            ContentPatternError: If malicious patterns detected (US-3)

        Examples:
            Valid template:

            >>> service = ContentSecurityService()
            >>> service.validate_prompt_template("Hello {{name}}")  # OK

            Invalid templates raise TemplateValidationError:

            >>> service.validate_prompt_template("{{user")  # doctest: +ELLIPSIS
            Traceback (most recent call last):
                ...
            mcpgateway.services.content_security.TemplateValidationError: Template validation failed for 'unnamed': Unbalanced template braces...

            >>> service.validate_prompt_template("{{__import__('os')}}")  # doctest: +ELLIPSIS
            Traceback (most recent call last):
                ...
            mcpgateway.services.content_security.TemplateValidationError: Template validation failed for 'unnamed': Template contains dangerous pattern...
        """
        if not settings.content_validate_prompt_templates:
            logger.debug("Template validation disabled via CONTENT_VALIDATE_PROMPT_TEMPLATES")
            return

        template_name = name or "unnamed"

        # Step 0: Check for malicious patterns (US-3) BEFORE template validation
        # This makes the ContentPatternError handlers in prompt_service.py reachable
        self.detect_malicious_patterns(
            content=template,
            content_type="Prompt template",
            user_email=user_email,
            ip_address=ip_address,
        )

        # Step 1: Check for balanced braces
        if not self._check_balanced_braces(template):
            sanitized = _sanitize_pii_for_logging(user_email, ip_address)
            logger.warning("Template syntax validation failed: unbalanced braces", extra={"template_name": template_name, **sanitized})
            raise TemplateValidationError(template_name, "Unbalanced template braces - check {{ }}, {% %}, or {# #} pairs")

        # Step 2: Scan for dangerous patterns using the same ReDoS-bounded path
        # as detect_malicious_patterns (size cap + compiled patterns + per-pattern timeout).
        regex_timeout = settings.content_pattern_regex_timeout
        for raw_pattern, compiled in self._compiled_template_patterns:
            try:
                if _HAS_NATIVE_REGEX_TIMEOUT:
                    match = compiled.search(template, timeout=regex_timeout)  # pylint: disable=unexpected-keyword-arg
                else:
                    match = self._regex_search_with_timeout(compiled, template, timeout=regex_timeout)
            except TimeoutError:
                sanitized = _sanitize_pii_for_logging(user_email, ip_address)
                logger.error("Template pattern matching timeout - possible ReDoS", extra={"template_name": template_name, "pattern_length": len(raw_pattern), **sanitized})
                raise TemplateValidationError(template_name, "Template pattern evaluation exceeded timeout", pattern=raw_pattern)
            if match:
                sanitized = _sanitize_pii_for_logging(user_email, ip_address)
                logger.warning("Template security validation failed: dangerous pattern detected", extra={"template_name": template_name, "pattern_length": len(raw_pattern), **sanitized})
                raise TemplateValidationError(template_name, "Template contains dangerous pattern that could lead to code injection", pattern=raw_pattern)

        # Step 3: Validate Jinja2 syntax by attempting to parse and analyze
        # Note: meta.find_undeclared_variables() only finds undefined variables,
        # it does NOT validate filters or raise exceptions for them
        try:
            # Third-Party
            from jinja2 import Environment, meta

            # nosec B701: Environment used only for parsing/validation, not rendering
            # Templates are never rendered with this Environment, so autoescape is not needed
            env = Environment()  # nosec B701
            ast = env.parse(template)
            # Find undeclared variables (does not validate filters)
            meta.find_undeclared_variables(ast)
        except Exception as e:
            sanitized = _sanitize_pii_for_logging(user_email, ip_address)
            logger.warning("Template Jinja2 syntax validation failed", extra={"template_name": template_name, "error_type": type(e).__name__, **sanitized})  # Log error type, not message
            # Generic message - don't leak template fragments (CWE-209 fix)
            raise TemplateValidationError(template_name, "Invalid Jinja2 syntax - template contains parsing errors")

        logger.debug(f"Template validation passed for: {template_name}")

    @staticmethod
    def _check_balanced_braces(template: str) -> bool:
        """Check if Jinja2 template braces are balanced.

        Validates three types of Jinja2 delimiters:
        - {{ }} for variables
        - {% %} for statements
        - {# #} for comments

        Uses stack-based validation for each delimiter type independently.

        Args:
            template: Template string to check

        Returns:
            True if all braces are balanced, False otherwise

        Examples:
            >>> ContentSecurityService._check_balanced_braces("{{var}}")
            True
            >>> ContentSecurityService._check_balanced_braces("{{var")
            False
            >>> ContentSecurityService._check_balanced_braces("{% if x %}{% endif %}")
            True
        """
        # Stack-based validation for each delimiter type
        pairs = [
            ("{{", "}}"),  # Variables
            ("{%", "%}"),  # Statements
            ("{#", "#}"),  # Comments
        ]

        for open_delim, close_delim in pairs:
            stack = []
            i = 0
            while i < len(template):
                # Check for opening delimiter
                if template[i : i + len(open_delim)] == open_delim:
                    stack.append(open_delim)
                    i += len(open_delim)
                # Check for closing delimiter
                elif template[i : i + len(close_delim)] == close_delim:
                    if not stack:
                        return False  # Closing without opening
                    stack.pop()
                    i += len(close_delim)
                else:
                    i += 1

            if stack:
                return False  # Unclosed delimiters

        return True


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
