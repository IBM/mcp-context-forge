# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/token_backends/test_base.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for base token backend utilities.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.services.token_backends.base import normalize_resource_url


class TestNormalizeResourceUrl:
    """Test suite for normalize_resource_url utility function."""

    def test_normalize_with_query_preserved(self):
        """Test URL normalization preserving query parameters."""
        url = "https://api.example.com/path?foo=bar&baz=qux"
        result = normalize_resource_url(url, preserve_query=True)
        assert result == "https://api.example.com/path?foo=bar&baz=qux"

    def test_normalize_without_query_stripped(self):
        """Test URL normalization stripping query parameters."""
        url = "https://api.example.com/path?foo=bar&baz=qux"
        result = normalize_resource_url(url, preserve_query=False)
        assert result == "https://api.example.com/path"

    def test_normalize_with_fragment(self):
        """Test URL normalization removes fragments."""
        url = "https://api.example.com/path#section"
        result = normalize_resource_url(url, preserve_query=False)
        assert result == "https://api.example.com/path"

    def test_normalize_trailing_slash(self):
        """Test URL normalization with trailing slashes."""
        url = "https://api.example.com/path/"
        result = normalize_resource_url(url, preserve_query=False)
        # Trailing slash is preserved per implementation
        assert result == "https://api.example.com/path/"

    def test_normalize_empty_url(self):
        """Test normalize_resource_url with empty string returns None."""
        result = normalize_resource_url("", preserve_query=False)
        assert result is None

    def test_normalize_none_url(self):
        """Test normalize_resource_url with None."""
        result = normalize_resource_url(None, preserve_query=False)
        assert result is None

    def test_normalize_invalid_url(self):
        """Test normalize_resource_url with invalid URL."""
        result = normalize_resource_url("not a valid url", preserve_query=False)
        # Should return original string if parsing fails
        assert result == "not a valid url"
