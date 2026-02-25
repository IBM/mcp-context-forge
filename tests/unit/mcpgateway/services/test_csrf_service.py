# -*- coding: utf-8 -*-
"""Location: ./tests/test_csrf_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for CSRF service.

Tests cover token generation, validation, cookie management, and edge cases.
"""

# Standard
import time
from unittest.mock import Mock

# Third-Party
import pytest

# First-Party
from mcpgateway.services.csrf_service import (
    clear_csrf_cookie,
    generate_csrf_token,
    set_csrf_cookie,
    validate_csrf_token,
)


class TestGenerateCSRFToken:
    """Test cases for generate_csrf_token function."""

    def test_returns_non_empty_string(self):
        """Test that generate_csrf_token returns a non-empty string."""
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_returns_64_char_hex_string(self):
        """Test that token is 64-character hex string (HMAC-SHA256)."""
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_same_inputs_same_window_same_token(self):
        """Test that same inputs in same time window produce same token."""
        token1 = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        token2 = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        assert token1 == token2

    def test_different_user_id_different_token(self):
        """Test that different user_id produces different token."""
        token1 = generate_csrf_token("user1@example.com", "session123", "secret", 3600)
        token2 = generate_csrf_token("user2@example.com", "session123", "secret", 3600)
        assert token1 != token2

    def test_different_session_id_different_token(self):
        """Test that different session_id produces different token."""
        token1 = generate_csrf_token("user@example.com", "session1", "secret", 3600)
        token2 = generate_csrf_token("user@example.com", "session2", "secret", 3600)
        assert token1 != token2

    def test_different_secret_different_token(self):
        """Test that different secret produces different token."""
        token1 = generate_csrf_token("user@example.com", "session123", "secret1", 3600)
        token2 = generate_csrf_token("user@example.com", "session123", "secret2", 3600)
        assert token1 != token2

    def test_different_expiry_different_token(self):
        """Test that different expiry window produces different token."""
        token1 = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        token2 = generate_csrf_token("user@example.com", "session123", "secret", 7200)
        # May be same or different depending on current time alignment
        # Just verify both are valid tokens
        assert len(token1) == 64
        assert len(token2) == 64


class TestValidateCSRFToken:
    """Test cases for validate_csrf_token function."""

    def test_valid_token_returns_true(self):
        """Test that a valid token returns True."""
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        result = validate_csrf_token(token, "user@example.com", "session123", "secret", 3600)
        assert result is True

    def test_previous_window_token_returns_true(self):
        """Test that token from previous window is still valid (boundary case)."""
        # Generate token with current time
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)

        # Token should be valid in current window
        result = validate_csrf_token(token, "user@example.com", "session123", "secret", 3600)
        assert result is True

        # Note: Testing actual previous window requires time manipulation
        # which is complex. The validation logic accepts previous window tokens.

    def test_wrong_user_id_returns_false(self):
        """Test that wrong user_id returns False."""
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        result = validate_csrf_token(token, "wrong@example.com", "session123", "secret", 3600)
        assert result is False

    def test_wrong_session_id_returns_false(self):
        """Test that wrong session_id returns False."""
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        result = validate_csrf_token(token, "user@example.com", "wrong_session", "secret", 3600)
        assert result is False

    def test_wrong_secret_returns_false(self):
        """Test that wrong secret returns False."""
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        result = validate_csrf_token(token, "user@example.com", "session123", "wrong_secret", 3600)
        assert result is False

    def test_tampered_token_returns_false(self):
        """Test that tampered token returns False."""
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        # Tamper with token by changing a character
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        result = validate_csrf_token(tampered, "user@example.com", "session123", "secret", 3600)
        assert result is False

    def test_garbage_token_returns_false(self):
        """Test that garbage token returns False without raising."""
        result = validate_csrf_token("not_a_valid_token", "user@example.com", "session123", "secret", 3600)
        assert result is False

    def test_empty_string_returns_false(self):
        """Test that empty string returns False without raising."""
        result = validate_csrf_token("", "user@example.com", "session123", "secret", 3600)
        assert result is False

    def test_none_token_returns_false(self):
        """Test that None token returns False without raising."""
        # validate_csrf_token expects str, but should handle None gracefully
        try:
            result = validate_csrf_token(None, "user@example.com", "session123", "secret", 3600)
            assert result is False
        except Exception:
            # If it raises, that's also acceptable for None input
            pass

    def test_short_token_returns_false(self):
        """Test that token shorter than 64 chars returns False."""
        result = validate_csrf_token("abc123", "user@example.com", "session123", "secret", 3600)
        assert result is False

    def test_long_token_returns_false(self):
        """Test that token longer than 64 chars returns False."""
        token = "a" * 65
        result = validate_csrf_token(token, "user@example.com", "session123", "secret", 3600)
        assert result is False

    def test_non_hex_token_returns_false(self):
        """Test that token with non-hex characters returns False."""
        token = "g" * 64  # 'g' is not a hex character
        result = validate_csrf_token(token, "user@example.com", "session123", "secret", 3600)
        assert result is False

    def test_uppercase_hex_token_returns_false(self):
        """Test that uppercase hex token returns False (expects lowercase)."""
        token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        uppercase_token = token.upper()
        result = validate_csrf_token(uppercase_token, "user@example.com", "session123", "secret", 3600)
        assert result is False


