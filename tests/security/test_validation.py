# -*- coding: utf-8 -*-
"""Tests for security validation middleware."""

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
        with patch('mcpgateway.common.validators.settings') as mock_settings:
            mock_settings.validation_strict = True
            with pytest.raises(ValueError, match="SQL injection"):
                SecurityValidator.validate_sql_parameter("'; DROP TABLE users; --")


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


class TestValidationMiddleware:
    """Test validation middleware."""

    def test_middleware_creation(self):
        """Test middleware can be created."""
        app = MagicMock()
        middleware = ValidationMiddleware(app)
        assert middleware is not None