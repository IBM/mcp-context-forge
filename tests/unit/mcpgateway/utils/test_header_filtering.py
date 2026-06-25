# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_header_filtering.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for header filtering utilities.

This test suite verifies that the filter_sensitive_headers function correctly
removes authentication and credential headers before passing data to plugins
or external services, preventing credential leakage.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.header_filtering import filter_sensitive_headers


class TestFilterSensitiveHeaders:
    """Test the filter_sensitive_headers function."""

    def test_empty_headers(self):
        """Empty dictionary should return empty dictionary."""
        assert filter_sensitive_headers({}) == {}

    def test_safe_headers_pass_through(self):
        """Non-sensitive headers should pass through unchanged."""
        safe_headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "test-client/1.0",
            "x-request-id": "abc123",
            "x-correlation-id": "def456",
        }
        result = filter_sensitive_headers(safe_headers)
        assert result == safe_headers

    def test_authorization_header_filtered(self):
        """Authorization header should be filtered out."""
        headers = {
            "authorization": "Bearer token123",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}
        assert "authorization" not in result

    def test_authorization_case_insensitive(self):
        """Authorization header filtering should be case-insensitive."""
        headers = {
            "Authorization": "Bearer token123",
            "AUTHORIZATION": "Bearer token456",
            "AuThOrIzAtIoN": "Bearer token789",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}

    def test_proxy_authorization_filtered(self):
        """Proxy-Authorization header should be filtered out."""
        headers = {
            "proxy-authorization": "Basic abc123",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}

    def test_api_key_variants_filtered(self):
        """Various API key header formats should be filtered."""
        headers = {
            "x-api-key": "secret123",  # pragma: allowlist secret
            "api-key": "secret456",  # pragma: allowlist secret
            "apikey": "secret789",  # pragma: allowlist secret
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}
        assert "x-api-key" not in result
        assert "api-key" not in result
        assert "apikey" not in result

    def test_api_key_case_insensitive(self):
        """API key header filtering should be case-insensitive."""
        headers = {
            "X-Api-Key": "secret123",  # pragma: allowlist secret
            "API-KEY": "secret456",  # pragma: allowlist secret
            "ApiKey": "secret789",  # pragma: allowlist secret
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}

    def test_cookie_headers_filtered(self):
        """Cookie and Set-Cookie headers should be filtered."""
        headers = {
            "cookie": "session=abc123",
            "set-cookie": "token=xyz789",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}
        assert "cookie" not in result
        assert "set-cookie" not in result

    def test_host_header_filtered(self):
        """Host header should be filtered out."""
        headers = {
            "host": "example.com",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}
        assert "host" not in result

    def test_x_auth_token_patterns_filtered(self):
        """X-Auth-Token and similar patterns should be filtered."""
        headers = {
            "x-auth-token": "token123",
            "x-api-token": "token456",
            "x-access-token": "token789",
            "x-refresh-token": "token012",
            "x-client-token": "token345",
            "x-bearer-token": "token678",
            "x-session-token": "token901",
            "x-security-token": "token234",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}
        assert len(result) == 1

    def test_x_auth_key_patterns_filtered(self):
        """X-Auth-Key and similar patterns should be filtered."""
        headers = {
            "x-auth-key": "key123",
            "x-api-key": "key456",  # pragma: allowlist secret
            "x-access-key": "key789",
            "x-client-key": "key012",
            "x-security-key": "key345",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}

    def test_x_auth_secret_patterns_filtered(self):
        """X-Auth-Secret and similar patterns should be filtered."""
        headers = {
            "x-auth-secret": "secret123",  # pragma: allowlist secret
            "x-api-secret": "secret456",  # pragma: allowlist secret
            "x-access-secret": "secret789",  # pragma: allowlist secret
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}

    def test_underscore_variants_filtered(self):
        """Underscore variants of sensitive headers should be filtered."""
        headers = {
            "x-auth_token": "token123",
            "x-api_key": "key456",  # pragma: allowlist secret
            "x-access_secret": "secret789",  # pragma: allowlist secret
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}

    def test_hyphen_variants_filtered(self):
        """Hyphen variants of sensitive headers should be filtered."""
        headers = {
            "x-auth-token": "token123",
            "x-api-key": "key456",  # pragma: allowlist secret
            "x-access-secret": "secret789",  # pragma: allowlist secret
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}

    def test_mixed_safe_and_sensitive_headers(self):
        """Mixed headers should only pass through safe ones."""
        headers = {
            "content-type": "application/json",
            "authorization": "Bearer token",
            "accept": "application/json",
            "x-api-key": "secret",
            "user-agent": "test-client",
            "cookie": "session=abc",
            "x-correlation-id": "trace123",
        }
        result = filter_sensitive_headers(headers)
        expected = {
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "test-client",
            "x-correlation-id": "trace123",
        }
        assert result == expected

    def test_all_sensitive_headers_filtered(self):
        """When all headers are sensitive, empty dict should be returned."""
        headers = {
            "authorization": "Bearer token",
            "x-api-key": "secret",
            "cookie": "session=abc",
        }
        result = filter_sensitive_headers(headers)
        assert result == {}

    def test_preserves_original_dict(self):
        """Original headers dict should not be modified."""
        original = {
            "authorization": "Bearer token",
            "content-type": "application/json",
        }
        original_copy = original.copy()
        result = filter_sensitive_headers(original)

        # Original should be unchanged
        assert original == original_copy
        # Result should be filtered
        assert result == {"content-type": "application/json"}

    def test_header_values_preserved(self):
        """Safe header values should be preserved exactly."""
        headers = {
            "content-type": "application/json; charset=utf-8",
            "accept-language": "en-US,en;q=0.9",
            "x-custom-header": "value with spaces and special chars: !@#$%",
        }
        result = filter_sensitive_headers(headers)
        assert result == headers

    def test_plugin_credential_leakage_prevention(self):
        """Verify that plugin hooks cannot receive credentials via headers.

        This is the primary security use case for this function (Issue #3621).
        Plugin hooks should ALWAYS receive sanitized headers to prevent
        credential leakage.
        """
        # Simulated headers from an incoming request with various credentials
        request_headers = {
            "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "x-api-key": "sk-prod-abc123xyz789",  # pragma: allowlist secret
            "cookie": "session_id=sensitive_session_token",
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "MyClient/1.0",
            "x-request-id": "req-12345",
        }

        # Filter before passing to plugin hooks
        plugin_headers = filter_sensitive_headers(request_headers)

        # Assert that NO credentials made it through
        assert "authorization" not in plugin_headers
        assert "x-api-key" not in plugin_headers
        assert "cookie" not in plugin_headers

        # Assert that safe headers are present
        assert plugin_headers["content-type"] == "application/json"
        assert plugin_headers["accept"] == "application/json"
        assert plugin_headers["user-agent"] == "MyClient/1.0"
        assert plugin_headers["x-request-id"] == "req-12345"

        # Verify the credential values are NOT in the filtered dict at all
        headers_str = str(plugin_headers)
        assert "Bearer" not in headers_str
        assert "sk-prod-abc123xyz789" not in headers_str
        assert "session_id" not in headers_str
        assert "sensitive_session_token" not in headers_str

    def test_downstream_passthrough_scenario(self):
        """Verify filtering works for downstream agent passthrough headers.

        When ENABLE_SENSITIVE_HEADER_PASSTHROUGH=false (Phase 1 default),
        downstream headers should also be filtered.
        """
        # Simulated whitelisted headers after passthrough_headers filtering
        whitelisted_headers = {
            "authorization": "Bearer token",  # User wants to pass this through
            "x-auth-token": "custom_value",  # Custom auth token header that matches pattern
            "content-type": "application/json",
        }

        # Apply sensitive header filtering (Phase 1 behavior)
        downstream_headers = filter_sensitive_headers(whitelisted_headers)

        # In Phase 1, even whitelisted sensitive headers are filtered
        assert "authorization" not in downstream_headers
        assert "x-auth-token" not in downstream_headers  # Matches x-*-token pattern
        assert downstream_headers == {"content-type": "application/json"}

    @pytest.mark.parametrize(
        "header_name",
        [
            "authorization",
            "Authorization",
            "AUTHORIZATION",
            "proxy-authorization",
            "Proxy-Authorization",
            "x-api-key",
            "X-API-KEY",
            "api-key",
            "API-KEY",
            "apikey",
            "ApiKey",
            "APIKEY",
            "cookie",
            "Cookie",
            "COOKIE",
            "set-cookie",
            "Set-Cookie",
            "SET-COOKIE",
            "host",
            "Host",
            "HOST",
        ],
    )
    def test_common_sensitive_headers_parametrized(self, header_name):
        """Parametrized test for common sensitive headers."""
        headers = {
            header_name: "sensitive_value",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}
        assert header_name not in result

    @pytest.mark.parametrize(
        "header_pattern",
        [
            "x-auth-token",
            "x-api-token",
            "x-access-token",
            "x-refresh-token",
            "x-client-token",
            "x-bearer-token",
            "x-session-token",
            "x-security-token",
            "x-auth-key",
            "x-api-key",
            "x-access-key",
            "x-client-key",
            "x-auth-secret",
            "x-api-secret",
            "x-access-secret",
            "x-auth_token",  # underscore variant
            "x-api_key",  # underscore variant
        ],
    )
    def test_x_pattern_headers_parametrized(self, header_pattern):
        """Parametrized test for X-* pattern sensitive headers."""
        headers = {
            header_pattern: "sensitive_value",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "application/json"}
        assert header_pattern not in result

    def test_safe_x_headers_not_filtered(self):
        """Safe X-* headers should not be filtered."""
        safe_x_headers = {
            "x-request-id": "req123",
            "x-correlation-id": "corr456",
            "x-trace-id": "trace789",
            "x-forwarded-for": "192.168.1.1",
            "x-forwarded-proto": "https",
            "x-real-ip": "10.0.0.1",
            "x-custom-header": "custom_value",
            "x-application-name": "my-app",
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(safe_x_headers)
        assert result == safe_x_headers

    def test_edge_case_empty_header_values(self):
        """Empty header values should be preserved if header name is safe."""
        headers = {
            "content-type": "",
            "accept": "",
            "authorization": "",  # Still filtered even if empty
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "", "accept": ""}

    def test_edge_case_whitespace_header_values(self):
        """Whitespace-only header values should be preserved if header name is safe."""
        headers = {
            "content-type": "   ",
            "accept": "\t\n",
            "authorization": "   ",  # Still filtered even if whitespace
        }
        result = filter_sensitive_headers(headers)
        assert result == {"content-type": "   ", "accept": "\t\n"}

    def test_unicode_header_values_preserved(self):
        """Unicode characters in safe header values should be preserved."""
        headers = {
            "content-type": "application/json; charset=utf-8",
            "x-custom-message": "Hello 世界 🌍",
            "accept-language": "en-US,zh-CN;q=0.9",
        }
        result = filter_sensitive_headers(headers)
        assert result == headers

    def test_very_long_header_value_preserved(self):
        """Very long safe header values should be preserved."""
        long_value = "a" * 10000
        headers = {
            "x-custom-header": long_value,
            "content-type": "application/json",
        }
        result = filter_sensitive_headers(headers)
        assert result == headers
        assert len(result["x-custom-header"]) == 10000

    def test_special_characters_in_safe_headers(self):
        """Special characters in safe header names and values should work."""
        headers = {
            "content-type": "application/json; boundary=----WebKitFormBoundary123",
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br",
            "x-custom-header": "value=with=equals&ampersands",
        }
        result = filter_sensitive_headers(headers)
        assert result == headers
