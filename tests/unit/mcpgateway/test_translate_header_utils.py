# -*- coding: utf-8 -*-
"""Unit tests for translate header utilities.

Location: ./tests/unit/mcpgateway/test_translate_header_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

Tests for dynamic environment variable injection utilities in mcpgateway.translate.
"""

import pytest
from unittest.mock import patch

# First-Party
from mcpgateway.translate_header_utils import (
    validate_header_mapping,
    sanitize_header_value,
    parse_header_mappings,
    extract_env_vars_from_headers,
    HeaderMappingError,
    ALLOWED_HEADERS_REGEX,
    MAX_HEADER_VALUE_LENGTH,
    MAX_ENV_VAR_NAME_LENGTH,
)


class TestHeaderMappingValidation:
    """Test header mapping validation functionality."""

    def test_valid_header_mapping(self):
        """Test valid header and environment variable names."""
        # Should not raise any exceptions
        validate_header_mapping("Authorization", "GITHUB_TOKEN")
        validate_header_mapping("X-Tenant-Id", "TENANT_ID")
        validate_header_mapping("X-GitHub-Enterprise-Host", "GITHUB_HOST")
        validate_header_mapping("Content-Type", "CONTENT_TYPE")

    def test_valid_environment_variable_names(self):
        """Test various valid environment variable name formats."""
        valid_names = [
            "GITHUB_TOKEN",
            "TENANT_ID",
            "_PRIVATE_VAR",
            "VAR123",
            "my_var",
            "A_B_C_D",
        ]
        for env_var in valid_names:
            validate_header_mapping("Valid-Header", env_var)

    def test_invalid_header_name(self):
        """Test invalid header names."""
        invalid_headers = [
            "Invalid Header!",  # Space
            "Header@Invalid",   # Special character
            "Header/Invalid",   # Forward slash
            "Header\\Invalid",  # Backslash
            "Header:Invalid",   # Colon
            "Header;Invalid",   # Semicolon
            "",                 # Empty
            "123Header",        # Starts with number
        ]

        for invalid_header in invalid_headers:
            with pytest.raises(HeaderMappingError, match="Invalid header name"):
                validate_header_mapping(invalid_header, "VALID_ENV")

    def test_invalid_environment_variable_name(self):
        """Test invalid environment variable names."""
        invalid_env_vars = [
            "123INVALID",       # Starts with number
            "INVALID-VAR",      # Contains hyphen
            "INVALID@VAR",      # Contains special character
            "INVALID VAR",      # Contains space
            "INVALID.VAR",      # Contains dot
            "INVALID/VAR",      # Contains slash
            "",                 # Empty
            "var-with-hyphen",  # Contains hyphen
        ]

        for invalid_env_var in invalid_env_vars:
            with pytest.raises(HeaderMappingError, match="Invalid environment variable name"):
                validate_header_mapping("Valid-Header", invalid_env_var)

    def test_environment_variable_name_too_long(self):
        """Test environment variable name length limit."""
        long_name = "A" * (MAX_ENV_VAR_NAME_LENGTH + 1)
        with pytest.raises(HeaderMappingError, match="too long"):
            validate_header_mapping("Valid-Header", long_name)


class TestHeaderValueSanitization:
    """Test header value sanitization functionality."""

    def test_normal_value(self):
        """Test sanitization of normal header values."""
        test_cases = [
            ("Bearer token123", "Bearer token123"),
            ("application/json", "application/json"),
            ("github-token-abc123", "github-token-abc123"),
            ("acme-corp", "acme-corp"),
        ]

        for input_val, expected in test_cases:
            result = sanitize_header_value(input_val)
            assert result == expected

    def test_long_value_truncation(self):
        """Test truncation of excessively long header values."""
        long_value = "x" * (MAX_HEADER_VALUE_LENGTH + 100)
        result = sanitize_header_value(long_value)
        assert len(result) == MAX_HEADER_VALUE_LENGTH
        assert result == "x" * MAX_HEADER_VALUE_LENGTH

    def test_dangerous_characters_removal(self):
        """Test removal of dangerous characters from header values."""
        test_cases = [
            ("token\x00with\x00nulls", "tokenwithnulls"),
            ("token\nwith\nnewlines", "tokenwithnewlines"),
            ("token\rwith\rcarriage", "tokenwithcarriage"),
            ("token\twith\ttabs", "tokenwithtabs"),
            ("token\x01with\x02control", "tokenwithcontrol"),
        ]

        for input_val, expected in test_cases:
            result = sanitize_header_value(input_val)
            assert result == expected

    def test_unicode_characters_removal(self):
        """Test removal of non-ASCII characters."""
        test_cases = [
            ("token\x80with\xffunicode", "tokenwithunicode"),
            ("token\u2603with\u2603snowman", "tokenwithsnowman"),
            ("token\x00\x01\x02\x03control", "tokencontrol"),
        ]

        for input_val, expected in test_cases:
            result = sanitize_header_value(input_val)
            assert result == expected

    def test_empty_value_after_sanitization(self):
        """Test handling of values that become empty after sanitization."""
        empty_after_sanitization = ["", "\x00", "\n\r\t", "\x80\xff"]

        for val in empty_after_sanitization:
            result = sanitize_header_value(val)
            assert result == ""


