# -*- coding: utf-8 -*-
"""Authentication verification utilities for MCP Gateway.

This module provides JWT and Basic authentication verification functions
for securing API endpoints. It supports authentication via Authorization
headers and cookies.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Examples:
    >>> from mcpgateway.utils import verify_credentials as vc
    >>> class DummySettings:
    ...     jwt_secret_key = 'secret'
    ...     jwt_algorithm = 'HS256'
    ...     basic_auth_user = 'user'
    ...     basic_auth_password = 'pass'
    ...     auth_required = True
    ...     require_token_expiration = False
    ...     docs_allow_basic_auth = False
    >>> vc.settings = DummySettings()
    >>> import jwt
    >>> token = jwt.encode({'sub': 'alice'}, 'secret', algorithm='HS256')
    >>> import asyncio
    >>> asyncio.run(vc.verify_jwt_token(token))['sub'] == 'alice'
    True
    >>> payload = asyncio.run(vc.verify_credentials(token))
    >>> payload['token'] == token
    True
    >>> from fastapi.security import HTTPBasicCredentials
    >>> creds = HTTPBasicCredentials(username='user', password='pass')
    >>> asyncio.run(vc.verify_basic_credentials(creds)) == 'user'
    True
    >>> creds_bad = HTTPBasicCredentials(username='user', password='wrong')
    >>> try:
    ...     asyncio.run(vc.verify_basic_credentials(creds_bad))
    ... except Exception as e:
    ...     print('error')
    error
"""

# Standard
from base64 import b64decode
import binascii
import logging
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

# First-Party
from mcpgateway.config import settings

basic_security = HTTPBasic(auto_error=False)
security = HTTPBearer(auto_error=False)

# Standard
logger = logging.getLogger(__name__)


async def verify_jwt_token(token: str) -> dict:
    """Verify and decode a JWT token.

    Decodes and validates a JWT token using the configured secret key
    and algorithm from settings. Checks for token expiration and validity.

    Args:
        token: The JWT token string to verify.

    Returns:
        dict: The decoded token payload containing claims (e.g., user info).

    Raises:
        HTTPException: 401 status if the token has expired or is invalid.
        MissingRequiredClaimError: If the 'exp' claim is required but missing.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = 'pass'
        ...     auth_required = True
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> import jwt
        >>> token = jwt.encode({'sub': 'alice'}, 'secret', algorithm='HS256')
        >>> import asyncio
        >>> asyncio.run(vc.verify_jwt_token(token))['sub'] == 'alice'
        True

        Test expired token:
        >>> import datetime
        >>> expired_payload = {'sub': 'bob', 'exp': datetime.datetime.utcnow() - datetime.timedelta(hours=1)}
        >>> expired_token = jwt.encode(expired_payload, 'secret', algorithm='HS256')
        >>> try:
        ...     asyncio.run(vc.verify_jwt_token(expired_token))
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Token has expired

        Test invalid token:
        >>> invalid_token = 'invalid.token.here'
        >>> try:
        ...     asyncio.run(vc.verify_jwt_token(invalid_token))
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Invalid token
    """
    # try:
    #     Decode and validate token
    #     payload = jwt.decode(
    #         token,
    #         settings.jwt_secret_key,
    #         algorithms=[settings.jwt_algorithm],
    #         # options={"require": ["exp"]},  # Require expiration
    #     )
    #     return payload  # Contains the claims (e.g., user info)
    # except jwt.ExpiredSignatureError:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Token has expired",
    #         headers={"WWW-Authenticate": "Bearer"},
    #     )
    # except PyJWTError:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid token",
    #         headers={"WWW-Authenticate": "Bearer"},
    #     )
    try:
        # First decode to check claims
        unverified = jwt.decode(token, options={"verify_signature": False})

        # Check for expiration claim
        if "exp" not in unverified and settings.require_token_expiration:
            raise jwt.MissingRequiredClaimError("exp")

        # Log warning for non-expiring tokens
        if "exp" not in unverified:
            logger.warning(f"JWT token without expiration accepted. Consider enabling REQUIRE_TOKEN_EXPIRATION for better security. Token sub: {unverified.get('sub', 'unknown')}")

        # Full validation
        options = {}
        if settings.require_token_expiration:
            options["require"] = ["exp"]

        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options=options)
        return payload

    except jwt.MissingRequiredClaimError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing required expiration claim. Set REQUIRE_TOKEN_EXPIRATION=false to allow.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_credentials(token: str) -> dict:
    """Verify credentials using a JWT token.

    A wrapper around verify_jwt_token that adds the original token
    to the decoded payload for reference.

    This function uses verify_jwt_token internally which may raise exceptions.

    Args:
        token: The JWT token string to verify.

    Returns:
        dict: The validated token payload with the original token added
            under the 'token' key.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = 'pass'
        ...     auth_required = True
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> import jwt
        >>> token = jwt.encode({'sub': 'alice'}, 'secret', algorithm='HS256')
        >>> import asyncio
        >>> payload = asyncio.run(vc.verify_credentials(token))
        >>> payload['token'] == token
        True
    """
    payload = await verify_jwt_token(token)
    payload["token"] = token
    return payload


