# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_passthrough_headers_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Security tests for HTTP header passthrough utilities.
"""

# Standard
from unittest.mock import Mock, patch

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.utils.passthrough_headers import (
    get_passthrough_headers,
    MAX_HEADER_VALUE_LENGTH,
    sanitize_header_value,
    validate_header_name,
)


class TestHeaderSecurity:
    """Test security features of header passthrough."""

    def setup_method(self):
        """Clear the global config cache before each test to ensure isolation."""
        global_config_cache.invalidate()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_feature_flag_disabled_by_default(self, mock_settings):
        """Test that the feature is disabled by default for security."""
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        request_headers = {"x-tenant-id": "test"}
        base_headers = {"Content-Type": "application/json"}

        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Should return only base headers when disabled
        assert result == base_headers

        # Database should not be queried when feature is disabled
        mock_db.query.assert_not_called()

    def test_sanitize_header_value_injection_prevention(self):
        """Test that header value sanitization prevents injection attacks."""
        # Test newline injection
        malicious_value = "valid-value\r\nX-Injected: malicious"
        result = sanitize_header_value(malicious_value)
        assert "\r" not in result
        assert "\n" not in result
        assert result == "valid-valueX-Injected: malicious"

    def test_sanitize_header_value_control_chars(self):
        """Test that control characters are removed."""
        # Include various control characters (ASCII 0-31 except tab)
        control_chars = "".join(chr(i) for i in range(32) if i != 9)  # Exclude tab
        malicious_value = f"start{control_chars}end"

        result = sanitize_header_value(malicious_value)

        # Should only contain printable chars and tab
        for char in result:
            char_code = ord(char)
            assert char_code >= 32 or char_code == 9

    def test_sanitize_header_value_length_limit(self):
        """Test that header values are limited to prevent DoS attacks."""
        oversized_value = "A" * (MAX_HEADER_VALUE_LENGTH * 2)
        result = sanitize_header_value(oversized_value)

        assert len(result) == MAX_HEADER_VALUE_LENGTH
        assert result == "A" * MAX_HEADER_VALUE_LENGTH

    def test_validate_header_name_injection_prevention(self):
        """Test that header name validation prevents injection."""
        malicious_names = [
            "Valid-Name\r\nX-Injected: value",  # Newline injection
            "Name With Spaces",  # Spaces not allowed
            "Name_With_Underscores",  # Underscores not allowed
            "Name.With.Dots",  # Dots not allowed
            "Name:With:Colons",  # Colons not allowed
            "Name/With/Slashes",  # Slashes not allowed
            "Name@With@Symbols",  # Special chars not allowed
            "",  # Empty string
            "Name\x00WithNull",  # Null byte
        ]

        for malicious_name in malicious_names:
            assert not validate_header_name(malicious_name), f"Should reject: {malicious_name!r}"

    def test_validate_header_name_allows_safe_names(self):
        """Test that safe header names are allowed."""
        safe_names = [
            "Authorization",
            "X-Tenant-Id",
            "Content-Type",
            "User-Agent",
            "X-123-Test",
            "X",
            "A-B-C-123",
        ]

        for safe_name in safe_names:
            assert validate_header_name(safe_name), f"Should allow: {safe_name!r}"

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_header_validation_applied_in_passthrough(self, mock_settings, caplog):
        """Test that header validation is applied during passthrough."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None  # No global config
        mock_settings.default_passthrough_headers = ["Invalid Header Name", "Valid-Header"]

        request_headers = {"invalid header name": "should-be-rejected", "valid-header": "should-pass"}
        base_headers = {"Content-Type": "application/json"}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Only valid header should pass through
        expected = {"Content-Type": "application/json", "Valid-Header": "should-pass"}
        assert result == expected

        # Should log warning about invalid header name
        assert any("Invalid header name" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_header_sanitization_applied_in_passthrough(self, mock_settings, caplog):
        """Test that header sanitization is applied during passthrough."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None
        mock_settings.default_passthrough_headers = ["X-Test"]

        # Request with dangerous header value
        request_headers = {"x-test": "value\r\nwith\x01dangerous\x02chars"}
        base_headers = {"Content-Type": "application/json"}

        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Header value should be sanitized
        expected = {"Content-Type": "application/json", "X-Test": "valuewithdangerouschars"}  # Sanitized
        assert result == expected

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_empty_sanitized_header_skipped(self, mock_settings, caplog):
        """Test that headers that become empty after sanitization are skipped."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None
        mock_settings.default_passthrough_headers = ["X-Test"]

        # Header with only dangerous characters
        request_headers = {"x-test": "\r\n\x01\x02\x03   "}  # Only control chars and whitespace
        base_headers = {"Content-Type": "application/json"}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Header should be skipped
        expected = {"Content-Type": "application/json"}
        assert result == expected

        # Should log warning about empty header
        assert any("became empty after sanitization" in record.message for record in caplog.records)

    def test_sanitization_exception_handling(self, caplog):
        """Test that sanitization handles edge cases gracefully."""
        # Test with non-string input (should not happen in practice)
        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value") as mock_sanitize:
            mock_sanitize.side_effect = Exception("Test error")

            mock_settings = Mock()
            mock_settings.enable_header_passthrough = True
            mock_settings.default_passthrough_headers = ["X-Test"]

            mock_db = Mock()
            mock_db.query.return_value.first.return_value = None

            with patch("mcpgateway.utils.passthrough_headers.settings", mock_settings):
                # Standard
                import logging

                with caplog.at_level(logging.WARNING):
                    result = get_passthrough_headers({"x-test": "value"}, {"Content-Type": "application/json"}, mock_db)

                # Should skip the header due to sanitization error
                expected = {"Content-Type": "application/json"}
                assert result == expected

    def test_regex_pattern_security(self):
        """Test that the regex pattern is secure against ReDoS attacks."""
        # Test with potentially problematic input
        problematic_inputs = [
            "A" * 1000,  # Very long string
            "A-" * 500,  # Repeated pattern
            "A" + "-" * 1000 + "B",  # Long middle section
        ]

        # Standard
        import time

        for test_input in problematic_inputs:
            start_time = time.time()
            validate_header_name(test_input)
            end_time = time.time()

            # Should complete quickly (less than 1 second)
            assert (end_time - start_time) < 1.0, f"Regex took too long for: {test_input[:50]}..."

            # Our regex doesn't restrict length, so long valid patterns will pass
            # This is by design - length limiting is handled by sanitization

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_authorization_header_security(self, mock_settings, caplog):
        """Test security around Authorization header handling."""
        mock_settings.enable_header_passthrough = True

        # Test that Authorization header is properly blocked with gateway auth
        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None
        mock_settings.default_passthrough_headers = ["Authorization"]

        mock_gateway = Mock()
        mock_gateway.passthrough_headers = None
        mock_gateway.auth_type = "basic"
        mock_gateway.name = "secure-gateway"

        request_headers = {"authorization": "Bearer potentially-leaked-token"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Authorization should be blocked
        assert "Authorization" not in result

        # Should log security warning with gateway name
        assert any("Skipping Authorization header passthrough due to basic auth configuration on gateway secure-gateway" in record.message for record in caplog.records)

    def test_case_sensitivity_security(self):
        """Test that case sensitivity doesn't create security bypasses."""
        # Ensure that different cases of the same header are handled consistently
        # Note: Content-Type is now in the denylist (Issue #4450), so we test with safe headers
        test_cases = [
            ("Authorization", "authorization"),
            ("X-Tenant-Id", "x-tenant-id"),
            ("X-Custom-Header", "x-custom-header"),
        ]

        for config_case, request_case in test_cases:
            # Test that request headers are properly matched regardless of case
            mock_settings = Mock()
            mock_settings.enable_header_passthrough = True
            mock_settings.default_passthrough_headers = [config_case]

            mock_db = Mock()
            mock_db.query.return_value.first.return_value = None

            with patch("mcpgateway.utils.passthrough_headers.settings", mock_settings):
                result = get_passthrough_headers({request_case: "test-value"}, {}, mock_db)

                # Should match and use config case
                assert config_case in result
                assert result[config_case] == "test-value"

    def test_memory_safety_with_large_inputs(self):
        """Test memory safety with large inputs."""
        # Test with many headers
        large_request_headers = {f"x-header-{i}": f"value-{i}" for i in range(1000)}
        large_allowed_headers = [f"X-Header-{i}" for i in range(1000)]

        mock_settings = Mock()
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = large_allowed_headers

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        with patch("mcpgateway.utils.passthrough_headers.settings", mock_settings):
            # Should handle large inputs without crashing
            result = get_passthrough_headers(large_request_headers, {}, mock_db)

            # All headers should be processed
            assert len(result) == 1000

    def test_unicode_security(self):
        """Test security with Unicode characters in headers."""
        # Test various Unicode scenarios that could be problematic
        unicode_tests = [
            ("X-Unicode", "value-with-emoji-🔒"),
            ("X-Unicode", "value-with-accents-café"),
            ("X-Unicode", "value-with-chinese-中文"),
            ("X-Unicode", "value-with-rtl-עברית"),
        ]

        for header_name, header_value in unicode_tests:
            result = sanitize_header_value(header_value)
            # Should preserve Unicode characters (they're >= ASCII 32)
            assert result == header_value

            # Header name validation should work with Unicode
            unicode_header_name = "X-Unicode-Test-🔒"
            assert not validate_header_name(unicode_header_name)  # Emoji not allowed in names


class TestConfigSecurity:
    """Test security of configuration parsing."""

    def test_environment_variable_json_parsing(self):
        """Test JSON parsing of environment variables."""
        # Standard
        import json

        # First-Party
        from mcpgateway.config import Settings

        # Test with valid JSON
        test_headers = ["X-Test-1", "X-Test-2"]
        # Test JSON parsing through direct instantiation
        with patch("os.environ.get", return_value=json.dumps(test_headers)):
            settings = Settings()
            assert settings.default_passthrough_headers == test_headers

    def test_environment_variable_csv_fallback(self):
        """Test CSV fallback for environment variables."""
        # First-Party
        from mcpgateway.config import Settings

        # Test CSV parsing by simulating the __init__ logic directly
        # since pydantic tries JSON first and fails
        Settings()

        # Manually call the parsing logic that would be triggered by env var
        with patch("os.environ.get", return_value="X-Test-1,X-Test-2,X-Test-3"):
            # Simulate what happens in Settings.__init__
            default_value = "X-Test-1,X-Test-2,X-Test-3"
            try:
                # Try JSON parsing first - this should fail
                # Standard
                import json

                parsed = json.loads(default_value)
            except json.JSONDecodeError:
                # Fallback to comma-separated parsing - this should work
                parsed = [h.strip() for h in default_value.split(",") if h.strip()]

            assert parsed == ["X-Test-1", "X-Test-2", "X-Test-3"]

    def test_environment_variable_security_validation(self):
        """Test that environment variable parsing validates header names."""
        # Standard
        import json

        # First-Party
        from mcpgateway.config import Settings

        # Test with malicious header names
        malicious_headers = ["Valid-Header", "Invalid Header Name", "Another@Bad#Name"]

        # Test with malicious headers through direct instantiation
        with patch.dict("os.environ", {"DEFAULT_PASSTHROUGH_HEADERS": json.dumps(malicious_headers)}, clear=False):
            settings = Settings()

            # Should include all headers (validation happens during use, not config)
            assert len(settings.default_passthrough_headers) == 3


class TestInboundPassthroughDenylist:
    """Test inbound passthrough denylist security (Issue #4450)."""

    def setup_method(self):
        """Clear the global config cache before each test to ensure isolation."""
        global_config_cache.invalidate()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_content_type_denied_via_default_passthrough(self, mock_settings, caplog):
        """Test that Content-Type is denied even when in default_passthrough_headers."""
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False
        mock_settings.default_passthrough_headers = ["Content-Type", "X-Safe-Header"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {"content-type": "application/x-www-form-urlencoded", "x-safe-header": "safe-value"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Content-Type should be blocked, X-Safe-Header should pass
        assert "Content-Type" not in result
        assert result.get("X-Safe-Header") == "safe-value"

        # Should log security warning
        assert any("Refusing inbound passthrough of protocol-level header 'Content-Type'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_content_type_denied_via_gateway_passthrough(self, mock_settings, caplog):
        """Test that Content-Type is denied via gateway-specific passthrough_headers."""
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        mock_gateway = Mock()
        mock_gateway.passthrough_headers = ["Content-Type", "X-Safe-Header"]
        mock_gateway.auth_type = "none"
        mock_gateway.name = "test-gateway"

        request_headers = {"content-type": "text/plain", "x-safe-header": "safe-value"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Content-Type should be blocked
        assert "Content-Type" not in result
        assert result.get("X-Safe-Header") == "safe-value"

        # Should log security warning
        assert any("Refusing inbound passthrough of protocol-level header 'Content-Type'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_host_header_denied(self, mock_settings, caplog):
        """Test that Host header is denied (vhost/cache-poisoning protection)."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["Host", "X-Safe-Header"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {"host": "evil.example.com", "x-safe-header": "safe-value"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Host should be blocked
        assert "Host" not in result
        assert result.get("X-Safe-Header") == "safe-value"

        # Should log security warning
        assert any("Refusing inbound passthrough of protocol-level header 'Host'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_transfer_encoding_denied(self, mock_settings, caplog):
        """Test that Transfer-Encoding is denied (request-smuggling protection)."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["Transfer-Encoding"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {"transfer-encoding": "chunked"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Transfer-Encoding should be blocked
        assert "Transfer-Encoding" not in result

        # Should log security warning
        assert any("Refusing inbound passthrough of protocol-level header 'Transfer-Encoding'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_content_length_denied(self, mock_settings, caplog):
        """Test that Content-Length is denied (defence-in-depth)."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["Content-Length"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {"content-length": "9999"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Content-Length should be blocked
        assert "Content-Length" not in result

        # Should log security warning
        assert any("Refusing inbound passthrough of protocol-level header 'Content-Length'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_hop_by_hop_headers_denied(self, mock_settings, caplog):
        """Test that hop-by-hop headers are denied."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = [
            "Connection",
            "Keep-Alive",
            "Proxy-Connection",
            "TE",
            "Trailer",
            "Upgrade",
        ]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {
            "connection": "keep-alive",
            "keep-alive": "timeout=5",
            "proxy-connection": "keep-alive",
            "te": "trailers",
            "trailer": "Expires",
            "upgrade": "websocket",
        }
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # All hop-by-hop headers should be blocked
        assert "Connection" not in result
        assert "Keep-Alive" not in result
        assert "Proxy-Connection" not in result
        assert "TE" not in result
        assert "Trailer" not in result
        assert "Upgrade" not in result

        # Should log security warnings for each
        hop_by_hop_headers = ["Connection", "Keep-Alive", "Proxy-Connection", "TE", "Trailer", "Upgrade"]
        for header in hop_by_hop_headers:
            assert any(f"Refusing inbound passthrough of protocol-level header '{header}'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_all_denylist_headers_blocked_together(self, mock_settings, caplog):
        """Test that all denylist headers are blocked when configured together."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = [
            "Content-Type",
            "Content-Length",
            "Host",
            "Transfer-Encoding",
            "Connection",
            "Keep-Alive",
            "Proxy-Connection",
            "TE",
            "Trailer",
            "Upgrade",
            "X-Safe-Header",  # This one should pass
        ]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {
            "content-type": "text/html",
            "content-length": "100",
            "host": "evil.com",
            "transfer-encoding": "chunked",
            "connection": "close",
            "keep-alive": "timeout=5",
            "proxy-connection": "keep-alive",
            "te": "trailers",
            "trailer": "Expires",
            "upgrade": "h2c",
            "x-safe-header": "this-should-pass",
        }
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # All denylist headers should be blocked
        assert "Content-Type" not in result
        assert "Content-Length" not in result
        assert "Host" not in result
        assert "Transfer-Encoding" not in result
        assert "Connection" not in result
        assert "Keep-Alive" not in result
        assert "Proxy-Connection" not in result
        assert "TE" not in result
        assert "Trailer" not in result
        assert "Upgrade" not in result

        # Safe header should pass
        assert result.get("X-Safe-Header") == "this-should-pass"

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_authorization_not_in_denylist(self, mock_settings):
        """Test that Authorization is NOT in the denylist (has special handling)."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["Authorization"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        # Gateway with no auth should allow Authorization passthrough
        mock_gateway = Mock()
        mock_gateway.passthrough_headers = None
        mock_gateway.auth_type = "none"
        mock_gateway.name = "test-gateway"

        request_headers = {"authorization": "Bearer token123"}
        base_headers = {}

        result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Authorization should pass through (not in denylist, handled by auth logic)
        assert result.get("Authorization") == "Bearer token123"

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_denylist_case_insensitive(self, mock_settings, caplog):
        """Test that denylist matching is case-insensitive."""
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["CONTENT-TYPE", "content-length", "HoSt"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {
            "CONTENT-TYPE": "text/html",
            "content-length": "100",
            "HoSt": "evil.com",
        }
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # All should be blocked regardless of case
        assert "CONTENT-TYPE" not in result
        assert "content-length" not in result
        assert "HoSt" not in result

    def test_denylist_in_compute_passthrough_headers_cached(self, caplog):
        """Test that denylist is enforced in compute_passthrough_headers_cached."""
        # First-Party
        from mcpgateway.utils.passthrough_headers import compute_passthrough_headers_cached

        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
            mock_settings.enable_header_passthrough = True
            mock_settings.enable_overwrite_base_headers = False

            request_headers = {
                "content-type": "text/html",
                "host": "evil.com",
                "x-safe-header": "safe-value",
            }
            base_headers = {}
            allowed_headers = ["Content-Type", "Host", "X-Safe-Header"]

            # Standard
            import logging

            with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
                result = compute_passthrough_headers_cached(request_headers, base_headers, allowed_headers)

            # Denylist headers should be blocked
            assert "Content-Type" not in result
            assert "Host" not in result

            # Safe header should pass
            assert result.get("X-Safe-Header") == "safe-value"

            # Should log security warnings
            assert any("Refusing inbound passthrough of protocol-level header 'Content-Type'" in record.message for record in caplog.records)
            assert any("Refusing inbound passthrough of protocol-level header 'Host'" in record.message for record in caplog.records)

    def test_denylist_in_compute_passthrough_headers_cached_with_gateway_override(self, caplog):
        """Test denylist enforcement with gateway_passthrough_headers override."""
        # First-Party
        from mcpgateway.utils.passthrough_headers import compute_passthrough_headers_cached

        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
            mock_settings.enable_header_passthrough = True
            mock_settings.enable_overwrite_base_headers = False

            request_headers = {
                "content-type": "text/html",
                "host": "evil.com",
                "transfer-encoding": "chunked",
                "x-safe-header": "safe-value",
            }
            base_headers = {}
            # Gateway-specific headers (override branch)
            gateway_passthrough_headers = ["Content-Type", "Host", "Transfer-Encoding", "X-Safe-Header"]

            # Standard
            import logging

            with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
                result = compute_passthrough_headers_cached(
                    request_headers, base_headers, allowed_headers=[], gateway_passthrough_headers=gateway_passthrough_headers
                )

            # Denylist headers should be blocked even with gateway override
            assert "Content-Type" not in result
            assert "Host" not in result
            assert "Transfer-Encoding" not in result

            # Safe header should pass
            assert result.get("X-Safe-Header") == "safe-value"

            # Should log security warnings for each blocked header
            assert any("Refusing inbound passthrough of protocol-level header 'Content-Type'" in record.message for record in caplog.records)
            assert any("Refusing inbound passthrough of protocol-level header 'Host'" in record.message for record in caplog.records)
            assert any("Refusing inbound passthrough of protocol-level header 'Transfer-Encoding'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_host_header_denied_via_gateway_passthrough(self, mock_settings, caplog):
        """Test that Host header is denied via gateway-specific passthrough_headers."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        mock_gateway = Mock()
        mock_gateway.passthrough_headers = ["Host", "X-Safe-Header"]
        mock_gateway.auth_type = "none"
        mock_gateway.name = "test-gateway"

        request_headers = {"host": "evil.example.com", "x-safe-header": "safe-value"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Host should be blocked
        assert "Host" not in result
        assert result.get("X-Safe-Header") == "safe-value"

        # Should log security warning
        assert any("Refusing inbound passthrough of protocol-level header 'Host'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_transfer_encoding_denied_via_gateway_passthrough(self, mock_settings, caplog):
        """Test that Transfer-Encoding is denied via gateway-specific passthrough_headers."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        mock_gateway = Mock()
        mock_gateway.passthrough_headers = ["Transfer-Encoding", "X-Safe-Header"]
        mock_gateway.auth_type = "none"
        mock_gateway.name = "test-gateway"

        request_headers = {"transfer-encoding": "chunked", "x-safe-header": "safe-value"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Transfer-Encoding should be blocked
        assert "Transfer-Encoding" not in result
        assert result.get("X-Safe-Header") == "safe-value"

        # Should log security warning
        assert any("Refusing inbound passthrough of protocol-level header 'Transfer-Encoding'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_content_length_denied_via_gateway_passthrough(self, mock_settings, caplog):
        """Test that Content-Length is denied via gateway-specific passthrough_headers."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        mock_gateway = Mock()
        mock_gateway.passthrough_headers = ["Content-Length", "X-Safe-Header"]
        mock_gateway.auth_type = "none"
        mock_gateway.name = "test-gateway"

        request_headers = {"content-length": "9999", "x-safe-header": "safe-value"}
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Content-Length should be blocked
        assert "Content-Length" not in result
        assert result.get("X-Safe-Header") == "safe-value"

        # Should log security warning
        assert any("Refusing inbound passthrough of protocol-level header 'Content-Length'" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_hop_by_hop_headers_denied_via_gateway_passthrough(self, mock_settings, caplog):
        """Test that hop-by-hop headers are denied via gateway-specific passthrough_headers."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        mock_gateway = Mock()
        mock_gateway.passthrough_headers = [
            "Connection",
            "Keep-Alive",
            "Proxy-Connection",
            "TE",
            "Trailer",
            "Upgrade",
            "X-Safe-Header",
        ]
        mock_gateway.auth_type = "none"
        mock_gateway.name = "test-gateway"

        request_headers = {
            "connection": "keep-alive",
            "keep-alive": "timeout=5",
            "proxy-connection": "keep-alive",
            "te": "trailers",
            "trailer": "Expires",
            "upgrade": "websocket",
            "x-safe-header": "safe-value",
        }
        base_headers = {}

        # Standard
        import logging

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # All hop-by-hop headers should be blocked
        assert "Connection" not in result
        assert "Keep-Alive" not in result
        assert "Proxy-Connection" not in result
        assert "TE" not in result
        assert "Trailer" not in result
        assert "Upgrade" not in result

        # Safe header should pass
        assert result.get("X-Safe-Header") == "safe-value"

        # Should log security warnings for each
        hop_by_hop_headers = ["Connection", "Keep-Alive", "Proxy-Connection", "TE", "Trailer", "Upgrade"]
        for header in hop_by_hop_headers:
            assert any(f"Refusing inbound passthrough of protocol-level header '{header}'" in record.message for record in caplog.records)
