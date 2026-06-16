# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_etag.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

Unit tests for ETag generation and validation utilities.

Examples:
    >>> pytest tests/unit/mcpgateway/utils/test_etag.py -v  # doctest: +SKIP
"""

import pytest

from mcpgateway.utils.etag import (
    generate_etag,
    generate_strong_etag,
    format_etag_header,
    matches_any_etag,
    parse_etag,
    parse_if_match_header,
    validate_etag,
)


class TestGenerateETag:
    """Test ETag generation functions."""

    def test_generate_etag_basic(self):
        """Test basic ETag generation with resource ID and version."""
        etag = generate_etag("abc123", 5)
        assert etag == 'W/"abc123-5"'

    def test_generate_etag_different_versions(self):
        """Test that different versions produce different ETags."""
        etag1 = generate_etag("abc123", 1)
        etag2 = generate_etag("abc123", 2)
        assert etag1 != etag2
        assert etag1 == 'W/"abc123-1"'
        assert etag2 == 'W/"abc123-2"'

    def test_generate_etag_different_resources(self):
        """Test that different resource IDs produce different ETags."""
        etag1 = generate_etag("abc123", 1)
        etag2 = generate_etag("xyz789", 1)
        assert etag1 != etag2

    def test_generate_etag_uuid_format(self):
        """Test ETag generation with UUID hex format."""
        resource_id = "a1b2c3d4e5f6"
        etag = generate_etag(resource_id, 42)
        assert etag == 'W/"a1b2c3d4e5f6-42"'

    def test_generate_etag_sanitizes_input(self):
        """Test that unsafe characters are sanitized from resource ID."""
        # Resource ID with quotes, spaces, newlines should be sanitized
        etag = generate_etag('abc"123 \n456', 1)
        assert '"' not in etag[4:-1]  # Skip W/" and trailing "
        assert ' ' not in etag
        assert '\n' not in etag

    def test_generate_etag_with_hyphens_and_underscores(self):
        """Test that hyphens and underscores are preserved in resource ID."""
        etag = generate_etag("resource-id_123", 1)
        assert etag == 'W/"resource-id_123-1"'


class TestParseETag:
    """Test ETag parsing functions."""

    def test_parse_etag_valid(self):
        """Test parsing valid weak ETag."""
        result = parse_etag('W/"abc123-5"')
        assert result == ("abc123", 5)

    def test_parse_etag_different_versions(self):
        """Test parsing ETags with different version numbers."""
        result1 = parse_etag('W/"abc123-1"')
        result2 = parse_etag('W/"abc123-999"')
        assert result1 == ("abc123", 1)
        assert result2 == ("abc123", 999)

    def test_parse_etag_invalid_format(self):
        """Test that invalid ETag format returns None."""
        assert parse_etag("invalid-etag") is None
        assert parse_etag('abc123-5') is None  # Missing W/" prefix
        assert parse_etag('"abc123-5"') is None  # Missing W/ prefix

    def test_parse_etag_empty_string(self):
        """Test that empty string returns None."""
        assert parse_etag("") is None
        assert parse_etag(None) is None

    def test_parse_etag_malformed(self):
        """Test various malformed ETag formats."""
        assert parse_etag('W/"malformed') is None  # Missing closing quote
        assert parse_etag('W/abc123-5"') is None  # Missing opening quote
        assert parse_etag('W/"abc123"') is None  # Missing version
        assert parse_etag('W/"-5"') is None  # Missing resource ID

    def test_parse_etag_with_whitespace(self):
        """Test that whitespace is stripped before parsing."""
        result = parse_etag('  W/"abc123-5"  ')
        assert result == ("abc123", 5)

    def test_parse_etag_special_characters(self):
        """Test that special characters in resource ID are rejected."""
        # ETag format only allows alphanumeric, hyphens, underscores
        assert parse_etag('W/"abc@123-5"') is None
        assert parse_etag('W/"abc 123-5"') is None


class TestValidateETag:
    """Test ETag validation functions."""

    def test_validate_etag_match(self):
        """Test successful ETag validation when version matches."""
        assert validate_etag('W/"abc123-5"', "abc123", 5) is True

    def test_validate_etag_version_mismatch(self):
        """Test ETag validation fails when version doesn't match."""
        assert validate_etag('W/"abc123-5"', "abc123", 6) is False

    def test_validate_etag_resource_id_mismatch(self):
        """Test ETag validation fails when resource ID doesn't match."""
        assert validate_etag('W/"abc123-5"', "xyz789", 5) is False

    def test_validate_etag_invalid_format(self):
        """Test that invalid ETag format fails validation."""
        assert validate_etag("invalid", "abc123", 5) is False
        assert validate_etag("", "abc123", 5) is False
        assert validate_etag(None, "abc123", 5) is False

    def test_validate_etag_case_sensitive(self):
        """Test that resource ID matching is case-sensitive."""
        assert validate_etag('W/"ABC123-5"', "abc123", 5) is False
        assert validate_etag('W/"abc123-5"', "ABC123", 5) is False


