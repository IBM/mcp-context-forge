# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_translate_header_utils.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for translate_header_utils helpers.
"""

# Standard
from unittest.mock import Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.translate_header_utils import (
    HeaderMappingError,
    NormalizedMappings,
    extract_env_vars_from_headers,
    parse_header_mappings,
    sanitize_header_value,
    validate_header_mapping,
)


def test_validate_header_mapping_errors():
    validate_header_mapping("Authorization", "AUTH_TOKEN")
    with pytest.raises(HeaderMappingError):
        validate_header_mapping("Invalid Header!", "VAR")
    with pytest.raises(HeaderMappingError):
        validate_header_mapping("Header", "123_VAR")
    with pytest.raises(HeaderMappingError):
        validate_header_mapping("Header", "A" * 65)


def test_sanitize_header_value():
    assert sanitize_header_value("Bearer token123") == "Bearer token123"
    assert sanitize_header_value("a" * 10, max_length=5) == "aaaaa"
    assert sanitize_header_value("hello\x00world") == "helloworld"


def test_parse_header_mappings_and_duplicates():
    mappings = parse_header_mappings(["Authorization=AUTH_TOKEN", "X-Api-Key=API_KEY"])
    assert mappings["Authorization"] == "AUTH_TOKEN"
    assert mappings["X-Api-Key"] == "API_KEY"

    with pytest.raises(HeaderMappingError):
        parse_header_mappings(["InvalidMapping"])

    with pytest.raises(HeaderMappingError):
        parse_header_mappings(["Authorization=AUTH1", "authorization=AUTH2"])

    with pytest.raises(HeaderMappingError):
        parse_header_mappings(["Authorization="])

    with pytest.raises(HeaderMappingError):
        parse_header_mappings(["Authorization=AUTH1", "Authorization=AUTH2"])


def test_normalized_mappings_and_extract():
    nm = NormalizedMappings({"Authorization": "AUTH"})
    assert nm.get_env_var("authorization") == "AUTH"
    assert list(nm) == [("authorization", "AUTH")]
    assert len(nm) == 1

    headers = {"authorization": "Bearer token", "Content-Type": "application/json"}
    env_vars = extract_env_vars_from_headers(headers, nm)
    assert env_vars == {"AUTH": "Bearer token"}


def test_extract_env_vars_skips_empty_sanitized_value(monkeypatch):
    monkeypatch.setattr("mcpgateway.translate_header_utils.sanitize_header_value", lambda _value: "")
    nm = NormalizedMappings({"Authorization": "AUTH"})

    env_vars = extract_env_vars_from_headers({"Authorization": "Bearer token"}, nm)

    assert env_vars == {}


def test_extract_env_vars_handles_sanitize_exception(monkeypatch):
    def _raise(_value: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr("mcpgateway.translate_header_utils.sanitize_header_value", _raise)
    nm = NormalizedMappings({"Authorization": "AUTH"})

    env_vars = extract_env_vars_from_headers({"Authorization": "Bearer token"}, nm)

    assert env_vars == {}


def test_mock_safe_max_length_fallback():
    """Test that Mock objects from settings are handled safely in sanitize_header_value."""
    # Mock settings.max_header_value_length to return a Mock object (test behavior)
    with patch("mcpgateway.translate_header_utils.settings") as mock_settings:
        mock_settings.max_header_value_length = Mock()  # Returns Mock, not int

        # Should fall back to 16384 default instead of using Mock (which would become 1)
        result = sanitize_header_value("test_value")
        assert result == "test_value"

        # Test with value larger than default
        large_value = "a" * 20000
        result = sanitize_header_value(large_value)
        assert len(result) == 16384  # Should use fallback, not Mock.__int__ (1)


def test_settings_attribute_error_fallback():
    """Test fallback when settings.max_header_value_length raises AttributeError."""
    # Mock settings to raise AttributeError when accessing max_header_value_length
    with patch("mcpgateway.translate_header_utils.settings") as mock_settings:
        type(mock_settings).max_header_value_length = property(lambda self: (_ for _ in ()).throw(AttributeError("attribute not found")))

        # Should fall back to 16384 default
        result = sanitize_header_value("test_value")
        assert result == "test_value"

        # Test with value larger than default
        large_value = "a" * 20000
        result = sanitize_header_value(large_value)
        assert len(result) == 16384


def test_settings_type_error_fallback():
    """Test fallback when settings.max_header_value_length raises TypeError."""
    # Mock settings to raise TypeError when accessing max_header_value_length
    with patch("mcpgateway.translate_header_utils.settings") as mock_settings:
        type(mock_settings).max_header_value_length = property(lambda self: (_ for _ in ()).throw(TypeError("type error")))

        # Should fall back to 16384 default
        result = sanitize_header_value("test_value")
        assert result == "test_value"

        # Test with value larger than default
        large_value = "a" * 20000
        result = sanitize_header_value(large_value)
        assert len(result) == 16384
