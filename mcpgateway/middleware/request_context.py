# -*- coding: utf-8 -*-
"""Small helpers for per-request caching.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This module provides optional helpers for caching request metadata on
request.state to avoid repeated property access in hot paths.

Note: This is an optional optimization. Use only if profiling shows
repeated request.url.path access as a hotspot.
"""

# Third-Party
from starlette.requests import Request


def get_request_path(request: Request) -> str:
    """Return cached request path (stores once in request.state).

    Caches the path on first access to avoid repeated URL parsing
    in middleware that check paths multiple times.

    IMPORTANT: Uses request.url.path (not request.scope["path"]) to preserve
    behavior with root_path/mounts when deployed behind proxies.

    Note: Uses _cached_path as a namespaced internal attribute on request.state
    to avoid conflicts with user-defined attributes.

    Args:
        request: The Starlette/FastAPI request object

    Returns:
        The request URL path string

    Examples:
        >>> from unittest.mock import MagicMock
        >>> request = MagicMock()
        >>> request.state = MagicMock()
        >>> request.state._cached_path = None
        >>> request.url.path = "/api/tools"
        >>> # First call stores in cache
        >>> get_request_path(request)  # doctest: +SKIP
        '/api/tools'
    """
    cached = getattr(request.state, "_cached_path", None)
    if cached is None:
        cached = request.url.path
        setattr(request.state, "_cached_path", cached)
    return cached