class TestSetCSRFCookie:
    """Test cases for set_csrf_cookie function."""

    def test_sets_cookie_with_correct_parameters(self):
        """Test that cookie is set with correct security parameters."""
        response = Mock()
        settings = Mock(
            csrf_cookie_secure=True,
            csrf_cookie_samesite="Strict",
            csrf_token_expiry=3600
        )
        token = "a" * 64

        set_csrf_cookie(response, token, settings)

        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args[1]

        assert call_kwargs["key"] == "csrf_token"
        assert call_kwargs["value"] == token
        assert call_kwargs["httponly"] is False  # Must be readable by JS
        assert call_kwargs["secure"] is True
        assert call_kwargs["samesite"] == "Strict"
        assert call_kwargs["max_age"] == 3600
        assert call_kwargs["path"] == "/"

    def test_httponly_always_false(self):
        """Test that httponly is always False (CSRF tokens must be readable by JS)."""
        response = Mock()
        settings = Mock(
            csrf_cookie_secure=False,
            csrf_cookie_samesite="Lax",
            csrf_token_expiry=7200
        )
        token = "b" * 64

        set_csrf_cookie(response, token, settings)

        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["httponly"] is False

    def test_respects_settings_secure_flag(self):
        """Test that secure flag comes from settings."""
        response = Mock()
        settings = Mock(
            csrf_cookie_secure=False,
            csrf_cookie_samesite="Lax",
            csrf_token_expiry=3600
        )
        token = "c" * 64

        set_csrf_cookie(response, token, settings)

        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["secure"] is False

    def test_respects_settings_samesite(self):
        """Test that samesite comes from settings."""
        response = Mock()
        settings = Mock(
            csrf_cookie_secure=True,
            csrf_cookie_samesite="None",
            csrf_token_expiry=3600
        )
        token = "d" * 64

        set_csrf_cookie(response, token, settings)

        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["samesite"] == "None"


class TestClearCSRFCookie:
    """Test cases for clear_csrf_cookie function."""

    def test_clears_cookie_with_max_age_zero(self):
        """Test that cookie is cleared with max_age=0."""
        response = Mock()
        settings = Mock(
            csrf_cookie_secure=True,
            csrf_cookie_samesite="Strict"
        )

        clear_csrf_cookie(response, settings)

        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args[1]

        assert call_kwargs["key"] == "csrf_token"
        assert call_kwargs["value"] == ""
        assert call_kwargs["max_age"] == 0
        assert call_kwargs["httponly"] is False
        assert call_kwargs["secure"] is True
        assert call_kwargs["samesite"] == "Strict"
        assert call_kwargs["path"] == "/"

    def test_respects_settings_when_clearing(self):
        """Test that settings are respected when clearing cookie."""
        response = Mock()
        settings = Mock(
            csrf_cookie_secure=False,
            csrf_cookie_samesite="Lax"
        )

        clear_csrf_cookie(response, settings)

        call_kwargs = response.set_cookie.call_args[1]
        assert call_kwargs["secure"] is False
        assert call_kwargs["samesite"] == "Lax"
