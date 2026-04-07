# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.baggage module.

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
    BaggageSizeLimitError,
    filter_incoming_baggage,
    HeaderMapping,
    extract_baggage_from_headers,
    format_w3c_baggage_header,
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
