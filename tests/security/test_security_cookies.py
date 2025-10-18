# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_security_cookies.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Security Cookie Testing.

This module contains tests for secure cookie configuration and handling.
"""

# Standard
from unittest.mock import patch

# Third-Party
from fastapi import Response
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.security_cookies import clear_auth_cookie, clear_session_cookie, set_auth_cookie, set_session_cookie


class TestSecureCookies:
    """Test secure cookie configuration and attributes."""

    def test_set_auth_cookie_development(self):
        """Test auth cookie in development environment."""
        response = Response()

        with patch.object(settings, "environment", "development"):
            with patch.object(settings, "secure_cookies", False):
                set_auth_cookie(response, "test_token", remember_me=False)

        # Check that cookie was set
        set_cookie_header = response.headers.get("set-cookie", "")
        assert "jwt_token=test_token" in set_cookie_header
        assert "HttpOnly" in set_cookie_header
        assert "SameSite=lax" in set_cookie_header
        assert "Path=/" in set_cookie_header
        assert "Max-Age=3600" in set_cookie_header  # 1 hour

        # In development with secure_cookies=False, Secure flag should not be present
        assert "Secure" not in set_cookie_header

    def test_set_auth_cookie_production(self):
        """Test auth cookie in production environment."""
        response = Response()

        with patch.object(settings, "environment", "production"):
            set_auth_cookie(response, "test_token", remember_me=False)

        set_cookie_header = response.headers.get("set-cookie", "")
        assert "jwt_token=test_token" in set_cookie_header
        assert "HttpOnly" in set_cookie_header
        assert "Secure" in set_cookie_header  # Should be secure in production
        assert "SameSite=lax" in set_cookie_header

    def test_set_auth_cookie_remember_me(self):
        """Test auth cookie with remember_me option."""
        response = Response()

        set_auth_cookie(response, "test_token", remember_me=True)

        set_cookie_header = response.headers.get("set-cookie", "")
        # 30 days = 30 * 24 * 3600 = 2592000 seconds
        assert "Max-Age=2592000" in set_cookie_header

    def test_set_auth_cookie_custom_samesite(self):
        """Test auth cookie with custom SameSite setting."""
        response = Response()

        with patch.object(settings, "cookie_samesite", "strict"):
            set_auth_cookie(response, "test_token")

        set_cookie_header = response.headers.get("set-cookie", "")
        assert "SameSite=strict" in set_cookie_header

    def test_clear_auth_cookie(self):
        """Test clearing auth cookie."""
        response = Response()

        clear_auth_cookie(response)

        set_cookie_header = response.headers.get("set-cookie", "")
        assert "jwt_token=" in set_cookie_header  # Empty value
        assert "HttpOnly" in set_cookie_header
        assert "Path=/" in set_cookie_header

    def test_set_session_cookie(self):
        """Test setting session cookie."""
        response = Response()

        set_session_cookie(response, "session_123", max_age=7200)

        set_cookie_header = response.headers.get("set-cookie", "")
        assert "session_id=session_123" in set_cookie_header
        assert "HttpOnly" in set_cookie_header
        assert "SameSite=lax" in set_cookie_header
        assert "Max-Age=7200" in set_cookie_header

    def test_clear_session_cookie(self):
        """Test clearing session cookie."""
        response = Response()

        clear_session_cookie(response)

        set_cookie_header = response.headers.get("set-cookie", "")
        assert "session_id=" in set_cookie_header
        assert "HttpOnly" in set_cookie_header

    def test_secure_flag_with_explicit_setting(self):
        """Test secure flag behavior with explicit secure_cookies setting."""
        response = Response()

        # Test with secure_cookies=True in development
        with patch.object(settings, "environment", "development"):
            with patch.object(settings, "secure_cookies", True):
                set_auth_cookie(response, "test_token")

        set_cookie_header = response.headers.get("set-cookie", "")
        assert "Secure" in set_cookie_header  # Should be secure when explicitly enabled

    def test_cookie_attributes_consistency(self):
        """Test that cookie attributes are consistent between set and clear operations."""
        response_set = Response()
        response_clear = Response()

        with patch.object(settings, "environment", "production"):
            with patch.object(settings, "cookie_samesite", "strict"):
                set_auth_cookie(response_set, "test_token")
                clear_auth_cookie(response_clear)

        set_header = response_set.headers.get("set-cookie", "")
        clear_header = response_clear.headers.get("set-cookie", "")

        # Both should have same security attributes
        for attr in ["HttpOnly", "Secure", "SameSite=strict", "Path=/"]:
            assert attr in set_header
            assert attr in clear_header


class TestCookieSecurityConfiguration:
    """Test cookie security configuration under different scenarios."""

    @pytest.mark.parametrize(
        "environment,secure_cookies,expected_secure",
        [
            ("development", False, False),
            ("development", True, True),
            ("production", False, True),  # Production always uses secure
            ("production", True, True),
        ],
    )
    def test_secure_flag_combinations(self, environment: str, secure_cookies: bool, expected_secure: bool):
        """Test secure flag under different environment and configuration combinations."""
        response = Response()

        with patch.object(settings, "environment", environment):
            with patch.object(settings, "secure_cookies", secure_cookies):
                set_auth_cookie(response, "test_token")

        set_cookie_header = response.headers.get("set-cookie", "")

        if expected_secure:
            assert "Secure" in set_cookie_header
        else:
            assert "Secure" not in set_cookie_header

    @pytest.mark.parametrize("samesite_value", ["strict", "lax", "none"])
    def test_samesite_options(self, samesite_value: str):
        """Test different SameSite options."""
        response = Response()

        with patch.object(settings, "cookie_samesite", samesite_value):
            set_auth_cookie(response, "test_token")

        set_cookie_header = response.headers.get("set-cookie", "")
        assert f"SameSite={samesite_value}" in set_cookie_header

    def test_cookie_httponly_always_set(self):
        """Test that HttpOnly is always set regardless of configuration."""
        response = Response()

        # Test in various configurations
        configurations = [
            {"environment": "development", "secure_cookies": False},
            {"environment": "development", "secure_cookies": True},
            {"environment": "production", "secure_cookies": False},
            {"environment": "production", "secure_cookies": True},
        ]

        for config in configurations:
            response = Response()  # Fresh response for each test
            with patch.multiple(settings, **config):
                set_auth_cookie(response, "test_token")

            set_cookie_header = response.headers.get("set-cookie", "")
            assert "HttpOnly" in set_cookie_header, f"HttpOnly missing in config: {config}"

    def test_cookie_path_always_set(self):
        """Test that Path is always set to root."""
        response = Response()

        set_auth_cookie(response, "test_token")

        set_cookie_header = response.headers.get("set-cookie", "")
        assert "Path=/" in set_cookie_header

    def test_multiple_cookies_do_not_interfere(self):
        """Test that setting multiple different cookies doesn't interfere."""
        response = Response()

        set_auth_cookie(response, "auth_token")
        set_session_cookie(response, "session_id", max_age=1800)

        # Response should have multiple set-cookie headers
        set_cookie_headers = response.headers.getlist("set-cookie")
        assert len(set_cookie_headers) == 2

        # Check that both cookies are present
        all_headers = " ".join(set_cookie_headers)
        assert "jwt_token=auth_token" in all_headers
        assert "session_id=session_id" in all_headers
