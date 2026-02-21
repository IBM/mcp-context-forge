# -*- coding: utf-8 -*-
"""Tests for environment variable parsing utilities."""

# Standard
import logging
import os
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from agent_runtimes.langchain_agent.env_utils import _env_bool, _env_int, _parse_csv


class TestEnvBool:
    """Test _env_bool() function."""

    def test_default_when_unset(self):
        """Test default value when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert _env_bool("MISSING_VAR") is False
            assert _env_bool("MISSING_VAR", default=True) is True

    @pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "Yes", "y", "Y", "on", "ON"])
    def test_truthy_values(self, value):
        """Test all accepted truthy values."""
        with patch.dict(os.environ, {"TEST_BOOL": value}):
            assert _env_bool("TEST_BOOL") is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "", "anything", "truthy"])
    def test_falsy_values(self, value):
        """Test values that resolve to False."""
        with patch.dict(os.environ, {"TEST_BOOL": value}):
            assert _env_bool("TEST_BOOL") is False

    def test_whitespace_stripped(self):
        """Test that surrounding whitespace is stripped."""
        with patch.dict(os.environ, {"TEST_BOOL": "  true  "}):
            assert _env_bool("TEST_BOOL") is True


class TestEnvInt:
    """Test _env_int() function."""

    def test_default_when_unset(self):
        """Test default value when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert _env_int("MISSING_VAR", default=42) == 42

    def test_valid_int(self):
        """Test parsing a valid integer."""
        with patch.dict(os.environ, {"TEST_INT": "8080"}):
            assert _env_int("TEST_INT", default=0) == 8080

    def test_negative_int(self):
        """Test parsing a negative integer."""
        with patch.dict(os.environ, {"TEST_INT": "-1"}):
            assert _env_int("TEST_INT", default=0) == -1

    def test_invalid_value_returns_default(self):
        """Test that invalid values fall back to the default."""
        with patch.dict(os.environ, {"TEST_INT": "not-a-number"}):
            assert _env_int("TEST_INT", default=99) == 99

    def test_invalid_value_logs_warning(self, caplog):
        """Test that invalid values log a warning."""
        with patch.dict(os.environ, {"TEST_INT": "abc"}):
            with caplog.at_level(logging.WARNING):
                _env_int("TEST_INT", default=10)
            assert "Invalid" in caplog.text
            assert "abc" in caplog.text

    def test_float_value_returns_default(self):
        """Test that float strings are treated as invalid."""
        with patch.dict(os.environ, {"TEST_INT": "3.14"}):
            assert _env_int("TEST_INT", default=0) == 0


class TestParseCsv:
    """Test _parse_csv() function."""

    def test_empty_string(self):
        """Test parsing an empty string."""
        assert _parse_csv("") == []

    def test_single_value(self):
        """Test parsing a single value."""
        assert _parse_csv("http://localhost:3000") == ["http://localhost:3000"]

    def test_multiple_values(self):
        """Test parsing comma-separated values."""
        result = _parse_csv("http://localhost:3000,https://example.com")
        assert result == ["http://localhost:3000", "https://example.com"]

    def test_whitespace_stripped(self):
        """Test that whitespace around values is stripped."""
        result = _parse_csv("  http://a.com , http://b.com  ")
        assert result == ["http://a.com", "http://b.com"]

    def test_empty_elements_filtered(self):
        """Test that empty elements from extra commas are filtered out."""
        result = _parse_csv("a,,b,,,c,")
        assert result == ["a", "b", "c"]

    def test_whitespace_only_elements_filtered(self):
        """Test that whitespace-only elements are filtered out."""
        result = _parse_csv("a,  ,b")
        assert result == ["a", "b"]
