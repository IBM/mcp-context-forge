# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_paths.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for shared request-path and filesystem-path utilities.

Covers the canonical root-path resolution helper introduced in issue #3298
to replace the 12 direct ``request.scope.get("root_path", "")`` call sites
that lacked the ``settings.app_root_path`` fallback.
"""

# Future
from __future__ import annotations

# Standard
import os
from pathlib import Path
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.paths import is_path_within, open_confined, replace_api_path_alias, resolve_root_path

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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/v1/virtual-servers", "/servers"),
        ("/v1/virtual-servers/", "/servers/"),
        ("/v1/virtual-servers/server-1/prompts", "/servers/server-1/prompts"),
        ("/v1/mcp-servers", "/gateways"),
        ("/v1/mcp-servers/gateway-1/tools/refresh/", "/gateways/gateway-1/tools/refresh/"),
        ("/servers/server-1", "/servers/server-1"),
        ("/v1/tools", "/v1/tools"),
        ("/v1/virtual-servers-extra/server-1", "/v1/virtual-servers-extra/server-1"),
        ("/prefix/v1/virtual-servers/server-1", "/prefix/v1/virtual-servers/server-1"),
    ],
)
def test_replace_api_path_alias(path: str, expected: str) -> None:
    """Known aliases are replaced without broad prefix matches."""
    assert replace_api_path_alias(path) == expected


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


# ---------------------------------------------------------------------------
# is_path_within
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        "/srv/logs",
        "/srv/logs/app.log",
        "/srv/logs/archive/app.log",
    ],
)
def test_is_path_within_accepts_root_and_descendants(candidate: str) -> None:
    """The root itself and anything beneath it are confined."""
    assert is_path_within(Path(candidate), Path("/srv/logs")) is True


@pytest.mark.parametrize(
    "candidate",
    [
        "/srv/logs_secret/creds.json",
        "/srv/logsx",
        "/srv/logs-backup/app.log",
        "/srv",
        "/etc/passwd",
    ],
)
def test_is_path_within_rejects_paths_outside_root(candidate: str) -> None:
    """Anything outside the root tree is rejected, siblings included."""
    assert is_path_within(Path(candidate), Path("/srv/logs")) is False


def test_is_path_within_rejects_sibling_that_startswith_would_allow() -> None:
    """Regression: the sibling-prefix case a ``startswith`` check gets wrong.

    ``/srv/logs_secret/creds.json`` shares a textual prefix with ``/srv/logs`` but
    lives outside that directory tree.
    """
    candidate = Path("/srv/logs_secret/creds.json")
    root = Path("/srv/logs")

    # The insecure check this helper replaces would allow it...
    assert str(candidate).startswith(str(root)) is True
    # ...while component-aware confinement correctly denies it.
    assert is_path_within(candidate, root) is False


def test_is_path_within_resolves_relative_escape(tmp_path: Path) -> None:
    """A ``..`` escape collapsed by ``resolve()`` is rejected."""
    root = (tmp_path / "logs").resolve()
    root.mkdir()
    (tmp_path / "logs_secret").mkdir()

    escaped = (root / ".." / "logs_secret" / "creds.json").resolve()

    assert str(escaped).startswith(str(root)) is True
    assert is_path_within(escaped, root) is False


# ---------------------------------------------------------------------------
# open_confined
# ---------------------------------------------------------------------------


def test_open_confined_opens_regular_file(tmp_path: Path) -> None:
    """A regular file directly under root is opened and its fd/stat returned."""
    (tmp_path / "app.log").write_text("hello")

    fd, st = open_confined(tmp_path, Path("app.log"))
    try:
        assert os.read(fd, 5) == b"hello"
        assert st.st_size == 5
    finally:
        os.close(fd)


def test_open_confined_opens_nested_file(tmp_path: Path) -> None:
    """Intermediate directory components are walked via dir_fd, not string joins."""
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "app.log").write_text("rotated")

    fd, st = open_confined(tmp_path, Path("archive/app.log"))
    try:
        assert os.read(fd, st.st_size) == b"rotated"
    finally:
        os.close(fd)


def test_open_confined_rejects_missing_file(tmp_path: Path) -> None:
    """A nonexistent file raises FileNotFoundError, not a generic OSError."""
    with pytest.raises(FileNotFoundError):
        open_confined(tmp_path, Path("does-not-exist.log"))


def test_open_confined_rejects_symlinked_file(tmp_path: Path) -> None:
    """The final component is opened with O_NOFOLLOW: a symlink is rejected even
    when its target is inside root, closing the TOCTOU window a resolve()-then-open()
    check leaves open (target can be swapped between the check and the reopen)."""
    (tmp_path / "real.log").write_text("main")
    (tmp_path / "app.log").symlink_to(tmp_path / "real.log")

    with pytest.raises(OSError):
        open_confined(tmp_path, Path("app.log"))


def test_open_confined_rejects_symlinked_parent_dir(tmp_path: Path) -> None:
    """A symlinked intermediate directory component is rejected too, not just the leaf."""
    real_dir = tmp_path / "real_archive"
    real_dir.mkdir()
    (real_dir / "app.log").write_text("rotated")
    (tmp_path / "archive").symlink_to(real_dir)

    with pytest.raises(OSError):
        open_confined(tmp_path, Path("archive/app.log"))


def test_open_confined_rejects_absolute_path(tmp_path: Path) -> None:
    """Absolute input is rejected before any filesystem access."""
    with pytest.raises(ValueError):
        open_confined(tmp_path, Path("/etc/passwd"))


def test_open_confined_rejects_dotdot_escape(tmp_path: Path) -> None:
    """A ``..`` component is rejected before any filesystem access."""
    with pytest.raises(ValueError):
        open_confined(tmp_path, Path("../secret.txt"))


def test_open_confined_rejects_empty_path(tmp_path: Path) -> None:
    """An empty relative path (no components at all) is rejected before any open()."""
    with pytest.raises(ValueError):
        open_confined(tmp_path, Path(""))


def test_open_confined_rejects_directory_as_final_component(tmp_path: Path) -> None:
    """The final component must be a regular file, not a directory."""
    (tmp_path / "subdir").mkdir()

    with pytest.raises(ValueError):
        open_confined(tmp_path, Path("subdir"))


@pytest.mark.timeout(5)
def test_open_confined_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    """A FIFO at the final component must be rejected, not block the caller.

    A plain ``O_RDONLY`` open of a FIFO blocks until a writer connects. Since
    open_confined() runs synchronously from an async admin handler, that would hang
    the event loop indefinitely; ``O_NONBLOCK`` on the final open must prevent it.
    This test has no writer for the FIFO, so it would hang (and time out) if that
    flag regressed.
    """
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are not supported on this platform")

    fifo_path = tmp_path / "blocked.log"
    os.mkfifo(fifo_path)

    with pytest.raises(ValueError):
        open_confined(tmp_path, Path("blocked.log"))


# ---------------------------------------------------------------------------
# open_confined — fallback path used on platforms without dir_fd/O_NOFOLLOW (e.g. Windows)
# ---------------------------------------------------------------------------


def test_open_confined_fallback_opens_regular_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without dir_fd/O_NOFOLLOW support, open_confined() must still succeed for a
    legitimate file via the per-component reparse-point-checking fallback."""
    monkeypatch.setattr("mcpgateway.utils.paths._SUPPORTS_CONFINED_OPENAT", False)
    (tmp_path / "app.log").write_text("hello")

    fd, file_stat = open_confined(tmp_path, Path("app.log"))
    try:
        assert os.pread(fd, file_stat.st_size, 0) == b"hello"
    finally:
        os.close(fd)


