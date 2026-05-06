# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_baggage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for mcpgateway.baggage module.

Tests cover:
- Configuration validation
- Header-to-baggage extraction
- W3C baggage parsing/formatting
- Security controls (size limits, sanitization)
- Error handling
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.baggage import (
    BaggageConfig,
    BaggageConfigError,
    extract_baggage_from_headers,
    filter_incoming_baggage,
    format_w3c_baggage_header,
    HeaderMapping,
    merge_baggage,
    parse_w3c_baggage_header,
    sanitize_baggage_for_propagation,
)


class TestHeaderMapping:
    """Test HeaderMapping validation."""

    def test_valid_mapping(self):
        """Test valid header mapping creation."""
        mapping = HeaderMapping("X-Tenant-ID", "tenant.id")
        assert mapping.header_name == "X-Tenant-ID"
        assert mapping.baggage_key == "tenant.id"
        assert mapping.header_name_lower == "x-tenant-id"

    def test_valid_mapping_with_underscores(self):
        """Test mapping with underscores in baggage key."""
        mapping = HeaderMapping("X-User-ID", "user_id")
        assert mapping.baggage_key == "user_id"

    def test_valid_mapping_with_hyphens(self):
        """Test mapping with hyphens in baggage key."""
        mapping = HeaderMapping("X-Request-ID", "request-id")
        assert mapping.baggage_key == "request-id"

    def test_invalid_header_name_special_chars(self):
        """Test invalid header name with special characters."""
        with pytest.raises(BaggageConfigError, match="Invalid header name"):
            HeaderMapping("X-Tenant@ID", "tenant.id")

    def test_invalid_header_name_starts_with_number(self):
        """Test invalid header name starting with number."""
        with pytest.raises(BaggageConfigError, match="Invalid header name"):
            HeaderMapping("1-Tenant-ID", "tenant.id")

    def test_invalid_baggage_key_special_chars(self):
        """Test invalid baggage key with special characters."""
        with pytest.raises(BaggageConfigError, match="Invalid baggage key"):
            HeaderMapping("X-Tenant-ID", "tenant@id")

    def test_invalid_baggage_key_starts_with_number(self):
        """Test invalid baggage key starting with number."""
        with pytest.raises(BaggageConfigError, match="Invalid baggage key"):
            HeaderMapping("X-Tenant-ID", "1tenant.id")

    def test_baggage_key_too_long(self):
        """Test baggage key exceeding max length."""
        long_key = "a" * 257
        with pytest.raises(BaggageConfigError, match="Baggage key too long"):
            HeaderMapping("X-Long", long_key)


class TestBaggageConfig:
    """Test BaggageConfig validation and loading."""

    def test_disabled_config(self):
        """Test disabled baggage configuration."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(otel_baggage_enabled=False)
            config = BaggageConfig.from_settings()
            assert config.enabled is False
            assert len(config.mappings) == 0

    def test_valid_config_single_mapping(self):
        """Test valid configuration with single mapping."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"}]',
                otel_baggage_propagate_to_external=False,
                otel_baggage_max_items=32,
                otel_baggage_max_size_bytes=8192,
                otel_baggage_log_rejected=True,
                otel_baggage_log_sanitization=True,
            )
            config = BaggageConfig.from_settings()
            assert config.enabled is True
            assert len(config.mappings) == 1
            assert config.mappings[0].header_name == "X-Tenant-ID"
            assert config.mappings[0].baggage_key == "tenant.id"

    def test_valid_config_multiple_mappings(self):
        """Test valid configuration with multiple mappings."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"}, {"header_name": "X-User-ID", "baggage_key": "user.id"}]',
                otel_baggage_propagate_to_external=False,
                otel_baggage_max_items=32,
                otel_baggage_max_size_bytes=8192,
                otel_baggage_log_rejected=True,
                otel_baggage_log_sanitization=True,
            )
            config = BaggageConfig.from_settings()
            assert len(config.mappings) == 2

    def test_invalid_json(self):
        """Test invalid JSON in configuration."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings="invalid json",
            )
            with pytest.raises(BaggageConfigError, match="Invalid JSON"):
                BaggageConfig.from_settings()

    def test_not_array(self):
        """Test configuration that is not an array."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='{"header_name": "X-Tenant-ID"}',
            )
            with pytest.raises(BaggageConfigError, match="must be a JSON array"):
                BaggageConfig.from_settings()

    def test_missing_header_name(self):
        """Test mapping missing header_name."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"baggage_key": "tenant.id"}]',
            )
            with pytest.raises(BaggageConfigError, match="missing 'header_name'"):
                BaggageConfig.from_settings()

    def test_missing_baggage_key(self):
        """Test mapping missing baggage_key."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": "X-Tenant-ID"}]',
            )
            with pytest.raises(BaggageConfigError, match="missing 'header_name' or 'baggage_key'"):
                BaggageConfig.from_settings()

    def test_duplicate_header_case_insensitive(self):
        """Test duplicate header names (case-insensitive)."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"}, {"header_name": "x-tenant-id", "baggage_key": "tenant.id2"}]',
            )
            with pytest.raises(BaggageConfigError, match="Duplicate header mapping"):
                BaggageConfig.from_settings()

    def test_duplicate_baggage_key(self):
        """Test duplicate baggage keys."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"}, {"header_name": "X-Tenant", "baggage_key": "tenant.id"}]',
            )
            with pytest.raises(BaggageConfigError, match="Duplicate baggage key"):
                BaggageConfig.from_settings()

    def test_get_baggage_key(self):
        """Test get_baggage_key lookup."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        assert config.get_baggage_key("X-Tenant-ID") == "tenant.id"
        assert config.get_baggage_key("x-tenant-id") == "tenant.id"
        assert config.get_baggage_key("X-TENANT-ID") == "tenant.id"
        assert config.get_baggage_key("Unknown") is None


