# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.utils.security_cookies."""

# Standard
from types import SimpleNamespace

# Third-Party
from fastapi import Response

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
