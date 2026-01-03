# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/token_scoping.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token scoping utilities for extracting and validating token scopes.
"""

# Standard
from typing import Optional

# Third-Party
from fastapi import HTTPException, Request

# First-Party
from mcpgateway.utils.verify_credentials import verify_jwt_token_cached


async def extract_token_scopes_from_request(request: Request) -> Optional[dict]:
    """Extract token scopes from JWT in request.

    Args:
        request: FastAPI request object

    Returns:
        Dict containing token scopes or None if no valid token

    Examples:
        >>> # Test with no authorization header
        >>> from unittest.mock import Mock
        >>> import asyncio
        >>> mock_request = Mock()
        >>> mock_request.headers = {}
        >>> asyncio.run(extract_token_scopes_from_request(mock_request)) is None
        True
        >>>
        >>> # Test with invalid authorization header
        >>> mock_request = Mock()
        >>> mock_request.headers = {"Authorization": "Invalid token"}
        >>> asyncio.run(extract_token_scopes_from_request(mock_request)) is None
        True
        >>>
        >>> # Test with malformed Bearer token
        >>> mock_request = Mock()
        >>> mock_request.headers = {"Authorization": "Bearer"}
        >>> asyncio.run(extract_token_scopes_from_request(mock_request)) is None
        True
        >>>
        >>> # Test with Bearer but no space
        >>> mock_request = Mock()
        >>> mock_request.headers = {"Authorization": "Bearer123"}
        >>> asyncio.run(extract_token_scopes_from_request(mock_request)) is None
        True
    """
    # Get authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]

    try:
        # Use the centralized verify_jwt_token_cached function for consistent JWT validation
        payload = await verify_jwt_token_cached(token, request)
        return payload.get("scopes")
    except HTTPException:
        # Token validation failed (expired, invalid, etc.)
        return None
    except Exception:
        # Any other error in token validation
        return None


def is_token_server_scoped(scopes: Optional[dict]) -> bool:
    """Check if token has server-specific scoping.

    Args:
        scopes: Token scopes dictionary

    Returns:
        bool: True if token is scoped to a specific server

    Examples:
        >>> scopes = {"server_id": "server-123", "permissions": ["tools.read"]}
        >>> is_token_server_scoped(scopes)
        True
        >>> scopes = {"server_id": None, "permissions": ["*"]}
        >>> is_token_server_scoped(scopes)
        False
    """
    if not scopes:
        return False
    return scopes.get("server_id") is not None


def get_token_server_id(scopes: Optional[dict]) -> Optional[str]:
    """Get the server ID that a token is scoped to.

    Args:
        scopes: Token scopes dictionary

    Returns:
        Optional[str]: Server ID if token is server-scoped, None otherwise

    Examples:
        >>> scopes = {"server_id": "server-123", "permissions": ["tools.read"]}
        >>> get_token_server_id(scopes)
        'server-123'
        >>> scopes = {"server_id": None, "permissions": ["*"]}
        >>> get_token_server_id(scopes) is None
        True
    """
    if not scopes:
        return None
    return scopes.get("server_id")


def validate_server_access(scopes: Optional[dict], requested_server_id: str) -> bool:
    """Validate that token scopes allow access to the requested server.

    Args:
        scopes: Token scopes dictionary
        requested_server_id: ID of server being accessed

    Returns:
        bool: True if access is allowed

    Examples:
        >>> scopes = {"server_id": "server-123", "permissions": ["tools.read"]}
        >>> validate_server_access(scopes, "server-123")
        True
        >>> validate_server_access(scopes, "server-456")
        False
        >>> scopes = {"server_id": None, "permissions": ["*"]}
        >>> validate_server_access(scopes, "any-server")
        True
    """
    if not scopes:
        return True  # No scopes means full access (legacy tokens)

    server_id = scopes.get("server_id")
    if server_id is None:
        return True  # Global scope token

    return server_id == requested_server_id
