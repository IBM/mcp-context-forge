# -*- coding: utf-8 -*-
"""Tests for mcpgateway.utils.subject_token."""

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


def test_opaque_bearer_falls_through_to_cookie():
    headers = {"Authorization": "Bearer opaque-session-token", "cookie": f"jwt_token={JWT}"}
    assert extract_subject_jwt(headers) == JWT


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
