# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_subject_token.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for mcpgateway.utils.subject_token.
"""

# Standard
from http.cookies import CookieError
from unittest.mock import patch

# First-Party
from mcpgateway.utils.subject_token import extract_subject_jwt

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.sig"  # pragma: allowlist secret


def test_bearer_header_wins():
    headers = {"Authorization": f"Bearer {JWT}", "cookie": "jwt_token=other.jwt.tok"}
    assert extract_subject_jwt(headers) == JWT


def test_cookie_fallback_when_no_bearer():
    headers = {"cookie": f"jwt_token={JWT}; mcpgateway_csrf_token=abc"}
    assert extract_subject_jwt(headers) == JWT


def test_cookie_header_case_insensitive():
    headers = {"Cookie": f"jwt_token={JWT}"}
    assert extract_subject_jwt(headers) == JWT


def test_opaque_bearer_does_not_fall_back_to_cookie():
    """Deny-path regression for CWE-287/CWE-346: an opaque bearer must not be
    silently swapped for a same- or different-principal cookie JWT."""
    headers = {"Authorization": "Bearer opaque-session-token", "cookie": f"jwt_token={JWT}"}
    assert extract_subject_jwt(headers) is None


def test_opaque_bearer_does_not_fall_back_to_other_principal_cookie():
    """Mixed-credential deny path: bearer authenticates principal A, cookie
    carries a JWT for principal B -- must fail closed, never forward B's token."""
    other_principal_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJiIn0.sig2"  # pragma: allowlist secret
    headers = {"Authorization": "Bearer opaque-session-token-for-principal-a", "cookie": f"jwt_token={other_principal_jwt}"}
    assert extract_subject_jwt(headers) is None


def test_opaque_cookie_rejected():
    headers = {"cookie": "jwt_token=not-a-jwt"}
    assert extract_subject_jwt(headers) is None


def test_no_headers():
    assert extract_subject_jwt(None) is None
    assert extract_subject_jwt({}) is None


def test_no_jwt_token_cookie():
    headers = {"cookie": "mcpgateway_csrf_token=abc; other=1"}
    assert extract_subject_jwt(headers) is None


def test_malformed_cookie_header_returns_none():
    headers = {"cookie": ";;;=;;"}
    assert extract_subject_jwt(headers) is None


def test_unexpected_cookie_parse_error_is_logged_and_returns_none(caplog):
    headers = {"cookie": f"jwt_token={JWT}"}
    with patch("mcpgateway.utils.subject_token.SimpleCookie") as mock_jar_cls:
        mock_jar_cls.return_value.load.side_effect = TypeError("boom")
        with caplog.at_level("DEBUG", logger="mcpgateway.utils.subject_token"):
            assert extract_subject_jwt(headers) is None
    assert "TypeError" in caplog.text


def test_cookie_error_returns_none():
    headers = {"cookie": f"jwt_token={JWT}"}
    with patch("mcpgateway.utils.subject_token.SimpleCookie") as mock_jar_cls:
        mock_jar_cls.return_value.load.side_effect = CookieError("bad cookie")
        assert extract_subject_jwt(headers) is None


def test_headers_present_but_no_cookie_key():
    headers = {"X-Something": "value"}
    assert extract_subject_jwt(headers) is None


def test_opaque_bearer_and_no_jwt_token_cookie_returns_none():
    headers = {"Authorization": "Bearer opaque-session-token", "cookie": "mcpgateway_csrf_token=abc"}
    assert extract_subject_jwt(headers) is None
