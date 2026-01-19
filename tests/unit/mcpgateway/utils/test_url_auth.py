# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_url_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for URL authentication helpers (query parameter auth).

Tests the apply_query_param_auth and sanitize_url_for_logging functions
used for handling query parameter authentication with upstream MCP servers.
"""

import pytest

from mcpgateway.utils.url_auth import (
    STATIC_SENSITIVE_PARAMS,
    apply_query_param_auth,
    sanitize_url_for_logging,
)


class TestApplyQueryParamAuth:
    """Test cases for apply_query_param_auth function."""

    def test_no_params_returns_original_url(self):
        """When auth_query_params is None, return original URL unchanged."""
        url = "https://api.example.com/mcp"
        result = apply_query_param_auth(url, None)
        assert result == url

    def test_empty_params_returns_original_url(self):
        """When auth_query_params is empty dict, return original URL unchanged."""
        url = "https://api.example.com/mcp"
        result = apply_query_param_auth(url, {})
        assert result == url

    def test_adds_single_query_param(self):
        """Add a single query parameter to URL without existing params."""
        url = "https://api.tavily.com/mcp"
        params = {"tavilyApiKey": "secret123"}
        result = apply_query_param_auth(url, params)
        assert result == "https://api.tavily.com/mcp?tavilyApiKey=secret123"

    def test_adds_multiple_query_params(self):
        """Add multiple query parameters to URL."""
        url = "https://api.example.com/mcp"
        params = {"api_key": "key123", "token": "token456"}
        result = apply_query_param_auth(url, params)
        # Note: Order may vary in dict iteration
        assert "api_key=key123" in result
        assert "token=token456" in result
        assert result.startswith("https://api.example.com/mcp?")

    def test_appends_to_existing_query_params(self):
        """Append auth params to URL that already has query parameters."""
        url = "https://api.example.com/search?q=test"
        params = {"api_key": "abc123"}
        result = apply_query_param_auth(url, params)
        assert "q=test" in result
        assert "api_key=abc123" in result

    def test_overrides_existing_param(self):
        """Auth params override existing params with same name."""
        url = "https://api.example.com/mcp?api_key=old_value"
        params = {"api_key": "new_value"}
        result = apply_query_param_auth(url, params)
        assert "api_key=new_value" in result
        assert "old_value" not in result

    def test_preserves_url_path_and_fragment(self):
        """Preserve URL path components when adding params."""
        url = "https://api.example.com/v1/mcp"
        params = {"key": "value"}
        result = apply_query_param_auth(url, params)
        assert result.startswith("https://api.example.com/v1/mcp?")

    def test_handles_special_characters_in_values(self):
        """URL-encode special characters in parameter values."""
        url = "https://api.example.com/mcp"
        params = {"api_key": "key=with+special&chars"}
        result = apply_query_param_auth(url, params)
        # urllib.parse.urlencode handles encoding
        assert "api.example.com/mcp?" in result


class TestSanitizeUrlForLogging:
    """Test cases for sanitize_url_for_logging function."""

    def test_no_query_params_returns_original(self):
        """URL without query params returns unchanged."""
        url = "https://api.example.com/mcp"
        result = sanitize_url_for_logging(url)
        assert result == url

    def test_redacts_static_sensitive_params(self):
        """Redact known sensitive parameter names from static list."""
        url = "https://api.example.com?api_key=secret123&q=search"
        result = sanitize_url_for_logging(url)
        assert "api_key=REDACTED" in result
        assert "q=search" in result
        assert "secret123" not in result

    def test_redacts_gateway_specific_params(self):
        """Redact parameters specified in auth_query_params."""
        url = "https://api.tavily.com/mcp?tavilyApiKey=secret&other=value"
        auth_params = {"tavilyApiKey": "secret"}
        result = sanitize_url_for_logging(url, auth_params)
        assert "tavilyApiKey=REDACTED" in result
        assert "other=value" in result
        assert "secret" not in result

    def test_case_insensitive_matching(self):
        """Sensitive param detection is case-insensitive."""
        url = "https://api.example.com?API_KEY=secret&q=test"
        result = sanitize_url_for_logging(url)
        assert "API_KEY=REDACTED" in result
        assert "q=test" in result

    def test_redacts_multiple_sensitive_params(self):
        """Redact multiple sensitive parameters in same URL."""
        url = "https://api.example.com?api_key=key1&token=tok1&auth=auth1&q=search"
        result = sanitize_url_for_logging(url)
        assert "api_key=REDACTED" in result
        assert "token=REDACTED" in result
        assert "auth=REDACTED" in result
        assert "q=search" in result

    def test_preserves_non_sensitive_params(self):
        """Non-sensitive parameters are preserved unchanged."""
        url = "https://api.example.com?page=1&limit=10&sort=asc"
        result = sanitize_url_for_logging(url)
        assert result == url

    def test_handles_empty_auth_query_params(self):
        """Empty auth_query_params dict only uses static sensitive list."""
        url = "https://api.example.com?api_key=secret&custom=value"
        result = sanitize_url_for_logging(url, {})
        assert "api_key=REDACTED" in result
        assert "custom=value" in result

    def test_redacts_tavily_specific_params(self):
        """Tavily-specific parameter names are in static list."""
        url = "https://mcp.tavily.com?tavilyApiKey=mykey"
        result = sanitize_url_for_logging(url)
        assert "tavilyApiKey=REDACTED" in result
        assert "mykey" not in result


class TestStaticSensitiveParams:
    """Test the STATIC_SENSITIVE_PARAMS constant."""

    def test_contains_common_auth_params(self):
        """Static list includes common authentication parameter names."""
        expected_params = [
            "api_key",
            "apikey",
            "api-key",
            "key",
            "token",
            "access_token",
            "auth",
            "auth_token",
            "secret",
            "password",
        ]
        for param in expected_params:
            assert param in STATIC_SENSITIVE_PARAMS

    def test_contains_tavily_params(self):
        """Static list includes Tavily-specific parameter names."""
        assert "tavilyapikey" in STATIC_SENSITIVE_PARAMS
        assert "tavilyApiKey" in STATIC_SENSITIVE_PARAMS

    def test_is_frozenset(self):
        """Static list is immutable frozenset."""
        assert isinstance(STATIC_SENSITIVE_PARAMS, frozenset)