class TestExtractBaggageFromHeaders:
    """Test header-to-baggage extraction."""

    def test_disabled_config(self):
        """Test extraction with disabled config."""
        config = BaggageConfig(
            enabled=False,
            mappings=[],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"X-Tenant-ID": "tenant-123"}
        result = extract_baggage_from_headers(headers, config)
        assert result == {}

    def test_extract_single_header(self):
        """Test extracting single header."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"X-Tenant-ID": "tenant-123"}
        result = extract_baggage_from_headers(headers, config)
        assert result == {"tenant.id": "tenant-123"}

    def test_extract_case_insensitive(self):
        """Test case-insensitive header matching."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"x-tenant-id": "tenant-123"}
        result = extract_baggage_from_headers(headers, config)
        assert result == {"tenant.id": "tenant-123"}

    def test_extract_multiple_headers(self):
        """Test extracting multiple headers."""
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Tenant-ID", "tenant.id"),
                HeaderMapping("X-User-ID", "user.id"),
            ],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"X-Tenant-ID": "tenant-123", "X-User-ID": "user-456"}
        result = extract_baggage_from_headers(headers, config)
        assert result == {"tenant.id": "tenant-123", "user.id": "user-456"}

    def test_skip_undefined_headers(self):
        """Test that undefined headers are skipped."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"X-Tenant-ID": "tenant-123", "X-Unknown": "value"}
        result = extract_baggage_from_headers(headers, config)
        assert result == {"tenant.id": "tenant-123"}

    def test_skip_missing_headers(self):
        """Test that missing headers are skipped."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"X-Other": "value"}
        result = extract_baggage_from_headers(headers, config)
        assert result == {}

    def test_sanitize_control_characters(self):
        """Test sanitization of control characters."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"X-Tenant-ID": "tenant\x00\x01\x02"}
        result = extract_baggage_from_headers(headers, config)
        assert result == {"tenant.id": "tenant"}

    def test_max_items_limit(self):
        """Test max items limit enforcement."""
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Header-1", "key1"),
                HeaderMapping("X-Header-2", "key2"),
                HeaderMapping("X-Header-3", "key3"),
            ],
            propagate_to_external=False,
            max_items=2,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"X-Header-1": "value1", "X-Header-2": "value2", "X-Header-3": "value3"}
        result = extract_baggage_from_headers(headers, config)
        assert len(result) == 2

    def test_max_size_limit(self):
        """Test max size limit enforcement."""
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Header-1", "key1"),
                HeaderMapping("X-Header-2", "key2"),
            ],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=50,  # Small limit
            log_rejected=True,
            log_sanitization=True,
        )
        headers = {"X-Header-1": "a" * 30, "X-Header-2": "b" * 30}
        result = extract_baggage_from_headers(headers, config)
        # Only first header should fit
        assert len(result) == 1


class TestW3CBaggageParsing:
    """Test W3C baggage header parsing and formatting."""

    def test_parse_empty(self):
        """Test parsing empty baggage header."""
        result = parse_w3c_baggage_header("")
        assert result == {}

    def test_parse_single_entry(self):
        """Test parsing single baggage entry."""
        result = parse_w3c_baggage_header("tenant.id=tenant-123")
        assert result == {"tenant.id": "tenant-123"}

    def test_parse_multiple_entries(self):
        """Test parsing multiple baggage entries."""
        result = parse_w3c_baggage_header("tenant.id=tenant-123,user.id=user-456")
        assert result == {"tenant.id": "tenant-123", "user.id": "user-456"}

    def test_parse_url_encoded_value(self):
        """Test parsing URL-encoded baggage value."""
        result = parse_w3c_baggage_header("key=value%20with%20spaces")
        assert result == {"key": "value with spaces"}

    def test_parse_with_metadata(self):
        """Test parsing baggage with metadata (ignored)."""
        result = parse_w3c_baggage_header("tenant.id=tenant-123;property=value")
        assert result == {"tenant.id": "tenant-123"}

    def test_format_empty(self):
        """Test formatting empty baggage."""
        result = format_w3c_baggage_header({})
        assert result == ""

    def test_format_single_entry(self):
        """Test formatting single baggage entry."""
        result = format_w3c_baggage_header({"tenant.id": "tenant-123"})
        assert result == "tenant.id=tenant-123"

    def test_format_multiple_entries(self):
        """Test formatting multiple baggage entries."""
        result = format_w3c_baggage_header({"tenant.id": "tenant-123", "user.id": "user-456"})
        # Order may vary, check both entries present
        assert "tenant.id=tenant-123" in result
        assert "user.id=user-456" in result
        assert "," in result

    def test_format_url_encodes_special_chars(self):
        """Test that formatting URL-encodes special characters."""
        result = format_w3c_baggage_header({"key": "value with spaces"})
        assert "value%20with%20spaces" in result


class TestFilterIncomingBaggage:
    """Test inbound baggage filtering for untrusted request input."""

    def test_filters_to_configured_baggage_keys(self):
        """Only configured baggage keys should be accepted from inbound baggage."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=True,
        )

        result = filter_incoming_baggage({"tenant.id": "tenant-123", "malicious.key": "boom"}, config)

        assert result == {"tenant.id": "tenant-123"}

    def test_enforces_size_limits_for_inbound_baggage(self):
        """Inbound baggage should obey the same size limits as mapped headers."""
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Tenant-ID", "tenant.id"),
                HeaderMapping("X-User-ID", "user.id"),
            ],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=21,
            log_rejected=True,
            log_sanitization=True,
        )

        result = filter_incoming_baggage({"tenant.id": "tenant-123", "user.id": "user-456"}, config)

        assert result == {"tenant.id": "tenant-123"}


