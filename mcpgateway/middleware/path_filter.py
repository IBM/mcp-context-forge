# -*- coding: utf-8 -*-
"""Centralized path filtering for middleware chain optimization.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This module provides cached path exclusion checks for middleware to reduce
per-request overhead. Each middleware has specific skip semantics that are
preserved (exact vs prefix matching).

Important: preserve existing skip semantics (exact vs prefix).
- ObservabilityMiddleware: exact matches + "/static/" prefix + configured include/exclude patterns
- AuthContextMiddleware: exact matches + "/static/" prefix
- RequestLoggingMiddleware: prefix matches
- DBQueryLoggingMiddleware: exact matches + "/static" prefix (no trailing slash)

Note on /healthz: This endpoint is used by translate.py for standalone MCP server
wrapping, while the main gateway uses /health and /ready. Both are included
for compatibility across deployment modes.
"""

# Standard
from functools import lru_cache
import logging
import re
from typing import FrozenSet, Pattern, Tuple

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# Observability: exact matches + "/static/" prefix + allowlist
# NOTE: /healthz is included for translate.py compatibility (gateway uses /health, /ready)
# See: mcpgateway/translate.py, mcpgateway/config.py:observability_include_paths/observability_exclude_paths
OBSERVABILITY_SKIP_EXACT: FrozenSet[str] = frozenset(
    [
        "/health",
        "/healthz",  # translate.py only, kept for compatibility
        "/ready",
        "/metrics",
        "/admin/events",
    ]
)
OBSERVABILITY_SKIP_PREFIXES: Tuple[str, ...] = ("/static/", "/admin/observability/")

# AuthContext: exact matches + "/static/" prefix (preserves pre-allowlist behavior)
AUTH_CONTEXT_SKIP_EXACT: FrozenSet[str] = frozenset(
    [
        "/health",
        "/healthz",  # translate.py only, kept for compatibility
        "/ready",
        "/metrics",
    ]
)
AUTH_CONTEXT_SKIP_PREFIXES: Tuple[str, ...] = ("/static/",)

# Request logging: prefix matches (current behavior skips "/health/security")
REQUEST_LOG_SKIP_PREFIXES: Tuple[str, ...] = (
    "/health",
    "/healthz",
    "/static",
    "/favicon.ico",
)

# DB query logging: exact matches + "/static" prefix (no trailing slash)
# NOTE: /healthz included for translate.py compatibility
DB_QUERY_LOG_SKIP_EXACT: FrozenSet[str] = frozenset(
    [
        "/health",
        "/healthz",  # translate.py only, kept for compatibility
        "/ready",
    ]
)
DB_QUERY_LOG_SKIP_PREFIXES: Tuple[str, ...] = ("/static",)


def _matches_prefix(path: str, prefixes: Tuple[str, ...]) -> bool:
    """Return True if path starts with any prefix in prefixes.

    Args:
        path: The URL path to check
        prefixes: Tuple of prefix strings to match against

    Returns:
        True if path starts with any of the prefixes

    Examples:
        >>> _matches_prefix("/static/css/app.css", ("/static/", "/assets/"))
        True
        >>> _matches_prefix("/api/users", ("/static/", "/assets/"))
        False
        >>> _matches_prefix("/health", ("/health",))
        True
        >>> _matches_prefix("/healthy", ("/health/",))
        False
    """
    return any(path.startswith(prefix) for prefix in prefixes)


def _matches_any_regex(path: str, patterns: Tuple[Pattern[str], ...]) -> bool:
    """Return True if path matches any regex in patterns.

    Args:
        path: The URL path to check.
        patterns: Tuple of compiled regex patterns to evaluate.

    Returns:
        True if any pattern matches the path.

    Examples:
        >>> import re
        >>> patterns = (re.compile(r"^/api/v[0-9]+/"), re.compile(r"^/rpc/?$"))
        >>> _matches_any_regex("/api/v1/users", patterns)
        True
        >>> _matches_any_regex("/rpc", patterns)
        True
        >>> _matches_any_regex("/health", patterns)
        False
        >>> _matches_any_regex("/api/users", patterns)
        False
    """
    return any(pattern.search(path) for pattern in patterns)


@lru_cache(maxsize=1)
def _get_observability_include_regex() -> Tuple[Pattern[str], ...]:
    """Compile include regex patterns from settings for observability filtering.

    Returns:
        Tuple of compiled regex patterns; invalid patterns are skipped.
    """
    compiled: list[Pattern[str]] = []
    for pattern in settings.observability_include_paths:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            logger.warning("Invalid observability_include_paths regex '%s': %s", pattern, exc)
    return tuple(compiled)


