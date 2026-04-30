# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_log_sanitizer.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for log sanitization utility.

This test suite verifies that the log sanitizer correctly prevents log injection
attacks by removing or replacing control characters in untrusted input.
"""

from mcpgateway.utils.log_sanitizer import (
    sanitize_for_log,
    sanitize_dict_for_log,
    sanitize_optional,
    CONTROL_CHARS_PATTERN,
)


class TestSanitizeForLog:
    """Test the main sanitize_for_log function."""

    def test_normal_text_unchanged(self):
        """Normal text without control characters should pass through unchanged."""
        assert sanitize_for_log("normal text") == "normal text"
        assert sanitize_for_log("hello world 123") == "hello world 123"
        assert sanitize_for_log("special chars: !@#$%^&*()") == "special chars: !@#$%^&*()"

    def test_newline_removed(self):
        """Newline characters should be replaced with space."""
        assert sanitize_for_log("line1\nline2") == "line1 line2"
        assert sanitize_for_log("text\n\nmore") == "text  more"

    def test_carriage_return_removed(self):
        """Carriage return characters should be replaced with space."""
        assert sanitize_for_log("text\rmore") == "text more"
        assert sanitize_for_log("line1\r\nline2") == "line1  line2"

    def test_tab_removed(self):
        """Tab characters should be replaced with space."""
        assert sanitize_for_log("col1\tcol2") == "col1 col2"
        assert sanitize_for_log("text\t\ttabs") == "text  tabs"

    def test_log_injection_attack_mitigated(self):
        """Verify that log injection attacks are prevented."""
        # Simulates URL-decoded %0A in error_description
        malicious_input = "bad scope\nCRITICAL:root:SECURITY BREACH detected"
        sanitized = sanitize_for_log(malicious_input)

        # Should be a single line with no newline
        assert "\n" not in sanitized
        assert sanitized == "bad scope CRITICAL:root:SECURITY BREACH detected"

    def test_multiple_control_chars(self):
        """Multiple different control characters should all be replaced."""
        text = "text\nwith\rmany\tcontrol\vchars\fhere"
        sanitized = sanitize_for_log(text)

        # Verify no control characters remain
        assert "\n" not in sanitized
        assert "\r" not in sanitized
        assert "\t" not in sanitized
        assert "\v" not in sanitized
        assert "\f" not in sanitized

    def test_null_byte_removed(self):
        """Null bytes should be replaced."""
        assert sanitize_for_log("text\x00null") == "text null"

    def test_other_c0_control_chars(self):
        """Other C0 control characters (0x00-0x1F) should be replaced."""
        # Test a few examples from the C0 range
        assert sanitize_for_log("text\x01\x02\x03") == "text   "
        assert sanitize_for_log("bell\x07here") == "bell here"

    def test_c1_control_chars(self):
        """C1 control characters (0x7F-0x9F) should be replaced."""
        assert sanitize_for_log("text\x7fmore") == "text more"
        assert sanitize_for_log("text\x80\x9fmore") == "text  more"

    def test_unicode_preserved(self):
        """Unicode characters outside control range should be preserved."""
        assert sanitize_for_log("emoji 😀 text") == "emoji 😀 text"
        assert sanitize_for_log("中文字符") == "中文字符"
        assert sanitize_for_log("Ñoño") == "Ñoño"

    def test_custom_replacement(self):
        """Custom replacement string should be used when provided."""
        assert sanitize_for_log("a\nb", replacement="") == "ab"
        assert sanitize_for_log("a\nb", replacement="-") == "a-b"
        assert sanitize_for_log("a\nb", replacement="[NL]") == "a[NL]b"

    def test_none_converted_to_string(self):
        """None should be converted to string 'None'."""
        assert sanitize_for_log(None) == "None"

    def test_numbers_converted_to_string(self):
        """Numbers should be converted to strings."""
        assert sanitize_for_log(123) == "123"
        assert sanitize_for_log(45.67) == "45.67"
        assert sanitize_for_log(0) == "0"

    def test_boolean_converted_to_string(self):
        """Booleans should be converted to strings."""
        assert sanitize_for_log(True) == "True"
        assert sanitize_for_log(False) == "False"

    def test_dict_converted_to_string(self):
        """Dictionaries should be converted to string representation."""
        result = sanitize_for_log({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_list_converted_to_string(self):
        """Lists should be converted to string representation."""
        result = sanitize_for_log([1, 2, 3])
        assert "1" in result
        assert "2" in result
        assert "3" in result

    def test_empty_string(self):
        """Empty string should remain empty."""
        assert sanitize_for_log("") == ""

    def test_only_control_chars(self):
        """String with only control characters should become spaces."""
        assert sanitize_for_log("\n\r\t") == "   "
        assert sanitize_for_log("\n\r\t", replacement="") == ""

    def test_real_world_oauth_error(self):
        """Test with real-world OAuth error scenario."""
        # Simulates malicious OAuth callback
        error = "invalid_scope"
        error_description = "Requested scope not available\nCRITICAL:security:BREACH"

        sanitized_error = sanitize_for_log(error)
        sanitized_desc = sanitize_for_log(error_description)

        assert sanitized_error == "invalid_scope"
        assert "\n" not in sanitized_desc
        assert "CRITICAL:security:BREACH" in sanitized_desc

    def test_real_world_path_injection(self):
        """Test with path traversal attempt in logs."""
        malicious_path = "../../etc/passwd\nINFO:fake:log"
        sanitized = sanitize_for_log(malicious_path)

        assert "\n" not in sanitized
        assert sanitized == "../../etc/passwd INFO:fake:log"


class TestSanitizeDictForLog:
    """Test the sanitize_dict_for_log function."""

    def test_empty_dict(self):
        """Empty dictionary should return empty dictionary."""
        assert sanitize_dict_for_log({}) == {}

    def test_single_value(self):
        """Single value should be sanitized."""
        result = sanitize_dict_for_log({"key": "value\nwith newline"})
        assert result == {"key": "value with newline"}

    def test_multiple_values(self):
        """All values should be sanitized."""
        input_dict = {
            "error": "invalid_scope",
            "description": "bad\nscope",
            "code": "123\t456",
        }
        result = sanitize_dict_for_log(input_dict)

        assert result["error"] == "invalid_scope"
        assert result["description"] == "bad scope"
        assert result["code"] == "123 456"

    def test_mixed_types(self):
        """Different value types should all be converted and sanitized."""
        input_dict = {
            "string": "text\nhere",
            "number": 42,
            "none": None,
            "bool": True,
        }
        result = sanitize_dict_for_log(input_dict)

        assert result["string"] == "text here"
        assert result["number"] == "42"
        assert result["none"] == "None"
        assert result["bool"] == "True"

    def test_custom_replacement(self):
        """Custom replacement should be applied to all values."""
        input_dict = {"a": "x\ny", "b": "p\nq"}
        result = sanitize_dict_for_log(input_dict, replacement="-")

        assert result["a"] == "x-y"
        assert result["b"] == "p-q"

    def test_oauth_callback_params(self):
        """Test with typical OAuth callback parameters."""
        params = {
            "state": "abc123",
            "error": "access_denied",
            "error_description": "User denied\nCRITICAL:fake:log",
        }
        result = sanitize_dict_for_log(params)

        assert result["state"] == "abc123"
        assert result["error"] == "access_denied"
        assert "\n" not in result["error_description"]


class TestSanitizeOptional:
    """Test the sanitize_optional function."""

    def test_none_preserved(self):
        """None should remain None, not converted to string."""
        assert sanitize_optional(None) is None

    def test_string_sanitized(self):
        """Non-None strings should be sanitized."""
        assert sanitize_optional("text\nhere") == "text here"

    def test_number_converted(self):
        """Numbers should be converted to sanitized strings."""
        assert sanitize_optional(123) == "123"

    def test_empty_string(self):
        """Empty string should remain empty string, not None."""
        assert sanitize_optional("") == ""

    def test_custom_replacement(self):
        """Custom replacement should work with optional values."""
        assert sanitize_optional("a\nb", replacement="-") == "a-b"
        assert sanitize_optional(None, replacement="-") is None


class TestControlCharsPattern:
    """Test the CONTROL_CHARS_PATTERN regex directly."""

    def test_pattern_matches_newline(self):
        """Pattern should match newline."""
        assert CONTROL_CHARS_PATTERN.search("\n") is not None

    def test_pattern_matches_carriage_return(self):
        """Pattern should match carriage return."""
        assert CONTROL_CHARS_PATTERN.search("\r") is not None

    def test_pattern_matches_tab(self):
        """Pattern should match tab."""
        assert CONTROL_CHARS_PATTERN.search("\t") is not None

    def test_pattern_matches_null(self):
        """Pattern should match null byte."""
        assert CONTROL_CHARS_PATTERN.search("\x00") is not None

    def test_pattern_does_not_match_space(self):
        """Pattern should NOT match regular space (0x20)."""
        assert CONTROL_CHARS_PATTERN.search(" ") is None

    def test_pattern_does_not_match_normal_chars(self):
        """Pattern should NOT match normal printable characters."""
        assert CONTROL_CHARS_PATTERN.search("abc123") is None
        assert CONTROL_CHARS_PATTERN.search("!@#$%") is None

    def test_pattern_matches_all_c0_range(self):
        """Pattern should match all C0 control characters (0x00-0x1F)."""
        for code in range(0x00, 0x20):
            char = chr(code)
            assert CONTROL_CHARS_PATTERN.search(char) is not None, f"Failed for 0x{code:02x}"

    def test_pattern_matches_del_and_c1_range(self):
        """Pattern should match DEL (0x7F) and C1 control characters (0x80-0x9F)."""
        assert CONTROL_CHARS_PATTERN.search("\x7f") is not None
        for code in range(0x80, 0xA0):
            char = chr(code)
            assert CONTROL_CHARS_PATTERN.search(char) is not None, f"Failed for 0x{code:02x}"


class TestSecurityScenarios:
    """Test specific security scenarios and attack vectors."""

    def test_crlf_injection_attack(self):
        """Test CRLF injection attack prevention."""
        # Attacker tries to inject HTTP headers via CRLF
        malicious = "value\r\nSet-Cookie: session=hijacked"
        sanitized = sanitize_for_log(malicious)

        assert "\r" not in sanitized
        assert "\n" not in sanitized

    def test_log_forging_attack(self):
        """Test log forging attack prevention."""
        # Attacker tries to forge admin action log
        malicious = "user_input\nINFO:admin:User admin deleted all data"
        sanitized = sanitize_for_log(malicious)

        assert "\n" not in sanitized
        # The malicious content is still there but can't create a new log line
        assert "INFO:admin:User admin deleted all data" in sanitized

    def test_siem_evasion_attack(self):
        """Test SIEM evasion attack prevention."""
        # Attacker tries to hide malicious activity by injecting benign log lines
        malicious = "failed_login\nINFO:auth:Successful login for admin"
        sanitized = sanitize_for_log(malicious)

        assert "\n" not in sanitized
        # Both parts are in one line, can't fool SIEM
        assert "failed_login" in sanitized
        assert "Successful login" in sanitized

    def test_multiple_injection_attempts(self):
        """Test multiple injection attempts in single input."""
        malicious = "input\nFAKE1\rFAKE2\n\rFAKE3"
        sanitized = sanitize_for_log(malicious)

        # All control chars removed
        assert "\n" not in sanitized
        assert "\r" not in sanitized
        # Content preserved but can't create multiple lines
        assert "FAKE1" in sanitized
        assert "FAKE2" in sanitized
        assert "FAKE3" in sanitized

    def test_url_encoded_attack(self):
        """Test that URL-decoded attack strings are sanitized."""
        # Simulates what happens after URL decoding %0A
        url_decoded = "error=foo&desc=bar\nCRITICAL:root:BREACH"
        sanitized = sanitize_for_log(url_decoded)

        assert "\n" not in sanitized

    def test_unicode_newline_variants(self):
        """Test that Unicode newline variants are handled."""
        # Note: Our pattern focuses on ASCII control chars (0x00-0x1F, 0x7F-0x9F)
        # Unicode line separators (U+2028, U+2029) are not in this range
        # This is acceptable as Python's logging module doesn't treat them as newlines
        text_with_unicode_newlines = "line1\u2028line2\u2029line3"
        sanitized = sanitize_for_log(text_with_unicode_newlines)

        # These Unicode chars are preserved (they're not in our control char range)
        # This is correct behavior - they won't create new log lines in Python logging
        assert "\u2028" in sanitized
        assert "\u2029" in sanitized