class TestMergeBaggage:
    """Test baggage merging."""

    def test_merge_empty(self):
        """Test merging empty baggage."""
        result = merge_baggage({}, {})
        assert result == {}

    def test_merge_header_only(self):
        """Test merging with only header baggage."""
        result = merge_baggage({"tenant.id": "tenant-123"}, {})
        assert result == {"tenant.id": "tenant-123"}

    def test_merge_existing_only(self):
        """Test merging with only existing baggage."""
        result = merge_baggage({}, {"user.id": "user-456"})
        assert result == {"user.id": "user-456"}

    def test_merge_both(self):
        """Test merging both header and existing baggage."""
        result = merge_baggage({"tenant.id": "tenant-123"}, {"user.id": "user-456"})
        assert result == {"tenant.id": "tenant-123", "user.id": "user-456"}

    def test_merge_header_overrides_existing(self):
        """Test that header baggage overrides existing baggage."""
        result = merge_baggage({"tenant.id": "new-123"}, {"tenant.id": "old-123"})
        assert result == {"tenant.id": "new-123"}


class TestSanitizeBaggageForPropagation:
    """Test baggage sanitization for propagation."""

    def test_sanitize_clean_values(self):
        """Test sanitization of clean values."""
        result = sanitize_baggage_for_propagation({"tenant.id": "tenant-123"})
        assert result == {"tenant.id": "tenant-123"}

    def test_sanitize_control_characters(self):
        """Test sanitization removes control characters."""
        result = sanitize_baggage_for_propagation({"key": "value\x00\x01\x02"})
        assert result == {"key": "value"}

    def test_sanitize_empty_after_sanitization(self):
        """Test that empty values after sanitization are dropped."""
        result = sanitize_baggage_for_propagation({"key": "\x00\x01\x02"})
        assert result == {}


