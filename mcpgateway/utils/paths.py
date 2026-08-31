# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/paths.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared request-path utilities for ContextForge.

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
