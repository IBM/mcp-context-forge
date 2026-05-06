# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_log_injection_protection.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for log injection protection (CWE-117).

This module tests the sanitize_log_message() method to ensure it properly
prevents log injection attacks by removing newlines, carriage returns,
ANSI escape sequences, and control characters.
"""

from mcpgateway.common.validators import SecurityValidator


class TestLogInjectionProtection:
    """Test log injection protection mechanisms."""

    def test_sanitize_log_removes_newlines(self):
        """Test that newlines are removed from log messages."""
        message = "User: admin\nFake log entry"
        result = SecurityValidator.sanitize_log_message(message)
        assert "\n" not in result
        assert result == "User: admin Fake log entry"

    def test_sanitize_log_removes_carriage_returns(self):
        """Test that carriage returns are removed."""
        message = "User: admin\rFake log entry"
        result = SecurityValidator.sanitize_log_message(message)
        assert "\r" not in result
        assert result == "User: admin Fake log entry"

    def test_sanitize_log_removes_both_newline_types(self):
        """Test that both \\n and \\r are removed."""
        message = "Line1\nLine2\rLine3\r\nLine4"
        result = SecurityValidator.sanitize_log_message(message)
        assert "\n" not in result
        assert "\r" not in result
        assert result == "Line1 Line2 Line3  Line4"

    def test_sanitize_log_removes_ansi_escapes(self):
        """Test that ANSI escape sequences are removed."""
        # Red text: \x1B[31m
        # Reset: \x1B[0m
        message = "User: \x1b[31madmin\x1b[0m"
        result = SecurityValidator.sanitize_log_message(message)
        assert "\x1b" not in result
        assert result == "User: admin"

    def test_sanitize_log_removes_control_chars(self):
        """Test that control characters are removed."""
        message = "User: admin\x00\x01\x02\x03"
        result = SecurityValidator.sanitize_log_message(message)
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x02" not in result
        assert "\x03" not in result
        # Control chars should be removed, leaving just the text
        assert "User: admin" in result

    def test_sanitize_log_truncates_long_messages(self):
        """Test that long messages are truncated."""
        message = "A" * 15000
        result = SecurityValidator.sanitize_log_message(message, max_length=10000)
        assert len(result) <= 10020  # 10000 + len("...[truncated]")
        assert result.endswith("...[truncated]")

    def test_sanitize_log_respects_custom_max_length(self):
        """Test that custom max_length is respected."""
        message = "B" * 5000
        result = SecurityValidator.sanitize_log_message(message, max_length=1000)
        assert len(result) <= 1020  # 1000 + len("...[truncated]")
        assert result.endswith("...[truncated]")

    def test_sanitize_log_handles_empty_input(self):
        """Test that empty input is handled correctly."""
        assert SecurityValidator.sanitize_log_message("") == ""
        assert SecurityValidator.sanitize_log_message(None) == ""

    def test_sanitize_log_handles_whitespace_only(self):
        """Test that whitespace-only input is preserved."""
        assert SecurityValidator.sanitize_log_message("   ") == "   "
        assert SecurityValidator.sanitize_log_message("\t\t") == "\t\t"

    def test_sanitize_log_preserves_normal_text(self):
        """Test that normal text is preserved unchanged."""
        message = "User admin performed action successfully"
        result = SecurityValidator.sanitize_log_message(message)
        assert result == message

    def test_sanitize_log_preserves_special_chars(self):
        """Test that safe special characters are preserved."""
        message = "User: admin@example.com, Action: create-resource_123"
        result = SecurityValidator.sanitize_log_message(message)
        assert result == message

    def test_sanitize_log_real_world_injection_attempt(self):
        """Test real-world log injection attack pattern."""
        # Attacker tries to inject fake admin login
        message = "Failed login for user: attacker\n[INFO] Admin login successful for user: admin"
        result = SecurityValidator.sanitize_log_message(message)
        # Newline should be replaced with space, preventing log injection
        assert "\n" not in result
        assert result == "Failed login for user: attacker [INFO] Admin login successful for user: admin"

    def test_sanitize_log_crlf_injection(self):
        """Test CRLF injection attack pattern."""
        message = "User input\r\n[ERROR] System compromised"
        result = SecurityValidator.sanitize_log_message(message)
        assert "\r" not in result
        assert "\n" not in result
        assert result == "User input  [ERROR] System compromised"

    def test_sanitize_log_converts_non_string_to_string(self):
        """Test that non-string inputs are converted to strings."""
        assert SecurityValidator.sanitize_log_message(12345) == "12345"
        assert SecurityValidator.sanitize_log_message(True) == "True"
        assert SecurityValidator.sanitize_log_message(3.14) == "3.14"

    def test_sanitize_log_handles_unicode(self):
        """Test that Unicode characters are preserved."""
        message = "User: 用户名 performed action: 操作"
        result = SecurityValidator.sanitize_log_message(message)
        assert result == message

    def test_sanitize_log_multiple_attack_vectors(self):
        """Test message with multiple attack vectors combined."""
        message = "User\nFake\rEntry\x00\x1b[31mColored\x1b[0m"
        result = SecurityValidator.sanitize_log_message(message)
        assert "\n" not in result
        assert "\r" not in result
        assert "\x00" not in result
        assert "\x1b" not in result
        # Should have spaces where newlines were
        assert "User Fake Entry" in result

    def test_sanitize_log_preserves_tabs(self):
        """Test that tab characters are preserved (not control chars)."""
        message = "Column1\tColumn2\tColumn3"
        result = SecurityValidator.sanitize_log_message(message)
        assert "\t" in result
        assert result == message

    def test_sanitize_log_default_max_length(self):
        """Test that default max_length is 10000."""
        message = "X" * 9999
        result = SecurityValidator.sanitize_log_message(message)
        # Should not be truncated
        assert not result.endswith("...[truncated]")
        assert len(result) == 9999

        message = "X" * 10001
        result = SecurityValidator.sanitize_log_message(message)
        # Should be truncated
        assert result.endswith("...[truncated]")

    def test_sanitize_log_edge_case_exact_max_length(self):
        """Test message exactly at max_length."""
        message = "Y" * 10000
        result = SecurityValidator.sanitize_log_message(message, max_length=10000)
        # Should not be truncated
        assert not result.endswith("...[truncated]")
        assert len(result) == 10000

    def test_sanitize_log_edge_case_one_over_max_length(self):
        """Test message one character over max_length."""
        message = "Z" * 10001
        result = SecurityValidator.sanitize_log_message(message, max_length=10000)
        # Should be truncated
        assert result.endswith("...[truncated]")
        assert len(result) == 10000 + len("...[truncated]")


class TestLogInjectionIntegration:
    """Integration tests for log injection protection in real-world scenarios."""

    def test_sanitize_user_email_in_log(self):
        """Test sanitizing user email that might contain injection."""
        user_email = "attacker@evil.com\nADMIN LOGIN SUCCESS"
        sanitized = SecurityValidator.sanitize_log_message(user_email)
        log_message = f"User {sanitized} attempted login"
        assert "\n" not in log_message
        assert log_message == "User attacker@evil.com ADMIN LOGIN SUCCESS attempted login"

    def test_sanitize_error_message_in_log(self):
        """Test sanitizing error messages that might contain injection."""
        error = "Database error\r\n[CRITICAL] System shutdown initiated"
        sanitized = SecurityValidator.sanitize_log_message(error)
        log_message = f"Error occurred: {sanitized}"
        assert "\r" not in log_message
        assert "\n" not in log_message

    def test_sanitize_session_id_in_log(self):
        """Test sanitizing session IDs that might contain control chars."""
        session_id = "abc123\x00\x01def456"
        sanitized = SecurityValidator.sanitize_log_message(session_id)
        log_message = f"Session {sanitized} established"
        assert "\x00" not in log_message
        assert "\x01" not in log_message

    def test_sanitize_tool_name_in_log(self):
        """Test sanitizing tool names that might contain ANSI codes."""
        tool_name = "\x1b[32mmalicious_tool\x1b[0m"
        sanitized = SecurityValidator.sanitize_log_message(tool_name)
        log_message = f"Tool {sanitized} executed"
        assert "\x1b" not in log_message
        assert "malicious_tool" in log_message
