"""URL utilities for MCP Gateway.

Provides functions for handling URL protocol detection and manipulation,
especially for proxy environments with forwarded headers.
"""

# Standard
from urllib.parse import urlparse, urlunparse

# Third-Party
from fastapi import Request


def get_protocol_from_request(request: Request) -> str:
    """Get protocol from request headers or URL scheme.
    
    Checks X-Forwarded-Proto header first, then falls back to request.url.scheme.

    Args:
        request: The FastAPI request object

    Returns:
        Protocol string: "http" or "https"
    """
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded:
        # may be a comma-separated list; take the first
        return forwarded.split(",")[0].strip()

    return request.url.scheme


def update_url_protocol(request: Request) -> str:
    """Update base URL protocol based on request headers.

    Args:
        request: The FastAPI request object

    Returns:
        Base URL with correct protocol
    """
    parsed = urlparse(str(request.base_url))
    proto = get_protocol_from_request(request)
    new_parsed = parsed._replace(scheme=proto)

    # urlunparse keeps netloc and path intact
    return urlunparse(new_parsed).rstrip("/")
