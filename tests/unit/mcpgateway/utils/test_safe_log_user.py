# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_safe_log_user.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for safe_log_user() function combining PII redaction and log injection protection.
"""

import pytest

from mcpgateway.utils.trace_redaction import safe_log_user


class TestSafeLogUser:
    """Test safe_log_user() combines PII redaction with log injection protection."""

    def test_dict_user_redacts_pii(self):
        """Test that PII fields in dict users are redacted."""
        user = {
            "email": "user@example.com",
            "password": "secret123",  # pragma: allowlist secret
            "token": "abc123",
            "name": "John Doe",
        }
        result = safe_log_user(user)

        # PII should be redacted
        assert "***" in result
        assert "secret123" not in result
        assert "abc123" not in result

        # Non-PII should be preserved
        assert "John Doe" in result

    def test_dict_user_prevents_log_injection(self):
        """Test that newlines in dict user values are removed."""
        user = {
            "email": "attacker@evil.com\nFAKE LOG: [INFO] Admin login successful",
            "name": "Attacker\rInjection",
        }
        result = safe_log_user(user)

        # Newlines and carriage returns should be removed
        assert "\n" not in result
        assert "\r" not in result
        assert "FAKE LOG" in result  # Content preserved but sanitized

    def test_dict_user_removes_ansi_escapes(self):
        """Test that ANSI escape sequences are removed from dict values."""
        user = {
            "email": "user@example.com",
            "name": "\x1b[31mRed Text\x1b[0m",
        }
        result = safe_log_user(user)

        # ANSI escapes should be removed
        assert "\x1b" not in result
        assert "Red Text" in result

    def test_dict_user_removes_control_chars(self):
        """Test that control characters are removed from dict values."""
        user = {
            "email": "user@example.com\x00\x01\x02",
            "name": "User\x03Name",
        }
        result = safe_log_user(user)

        # Control characters should be removed
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x02" not in result
        assert "\x03" not in result

    def test_dict_user_combined_attack(self):
        """Test dict user with multiple attack vectors combined."""
        user = {
            "email": "attacker@evil.com\nFAKE\rLOG",
            "password": "secret\x00\x1b[31mcolored\x1b[0m",  # pragma: allowlist secret
            "token": "abc123",
        }
        result = safe_log_user(user)

        # PII redacted
        assert "secret" not in result
        assert "abc123" not in result
        assert "***" in result

        # Log injection prevented
        assert "\n" not in result
        assert "\r" not in result
        assert "\x00" not in result
        assert "\x1b" not in result

    def test_string_user_prevents_log_injection(self):
        """Test that string users have log injection protection."""
        user = "user@example.com\nFAKE LOG: Admin action"
        result = safe_log_user(user)

        # Newlines should be removed
        assert "\n" not in result
        assert "FAKE LOG" in result

    def test_string_user_removes_ansi_escapes(self):
        """Test that ANSI escapes are removed from string users."""
        user = "\x1b[31muser@example.com\x1b[0m"
        result = safe_log_user(user)

        # ANSI escapes should be removed
        assert "\x1b" not in result
        assert "user@example.com" in result

    def test_string_user_removes_control_chars(self):
        """Test that control characters are removed from string users."""
        user = "user@example.com\x00\x01\x02"
        result = safe_log_user(user)

        # Control characters should be removed
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x02" not in result

    def test_non_dict_non_string_user(self):
        """Test that other types are converted to string and sanitized."""
        user = 12345
        result = safe_log_user(user)

        assert result == "12345"
        assert isinstance(result, str)

    def test_empty_dict_user(self):
        """Test that empty dict is handled correctly."""
        user = {}
        result = safe_log_user(user)

        assert isinstance(result, str)
        assert result == "{}"

    def test_empty_string_user(self):
        """Test that empty string is handled correctly."""
        user = ""
        result = safe_log_user(user)

        assert result == ""

    def test_none_user(self):
        """Test that None is handled correctly."""
        user = None
        result = safe_log_user(user)

        assert result == "None"

    def test_nested_dict_user(self):
        """Test that nested dicts have PII redacted."""
        user = {
            "email": "user@example.com",
            "profile": {
                "password": "secret",
                "name": "John",
            },
        }
        result = safe_log_user(user)

        # Nested PII should be redacted
        assert "secret" not in result
        assert "***" in result
        assert "John" in result

    def test_real_world_attack_scenario(self):
        """Test real-world combined attack scenario."""
        # Attacker tries to inject fake admin login while leaking credentials
        user = {
            "email": "attacker@evil.com\n[INFO] Admin login successful for admin@company.com",
            "password": "stolen_password",  # pragma: allowlist secret
            "api_key": "abc123\rFAKE SESSION",
        }
        result = safe_log_user(user)

        # PII must be redacted
        assert "stolen_password" not in result
        assert "abc123" not in result
        assert "***" in result

        # Log injection must be prevented (newlines/carriage returns removed from email)
        assert "\n" not in result
        assert "\r" not in result

        # Email content sanitized (injection attempt neutralized)
        assert "Admin login successful" in result

    def test_unicode_preserved(self):
        """Test that Unicode characters are preserved."""
        user = {
            "email": "用户@example.com",
            "name": "用户名",
        }
        result = safe_log_user(user)

        # Unicode should be preserved
        assert "用户" in result
        assert "用户名" in result

    def test_long_user_data_truncated(self):
        """Test that very long user data is truncated."""
        user = {"email": "A" * 15000}
        result = safe_log_user(user)

        # Should be truncated
        assert len(result) <= 10020  # 10000 + len("...[truncated]")
        assert result.endswith("...[truncated]")

    def test_preserves_safe_special_chars(self):
        """Test that safe special characters are preserved."""
        user = {
            "email": "user+test@example.com",
            "name": "John-Doe_123",
        }
        result = safe_log_user(user)

        # Safe special chars should be preserved
        assert "+" in result or "***" in result  # email might be redacted
        assert "-" in result
        assert "_" in result

    def test_tabs_preserved(self):
        """Test that tab characters are preserved (escaped in string repr)."""
        user = {"data": "Column1\tColumn2\tColumn3"}
        result = safe_log_user(user)

        # Tabs are escaped in string representation
        assert "\\t" in result or "\t" in result


class TestSafeLogUserIntegration:
    """Integration tests for safe_log_user in realistic logging scenarios."""

    def test_logging_user_action(self):
        """Test logging a user action with safe_log_user."""
        user = {
            "email": "user@example.com",
            "password": "secret",
        }
        log_message = f"User {safe_log_user(user)} performed action"

        # Should be safe to log
        assert "secret" not in log_message
        assert "***" in log_message
        assert "\n" not in log_message

    def test_logging_failed_login(self):
        """Test logging a failed login attempt."""
        user = "attacker@evil.com\n[INFO] Admin login successful"
        log_message = f"Failed login for {safe_log_user(user)}"

        # Should prevent log injection
        assert "\n" not in log_message
        assert "Failed login for attacker@evil.com [INFO] Admin login successful" == log_message

    def test_logging_session_creation(self):
        """Test logging session creation with sensitive data."""
        user = {
            "email": "user@example.com",
            "api_key": "abc123\x00\x01",  # pragma: allowlist secret
        }
        log_message = f"Session created for {safe_log_user(user)}"

        # Should redact token and remove control chars
        assert "abc123" not in log_message
        assert "\x00" not in log_message
        assert "\x01" not in log_message
        assert "***" in log_message

    def test_logging_api_request(self):
        """Test logging API request with user context."""
        user = {
            "email": "user@example.com",
            "api_key": "key123\rFAKE",
        }
        log_message = f"API request from {safe_log_user(user)}"

        # Should redact API key and prevent injection
        assert "key123" not in log_message
        assert "\r" not in log_message
        assert "***" in log_message