def test_open_confined_fallback_opens_nested_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback must walk and open intermediate directory components too, not just
    the final one."""
    monkeypatch.setattr("mcpgateway.utils.paths._SUPPORTS_CONFINED_OPENAT", False)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "app.log").write_text("nested")

    fd, file_stat = open_confined(tmp_path, Path("sub/app.log"))
    try:
        assert os.pread(fd, file_stat.st_size, 0) == b"nested"
    finally:
        os.close(fd)


def test_open_confined_fallback_rejects_symlinked_final_component(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback is not atomic, but it must still reject a symlink at the final
    path component checked at open time."""
    monkeypatch.setattr("mcpgateway.utils.paths._SUPPORTS_CONFINED_OPENAT", False)
    (tmp_path / "real.log").write_text("hello")
    (tmp_path / "app.log").symlink_to(tmp_path / "real.log")

    with pytest.raises(OSError):
        open_confined(tmp_path, Path("app.log"))


def test_open_confined_fallback_rejects_symlinked_intermediate_component(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A symlinked intermediate directory component must be rejected too, not just the
    final component."""
    monkeypatch.setattr("mcpgateway.utils.paths._SUPPORTS_CONFINED_OPENAT", False)
    outside = tmp_path.with_name(tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "app.log").write_text("secret")
    (tmp_path / "sub").symlink_to(outside)

    with pytest.raises(OSError):
        open_confined(tmp_path, Path("sub/app.log"))
