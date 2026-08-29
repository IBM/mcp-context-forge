# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/subject_token.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Extract the inbound user bearer to use as RFC 8693 subject_token.
"""

# Standard
from http.cookies import CookieError, SimpleCookie
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def extract_inbound_bearer(request_headers: Optional[Dict[str, str]]) -> Optional[str]:
    """Return the bearer credential from request headers, or None.

    Case-insensitive header lookup and scheme match.

    Args:
        request_headers: Inbound request headers, or None.

    Returns:
        The bearer credential string if an ``Authorization: Bearer <token>``
        header is present (case-insensitive), otherwise None.
    """
    if not request_headers:
        return None
    for k, v in request_headers.items():
        if k.lower() == "authorization" and isinstance(v, str):
            parts = v.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
                return parts[1]
    return None


def looks_like_jwt(token: Optional[str]) -> bool:
    """Cheap structural check that ``token`` is a compact-serialization JWT.

    Guards H2: an opaque inbound bearer (e.g. a CF session/API token) must not
    be shipped to an external authorization server as a subject_token. This is a
    shape check only, not signature verification.

    Args:
        token: The token string to check, or None.

    Returns:
        True if ``token`` has the three-segment, non-empty-segment shape of a
        compact-serialization JWT, otherwise False.
    """
    if not token or not isinstance(token, str):
        return False
    parts = token.split(".")
    return len(parts) == 3 and all(parts)


def extract_subject_jwt(request_headers: Optional[Dict[str, str]]) -> Optional[str]:
    """Resolve the RFC 8693 subject token from a bearer header or the ``jwt_token`` cookie.

    Resolution order: ``Authorization: Bearer`` header first, then the
    ``jwt_token`` cookie parsed from the raw ``Cookie`` header. Admin UI
    sessions authenticate with an HttpOnly ``jwt_token`` cookie and cannot
    attach a bearer header, so the cookie path is the primary UI route.
    Each candidate must structurally be a compact-serialization JWT (H2:
    an opaque CF session/API token is never forwarded to an external AS).

    Fail-closed on a mixed credential: if a bearer credential is present at
    all, it is the one the auth dependency already authenticated the request
    against, so a non-JWT-shaped bearer must not fall back to the cookie --
    that cookie may belong to a different principal than the one the bearer
    authenticated (CWE-287/CWE-346). The cookie is only consulted when no
    bearer credential was presented.

    Args:
        request_headers: Inbound request headers, or None.

    Returns:
        The JWT string to use as ``subject_token``, or None if no
        structurally valid JWT is present.
    """
    token = extract_inbound_bearer(request_headers)
    if token is not None:
        return token if looks_like_jwt(token) else None
    if not request_headers:
        return None
    raw_cookie = None
    for k, v in request_headers.items():
        if k.lower() == "cookie" and isinstance(v, str):
            raw_cookie = v
            break
    if not raw_cookie:
        return None
    jar = SimpleCookie()
    try:
        jar.load(raw_cookie)
    except CookieError:
        return None
    except (AttributeError, TypeError) as e:
        logger.debug("Unexpected cookie parsing error: %s: %s", type(e).__name__, e)
        return None
    morsel = jar.get("jwt_token")
    cookie_token = morsel.value if morsel is not None else None
    if cookie_token and looks_like_jwt(cookie_token):
        return cookie_token
    return None
