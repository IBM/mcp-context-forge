# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_validators.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for the framework's self-contained SecurityValidator.
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.validators import SecurityValidator


class TestSecurityValidatorUrl:
    """Tests for SecurityValidator.validate_url."""

    def test_valid_https_url(self):
        result = SecurityValidator.validate_url("https://example.com")
        assert result == "https://example.com"

    def test_valid_http_url(self):
        result = SecurityValidator.validate_url("http://localhost:8080/mcp")
        assert result == "http://localhost:8080/mcp"

    def test_valid_ws_url(self):
        result = SecurityValidator.validate_url("ws://localhost:9000")
        assert result == "ws://localhost:9000"

    def test_valid_wss_url(self):
        result = SecurityValidator.validate_url("wss://secure.example.com/ws")
        assert result == "wss://secure.example.com/ws"

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            SecurityValidator.validate_url("")

    def test_empty_url_with_field_name(self):
        with pytest.raises(ValueError, match="Server URL cannot be empty"):
            SecurityValidator.validate_url("", field_name="Server URL")

    def test_url_exceeds_max_length(self):
        long_url = "https://example.com/" + "a" * 2048
        with pytest.raises(ValueError, match="exceeds maximum length"):
            SecurityValidator.validate_url(long_url)

    def test_disallowed_scheme_ftp(self):
        with pytest.raises(ValueError, match="must start with one of"):
            SecurityValidator.validate_url("ftp://example.com")

    def test_disallowed_scheme_file(self):
        with pytest.raises(ValueError, match="must start with one of"):
            SecurityValidator.validate_url("file:///etc/passwd")

    def test_url_with_newline(self):
        with pytest.raises(ValueError, match="contains line breaks"):
            SecurityValidator.validate_url("https://example.com\n/malicious")

    def test_url_with_carriage_return(self):
        with pytest.raises(ValueError, match="contains line breaks"):
            SecurityValidator.validate_url("https://example.com\r/malicious")

    def test_url_missing_netloc(self):
        with pytest.raises(ValueError, match="is not a valid URL"):
            SecurityValidator.validate_url("http://")

    def test_urlparse_generic_exception(self):
        with patch("mcpgateway.plugins.framework.validators.urlparse", side_effect=RuntimeError("parse failure")):
            with pytest.raises(ValueError, match="is not a valid URL"):
                SecurityValidator.validate_url("https://example.com")

    def test_case_insensitive_scheme(self):
        result = SecurityValidator.validate_url("HTTPS://EXAMPLE.COM")
        assert result == "HTTPS://EXAMPLE.COM"
