# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_url_auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for URL authentication helpers (query parameter auth).

Tests the apply_query_param_auth and sanitize_url_for_logging functions
used for handling query parameter authentication with upstream MCP servers.
"""

# First-Party
from mcpgateway.utils.url_auth import (
    apply_query_param_auth,
    sanitize_exception_message,
    sanitize_url_for_logging,
    STATIC_SENSITIVE_PARAMS,
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
        params = {"tavilyApiKey": "secret123"}  # pragma: allowlist secret
        result = apply_query_param_auth(url, params)
        assert result == "https://api.tavily.com/mcp?tavilyApiKey=secret123"

    def test_adds_multiple_query_params(self):
        """Add multiple query parameters to URL."""
        url = "https://api.example.com/mcp"
        params = {"api_key": "key123", "token": "token456"}  # pragma: allowlist secret
        result = apply_query_param_auth(url, params)
        # Note: Order may vary in dict iteration
        assert "api_key=key123" in result
        assert "token=token456" in result
        assert result.startswith("https://api.example.com/mcp?")

    def test_appends_to_existing_query_params(self):
        """Append auth params to URL that already has query parameters."""
        url = "https://api.example.com/search?q=test"
        params = {"api_key": "abc123"}  # pragma: allowlist secret
        result = apply_query_param_auth(url, params)
        assert "q=test" in result
        assert "api_key=abc123" in result

    def test_overrides_existing_param(self):
        """Auth params override existing params with same name."""
        url = "https://api.example.com/mcp?api_key=old_value"
        params = {"api_key": "new_value"}  # pragma: allowlist secret
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
        params = {"api_key": "key=with+special&chars"}  # pragma: allowlist secret
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

    def test_redacts_userinfo_in_netloc(self):
        url = "https://user:pass@api.example.com/endpoint"  # pragma: allowlist secret
        result = sanitize_url_for_logging(url)
        assert result == "https://REDACTED:REDACTED@api.example.com/endpoint"  # pragma: allowlist secret

        url_v6 = "https://user:pass@[::1]:8080/path"  # pragma: allowlist secret
        result_v6 = sanitize_url_for_logging(url_v6)
        assert result_v6 == "https://REDACTED:REDACTED@[::1]:8080/path"  # pragma: allowlist secret


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


class TestSanitizeExceptionMessage:
    """Test cases for sanitize_exception_message function."""

    def test_empty_message_returns_empty(self):
        """Empty message returns empty string."""
        assert sanitize_exception_message("") == ""

    def test_none_message_returns_none(self):
        """None message returns None (falsy passthrough)."""
        assert sanitize_exception_message(None) is None

    def test_message_without_url_unchanged(self):
        """Message without URLs returns unchanged."""
        msg = "Connection refused: server not responding"
        assert sanitize_exception_message(msg) == msg

    def test_sanitizes_single_url_with_static_sensitive_param(self):
        """Sanitize URL with static sensitive param in exception message."""
        msg = "Connection failed: https://api.example.com?api_key=secret123"
        result = sanitize_exception_message(msg)
        assert "api_key=REDACTED" in result
        assert "secret123" not in result
        assert result.startswith("Connection failed:")

    def test_sanitizes_url_with_gateway_specific_param(self):
        """Sanitize URL with gateway-specific auth param."""
        msg = "Error connecting to https://api.tavily.com/mcp?tavilyApiKey=mykey123"
        result = sanitize_exception_message(msg, {"tavilyApiKey": "mykey123"})  # pragma: allowlist secret
        assert "tavilyApiKey=REDACTED" in result
        assert "mykey123" not in result

    def test_redacts_configured_secret_outside_urls_and_in_unknown_url_params(self):
        """Configured values are redacted even outside URL query parameters."""
        secret = "dummy-configured-key-12345"  # pragma: allowlist secret
        msg = f"Request apiToken={secret} failed; " f"upstream URL https://api.example.com?routeKey={secret}&page=2"

        result = sanitize_exception_message(msg, {"apiToken": secret})

        assert "apiToken=REDACTED" in result
        assert "routeKey=REDACTED" in result
        assert "page=2" in result
        assert secret not in result

    def test_redacts_repeated_overlapping_configured_values(self):
        """Longer overlapping values are replaced first and all occurrences are removed."""
        longer = "dummy-secret-value-123"  # pragma: allowlist secret
        shorter = "secret-value-123"  # pragma: allowlist secret
        msg = f"first={longer}; second={shorter}; repeat={longer}"

        result = sanitize_exception_message(msg, {"long": longer, "short": shorter})

        assert result.count("REDACTED") == 3
        assert longer not in result
        assert shorter not in result

    def test_skips_empty_and_short_configured_values(self):
        """Empty and short values do not cause broad replacements in ordinary text."""
        msg = "id appears in words like identity; empty stays empty"

        result = sanitize_exception_message(msg, {"empty": "", "short": "id"})

        assert result == msg

    def test_message_without_configured_secret_remains_unchanged(self):
        """Configured values absent from a message do not alter it."""
        msg = "Connection failed while requesting page=2"

        result = sanitize_exception_message(msg, {"apiToken": "dummy-configured-key-12345"})

        assert result == msg

    def test_sanitizes_multiple_urls_in_message(self):
        """Sanitize multiple URLs in a single exception message."""
        msg = "Redirect from https://api.example.com?token=tok1 to https://api.example.com/v2?api_key=key2"
        result = sanitize_exception_message(msg)
        assert "token=REDACTED" in result
        assert "api_key=REDACTED" in result
        assert "tok1" not in result
        assert "key2" not in result

    def test_preserves_non_sensitive_params_in_url(self):
        """Non-sensitive params in URLs are preserved."""
        msg = "Request to https://api.example.com?page=1&api_key=secret failed"
        result = sanitize_exception_message(msg)
        assert "page=1" in result
        assert "api_key=REDACTED" in result
        assert "secret" not in result

    def test_handles_url_at_end_of_message(self):
        """Handle URL at the end of message without trailing space."""
        msg = "Failed to connect to https://api.example.com?token=abc123"
        result = sanitize_exception_message(msg)
        assert "token=REDACTED" in result
        assert "abc123" not in result

    def test_handles_url_without_query_params(self):
        """URL without query params passes through unchanged."""
        msg = "Connection to https://api.example.com/mcp failed"
        result = sanitize_exception_message(msg)
        assert result == msg

    def test_handles_http_url(self):
        """Handle non-HTTPS (HTTP) URLs as well."""
        msg = "Error: http://localhost:8000?api_key=localkey"
        result = sanitize_exception_message(msg)
        assert "api_key=REDACTED" in result
        assert "localkey" not in result
