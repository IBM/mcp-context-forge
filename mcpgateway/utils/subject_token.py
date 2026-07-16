# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/subject_token.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Extract the inbound user bearer to use as RFC 8693 subject_token.
"""

# Standard
from typing import Dict, Optional


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