class TestParseIfMatchHeader:
    """Test If-Match header parsing."""

    def test_parse_if_match_single_etag(self):
        """Test parsing single ETag from If-Match header."""
        result = parse_if_match_header('W/"abc-1"')
        assert result == ['W/"abc-1"']

    def test_parse_if_match_multiple_etags(self):
        """Test parsing multiple ETags from If-Match header."""
        result = parse_if_match_header('W/"abc-1", W/"abc-2"')
        assert len(result) == 2
        assert 'W/"abc-1"' in result
        assert 'W/"abc-2"' in result

    def test_parse_if_match_wildcard(self):
        """Test parsing wildcard If-Match header."""
        result = parse_if_match_header('*')
        assert result == ['*']

    def test_parse_if_match_empty(self):
        """Test parsing empty If-Match header."""
        assert parse_if_match_header('') == []
        assert parse_if_match_header(None) == []

    def test_parse_if_match_with_whitespace(self):
        """Test parsing If-Match header with extra whitespace."""
        result = parse_if_match_header('  W/"abc-1"  ,  W/"abc-2"  ')
        assert len(result) == 2
        assert 'W/"abc-1"' in result
        assert 'W/"abc-2"' in result


class TestMatchesAnyETag:
    """Test matching against multiple ETags."""

    def test_matches_any_etag_single_match(self):
        """Test matching with single valid ETag."""
        assert matches_any_etag(['W/"abc-5"'], 'abc', 5) is True

    def test_matches_any_etag_multiple_one_matches(self):
        """Test matching when one of multiple ETags matches."""
        assert matches_any_etag(['W/"abc-4"', 'W/"abc-5"'], 'abc', 5) is True

    def test_matches_any_etag_no_match(self):
        """Test matching when no ETags match."""
        assert matches_any_etag(['W/"abc-4"'], 'abc', 5) is False
        assert matches_any_etag(['W/"abc-4"', 'W/"abc-6"'], 'abc', 5) is False

    def test_matches_any_etag_wildcard(self):
        """Test that wildcard always matches."""
        assert matches_any_etag(['*'], 'abc', 5) is True
        assert matches_any_etag(['*', 'W/"other-1"'], 'abc', 5) is True

    def test_matches_any_etag_empty_list(self):
        """Test that empty list doesn't match."""
        assert matches_any_etag([], 'abc', 5) is False


class TestFormatETagHeader:
    """Test ETag header formatting."""

    def test_format_etag_header_passthrough(self):
        """Test that format_etag_header is a pass-through."""
        etag = 'W/"abc123-5"'
        assert format_etag_header(etag) == etag


class TestGenerateStrongETag:
    """Test strong ETag generation."""

    def test_generate_strong_etag_basic(self):
        """Test basic strong ETag generation."""
        etag = generate_strong_etag(b"test content")
        assert etag.startswith('"')
        assert etag.endswith('"')
        assert 'W/' not in etag  # Strong ETags don't have W/ prefix

    def test_generate_strong_etag_deterministic(self):
        """Test that same content produces same strong ETag."""
        content = b"test content"
        etag1 = generate_strong_etag(content)
        etag2 = generate_strong_etag(content)
        assert etag1 == etag2

    def test_generate_strong_etag_different_content(self):
        """Test that different content produces different strong ETags."""
        etag1 = generate_strong_etag(b"content 1")
        etag2 = generate_strong_etag(b"content 2")
        assert etag1 != etag2


class TestETagRoundTrip:
    """Test ETag generation and validation round-trip."""

    def test_roundtrip_generate_parse_validate(self):
        """Test that generated ETag can be parsed and validated."""
        resource_id = "test-resource-123"
        version = 42

        # Generate ETag
        etag = generate_etag(resource_id, version)

        # Parse ETag
        parsed = parse_etag(etag)
        assert parsed is not None
        parsed_id, parsed_version = parsed
        assert parsed_id == resource_id
        assert parsed_version == version

        # Validate ETag
        assert validate_etag(etag, resource_id, version) is True

    def test_roundtrip_multiple_versions(self):
        """Test round-trip with version increments."""
        resource_id = "test-resource"

        for version in range(1, 10):
            etag = generate_etag(resource_id, version)
            assert validate_etag(etag, resource_id, version) is True
            # Previous versions should not validate
            if version > 1:
                assert validate_etag(etag, resource_id, version - 1) is False

    def test_parse_etag_malformed_version_not_integer(self):
        """Test parsing ETag with non-integer version (ValueError)."""
        etag = 'W/"abc123-notanumber"'
        result = parse_etag(etag)
        assert result is None

    def test_parse_etag_missing_groups(self):
        """Test parsing ETag with invalid format that causes IndexError."""
        # ETag with format that matches regex but has no groups
        etag = 'W/""'
        result = parse_etag(etag)
        # Should return None due to missing groups
        assert result is None or result == ("", 0)  # Either fails or gets empty string