class TestHeaderMappingParsing:
    """Test header mapping parsing from CLI arguments."""

    def test_valid_mappings(self):
        """Test parsing of valid header mappings."""
        mappings = parse_header_mappings([
            "Authorization=GITHUB_TOKEN",
            "X-Tenant-Id=TENANT_ID",
            "X-GitHub-Enterprise-Host=GITHUB_HOST",
        ])

        expected = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "X-GitHub-Enterprise-Host": "GITHUB_HOST",
        }
        assert mappings == expected

    def test_mappings_with_spaces(self):
        """Test parsing of mappings with spaces around equals sign."""
        mappings = parse_header_mappings([
            "Authorization = GITHUB_TOKEN",
            " X-Tenant-Id = TENANT_ID ",
            "Content-Type=CONTENT_TYPE",
        ])

        expected = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "Content-Type": "CONTENT_TYPE",
        }
        assert mappings == expected

    def test_duplicate_header(self):
        """Test error handling for duplicate header mappings."""
        with pytest.raises(HeaderMappingError, match="Duplicate header mapping"):
            parse_header_mappings([
                "Authorization=GITHUB_TOKEN",
                "Authorization=API_TOKEN",  # Duplicate
            ])

    def test_invalid_format(self):
        """Test error handling for invalid mapping formats."""
        invalid_formats = [
            "InvalidFormat",           # No equals sign
            "Header=",                # Empty env var name
            "=ENV_VAR",               # Empty header name
            "Header=Env=Var",         # Multiple equals signs
        ]

        for invalid_format in invalid_formats:
            with pytest.raises(HeaderMappingError):
                parse_header_mappings([invalid_format])

    def test_empty_mappings_list(self):
        """Test handling of empty mappings list."""
        mappings = parse_header_mappings([])
        assert mappings == {}

    def test_invalid_header_name_in_mapping(self):
        """Test validation of header names in mappings."""
        with pytest.raises(HeaderMappingError, match="Invalid header name"):
            parse_header_mappings(["Invalid Header!=GITHUB_TOKEN"])

    def test_invalid_env_var_name_in_mapping(self):
        """Test validation of environment variable names in mappings."""
        with pytest.raises(HeaderMappingError, match="Invalid environment variable name"):
            parse_header_mappings(["Authorization=123INVALID"])


class TestEnvironmentVariableExtraction:
    """Test extraction of environment variables from request headers."""

    def test_basic_header_extraction(self):
        """Test basic extraction of environment variables from headers."""
        headers = {
            "Authorization": "Bearer token123",
            "X-Tenant-Id": "acme-corp",
            "Content-Type": "application/json",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
        }

        env_vars = extract_env_vars_from_headers(headers, mappings)

        expected = {
            "GITHUB_TOKEN": "Bearer token123",
            "TENANT_ID": "acme-corp",
        }
        assert env_vars == expected

    def test_case_insensitive_matching(self):
        """Test case-insensitive header matching."""
        headers = {
            "authorization": "Bearer token123",
            "x-tenant-id": "acme-corp",
            "CONTENT-TYPE": "application/json",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "Content-Type": "CONTENT_TYPE",
        }

        env_vars = extract_env_vars_from_headers(headers, mappings)

        expected = {
            "GITHUB_TOKEN": "Bearer token123",
            "TENANT_ID": "acme-corp",
            "CONTENT_TYPE": "application/json",
        }
        assert env_vars == expected

    def test_missing_headers(self):
        """Test handling of missing headers."""
        headers = {
            "Other-Header": "value",
            "Content-Type": "application/json",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
            "Content-Type": "CONTENT_TYPE",
        }

        env_vars = extract_env_vars_from_headers(headers, mappings)

        expected = {
            "CONTENT_TYPE": "application/json",
        }
        assert env_vars == expected

    def test_empty_mappings(self):
        """Test handling of empty mappings."""
        headers = {
            "Authorization": "Bearer token123",
            "X-Tenant-Id": "acme-corp",
        }
        mappings = {}

        env_vars = extract_env_vars_from_headers(headers, mappings)
        assert env_vars == {}

    def test_empty_headers(self):
        """Test handling of empty headers."""
        headers = {}
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
        }

        env_vars = extract_env_vars_from_headers(headers, mappings)
        assert env_vars == {}

    def test_value_sanitization_in_extraction(self):
        """Test that header values are sanitized during extraction."""
        headers = {
            "Authorization": "Bearer\x00token\n123",
            "X-Tenant-Id": "acme\x01corp",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
        }

        env_vars = extract_env_vars_from_headers(headers, mappings)

        expected = {
            "GITHUB_TOKEN": "Bearertoken123",
            "TENANT_ID": "acmecorp",
        }
        assert env_vars == expected

    def test_empty_values_after_sanitization(self):
        """Test handling of values that become empty after sanitization."""
        headers = {
            "Authorization": "\x00\n\r",  # Will become empty after sanitization
            "X-Tenant-Id": "valid-value",
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
            "X-Tenant-Id": "TENANT_ID",
        }

        env_vars = extract_env_vars_from_headers(headers, mappings)

        # Only non-empty values should be included
        expected = {
            "TENANT_ID": "valid-value",
        }
        assert env_vars == expected

    def test_long_values_truncation_in_extraction(self):
        """Test that long header values are truncated during extraction."""
        long_value = "x" * (MAX_HEADER_VALUE_LENGTH + 100)
        headers = {
            "Authorization": long_value,
        }
        mappings = {
            "Authorization": "GITHUB_TOKEN",
        }

        env_vars = extract_env_vars_from_headers(headers, mappings)

        expected = {
            "GITHUB_TOKEN": "x" * MAX_HEADER_VALUE_LENGTH,
        }
        assert env_vars == expected


