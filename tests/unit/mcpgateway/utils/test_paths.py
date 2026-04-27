# -*- coding: utf-8 -*-
"""Unit tests for mcpgateway.utils.paths.resolve_root_path.

Covers the canonical root-path resolution helper introduced in issue #3298
to replace the 12 direct ``request.scope.get("root_path", "")`` call sites
that lacked the ``settings.app_root_path`` fallback.
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.paths import resolve_root_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(root_path: str | None = "") -> MagicMock:
    """Return a minimal mock Request whose scope contains *root_path*."""
    req = MagicMock()
    if root_path is None:
        req.scope = {}
    else:
        req.scope = {"root_path": root_path}
    return req


# ---------------------------------------------------------------------------
# Scope-based resolution (no settings fallback needed)
# ---------------------------------------------------------------------------


def test_scope_root_path_returned_as_is_when_set() -> None:
    """A non-empty scope root_path is returned normalised."""
    req = _make_request("/api/v1")
    assert resolve_root_path(req) == "/api/v1"


def test_scope_root_path_adds_leading_slash() -> None:
    """A scope root_path without a leading slash gets one added."""
    req = _make_request("api/v1")
    assert resolve_root_path(req) == "/api/v1"


def test_scope_root_path_strips_trailing_slash() -> None:
    """A scope root_path with a trailing slash has it removed."""
    req = _make_request("/api/v1/")
    assert resolve_root_path(req) == "/api/v1"


def test_scope_root_path_normalises_multiple_leading_slashes() -> None:
    """Multiple leading slashes are collapsed to one."""
    req = _make_request("///api/v1")
    assert resolve_root_path(req) == "/api/v1"


# ---------------------------------------------------------------------------
# Empty / whitespace scope → settings fallback
# ---------------------------------------------------------------------------


def test_empty_scope_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """When scope root_path is empty, settings.app_root_path is used."""
    monkeypatch.setattr("mcpgateway.utils.paths.settings", MagicMock(app_root_path="/proxy/mcp"))
    req = _make_request("")
    assert resolve_root_path(req) == "/proxy/mcp"


def test_whitespace_scope_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """A whitespace-only scope root_path is treated as empty."""
    monkeypatch.setattr("mcpgateway.utils.paths.settings", MagicMock(app_root_path="/proxy/mcp"))
    req = _make_request("   ")
    assert resolve_root_path(req) == "/proxy/mcp"


def test_missing_scope_key_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """When root_path key is absent from scope, settings fallback is used."""
    monkeypatch.setattr("mcpgateway.utils.paths.settings", MagicMock(app_root_path="/proxy/mcp"))
    req = _make_request(None)  # scope has no root_path key
    assert resolve_root_path(req) == "/proxy/mcp"


def test_empty_scope_and_empty_settings_returns_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """When both scope and settings are empty, an empty string is returned."""
    monkeypatch.setattr("mcpgateway.utils.paths.settings", MagicMock(app_root_path=""))
    req = _make_request("")
    assert resolve_root_path(req) == ""


def test_empty_scope_and_none_settings_returns_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """When settings.app_root_path is None, an empty string is returned."""
    monkeypatch.setattr("mcpgateway.utils.paths.settings", MagicMock(app_root_path=None))
    req = _make_request("")
    assert resolve_root_path(req) == ""


# ---------------------------------------------------------------------------
# Explicit fallback parameter overrides settings
# ---------------------------------------------------------------------------


def test_explicit_fallback_used_when_scope_empty() -> None:
    """An explicit *fallback* argument takes precedence over settings."""
    req = _make_request("")
    assert resolve_root_path(req, fallback="/custom") == "/custom"


def test_explicit_fallback_empty_string_returns_empty() -> None:
    """An explicit empty-string fallback returns empty string."""
    req = _make_request("")
    assert resolve_root_path(req, fallback="") == ""


def test_explicit_fallback_not_used_when_scope_has_value() -> None:
    """The fallback is ignored when scope already provides a root_path."""
    req = _make_request("/from-scope")
    assert resolve_root_path(req, fallback="/ignored") == "/from-scope"


# ---------------------------------------------------------------------------
# Settings fallback normalisation
# ---------------------------------------------------------------------------


def test_settings_fallback_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    """The settings fallback value is also normalised (leading /, no trailing /)."""
    monkeypatch.setattr("mcpgateway.utils.paths.settings", MagicMock(app_root_path="proxy/mcp/"))
    req = _make_request("")
    assert resolve_root_path(req) == "/proxy/mcp"


# ---------------------------------------------------------------------------
# Regression: scope value takes priority over non-empty settings
# ---------------------------------------------------------------------------


def test_scope_takes_priority_over_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty scope root_path is used even when settings has a different value."""
    monkeypatch.setattr("mcpgateway.utils.paths.settings", MagicMock(app_root_path="/settings-path"))
    req = _make_request("/scope-path")
    assert resolve_root_path(req) == "/scope-path"


# ---------------------------------------------------------------------------
# Edge case: bare slash
# ---------------------------------------------------------------------------


def test_bare_slash_returns_empty_string() -> None:
    """A scope root_path of '/' normalises to empty string (no trailing slash)."""
    req = _make_request("/")
    assert resolve_root_path(req) == ""


# ---------------------------------------------------------------------------
# Security: reject unsafe characters (defense-in-depth)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    [
        "https://evil.com",
        "http://evil.com/path",
        "/app\r\nX-Injected: true",
        "/app\nSet-Cookie: pwned=true",
        "/app\r\nmiddlecrlf",
        "/app\x00null",
        "/app?query=1",
        "/app#fragment",
    ],
    ids=[
        "url-https-scheme",
        "url-http-scheme",
        "crlf-header-injection",
        "lf-header-injection",
        "embedded-crlf",
        "null-byte",
        "query-delimiter",
        "fragment-delimiter",
    ],
)
def test_rejects_unsafe_scope_root_path(bad_value: str) -> None:
    """resolve_root_path sanitises unsafe scope values to empty string."""
    req = _make_request(bad_value)
    assert resolve_root_path(req) == ""


@pytest.mark.parametrize(
    "bad_value",
    [
        "https://evil.com",
        "/app\r\nX-Injected: true",
        "/app\x00null",
        "/app?query=1",
    ],
    ids=[
        "url-scheme-in-settings",
        "crlf-in-settings",
        "null-byte-in-settings",
        "query-in-settings",
    ],
)
def test_rejects_unsafe_settings_fallback(bad_value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_root_path sanitises unsafe settings fallback to empty string."""
    monkeypatch.setattr("mcpgateway.utils.paths.settings", MagicMock(app_root_path=bad_value))
    req = _make_request("")
    assert resolve_root_path(req) == ""


def test_rejects_unsafe_explicit_fallback() -> None:
    """resolve_root_path sanitises unsafe explicit fallback to empty string."""
    req = _make_request("")
    assert resolve_root_path(req, fallback="https://evil.com") == ""


def test_path_traversal_dots_preserved() -> None:
    """Path traversal sequences are preserved (they are handled by ASGI/routing)."""
    req = _make_request("/app/../admin")
    assert resolve_root_path(req) == "/app/../admin"


def test_encoded_chars_preserved() -> None:
    """Percent-encoded characters are preserved as-is."""
    req = _make_request("/app%2Fpath")
    assert resolve_root_path(req) == "/app%2Fpath"