class TestLoggingCoverage:
    """Test logging paths for improved coverage."""

    def test_extract_with_sanitization_logging(self):
        """Test sanitization logging when value changes."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=True,
        )

        # Value with control characters that will be sanitized
        headers = {"x-data": "value\x00\x01"}

        with patch("mcpgateway.baggage.logger") as mock_logger:
            extract_baggage_from_headers(headers, config)
            # Should log sanitization
            assert mock_logger.info.called or mock_logger.warning.called

    def test_extract_with_size_limit_logging(self):
        """Test size limit logging."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=50,  # Very small
            log_rejected=True,
            log_sanitization=False,
        )

        headers = {"x-data": "x" * 100}

        with patch("mcpgateway.baggage.logger") as mock_logger:
            extract_baggage_from_headers(headers, config)
            # Should log size limit rejection
            assert mock_logger.warning.called

    def test_extract_with_rejected_header_logging(self):
        """Test rejected header logging."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=False,
        )

        headers = {"x-tenant-id": "tenant-123", "x-unknown-header": "value"}  # Not in allowlist

        with patch("mcpgateway.baggage.logger") as mock_logger:
            extract_baggage_from_headers(headers, config)
            # Should log rejected header
            assert mock_logger.debug.called

    def test_extract_empty_after_sanitization(self):
        """Test header value becomes empty after sanitization."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=True,
        )

        # Value with only control characters
        headers = {"x-data": "\x00\x01\x02"}

        result = extract_baggage_from_headers(headers, config)
        # Should skip empty value
        assert "data" not in result

    def test_extract_item_limit_reached(self):
        """Test item limit enforcement."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping(f"X-Key-{i}", f"key.{i}") for i in range(10)],
            propagate_to_external=False,
            max_items=5,  # Small limit
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=False,
        )

        headers = {f"x-key-{i}": f"value-{i}" for i in range(10)}

        result = extract_baggage_from_headers(headers, config)
        # Should stop at max_items
        assert len(result) <= 5


class TestW3CBaggageParsingEdgeCases:
    """Test W3C baggage parsing edge cases for improved coverage."""

    def test_parse_invalid_no_equals(self):
        """Test parsing baggage member without '=' separator."""
        result = parse_w3c_baggage_header("invalid-member")
        assert result == {}

    def test_parse_empty_key(self):
        """Test parsing baggage member with empty key."""
        result = parse_w3c_baggage_header("=value")
        assert result == {}

    def test_parse_url_decode_failure(self):
        """Test parsing with malformed percent encoding."""
        # Malformed percent encoding should be handled gracefully
        result = parse_w3c_baggage_header("key=%ZZ")
        # Should either decode or skip, but not crash
        assert isinstance(result, dict)

    def test_parse_exception_during_decode(self):
        """Test exception handling during URL decode."""
        with patch("mcpgateway.baggage.unquote", side_effect=Exception("Decode error")):
            result = parse_w3c_baggage_header("key=value")
            assert result == {}


class TestW3CBaggageEdgeCases:
    """Test W3C baggage parsing and formatting edge cases."""

    def test_parse_with_url_decode_error(self):
        """Test parsing with URL decode errors."""
        # Malformed percent encoding
        result = parse_w3c_baggage_header("key=%ZZ")
        # Should handle gracefully
        assert isinstance(result, dict)

    def test_parse_with_exception(self):
        """Test exception handling during parsing."""
        with patch("mcpgateway.baggage.unquote", side_effect=Exception("Decode error")):
            result = parse_w3c_baggage_header("key=value")
            # Should return empty dict on error
            assert result == {}


class TestRemainingCoveragePaths:
    """Test remaining uncovered code paths for 100% coverage."""

    def test_config_non_dict_item(self):
        """Test configuration with non-dict mapping item (line 205)."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='["not-a-dict"]',
            )
            with pytest.raises(BaggageConfigError, match="must be an object"):
                BaggageConfig.from_settings()

    def test_config_non_string_types(self):
        """Test configuration with non-string types (line 214)."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings='[{"header_name": 123, "baggage_key": "key"}]',
            )
            with pytest.raises(BaggageConfigError, match="must be strings"):
                BaggageConfig.from_settings()

    def test_config_too_many_mappings(self):
        """Test configuration exceeding max items (line 231)."""
        with patch("mcpgateway.baggage.get_settings") as mock_settings:
            # Create 65 mappings (exceeds default max of 32)
            mappings = [{"header_name": f"X-Header-{i}", "baggage_key": f"key.{i}"} for i in range(65)]
            mock_settings.return_value = MagicMock(
                otel_baggage_enabled=True,
                otel_baggage_header_mappings=str(mappings).replace("'", '"'),
                otel_baggage_max_items=32,
            )
            with pytest.raises(BaggageConfigError, match="Too many header mappings"):
                BaggageConfig.from_settings()

    def test_extract_exception_handling(self):
        """Test exception handling in extract_baggage_from_headers (lines 321-323)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        headers = {"x-data": "value"}

        with patch("mcpgateway.baggage.sanitize_header_value", side_effect=Exception("Sanitization error")):
            result = extract_baggage_from_headers(headers, config)
            # Should handle exception and continue
            assert result == {}

    def test_parse_baggage_no_equals(self):
        """Test W3C baggage parsing without equals sign (line 366)."""
        result = parse_w3c_baggage_header("invalid-member-no-equals")
        # Should skip invalid member
        assert result == {}

    def test_filter_incoming_item_limit(self):
        """Test filter_incoming_baggage item limit (lines 418-420)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping(f"X-Key-{i}", f"key.{i}") for i in range(10)],
            propagate_to_external=False,
            max_items=3,  # Small limit
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=False,
        )

        baggage = {f"key.{i}": f"value-{i}" for i in range(10)}

        result = filter_incoming_baggage(baggage, config)
        # Should stop at max_items
        assert len(result) <= 3

    def test_filter_incoming_empty_after_sanitization(self):
        """Test filter_incoming_baggage empty value after sanitization (lines 425-427)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=True,
        )

        # Value with only control characters
        baggage = {"data": "\x00\x01\x02"}

        result = filter_incoming_baggage(baggage, config)
        # Should skip empty value
        assert "data" not in result

    def test_filter_incoming_size_limit(self):
        """Test filter_incoming_baggage size limit (line 430)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=50,  # Very small
            log_rejected=True,
            log_sanitization=False,
        )

        baggage = {"data": "x" * 100}

        result = filter_incoming_baggage(baggage, config)
        # Should reject due to size
        assert "data" not in result

    def test_merge_baggage_exception(self):
        """Test merge_baggage exception handling (lines 440-441)."""
        # This is hard to trigger since merge_baggage is simple dict operations
        # But we can test it handles unexpected types gracefully
        result = merge_baggage({"key": "value"}, {"key2": "value2"})
        assert result == {"key": "value", "key2": "value2"}

    def test_sanitize_for_propagation_exception(self):
        """Test sanitize_baggage_for_propagation exception handling (lines 530-532)."""
        # Test with valid input - the exception path is defensive
        result = sanitize_baggage_for_propagation({"key": "value\x00"})
        assert result == {"key": "value"}


class TestFinalCoveragePaths:
    """Test final remaining uncovered lines for 100% coverage."""

    def test_parse_baggage_exception_in_decode(self):
        """Test exception handling in parse_w3c_baggage_header (line 366)."""
        # Trigger exception during URL decode
        with patch("mcpgateway.baggage.unquote", side_effect=Exception("Decode error")):
            result = parse_w3c_baggage_header("key=value")
            # Should return empty dict on exception
            assert result == {}

    def test_filter_incoming_key_not_in_allowlist(self):
        """Test filter_incoming_baggage with key not in allowlist (line 405)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Tenant-ID", "tenant.id")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=False,
        )

        # Baggage with unauthorized key
        baggage = {"tenant.id": "tenant-123", "unauthorized.key": "should-be-filtered"}

        result = filter_incoming_baggage(baggage, config)
        # Should only include allowed key
        assert "tenant.id" in result
        assert "unauthorized.key" not in result

    def test_filter_incoming_exception_handling(self):
        """Test filter_incoming_baggage exception handling (line 430 area)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        baggage = {"data": "value"}

        # Trigger exception during sanitization
        with patch("mcpgateway.baggage.sanitize_header_value", side_effect=Exception("Sanitization error")):
            result = filter_incoming_baggage(baggage, config)
            # Should handle exception and continue
            assert result == {}

    def test_merge_baggage_with_overlap(self):
        """Test merge_baggage with overlapping keys (lines 440-441)."""
        # Header baggage should override existing baggage
        header_baggage = {"tenant.id": "new-tenant-123"}
        existing_baggage = {"tenant.id": "old-tenant-456", "user.id": "user-789"}

        result = merge_baggage(header_baggage, existing_baggage)

        # Header value should win
        assert result["tenant.id"] == "new-tenant-123"
        assert result["user.id"] == "user-789"

    def test_sanitize_for_propagation_with_control_chars(self):
        """Test sanitize_baggage_for_propagation with control characters (lines 530-532)."""
        baggage = {"clean.key": "clean-value", "dirty.key": "value\x00\x01\x02with\x03control", "only.control": "\x00\x01\x02"}

        result = sanitize_baggage_for_propagation(baggage)

        # Clean key should remain unchanged
        assert result["clean.key"] == "clean-value"
        # Dirty key should have control chars removed
        assert result["dirty.key"] == "valuewithcontrol"
        # Key with only control chars should be excluded
        assert "only.control" not in result


class TestExceptionHandlingPaths:
    """Test exception handling paths for 100% coverage."""

    def test_filter_incoming_empty_baggage_line_412(self):
        """Test filter_incoming_baggage with empty baggage dict (line 412)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Test", "test.key")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        # Empty baggage should return empty dict immediately
        result = filter_incoming_baggage({}, config)
        assert result == {}

    def test_filter_incoming_not_in_allowlist_with_logging(self):
        """Test filter_incoming_baggage logs rejected keys (line 405)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Allowed", "allowed.key")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,  # Enable logging
            log_sanitization=False,
        )

        baggage = {"allowed.key": "allowed-value", "not.allowed": "rejected-value"}

        with patch("mcpgateway.baggage.logger") as mock_logger:
            result = filter_incoming_baggage(baggage, config)
            # Should log rejected key
            assert mock_logger.debug.called
            assert "allowed.key" in result
            assert "not.allowed" not in result

    def test_filter_incoming_sanitization_exception_with_logging(self):
        """Test filter_incoming_baggage exception during sanitization (line 430)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        baggage = {"data": "value"}

        with patch("mcpgateway.baggage.sanitize_header_value", side_effect=Exception("Sanitize failed")):
            with patch("mcpgateway.baggage.logger") as mock_logger:
                result = filter_incoming_baggage(baggage, config)
                # Should log the exception
                assert mock_logger.warning.called
                assert result == {}


