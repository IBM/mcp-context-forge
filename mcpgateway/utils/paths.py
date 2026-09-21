# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/paths.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared request-path and filesystem-path utilities for ContextForge.

Some embedded/proxy deployments do not populate ``scope["root_path"]``
consistently.  This module provides a single canonical helper that checks
the ASGI scope first and falls back to ``settings.app_root_path`` when the
scope value is empty — the same logic that was previously private to
``mcpgateway/admin.py`` (issue #3298).

All call sites that previously read ``request.scope.get("root_path", "")``
directly should use :func:`resolve_root_path` instead.
"""

# Standard
import logging
import os
from pathlib import Path
import re
import stat as stat_module

# Third-Party
from fastapi import Request

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# ``dir_fd``/``O_NOFOLLOW``-based ``openat`` chaining (the TOCTOU-proof path in
# ``open_confined()``) is POSIX-only: Windows' ``os.open()`` does not accept
# ``dir_fd`` and neither ``os.O_DIRECTORY`` nor ``os.O_NOFOLLOW`` exist there.
_SUPPORTS_CONFINED_OPENAT = hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd

# Windows ``FILE_ATTRIBUTE_REPARSE_POINT``: set on NTFS symlinks *and* junctions.
# ``stat.S_ISLNK`` alone misses junctions, which Windows does not report as a
# symlink via ``lstat()`` but does mark with this attribute bit.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# Characters that must never appear in a root path — control chars, URL
# scheme markers, query/fragment delimiters, and whitespace other than
# leading/trailing (which is stripped before this check).
_UNSAFE_ROOT_PATH_RE: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f?#]|://")

# Public product-language aliases map to the established internal route names.
# Keep this as the single source of truth so security and transport middleware
# cannot drift when aliases are added or renamed.
_API_PATH_ALIASES: tuple[tuple[str, str], ...] = (
    ("/v1/virtual-servers", "/servers"),
    ("/v1/mcp-servers", "/gateways"),
)


def replace_api_path_alias(path: str) -> str:
    """Replace a public API path alias with its internal route name.

    Only complete path segments are translated. The suffix, including a
    trailing slash, is preserved so callers can continue to apply their own
    endpoint-specific matching rules.

    Args:
        path: Application-relative request path.

    Returns:
        Internal path for a known alias, otherwise ``path`` unchanged.

    Examples:
        >>> replace_api_path_alias("/v1/virtual-servers/server-1/prompts")
        '/servers/server-1/prompts'
        >>> replace_api_path_alias("/v1/mcp-servers/gateway-1")
        '/gateways/gateway-1'
        >>> replace_api_path_alias("/v1/virtual-servers-extra")
        '/v1/virtual-servers-extra'
    """
    for alias_prefix, canonical_prefix in _API_PATH_ALIASES:
        if path == alias_prefix:
            return canonical_prefix
        if path.startswith(f"{alias_prefix}/"):
            return f"{canonical_prefix}{path[len(alias_prefix) :]}"
    return path


def _validate_root_path(value: str) -> str:
    """Reject root-path values that contain unsafe characters.

    Returns an empty string (and logs a warning) for values containing
    control characters (``\\r``, ``\\n``, ``\\0``, etc.), URL scheme
    markers (``://``), or query/fragment delimiters (``?``, ``#``).
    """
    if _UNSAFE_ROOT_PATH_RE.search(value):
        logger.warning("Rejected root_path containing unsafe characters: %r", value[:120])
        return ""
    return value


def resolve_root_path(request: Request, *, fallback: str | None = None) -> str:
    """Resolve the application root path from the request scope with fallback.

    Checks ``request.scope["root_path"]`` first; when that is absent or empty
    falls back to ``settings.app_root_path`` (or *fallback* when explicitly
    supplied).  The returned value is normalised: a leading ``/`` is added when
    the path is non-empty, and any trailing ``/`` is stripped.

    Values containing control characters, URL scheme markers, or query/fragment
    delimiters are sanitised to an empty string (with a warning log) to prevent
    header-injection and open-redirect attacks without crashing the request
    pipeline.

    Args:
        request: Incoming ASGI request whose scope is inspected. Should not be none.
        fallback: Optional explicit fallback string.  When *None* (default)
            ``settings.app_root_path`` is used as the fallback.

    Returns:
        Normalised root path (leading ``/``, no trailing ``/``), or an empty
        string when no root path is configured or the value was rejected.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> req = MagicMock()
        >>> req.scope = {"root_path": "/proxy/mcp"}
        >>> resolve_root_path(req)
        '/proxy/mcp'
        >>> req.scope = {"root_path": ""}
        >>> resolve_root_path(req, fallback="/custom")
        '/custom'
        >>> req.scope = {"root_path": "  "}
        >>> resolve_root_path(req, fallback="")
        ''
    """
    raw = request.scope.get("root_path", "")
    if raw and not isinstance(raw, str):
        logger.warning("Non-string root_path in ASGI scope (type=%s), ignoring", type(raw).__name__)
        raw = ""
    root_path = (raw if isinstance(raw, str) else "").strip()
    if not root_path:
        root_path = (fallback if fallback is not None else (settings.app_root_path or "")).strip()
    if root_path:
        root_path = _validate_root_path(root_path)
    if root_path:
        root_path = "/" + root_path.lstrip("/")
    return root_path.rstrip("/")


def is_path_within(candidate: Path, root: Path) -> bool:
    """Report whether *candidate* is confined to the directory tree rooted at *root*.

    This is the canonical directory-confinement check for ContextForge.  It must be
    used instead of ``str(candidate).startswith(str(root))``: a plain string prefix
    comparison has no notion of a path-component boundary, so a *sibling* directory
    that merely shares a textual prefix (``/srv/logs_secret`` vs. root ``/srv/logs``)
    passes the prefix test while living entirely outside the intended tree.

    Both arguments are expected to be already resolved (``Path.resolve()``) by the
    caller, so that symlinks and ``..`` segments have been collapsed before the
    comparison.  The check itself is purely lexical and touches no filesystem.

    Args:
        candidate: Resolved path to test.
        root: Resolved directory that *candidate* must not escape.

    Returns:
        ``True`` when *candidate* is *root* itself or lives beneath it, else ``False``.

    Examples:
        >>> from pathlib import Path
        >>> is_path_within(Path("/srv/logs/app.log"), Path("/srv/logs"))
        True
        >>> is_path_within(Path("/srv/logs"), Path("/srv/logs"))
        True
        >>> is_path_within(Path("/srv/logs/sub/app.log"), Path("/srv/logs"))
        True

        A sibling directory sharing a textual prefix is correctly rejected, where a
        ``startswith`` check would wrongly allow it:

        >>> str(Path("/srv/logs_secret/creds.json")).startswith(str(Path("/srv/logs")))
        True
        >>> is_path_within(Path("/srv/logs_secret/creds.json"), Path("/srv/logs"))
        False
        >>> is_path_within(Path("/etc/passwd"), Path("/srv/logs"))
        False
    """
    return candidate == root or candidate.is_relative_to(root)


def open_confined(root: Path, relative: Path) -> "tuple[int, os.stat_result]":
    """Open *relative* under *root* confined to that tree, returning a live fd.

    A confinement check performed with ``Path.resolve()`` followed by a *separate*
    ``open()`` call (or, worse, a path handed to something like Starlette's
    ``FileResponse`` that reopens it later) is subject to a TOCTOU race: a process able
    to write into *root* can rename the checked file away and put a symlink in its place
    between the check and the actual open, causing the eventual read to follow the
    symlink to an arbitrary target.

    On POSIX (where ``os.open()`` supports ``dir_fd`` and ``O_DIRECTORY``/``O_NOFOLLOW``
    exist), this closes that window completely by resolving and opening each path
    component with ``dir_fd`` relative to its already-open parent, ``O_NOFOLLOW`` on
    every hop including the final component. A symlink anywhere along the chain raises
    ``OSError`` instead of being followed, and the returned fd refers to the exact inode
    that was validated — nothing can be swapped out from under it after this call
    returns.

    On platforms without that support (Windows lacks ``dir_fd``/``O_NOFOLLOW``), this
    falls back to :func:`_open_confined_fallback`, which rejects a symlink or NTFS
    reparse point (junction) at any path component — including the final one — before
    it is traversed or opened. That check and the following open are two separate
    syscalls rather than one atomic ``openat()`` chain, so it does not close the TOCTOU
    window the POSIX path closes: a process able to write into *root* could in
    principle swap a checked component for a symlink/junction in the gap between them.
    It does close the gap the previous ``resolve()`` + string-prefix check left wide
    open (no per-component check at all), and is the best guarantee available on a
    platform without atomic no-follow traversal.

    Args:
        root: Resolved, trusted directory that confines the lookup.
        relative: Path relative to *root* to open. Must not be absolute, escape *root*
            via ``..``, or be empty.

    Returns:
        A ``(fd, stat_result)`` tuple for the opened regular file. Callers own the fd
        and must close it (e.g. via ``os.fdopen(fd, "rb")`` as a context manager).

    Raises:
        ValueError: *relative* is absolute, escapes *root*, is empty, or resolves to
            something other than a regular file.
        OSError: A path component does not exist, is a symlink/reparse point, or
            cannot be opened (including a symlink rejected by ``O_NOFOLLOW`` on the
            POSIX path).
    """
    if relative.is_absolute() or relative.drive or relative.root or ".." in relative.parts:
        raise ValueError("path escapes confinement root")
    parts = relative.parts
    if not parts:
        raise ValueError("empty path")

    file_fd = _open_confined_posix(root, parts) if _SUPPORTS_CONFINED_OPENAT else _open_confined_fallback(root, parts)

    try:
        file_stat = os.fstat(file_fd)
        if not stat_module.S_ISREG(file_stat.st_mode):
            raise ValueError("not a regular file")
    except BaseException:
        os.close(file_fd)
        raise
    return file_fd, file_stat


def _open_confined_posix(root: Path, parts: "tuple[str, ...]") -> int:
    """Open the final path component via an ``openat``/``O_NOFOLLOW`` chain. POSIX only.

    The final component is opened with ``O_NONBLOCK`` in addition to ``O_NOFOLLOW``.
    Without it, a FIFO planted at that path would block this call — and the calling
    event loop, since ``open_confined()`` runs synchronously — until a writer connects,
    since a read-only open of a FIFO blocks by default. ``O_NONBLOCK`` makes that open
    return immediately instead, and the caller's ``fstat`` check (which requires a
    regular file) rejects the FIFO. Regular-file opens and reads are unaffected:
    ``O_NONBLOCK`` has no effect on them.
    """
    dir_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
            os.close(dir_fd)
            dir_fd = next_fd
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)


def _open_confined_fallback(root: Path, parts: "tuple[str, ...]") -> int:
    """Open the final path component with a per-component reparse-point check.

    Used on platforms without ``dir_fd``/``O_NOFOLLOW`` support (Windows, and any
    other platform where ``os.open()`` cannot chain ``openat()``-style). Each
    component, walked from *root* down, is ``lstat()``-ed and rejected if it is a
    symlink or — on Windows, where a junction is not reported as a symlink by
    ``lstat()`` — a reparse point, before the next component is joined onto it or the
    final component is opened.

    This is not atomic: the check and the following join/open are separate syscalls,
    so a process able to write into *root* could still swap a checked component for a
    symlink/junction in the gap between them (TOCTOU). It rejects every reparse point
    that exists at the time each component is checked, which is strictly more than the
    single post-resolve string-prefix check this replaced ever did.
    """
    current = root
    for part in parts:
        current = current / part
        component_stat = os.lstat(current)
        if stat_module.S_ISLNK(component_stat.st_mode) or (getattr(component_stat, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
            raise OSError(f"path component is a symlink or reparse point: {part!r}")
    return os.open(str(current), os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0))
