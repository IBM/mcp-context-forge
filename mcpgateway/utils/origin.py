# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/origin.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Origin normalization and redirect validation utilities.

Shared by :mod:`mcpgateway.admin` and :mod:`mcpgateway.routers.oauth_router`
to avoid duplication and circular imports.
"""

from urllib.parse import urlparse


def normalize_origin_parts(scheme: str, netloc: str) -> tuple[str, str, int]:
    """Normalize origin components for exact same-origin comparisons.

    Resolves default ports so that ``http://host:80`` and ``http://host``
    compare equal.

    Args:
        scheme: URL scheme (for example ``http`` or ``https``).
        netloc: URL authority component (host and optional port).

    Returns:
        Tuple of normalized scheme, hostname, and resolved port.
    """
    parsed = urlparse(f"{scheme}://{netloc}")
    normalized_scheme = (parsed.scheme or scheme or "http").lower()
    normalized_host = (parsed.hostname or "").lower()
    normalized_port = parsed.port
    if normalized_port is None:
        normalized_port = 443 if normalized_scheme == "https" else 80
    return normalized_scheme, normalized_host, normalized_port


def origin_from_url(url: str) -> str:
    """Return the ``scheme://host[:port]`` origin of *url*, with no trailing slash.

    Args:
        url: Any absolute URL (e.g. a Pydantic ``HttpUrl`` stringified value).

    Returns:
        Clean origin string such as ``http://localhost:8080``.
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def is_same_origin(url: str, origin: str) -> bool:
    """Return True if *url* is absolute and has the same origin as *origin*."""
    if "\\" in url or "\\" in origin:
        return False

    try:
        parsed = urlparse(url)
        ref = urlparse(origin)
        if not parsed.scheme or not parsed.netloc or not ref.scheme or not ref.netloc:
            return False
        return normalize_origin_parts(parsed.scheme, parsed.netloc) == normalize_origin_parts(ref.scheme, ref.netloc)
    except (TypeError, ValueError):
        return False


def is_exact_https_origin(origin: str) -> bool:
    """Return whether origin is an HTTPS origin without URL suffix state.

    Args:
        origin: Candidate origin.

    Returns:
        True when the value contains only an HTTPS scheme, host, and optional port.
    """
    if "\\" in origin:
        return False
    try:
        parsed = urlparse(origin)
        port = parsed.port
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
    except (TypeError, ValueError):
        return False
    return bool(
        parsed.scheme.lower() == "https"
        and hostname
        and username is None
        and password is None
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and not (port is None and parsed.netloc.rsplit("@", 1)[-1].endswith(":"))
    )


def is_allowed_redirect(url: str, app_origin: str, allowed_origin: str | None) -> bool:
    """Return whether a post-OAuth redirect target is trusted.

    Args:
        url: Redirect target.
        app_origin: Gateway's trusted application origin.
        allowed_origin: Exact external HTTPS origin configured by the operator.

    Returns:
        True for absolute same-origin URLs or allowlisted absolute HTTPS URLs.
    """
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if is_same_origin(url, app_origin):
            return True
        if parsed.scheme.lower() != "https":
            return False
        return bool(allowed_origin and is_same_origin(url, allowed_origin))
    except (TypeError, ValueError):
        return False
