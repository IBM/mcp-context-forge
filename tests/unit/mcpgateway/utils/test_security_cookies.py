# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.utils.security_cookies."""

# Standard
import logging
from types import SimpleNamespace

# Third-Party
from fastapi import Response
import pytest

# First-Party
import mcpgateway.utils.security_cookies as security_cookies


def test_set_auth_cookie_uses_short_expiry_and_insecure_in_dev(monkeypatch) -> None:
    monkeypatch.setattr(
        security_cookies,
        "settings",
        SimpleNamespace(environment="development", secure_cookies=False, cookie_samesite="lax", app_root_path=""),
    )

    resp = Response()
    security_cookies.set_auth_cookie(resp, token="tok123", remember_me=False)

    header = resp.headers.get("set-cookie") or ""
    assert "jwt_token=tok123" in header
    assert "Max-Age=3600" in header
    assert "Path=/" in header
    assert "HttpOnly" in header
    assert "Secure" not in header


def test_set_auth_cookie_remember_me_sets_long_expiry_and_secure_in_production(monkeypatch) -> None:
    monkeypatch.setattr(
        security_cookies,
        "settings",
        SimpleNamespace(environment="production", secure_cookies=False, cookie_samesite="strict", app_root_path="/mcp"),
    )

    resp = Response()
    security_cookies.set_auth_cookie(resp, token="tok123", remember_me=True)

    header = resp.headers.get("set-cookie") or ""
    assert "Max-Age=2592000" in header  # 30 days
    assert "Path=/mcp" in header
    assert "SameSite=strict" in header
    assert "Secure" in header


def test_clear_auth_cookie_uses_same_security_attributes(monkeypatch) -> None:
    monkeypatch.setattr(
        security_cookies,
        "settings",
        SimpleNamespace(environment="production", secure_cookies=False, cookie_samesite="lax", app_root_path=""),
    )

    resp = Response()
    security_cookies.set_auth_cookie(resp, token="tok123", remember_me=False)
    security_cookies.clear_auth_cookie(resp)

    # Starlette appends a second Set-Cookie header for the deletion.
    set_cookies = resp.headers.getlist("set-cookie")
    assert any("jwt_token=" in c for c in set_cookies)
    assert any("Secure" in c for c in set_cookies)


def test_session_cookie_set_and_clear(monkeypatch) -> None:
    monkeypatch.setattr(
        security_cookies,
        "settings",
        SimpleNamespace(environment="development", secure_cookies=True, cookie_samesite="lax", app_root_path="/"),
    )

    resp = Response()
    security_cookies.set_session_cookie(resp, session_id="sess-1", max_age=60)
    security_cookies.clear_session_cookie(resp)

    set_cookies = resp.headers.getlist("set-cookie")
    assert any("session_id=sess-1" in c for c in set_cookies)
    assert any("session_id=" in c for c in set_cookies)  # deletion cookie
    assert any("Max-Age=60" in c for c in set_cookies)
    assert any("Secure" in c for c in set_cookies)


def test_set_auth_cookie_best_effort_sub_extraction_swallows_decode_errors(monkeypatch) -> None:
    """If the token looks like a JWT but is not decodable, we still set the cookie."""
    monkeypatch.setattr(
        security_cookies,
        "settings",
        SimpleNamespace(environment="development", secure_cookies=False, cookie_samesite="lax", app_root_path=""),
    )

    resp = Response()
    # Second segment is intentionally not valid base64/json, triggering the best-effort except block.
    security_cookies.set_auth_cookie(resp, token="header..sig", remember_me=False)

    header = resp.headers.get("set-cookie") or ""
    assert "jwt_token=header..sig" in header


def test_set_auth_cookie_warns_when_cookie_approaches_limit(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        security_cookies,
        "settings",
        SimpleNamespace(environment="development", secure_cookies=False, cookie_samesite="lax", app_root_path=""),
    )
    monkeypatch.setattr(security_cookies, "_COOKIE_WARN_THRESHOLD", 1)

    resp = Response()
    with caplog.at_level(logging.WARNING, logger=security_cookies.logger.name):
        security_cookies.set_auth_cookie(resp, token="tok123", remember_me=False)

    assert any("approaching" in rec.message for rec in caplog.records)


def test_set_auth_cookie_raises_when_cookie_exceeds_hard_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        security_cookies,
        "settings",
        SimpleNamespace(environment="development", secure_cookies=False, cookie_samesite="lax", app_root_path=""),
    )

    with pytest.raises(security_cookies.CookieTooLargeError):
        security_cookies.set_auth_cookie(Response(), token="x" * 5000, remember_me=False)