@lru_cache(maxsize=1)
def _get_observability_exclude_regex() -> Tuple[Pattern[str], ...]:
    """Compile exclude regex patterns from settings for observability filtering.

    Returns:
        Tuple of compiled regex patterns; invalid patterns are skipped.
    """
    compiled: list[Pattern[str]] = []
    for pattern in settings.observability_exclude_paths:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            logger.warning("Invalid observability_exclude_paths regex '%s': %s", pattern, exc)
    return tuple(compiled)


@lru_cache(maxsize=256)
def should_skip_observability(path: str) -> bool:
    """Skip logic for ObservabilityMiddleware.

    Skips health endpoints (exact match), static files (prefix match), configured
    include/exclude patterns (include first, then exclude).

    Args:
        path: The URL path from request.url.path

    Returns:
        True if observability should be skipped for this path

    Examples:
        >>> should_skip_observability("/health")
        True
        >>> should_skip_observability("/metrics")
        True
        >>> should_skip_observability("/static/css/app.css")
        True
        >>> should_skip_observability("/health/security")
        True
        >>> should_skip_observability("/tools")
        True
        >>> should_skip_observability("/rpc")
        False
    """
    if path in OBSERVABILITY_SKIP_EXACT or _matches_prefix(path, OBSERVABILITY_SKIP_PREFIXES):
        return True

    if _matches_any_regex(path, _get_observability_exclude_regex()):
        return True

    include_patterns = _get_observability_include_regex()
    if include_patterns and not _matches_any_regex(path, include_patterns):
        return True

    return False


@lru_cache(maxsize=256)
def should_skip_auth_context(path: str) -> bool:
    """Skip logic for AuthContextMiddleware.

    Args:
        path: The URL path from request.url.path

    Returns:
        True if auth context extraction should be skipped for this path

    Examples:
        >>> should_skip_auth_context("/health")
        True
        >>> should_skip_auth_context("/static/js/app.js")
        True
        >>> should_skip_auth_context("/tools")
        False
    """
    return path in AUTH_CONTEXT_SKIP_EXACT or _matches_prefix(path, AUTH_CONTEXT_SKIP_PREFIXES)


@lru_cache(maxsize=256)
def should_skip_request_logging(path: str) -> bool:
    """Skip logic for RequestLoggingMiddleware.

    Uses prefix matching - this means /health/security will also be skipped
    (intentional: preserves existing behavior).

    Args:
        path: The URL path from request.url.path

    Returns:
        True if request logging should be skipped for this path

    Examples:
        >>> should_skip_request_logging("/health")
        True
        >>> should_skip_request_logging("/health/security")
        True
        >>> should_skip_request_logging("/static/css/app.css")
        True
        >>> should_skip_request_logging("/favicon.ico")
        True
        >>> should_skip_request_logging("/ready")
        False
        >>> should_skip_request_logging("/metrics")
        False
    """
    return _matches_prefix(path, REQUEST_LOG_SKIP_PREFIXES)


@lru_cache(maxsize=256)
def should_skip_db_query_logging(path: str) -> bool:
    """Skip logic for DBQueryLoggingMiddleware.

    Skips health endpoints (exact match) and static files (prefix match).
    Note: /metrics is NOT skipped for DB query logging (may query DB for metrics).

    Args:
        path: The URL path from request.url.path

    Returns:
        True if DB query logging should be skipped for this path

    Examples:
        >>> should_skip_db_query_logging("/health")
        True
        >>> should_skip_db_query_logging("/ready")
        True
        >>> should_skip_db_query_logging("/static/css/app.css")
        True
        >>> should_skip_db_query_logging("/health/security")
        False
        >>> should_skip_db_query_logging("/metrics")
        False
    """
    return path in DB_QUERY_LOG_SKIP_EXACT or _matches_prefix(path, DB_QUERY_LOG_SKIP_PREFIXES)


def clear_all_caches() -> None:
    """Clear all path filter caches.

    Useful for testing to ensure cache state doesn't affect test isolation.

    Examples:
        >>> clear_all_caches()
        >>> should_skip_request_logging.cache_info().currsize >= 0
        True
    """
    should_skip_observability.cache_clear()
    should_skip_auth_context.cache_clear()
    should_skip_request_logging.cache_clear()
    should_skip_db_query_logging.cache_clear()
    _get_observability_include_regex.cache_clear()
    _get_observability_exclude_regex.cache_clear()
