# -*- coding: utf-8 -*-
"""

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

"""

# Standard
from typing import Optional

# Third-Party
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from fastapi.security.utils import get_authorization_scheme_param
import jwt
from jwt import PyJWTError

# First-Party
from mcpgateway.config import settings

basic_security = HTTPBasic(auto_error=False)
security = HTTPBearer(auto_error=False)


async def verify_jwt_token(token: str) -> dict:
    """Verify and decode a JWT token.

    Args:
        token: The JWT token to verify.

    Returns:
        dict: The decoded token payload containing claims.

    Raises:
        HTTPException: If the token has expired or is invalid.
    """
    try:
        # Decode and validate token
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            # options={"require": ["exp"]},  # Require expiration
        )
        return payload  # Contains the claims (e.g., user info)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_credentials(token: str) -> dict:
    """Verify credentials using a JWT token.

    This function uses verify_jwt_token internally which may raise exceptions.

    Args:
        token: The JWT token to verify.

    Returns:
        dict: The validated token payload with the original token added.
    """
    payload = await verify_jwt_token(token)
    payload["token"] = token
    return payload


async def require_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), jwt_token: Optional[str] = Cookie(None)) -> str | dict:
    """Require authentication via JWT token.

    Checks for a JWT token either in the Authorization header or as a cookie.

    Args:
        credentials: HTTP Authorization credentials from the request header.
        jwt_token: JWT token from cookies.

    Returns:
        str or dict: The verified credentials payload or "anonymous" if authentication is not required.

    Raises:
        HTTPException: If authentication is required but no valid token is provided.
    """
    token = credentials.credentials if credentials else jwt_token

    if settings.auth_required and not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await verify_credentials(token) if token else "anonymous"


async def verify_basic_credentials(credentials: HTTPBasicCredentials) -> str:
    """Verify provided credentials.

    Args:
        credentials: HTTP Basic credentials.

    Returns:
        The username if credentials are valid.

    Raises:
        HTTPException: If credentials are invalid.
    """
    is_valid_user = credentials.username == settings.basic_auth_user
    is_valid_pass = credentials.password == settings.basic_auth_password

    if not (is_valid_user and is_valid_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


async def require_basic_auth(credentials: HTTPBasicCredentials = Depends(basic_security)) -> str:
    """Require valid authentication.

    Args:
        credentials: HTTP Basic credentials provided by the client.

    Returns:
        str: The authenticated username or "anonymous" if auth is not required.

    Raises:
        HTTPException: If authentication is required but no valid credentials are provided.
    """
    if settings.auth_required:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Basic"},
            )
        return await verify_basic_credentials(credentials)
    return "anonymous"


async def require_auth_override(
    auth_header: str | None = None,
    jwt_token: str | None = None,
) -> str | dict:
    """
    Call :func:`require_auth` manually from middleware, without FastAPI
    dependency injection.

    Args:
        auth_header: Raw ``Authorization`` header value
                     (e.g. ``"Bearer eyJhbGciOi..."``).
        jwt_token:   JWT taken from a cookie. If both header and cookie are
                     supplied, the header wins.

    Returns:
        str or dict: Whatever :func:`require_auth` returns
        (decoded JWT payload or the string ``"anonymous"``).

    Note:
        This wrapper may propagate :class:`fastapi.HTTPException` raised by
        :func:`require_auth`, but it does not raise anything on its own, so
        we omit a formal *Raises* section to satisfy pydocstyle.
    """
    credentials = None
    if auth_header:
        scheme, param = get_authorization_scheme_param(auth_header)
        if scheme.lower() == "bearer" and param:
            credentials = HTTPAuthorizationCredentials(scheme=scheme, credentials=param)

    return await require_auth(credentials=credentials, jwt_token=jwt_token)