async def require_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), jwt_token: Optional[str] = Cookie(None)) -> str | dict:
    """Require authentication via JWT token.

    FastAPI dependency that checks for a JWT token either in the Authorization
    header (Bearer scheme) or as a cookie. If authentication is required but
    no token is provided, raises an HTTP 401 error.

    Args:
        credentials: HTTP Authorization credentials from the request header.
        jwt_token: JWT token from cookies.

    Returns:
        str | dict: The verified credentials payload if authenticated,
            or "anonymous" if authentication is not required.

    Raises:
        HTTPException: 401 status if authentication is required but no valid
            token is provided.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = 'pass'
        ...     auth_required = True
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> import jwt
        >>> from fastapi.security import HTTPAuthorizationCredentials
        >>> import asyncio

        Test with valid credentials in header:
        >>> token = jwt.encode({'sub': 'alice'}, 'secret', algorithm='HS256')
        >>> creds = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
        >>> result = asyncio.run(vc.require_auth(credentials=creds, jwt_token=None))
        >>> result['sub'] == 'alice'
        True

        Test with valid token in cookie:
        >>> result = asyncio.run(vc.require_auth(credentials=None, jwt_token=token))
        >>> result['sub'] == 'alice'
        True

        Test with auth required but no token:
        >>> try:
        ...     asyncio.run(vc.require_auth(credentials=None, jwt_token=None))
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Not authenticated

        Test with auth not required:
        >>> vc.settings.auth_required = False
        >>> result = asyncio.run(vc.require_auth(credentials=None, jwt_token=None))
        >>> result
        'anonymous'
        >>> vc.settings.auth_required = True
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
    """Verify HTTP Basic authentication credentials.

    Validates the provided username and password against the configured
    basic auth credentials in settings.

    Args:
        credentials: HTTP Basic credentials containing username and password.

    Returns:
        str: The authenticated username if credentials are valid.

    Raises:
        HTTPException: 401 status if credentials are invalid.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = 'pass'
        ...     auth_required = True
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> from fastapi.security import HTTPBasicCredentials
        >>> creds = HTTPBasicCredentials(username='user', password='pass')
        >>> import asyncio
        >>> asyncio.run(vc.verify_basic_credentials(creds)) == 'user'
        True
        >>> creds_bad = HTTPBasicCredentials(username='user', password='wrong')
        >>> try:
        ...     asyncio.run(vc.verify_basic_credentials(creds_bad))
        ... except Exception as e:
        ...     print('error')
        error
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
    """Require valid HTTP Basic authentication.

    FastAPI dependency that enforces Basic authentication when enabled.
    Returns the authenticated username or "anonymous" if auth is not required.

    Args:
        credentials: HTTP Basic credentials provided by the client.

    Returns:
        str: The authenticated username or "anonymous" if auth is not required.

    Raises:
        HTTPException: 401 status if authentication is required but no valid
            credentials are provided.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = 'pass'
        ...     auth_required = True
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> from fastapi.security import HTTPBasicCredentials
        >>> import asyncio

        Test with valid credentials:
        >>> creds = HTTPBasicCredentials(username='user', password='pass')
        >>> asyncio.run(vc.require_basic_auth(creds))
        'user'

        Test with auth required but no credentials:
        >>> try:
        ...     asyncio.run(vc.require_basic_auth(None))
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Not authenticated

        Test with auth not required:
        >>> vc.settings.auth_required = False
        >>> asyncio.run(vc.require_basic_auth(None))
        'anonymous'
        >>> vc.settings.auth_required = True
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


async def require_docs_basic_auth(auth_header: str) -> str:
    """Dedicated handler for HTTP Basic Auth for documentation endpoints only.

    This function is ONLY intended for /docs, /redoc, or similar endpoints, and is enabled
    via the settings.docs_allow_basic_auth flag. It should NOT be used for general API authentication.

    Args:
        auth_header: Raw Authorization header value (e.g. "Basic username:password").

    Returns:
        str: The authenticated username if credentials are valid.

    Raises:
        HTTPException: If credentials are invalid or malformed.
        ValueError: If the basic auth format is invalid (missing colon).
    """
    """Dedicated handler for HTTP Basic Auth for documentation endpoints only.

    This function is ONLY intended for /docs, /redoc, or similar endpoints, and is enabled
    via the settings.docs_allow_basic_auth flag. It should NOT be used for general API authentication.

    Args:
        auth_header: Raw Authorization header value (e.g. "Basic dXNlcjpwYXNz").

    Returns:
        str: The authenticated username if credentials are valid.

    Raises:
        HTTPException: If credentials are invalid or malformed.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = 'pass'
        ...     auth_required = True
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = True
        >>> vc.settings = DummySettings()
        >>> import base64, asyncio
        >>> userpass = base64.b64encode(b'user:pass').decode()
        >>> auth_header = f'Basic {userpass}'
        >>> asyncio.run(vc.require_docs_basic_auth(auth_header))
        'user'

        Test with invalid password:
        >>> badpass = base64.b64encode(b'user:wrong').decode()
        >>> bad_header = f'Basic {badpass}'
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(bad_header))
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Invalid credentials

        Test with malformed header:
        >>> malformed = base64.b64encode(b'userpass').decode()
        >>> malformed_header = f'Basic {malformed}'
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(malformed_header))
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Invalid basic auth credentials

        Test when docs_allow_basic_auth is False:
        >>> vc.settings.docs_allow_basic_auth = False
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(auth_header))
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Basic authentication not allowed or malformed
        >>> vc.settings.docs_allow_basic_auth = True
    """
    scheme, param = get_authorization_scheme_param(auth_header)
    if scheme.lower() == "basic" and param and settings.docs_allow_basic_auth:
        try:
            data = b64decode(param).decode("ascii")
            username, separator, password = data.partition(":")
            if not separator:
                raise ValueError("Invalid basic auth format")
            credentials = HTTPBasicCredentials(username=username, password=password)
            return await require_basic_auth(credentials=credentials)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid basic auth credentials",
                headers={"WWW-Authenticate": "Basic"},
            )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Basic authentication not allowed or malformed",
        headers={"WWW-Authenticate": "Basic"},
    )


async def require_auth_override(
    auth_header: str | None = None,
    jwt_token: str | None = None,
) -> str | dict:
    """Call require_auth manually from middleware without FastAPI dependency injection.

    This wrapper allows manual authentication verification in contexts where
    FastAPI's dependency injection is not available (e.g., middleware).
    It parses the Authorization header and creates the appropriate credentials
    object before calling require_auth.

    Args:
        auth_header: Raw Authorization header value (e.g. "Bearer eyJhbGciOi...").
        jwt_token: JWT taken from a cookie. If both header and cookie are
            supplied, the header takes precedence.

    Returns:
        str | dict: The decoded JWT payload or the string "anonymous",
            same as require_auth.

    Raises:
        HTTPException: If authentication fails or credentials are invalid.
        ValueError: If basic auth credentials are malformed.

    Note:
        This wrapper may propagate HTTPException raised by require_auth,
        but it does not raise anything on its own.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = 'pass'
        ...     auth_required = True
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> import jwt
        >>> import asyncio

        Test with Bearer token in auth header:
        >>> token = jwt.encode({'sub': 'alice'}, 'secret', algorithm='HS256')
        >>> auth_header = f'Bearer {token}'
        >>> result = asyncio.run(vc.require_auth_override(auth_header=auth_header))
        >>> result['sub'] == 'alice'
        True

        Test with invalid auth scheme:
        >>> auth_header = 'Basic dXNlcjpwYXNz'  # Base64 encoded user:pass
        >>> vc.settings.auth_required = False
        >>> result = asyncio.run(vc.require_auth_override(auth_header=auth_header))
        >>> result
        'anonymous'

        Test with only cookie token:
        >>> result = asyncio.run(vc.require_auth_override(jwt_token=token))
        >>> result['sub'] == 'alice'
        True

        Test with no auth:
        >>> result = asyncio.run(vc.require_auth_override())
        >>> result
        'anonymous'
        >>> vc.settings.auth_required = True
    """
    credentials = None
    if auth_header:
        scheme, param = get_authorization_scheme_param(auth_header)
        if scheme.lower() == "bearer" and param:
            credentials = HTTPAuthorizationCredentials(scheme=scheme, credentials=param)
        elif scheme.lower() == "basic" and param and settings.docs_allow_basic_auth:
            # Only allow Basic Auth for docs endpoints when explicitly enabled
            return await require_docs_basic_auth(auth_header)
    return await require_auth(credentials=credentials, jwt_token=jwt_token)
