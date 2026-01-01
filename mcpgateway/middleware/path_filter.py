# -*- coding: utf-8 -*-
"""Centralized path filtering for middleware chain optimization.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This module provides cached path exclusion checks for middleware to reduce
per-request overhead. Each middleware has specific skip semantics that are
preserved (exact vs prefix matching).

Important: preserve existing skip semantics (exact vs prefix).
- ObservabilityMiddleware/AuthContextMiddleware: exact matches + "/static/" prefix
- RequestLoggingMiddleware: prefix matches
- DBQueryLoggingMiddleware: exact matches + "/static" prefix (no trailing slash)

Note on /healthz: This endpoint is used by translate.py for standalone MCP server
wrapping, while the main gateway uses /health and /ready. Both are included
for compatibility across deployment modes.
"""

# Standard
from functools import lru_cache
from typing import FrozenSet, Tuple

# Observability/AuthContext: exact matches + "/static/" prefix
# NOTE: /healthz is included for translate.py compatibility (gateway uses /health, /ready)
# See: mcpgateway/translate.py, mcpgateway/config.py:observability_exclude_paths
OBSERVABILITY_SKIP_EXACT: FrozenSet[str] = frozenset(
    [
        "/health",
        "/healthz",  # translate.py only, kept for compatibility
        "/ready",
        "/metrics",
    ]
)
OBSERVABILITY_SKIP_PREFIXES: Tuple[str, ...] = ("/static/",)

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
    """
    return any(path.startswith(prefix) for prefix in prefixes)


@lru_cache(maxsize=256)
def should_skip_observability(path: str) -> bool:
    """Skip logic for ObservabilityMiddleware.

    Skips health endpoints (exact match) and static files (prefix match).

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
        False
        >>> should_skip_observability("/tools")
        False
    """
    return path in OBSERVABILITY_SKIP_EXACT or _matches_prefix(path, OBSERVABILITY_SKIP_PREFIXES)


@lru_cache(maxsize=256)
def should_skip_auth_context(path: str) -> bool:
    """Skip logic for AuthContextMiddleware (same as observability).

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
    return should_skip_observability(path)


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
    """
    should_skip_observability.cache_clear()
    should_skip_auth_context.cache_clear()
    should_skip_request_logging.cache_clear()
    should_skip_db_query_logging.cache_clear()
