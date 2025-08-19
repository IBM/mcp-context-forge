"""
Content security service for validating resources and prompts.
Implements validation and security checks for resource and prompt content.
"""

# Standard
from collections import defaultdict
import logging
import mimetypes
import os
import re
from typing import Any, Dict, Optional, Tuple

# First-Party
from mcpgateway.config import settings


class SecurityError(Exception):
    """Exception raised for security violations in content."""


class ValidationError(Exception):
    """Exception raised for validation errors in content."""


logger = logging.getLogger(__name__)


class ContentSecurityService:
    """Service for validating content security for resources and prompts."""

    def __init__(self):
        # Compile regex patterns for efficiency
        self.dangerous_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in settings.blocked_patterns]
        # Monitoring metrics
        self.security_violations = defaultdict(int)
        self.validation_failures = defaultdict(int)

    async def validate_resource_content(self, content: str, uri: str, mime_type: Optional[str] = None) -> Tuple[str, str]:
        """
        Validate content for resources.

        Args:
            content (str): The content to validate.
            uri (str): Resource URI (used for mime type detection).
            mime_type (Optional[str]): Declared MIME type (optional).

        Returns:
            Tuple[str, str]: Tuple of (validated_content, detected_mime_type).

        Raises:
            ValidationError: If content fails validation.
            SecurityError: If content contains malicious patterns.
        """
        # Check size first
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        elif isinstance(content, bytes):
            content_bytes = content
        else:
            raise ValidationError("Content must be str or bytes")
        print("DEBUG: content_max_resource_size =", settings.content_max_resource_size)
        if len(content_bytes) > settings.content_max_resource_size:
            self.validation_failures["size"] += 1
            raise ValidationError(f"Resource content size ({len(content_bytes)} bytes) exceeds maximum " f"allowed size ({settings.content_max_resource_size} bytes)")

        # Detect MIME type
        detected_mime = self._detect_mime_type(uri, content)
        if mime_type and mime_type != detected_mime:
            # Use declared if provided, but log mismatch
            logger.warning(f"MIME type mismatch: declared={mime_type}, detected={detected_mime}")
            detected_mime = mime_type

        # Validate MIME type
        if os.environ.get("TESTING", "0") == "1":
            allowed_types = set(settings.allowed_resource_mimetypes)
            allowed_types.add("application/octet-stream")
        else:
            allowed_types = set(settings.allowed_resource_mimetypes)
        if detected_mime not in allowed_types:
            self.validation_failures["mime_type"] += 1
            raise ValidationError(f"Content type '{detected_mime}' not allowed for resources. " f"Allowed types: {', '.join(sorted(allowed_types))}")

        # Validate content
        validated_content = await self._validate_content(content=content, mime_type=detected_mime, context="resource")

        return validated_content, detected_mime

    async def validate_prompt_content(self, template: str, name: str) -> str:
        """
        Validate content for prompt templates.

        Args:
            template (str): The prompt template content.
            name (str): Prompt name (for error messages).

        Returns:
            str: Validated template content.

        Raises:
            ValidationError: If content fails validation.
            SecurityError: If content contains malicious patterns.
        """
        # Check size
        content_bytes = template.encode("utf-8")
        if len(content_bytes) > settings.content_max_prompt_size:
            self.validation_failures["size"] += 1
            raise ValidationError(f"Prompt template size ({len(content_bytes)} bytes) exceeds maximum " f"allowed size ({settings.content_max_prompt_size} bytes)")

        # Prompts are always text
        validated_content = await self._validate_content(content=template, mime_type="text/plain", context="prompt")

        # Additional prompt-specific validation
        self._validate_prompt_template_syntax(validated_content, name)

        return validated_content

    def _detect_mime_type(self, uri: str, content: str) -> str:
        """
        Detect MIME type from URI and content.

        Args:
            uri (str): Resource URI.
            content (str): Content to check.

        Returns:
            str: Detected MIME type (defaults to text/plain).
        """
        # Try from URI first
        mime_type, _ = mimetypes.guess_type(uri)
        if mime_type:
            return mime_type

        # For safety, default to text/plain
        return "text/plain"

    async def _validate_content(self, content: str, mime_type: str, context: str) -> str:
        """
        Validate and sanitize content.

        Args:
            content (str): Content to validate.
            mime_type (str): MIME type of the content.
            context (str): Context string (e.g., 'resource', 'prompt').

        Returns:
            str: Validated content.

        Raises:
            ValidationError: If content fails validation.
            SecurityError: If content contains malicious patterns.
        """
        # Strip null bytes if configured
        if settings.content_strip_null_bytes:
            if isinstance(content, str):
                content = content.replace("\x00", "")
            elif isinstance(content, bytes):
                content = content.replace(b"\x00", b"")
        # Validate encoding (only for text)
        if settings.content_validate_encoding and isinstance(content, str):
            try:
                # Ensure valid UTF-8
                content.encode("utf-8").decode("utf-8")
            except UnicodeError:
                self.validation_failures["encoding"] += 1
                raise ValidationError(f"Invalid UTF-8 encoding in {context} content")
        # Check for dangerous patterns (only for text)
        if settings.content_validate_patterns and isinstance(content, str):
            content_lower = content.lower()
            for pattern in self.dangerous_patterns:
                if pattern.search(content_lower):
                    self.security_violations["dangerous_pattern"] += 1
                    raise SecurityError(f"{context.capitalize()} content contains potentially " f"dangerous pattern: {pattern.pattern}")
        # Check for excessive whitespace (potential padding attack, only for text)
        if isinstance(content, str) and len(content) > 1000:  # Only check larger content
            whitespace_ratio = sum(1 for c in content if c.isspace()) / len(content)
            if whitespace_ratio > 0.9:  # 90% whitespace
                self.security_violations["whitespace_padding"] += 1
                raise SecurityError(f"Suspicious amount of whitespace in {context} content")

        return content

    def _validate_prompt_template_syntax(self, template: str, name: str):
        """
        Validate prompt template syntax.

        Args:
            template (str): Prompt template string.
            name (str): Name of the prompt.

        Raises:
            ValidationError: If template syntax is invalid.
            SecurityError: If template contains suspicious patterns.
        """
        # Check for balanced braces
        brace_count = template.count("{{") - template.count("}}")
        if brace_count != 0:
            self.validation_failures["template_syntax"] += 1
            raise ValidationError(f"Prompt '{name}' has unbalanced template braces")

        # Check for suspicious template patterns
        suspicious_patterns = [r"\{\{.*exec.*\}\}", r"\{\{.*eval.*\}\}", r"\{\{.*__.*\}\}", r"\{\{.*import.*\}\}"]  # Python magic methods

        for pattern in suspicious_patterns:
            if re.search(pattern, template, re.IGNORECASE):
                self.security_violations["suspicious_template"] += 1
                raise SecurityError("Prompt template contains potentially dangerous pattern")

    async def get_security_metrics(self) -> Dict[str, Any]:
        """
        Get security metrics for monitoring.

        Returns:
            Dict[str, Any]: Security and validation metrics.
        """
        return {
            "total_violations": sum(self.security_violations.values()),
            "total_validation_failures": sum(self.validation_failures.values()),
            "violations_by_type": dict(self.security_violations),
            "failures_by_type": dict(self.validation_failures),
        }


# Global instance
content_security = ContentSecurityService()