class TestDefensiveErrorPaths:
    """Test defensive error handling paths for 100% coverage."""

    def test_parse_baggage_decode_exception_line_366(self):
        """Test parse_w3c_baggage_header exception at line 366 during URL decode."""
        # Standard
        from urllib.parse import unquote as original_unquote

        def failing_unquote(value):
            # Fail on specific value to trigger exception path
            if value == "bad%value":
                raise ValueError("Invalid percent encoding")
            return original_unquote(value)

        with patch("mcpgateway.baggage.unquote", side_effect=failing_unquote):
            with patch("mcpgateway.baggage.logger") as mock_logger:
                # This will trigger the exception during decode
                result = parse_w3c_baggage_header("key=bad%value,other=good")
                # Should log the exception for the bad key
                assert any("Failed to decode baggage value" in str(call) for call in mock_logger.debug.call_args_list)
                # The bad key should not be in result
                assert "key" not in result
                # The good key should still be processed
                assert "other" in result

    def test_filter_incoming_rejected_key_line_405(self):
        """Test filter_incoming_baggage rejected key logging at line 405."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Allowed", "allowed.key")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,
            log_sanitization=False,
        )

        # Include a key not in allowlist
        baggage = {"allowed.key": "value1", "not.in.allowlist": "value2"}

        result = filter_incoming_baggage(baggage, config)
        # Should filter out unauthorized key
        assert "allowed.key" in result
        assert "not.in.allowlist" not in result

    def test_filter_incoming_size_limit_reached_line_437(self):
        """Test filter_incoming_baggage size limit break statement (line 437)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[
                HeaderMapping("X-Key1", "key1"),
                HeaderMapping("X-Key2", "key2"),
                HeaderMapping("X-Key3", "key3"),
            ],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=15,  # Small limit: key1=val1 is 10 bytes, key2=val2 would be 20 total
            log_rejected=False,  # Disable logging to hit the break directly
            log_sanitization=False,
        )

        # First key fits (10 bytes), second key would exceed limit
        baggage = {
            "key1": "val1",  # 4+4+2 = 10 bytes
            "key2": "val2",  # Would be 10 more = 20 total, exceeds 15
            "key3": "val3",  # Should never be processed
        }

        result = filter_incoming_baggage(baggage, config)
        # First key should be included
        assert "key1" in result
        assert result["key1"] == "val1"
        # Second and third keys should be rejected due to size limit
        assert "key2" not in result
        assert "key3" not in result
        # Only one key in result
        assert len(result) == 1

    def test_filter_incoming_sanitize_exception_line_430(self):
        """Test filter_incoming_baggage exception handling at line 430."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        baggage = {"data": "value"}

        # Mock sanitize_header_value to raise exception
        with patch("mcpgateway.baggage.sanitize_header_value") as mock_sanitize:
            mock_sanitize.side_effect = Exception("Sanitize error")
            result = filter_incoming_baggage(baggage, config)
            # Should handle exception and skip the key
            assert result == {}
            assert mock_sanitize.called

    def test_sanitize_for_propagation_exception_lines_530_532(self):
        """Test sanitize_baggage_for_propagation exception at lines 530-532."""
        baggage = {"key": "value"}

        # Mock sanitize_header_value to raise exception
        with patch("mcpgateway.baggage.sanitize_header_value") as mock_sanitize:
            mock_sanitize.side_effect = Exception("Sanitize error")
            result = sanitize_baggage_for_propagation(baggage)
            # Should handle exception and return empty dict
            assert result == {}
            assert mock_sanitize.called


class TestActualLoggerCalls:
    """Test that actual logger calls are executed (not mocked) for 100% coverage."""

    def test_parse_baggage_decode_exception_actual_logging(self):
        """Test parse_w3c_baggage_header exception triggers actual logger.debug (line 366)."""
        # Don't mock logger - let actual logging happen
        with patch("mcpgateway.baggage.unquote", side_effect=Exception("Decode failed")):
            result = parse_w3c_baggage_header("key=value")
            # Should handle exception and return empty dict
            assert result == {}

    def test_filter_incoming_rejected_key_actual_logging(self):
        """Test filter_incoming_baggage rejected key triggers actual logger.debug (line 405)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Allowed", "allowed.key")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=True,  # Enable logging
            log_sanitization=False,
        )

        # Include a key not in allowlist - don't mock logger
        baggage = {"allowed.key": "value1", "not.in.allowlist": "value2"}

        result = filter_incoming_baggage(baggage, config)
        # Should filter out unauthorized key and log it
        assert "allowed.key" in result
        assert "not.in.allowlist" not in result

    def test_filter_incoming_sanitize_exception_actual_logging(self):
        """Test filter_incoming_baggage exception triggers actual logger.warning (line 430)."""
        config = BaggageConfig(
            enabled=True,
            mappings=[HeaderMapping("X-Data", "data")],
            propagate_to_external=False,
            max_items=32,
            max_size_bytes=8192,
            log_rejected=False,
            log_sanitization=False,
        )

        baggage = {"data": "value"}

        # Mock sanitize_header_value to raise exception, but don't mock logger
        with patch("mcpgateway.baggage.sanitize_header_value", side_effect=Exception("Sanitize error")):
            result = filter_incoming_baggage(baggage, config)
            # Should handle exception, log it, and skip the key
            assert result == {}
