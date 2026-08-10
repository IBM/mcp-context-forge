# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/paths.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared root-path resolution utility for ContextForge.

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
import re

# Third-Party
from fastapi import Request

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# Characters that must never appear in a root path — control chars, URL
# scheme markers, query/fragment delimiters, and whitespace other than
# leading/trailing (which is stripped before this check).
_UNSAFE_ROOT_PATH_RE: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f?#]|://")


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


def _normalize_scope_path(scope_path: str, root_path: str) -> str:
    """Strip ``root_path`` prefix from *scope_path* when a reverse proxy forwards the full path.

    Returns the route-only path (e.g. ``"/qa/gateway/docs"`` -> ``"/docs"``).
    A ``root_path`` of ``"/"`` is ignored to avoid stripping the leading slash
    from every path.  Trailing slashes on *root_path* are stripped before
    comparison so that ``"/qa/gateway/"`` is handled identically to
    ``"/qa/gateway"``.

    Args:
        scope_path: The full path from the request scope.
        root_path: The root path prefix to be stripped.

    Returns:
        The normalized path with the root_path prefix removed.
    """
    if root_path and len(root_path) > 1:
        root_path = root_path.rstrip("/")
    if root_path and len(root_path) > 1 and scope_path.startswith(root_path):
        rest = scope_path[len(root_path) :]
        # Ensure we matched a full path segment, not a partial prefix
        # e.g. root_path="/app" must not strip from "/application/admin"
        if not rest or rest[0] == "/":
            return rest or "/"
    return scope_path