class TestSecurityConstants:
    """Test security constants and regex patterns."""

    def test_allowed_headers_regex(self):
        """Test the allowed headers regex pattern."""
        valid_headers = [
            "Authorization",
            "X-Tenant-Id",
            "Content-Type",
            "User-Agent",
            "X-GitHub-Enterprise-Host",
            "API-Key",
            "Custom-Header-123",
        ]

        for header in valid_headers:
            assert ALLOWED_HEADERS_REGEX.match(header), f"Header '{header}' should be valid"

    def test_disallowed_headers_regex(self):
        """Test that invalid headers are rejected by regex."""
        invalid_headers = [
            "Invalid Header",
            "Header@Invalid",
            "Header/Invalid",
            "Header:Invalid",
            "Header;Invalid",
            "",
            "123Header",
        ]

        for header in invalid_headers:
            assert not ALLOWED_HEADERS_REGEX.match(header), f"Header '{header}' should be invalid"

    def test_max_length_constants(self):
        """Test that length constants are reasonable."""
        assert MAX_HEADER_VALUE_LENGTH == 4096
        assert MAX_ENV_VAR_NAME_LENGTH == 64
        assert MAX_HEADER_VALUE_LENGTH > 0
        assert MAX_ENV_VAR_NAME_LENGTH > 0


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_header_mapping_error_inheritance(self):
        """Test that HeaderMappingError inherits from Exception."""
        error = HeaderMappingError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"

    def test_logging_in_sanitization(self):
        """Test that appropriate logging occurs during sanitization."""
        with patch('mcpgateway.translate_header_utils.logger') as mock_logger:
            # Test long value truncation logging
            long_value = "x" * (MAX_HEADER_VALUE_LENGTH + 100)
            sanitize_header_value(long_value)
            mock_logger.warning.assert_called_once()
            assert "truncated" in mock_logger.warning.call_args[0][0]

    def test_logging_in_extraction(self):
        """Test that appropriate logging occurs during extraction."""
        with patch('mcpgateway.translate_header_utils.logger') as mock_logger:
            headers = {"Authorization": "Bearer token123"}
            mappings = {"Authorization": "GITHUB_TOKEN"}

            extract_env_vars_from_headers(headers, mappings)

            # Should log debug message about successful mapping
            mock_logger.debug.assert_called()
            debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
            assert any("Mapped header Authorization to GITHUB_TOKEN" in call for call in debug_calls)

    def test_exception_handling_in_extraction(self):
        """Test exception handling during header extraction."""
        with patch('mcpgateway.translate_header_utils.sanitize_header_value') as mock_sanitize:
            mock_sanitize.side_effect = Exception("Sanitization failed")

            with patch('mcpgateway.translate_header_utils.logger') as mock_logger:
                headers = {"Authorization": "Bearer token123"}
                mappings = {"Authorization": "GITHUB_TOKEN"}

                env_vars = extract_env_vars_from_headers(headers, mappings)

                # Should log warning and continue processing
                mock_logger.warning.assert_called()
                assert "Failed to process header Authorization" in mock_logger.warning.call_args[0][0]
                assert env_vars == {}  # Should return empty dict on error
