# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/paths.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared root-path resolution utility for ContextForge.

Some embedded/proxy deployments do not populate ``scope["root_path"]``
consistently.  This module provides a single canonical helper that checks
the ASGI scope first and falls back to ``settings.app_root_path`` when the
scope value is empty — the same logic that was previously private to
``mcpgateway/admin.py`` (PR #3297).

All call sites that previously read ``request.scope.get("root_path", "")``
directly should use :func:`resolve_root_path` instead.

Examples:
    >>> from unittest.mock import MagicMock
    >>> from mcpgateway.utils.paths import resolve_root_path
    >>> req = MagicMock()
    >>> req.scope = {"root_path": "/api/v1"}
    >>> resolve_root_path(req)
    '/api/v1'
    >>> req.scope = {"root_path": ""}
    >>> resolve_root_path(req, fallback="/fallback")
    '/fallback'
    >>> req.scope = {}
    >>> resolve_root_path(req, fallback="")
    ''
"""

# Third-Party
from fastapi import Request

# First-Party
from mcpgateway.config import settings


def resolve_root_path(request: Request, *, fallback: str | None = None) -> str:
    """Resolve the application root path from the request scope with fallback.

    Checks ``request.scope["root_path"]`` first; when that is absent or empty
    falls back to ``settings.app_root_path`` (or *fallback* when explicitly
    supplied).  The returned value is normalised: a leading ``/`` is added when
    the path is non-empty, and any trailing ``/`` is stripped.

    Args:
        request: Incoming ASGI request whose scope is inspected.
        fallback: Optional explicit fallback string.  When *None* (default)
            ``settings.app_root_path`` is used as the fallback.

    Returns:
        Normalised root path (leading ``/``, no trailing ``/``), or an empty
        string when no root path is configured.

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
    root_path = request.scope.get("root_path", "") or ""
    if not root_path or not str(root_path).strip():
        root_path = fallback if fallback is not None else (settings.app_root_path or "")
    root_path = str(root_path).strip()
    if root_path:
        root_path = "/" + root_path.lstrip("/")
    return root_path.rstrip("/")
