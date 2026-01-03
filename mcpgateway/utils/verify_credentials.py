# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/verify_credentials.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Authentication verification utilities for MCP Gateway.
This module provides JWT and Basic authentication verification functions
for securing API endpoints. It supports authentication via Authorization
headers and cookies.
Examples:
    >>> from mcpgateway.utils import verify_credentials as vc
    >>> from pydantic import SecretStr
    >>> class DummySettings:
    ...     jwt_secret_key = 'secret'
    ...     jwt_algorithm = 'HS256'
    ...     jwt_audience = 'mcpgateway-api'
    ...     jwt_issuer = 'mcpgateway'
    ...     jwt_audience_verification = True
    ...     basic_auth_user = 'user'
    ...     basic_auth_password = SecretStr('pass')
    ...     auth_required = True
    ...     require_token_expiration = False
    ...     docs_allow_basic_auth = False
    >>> vc.settings = DummySettings()
    >>> import jwt
    >>> token = jwt.encode({'sub': 'alice', 'aud': 'mcpgateway-api', 'iss': 'mcpgateway'}, 'secret', algorithm='HS256')
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
from typing import Optional

# Third-Party
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param
import jwt

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.jwt_config_helper import validate_jwt_algo_and_keys

basic_security = HTTPBasic(auto_error=False)
security = HTTPBearer(auto_error=False)

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


async def verify_jwt_token(token: str) -> dict:
    """Verify and decode a JWT token in a single pass.

    Decodes and validates a JWT token using the configured secret key
    and algorithm from settings. Uses PyJWT's require option for claim
    enforcement instead of a separate unverified decode.

    Note:
        With single-pass decoding, signature validation occurs before
        claim validation. An invalid signature will result in "Invalid token"
        error even if the token is also missing required claims.

    Args:
        token: The JWT token string to verify.

    Returns:
        dict: The decoded token payload containing claims (e.g., user info).

    Raises:
        HTTPException: If token is invalid, expired, or missing required claims.
    """
    try:
        validate_jwt_algo_and_keys()

        # Import the verification key helper
        # First-Party
        from mcpgateway.utils.jwt_config_helper import get_jwt_public_key_or_secret

        options = {
            "verify_aud": settings.jwt_audience_verification,
        }

        if settings.require_token_expiration:
            options["require"] = ["exp"]

        decode_kwargs = {
            "key": get_jwt_public_key_or_secret(),
            "algorithms": [settings.jwt_algorithm],
            "options": options,
            "audience": settings.jwt_audience,
            "issuer": settings.jwt_issuer,
        }

        payload = jwt.decode(token, **decode_kwargs)

        # Log warning for tokens without expiration (when not required)
        if not settings.require_token_expiration and "exp" not in payload:
            logger.warning(f"JWT token without expiration accepted. Consider enabling REQUIRE_TOKEN_EXPIRATION for better security. Token sub: {payload.get('sub', 'unknown')}")

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


async def verify_jwt_token_cached(token: str, request: Optional[Request] = None) -> dict:
    """Verify JWT token with request-level caching.

    If a request object is provided and the token has already been verified
    for this request, returns the cached payload. Otherwise, performs
    verification and caches the result in request.state.

    Args:
        token: JWT token string to verify
        request: Optional FastAPI/Starlette request for request-level caching.
            Must have a 'state' attribute to enable caching.

    Returns:
        dict: Decoded and verified JWT payload

    Raises:
        HTTPException: If token is invalid, expired, or missing required claims.
    """
    # Check request.state cache first (safely handle non-Request objects)
    if request is not None and hasattr(request, "state"):
        cached = getattr(request.state, "_jwt_verified_payload", None)
        # Verify cache is a valid tuple of (token, payload) before unpacking
        if cached is not None and isinstance(cached, tuple) and len(cached) == 2:
            cached_token, cached_payload = cached
            if cached_token == token:
                return cached_payload

    # Verify token (single decode)
    payload = await verify_jwt_token(token)

    # Cache in request.state for reuse across middleware
    if request is not None and hasattr(request, "state"):
        request.state._jwt_verified_payload = (token, payload)

    return payload


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
        >>> from pydantic import SecretStr
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     jwt_audience = 'mcpgateway-api'
        ...     jwt_issuer = 'mcpgateway'
        ...     jwt_audience_verification = True
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = SecretStr('pass')
        ...     auth_required = True
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> import jwt
        >>> token = jwt.encode({'sub': 'alice', 'aud': 'mcpgateway-api', 'iss': 'mcpgateway'}, 'secret', algorithm='HS256')
        >>> import asyncio
        >>> payload = asyncio.run(vc.verify_credentials(token))
        >>> payload['token'] == token
        True
    """
    payload = await verify_jwt_token(token)
    payload["token"] = token
    return payload


async def verify_credentials_cached(token: str, request: Optional[Request] = None) -> dict:
    """Verify credentials using a JWT token with request-level caching.

    A wrapper around verify_jwt_token_cached that adds the original token
    to the decoded payload for reference.

    Args:
        token: The JWT token string to verify.
        request: Optional FastAPI/Starlette request for request-level caching.

    Returns:
        dict: The validated token payload with the original token added
            under the 'token' key. Returns a copy to avoid mutating cached payload.
    """
    payload = await verify_jwt_token_cached(token, request)
    # Return a copy with token added to avoid mutating the cached payload
    return {**payload, "token": token}


async def require_auth(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security), jwt_token: Optional[str] = Cookie(default=None)) -> str | dict:
    """Require authentication via JWT token or proxy headers.

    FastAPI dependency that checks for authentication via:
    1. Proxy headers (if mcp_client_auth_enabled=false and trust_proxy_auth=true)
    2. JWT token in Authorization header (Bearer scheme)
    3. JWT token in cookies

    If authentication is required but no token is provided, raises an HTTP 401 error.

    Args:
        request: The FastAPI request object for accessing headers.
        credentials: HTTP Authorization credentials from the request header.
        jwt_token: JWT token from cookies.

    Returns:
        str | dict: The verified credentials payload if authenticated,
            proxy user if proxy auth enabled, or "anonymous" if authentication is not required.

    Raises:
        HTTPException: 401 status if authentication is required but no valid
            token is provided.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> from pydantic import SecretStr
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     jwt_audience = 'mcpgateway-api'
        ...     jwt_issuer = 'mcpgateway'
        ...     jwt_audience_verification = True
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = SecretStr('pass')
        ...     auth_required = True
        ...     mcp_client_auth_enabled = True
        ...     trust_proxy_auth = False
        ...     proxy_user_header = 'X-Authenticated-User'
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> import jwt
        >>> from fastapi.security import HTTPAuthorizationCredentials
        >>> from fastapi import Request
        >>> import asyncio

        Test with valid credentials in header:
        >>> token = jwt.encode({'sub': 'alice', 'aud': 'mcpgateway-api', 'iss': 'mcpgateway'}, 'secret', algorithm='HS256')
        >>> creds = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
        >>> req = Request(scope={'type': 'http', 'headers': []})
        >>> result = asyncio.run(vc.require_auth(request=req, credentials=creds, jwt_token=None))
        >>> result['sub'] == 'alice'
        True

        Test with valid token in cookie:
        >>> result = asyncio.run(vc.require_auth(request=req, credentials=None, jwt_token=token))
        >>> result['sub'] == 'alice'
        True

        Test with auth required but no token:
        >>> try:
        ...     asyncio.run(vc.require_auth(request=req, credentials=None, jwt_token=None))
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Not authenticated

        Test with auth not required:
        >>> vc.settings.auth_required = False
        >>> result = asyncio.run(vc.require_auth(request=req, credentials=None, jwt_token=None))
        >>> result
        'anonymous'
        >>> vc.settings.auth_required = True
    """
    # If MCP client auth is disabled and proxy auth is trusted, use proxy headers
    if not settings.mcp_client_auth_enabled:
        if settings.trust_proxy_auth:
            # Extract user from proxy header
            proxy_user = request.headers.get(settings.proxy_user_header)
            if proxy_user:
                return {"sub": proxy_user, "source": "proxy", "token": None}
            # If no proxy header but proxy auth is trusted, treat as anonymous
            return "anonymous"
        else:
            # Warning: MCP auth disabled without proxy trust - security risk!
            # This case is already warned about in config validation
            return "anonymous"

    # Standard JWT authentication flow - prioritize manual cookie reading
    token = None

    # 1. First try manual cookie reading (most reliable)
    if hasattr(request, "cookies") and request.cookies:
        manual_token = request.cookies.get("jwt_token")
        if manual_token:
            token = manual_token

    # 2. Then try Authorization header
    if not token and credentials and credentials.credentials:
        token = credentials.credentials

    # 3. Finally try FastAPI Cookie dependency (fallback)
    if not token and jwt_token:
        token = jwt_token

    if settings.auth_required and not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await verify_credentials_cached(token, request) if token else "anonymous"


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
        >>> from pydantic import SecretStr
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     jwt_audience = 'mcpgateway-api'
        ...     jwt_issuer = 'mcpgateway'
        ...     jwt_audience_verification = True
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = SecretStr('pass')
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
    is_valid_pass = credentials.password == settings.basic_auth_password.get_secret_value()

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
        >>> from pydantic import SecretStr
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     jwt_audience = 'mcpgateway-api'
        ...     jwt_issuer = 'mcpgateway'
        ...     jwt_audience_verification = True
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = SecretStr('pass')
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

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> from pydantic import SecretStr
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     jwt_audience = 'mcpgateway-api'
        ...     jwt_issuer = 'mcpgateway'
        ...     jwt_audience_verification = True
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = SecretStr('pass')
        ...     auth_required = True
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = True
        >>> vc.settings = DummySettings()
        >>> import base64, asyncio

        Test with properly encoded credentials:
        >>> userpass = base64.b64encode(b'user:pass').decode()
        >>> auth_header = f'Basic {userpass}'
        >>> asyncio.run(vc.require_docs_basic_auth(auth_header))
        'user'

        Test with different valid credentials:
        >>> valid_creds = base64.b64encode(b'user:pass').decode()
        >>> valid_header = f'Basic {valid_creds}'
        >>> result = asyncio.run(vc.require_docs_basic_auth(valid_header))
        >>> result == 'user'
        True

        Test with invalid password:
        >>> badpass = base64.b64encode(b'user:wrong').decode()
        >>> bad_header = f'Basic {badpass}'
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(bad_header))
        ... except vc.HTTPException as e:
        ...     e.status_code == 401
        True

        Test with malformed base64 (no colon):
        >>> malformed = base64.b64encode(b'userpass').decode()
        >>> malformed_header = f'Basic {malformed}'
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(malformed_header))
        ... except vc.HTTPException as e:
        ...     e.status_code == 401
        True

        Test with invalid base64 encoding:
        >>> invalid_header = 'Basic invalid_base64!'
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(invalid_header))
        ... except vc.HTTPException as e:
        ...     'Invalid basic auth credentials' in e.detail
        True

        Test when docs_allow_basic_auth is disabled:
        >>> vc.settings.docs_allow_basic_auth = False
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(auth_header))
        ... except vc.HTTPException as e:
        ...     'not allowed' in e.detail
        True
        >>> vc.settings.docs_allow_basic_auth = True

        Test with non-Basic auth scheme:
        >>> bearer_header = 'Bearer eyJhbGciOiJIUzI1NiJ9...'
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(bearer_header))
        ... except vc.HTTPException as e:
        ...     e.status_code == 401
        True

        Test with empty credentials part:
        >>> empty_header = 'Basic '
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(empty_header))
        ... except vc.HTTPException as e:
        ...     'not allowed' in e.detail
        True

        Test with Unicode decode error:
        >>> from base64 import b64encode
        >>> bad_bytes = bytes([0xff, 0xfe])  # Invalid UTF-8 bytes
        >>> bad_unicode = b64encode(bad_bytes).decode()
        >>> unicode_header = f'Basic {bad_unicode}'
        >>> try:
        ...     asyncio.run(vc.require_docs_basic_auth(unicode_header))
        ... except vc.HTTPException as e:
        ...     'Invalid basic auth credentials' in e.detail
        True
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


async def require_docs_auth_override(
    auth_header: str | None = None,
    jwt_token: str | None = None,
) -> str | dict:
    """Require authentication for docs endpoints, bypassing global auth settings.

    This function specifically validates JWT tokens for documentation endpoints
    (/docs, /redoc, /openapi.json) regardless of global authentication settings
    like mcp_client_auth_enabled or auth_required.

    Args:
        auth_header: Raw Authorization header value (e.g. "Bearer eyJhbGciOi...").
        jwt_token: JWT token from cookies.

    Returns:
        str | dict: The decoded JWT payload.

    Raises:
        HTTPException: If authentication fails or credentials are invalid.

    Examples:
        >>> from mcpgateway.utils import verify_credentials as vc
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     jwt_audience = 'mcpgateway-api'
        ...     jwt_issuer = 'mcpgateway'
        ...     jwt_audience_verification = True
        ...     docs_allow_basic_auth = False
        ...     require_token_expiration = False
        >>> vc.settings = DummySettings()
        >>> import jwt
        >>> import asyncio

        Test with valid JWT:
        >>> token = jwt.encode({'sub': 'alice', 'aud': 'mcpgateway-api', 'iss': 'mcpgateway'}, 'secret', algorithm='HS256')
        >>> auth_header = f'Bearer {token}'
        >>> result = asyncio.run(vc.require_docs_auth_override(auth_header=auth_header))
        >>> result['sub'] == 'alice'
        True

        Test with no token:
        >>> try:
        ...     asyncio.run(vc.require_docs_auth_override())
        ... except vc.HTTPException as e:
        ...     print(e.status_code, e.detail)
        401 Not authenticated
    """
    # Extract token from header or cookie
    token = jwt_token
    if auth_header:
        scheme, param = get_authorization_scheme_param(auth_header)
        if scheme.lower() == "bearer" and param:
            token = param
        elif scheme.lower() == "basic" and param and settings.docs_allow_basic_auth:
            # Only allow Basic Auth for docs endpoints when explicitly enabled
            return await require_docs_basic_auth(auth_header)

    # Always require a token for docs endpoints
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate the JWT token
    return await verify_credentials(token)


async def require_auth_override(
    auth_header: str | None = None,
    jwt_token: str | None = None,
    request: Request | None = None,
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
        request: Optional Request object for accessing headers (used for proxy auth).

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
        >>> from pydantic import SecretStr
        >>> class DummySettings:
        ...     jwt_secret_key = 'secret'
        ...     jwt_algorithm = 'HS256'
        ...     jwt_audience = 'mcpgateway-api'
        ...     jwt_issuer = 'mcpgateway'
        ...     jwt_audience_verification = True
        ...     basic_auth_user = 'user'
        ...     basic_auth_password = SecretStr('pass')
        ...     auth_required = True
        ...     mcp_client_auth_enabled = True
        ...     trust_proxy_auth = False
        ...     proxy_user_header = 'X-Authenticated-User'
        ...     require_token_expiration = False
        ...     docs_allow_basic_auth = False
        >>> vc.settings = DummySettings()
        >>> import jwt
        >>> import asyncio

        Test with Bearer token in auth header:
        >>> token = jwt.encode({'sub': 'alice', 'aud': 'mcpgateway-api', 'iss': 'mcpgateway'}, 'secret', algorithm='HS256')
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
    # Create a mock request if not provided (for backward compatibility)
    if request is None:
        request = Request(scope={"type": "http", "headers": []})

    credentials = None
    if auth_header:
        scheme, param = get_authorization_scheme_param(auth_header)
        if scheme.lower() == "bearer" and param:
            credentials = HTTPAuthorizationCredentials(scheme=scheme, credentials=param)
        elif scheme.lower() == "basic" and param and settings.docs_allow_basic_auth:
            # Only allow Basic Auth for docs endpoints when explicitly enabled
            return await require_docs_basic_auth(auth_header)
    return await require_auth(request=request, credentials=credentials, jwt_token=jwt_token)


async def require_admin_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    jwt_token: Optional[str] = Cookie(None, alias="jwt_token"),
    basic_credentials: Optional[HTTPBasicCredentials] = Depends(basic_security),
) -> str:
    """Require admin authentication supporting both email auth and basic auth.

    This dependency supports multiple authentication methods:
    1. Email-based JWT authentication (when EMAIL_AUTH_ENABLED=true)
    2. Basic authentication (legacy support)
    3. Proxy headers (if configured)

    For email auth, the user must have is_admin=true.
    For basic auth, uses the configured BASIC_AUTH_USER/PASSWORD.

    Args:
        request: FastAPI request object
        credentials: HTTP Authorization credentials
        jwt_token: JWT token from cookies
        basic_credentials: HTTP Basic auth credentials

    Returns:
        str: Username/email of authenticated admin user

    Raises:
        HTTPException: 401 if authentication fails, 403 if user is not admin
        RedirectResponse: Redirect to login page for browser requests

    Examples:
        >>> # This function is typically used as a FastAPI dependency
        >>> callable(require_admin_auth)
        True
    """
    # First-Party
    from mcpgateway.config import settings

    # Try email authentication first if enabled
    if getattr(settings, "email_auth_enabled", False):
        try:
            # First-Party
            from mcpgateway.db import get_db
            from mcpgateway.services.email_auth_service import EmailAuthService

            token = jwt_token
            if not token and credentials:
                token = credentials.credentials

            if token:
                db_session = next(get_db())
                try:
                    # Decode and verify JWT token (use cached version for performance)
                    payload = await verify_jwt_token_cached(token, request)
                    username = payload.get("sub") or payload.get("username")  # Support both new and legacy formats

                    if username:
                        # Get user from database
                        auth_service = EmailAuthService(db_session)
                        current_user = await auth_service.get_user_by_email(username)

                        if current_user and current_user.is_admin:
                            return current_user.email
                        elif current_user:
                            # User is authenticated but not admin - check if this is a browser request
                            accept_header = request.headers.get("accept", "")
                            if "text/html" in accept_header:
                                # Redirect browser to login page with error
                                root_path = request.scope.get("root_path", "")
                                raise HTTPException(status_code=status.HTTP_302_FOUND, detail="Admin privileges required", headers={"Location": f"{root_path}/admin/login?error=admin_required"})
                            else:
                                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
                        else:
                            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
                except Exception:
                    raise Exception
                finally:
                    db_session.close()
        except HTTPException as e:
            # Re-raise HTTP exceptions (403, redirects, etc.)
            if e.status_code != status.HTTP_401_UNAUTHORIZED:
                raise
            # For 401, check if we should redirect browser users
            accept_header = request.headers.get("accept", "")
            if "text/html" in accept_header:
                root_path = request.scope.get("root_path", "")
                raise HTTPException(status_code=status.HTTP_302_FOUND, detail="Authentication required", headers={"Location": f"{root_path}/admin/login"})
            # If JWT auth fails, fall back to basic auth for backward compatibility
        except Exception:
            # If there's any other error with email auth, fall back to basic auth
            pass  # nosec B110 - Intentional fallback to basic auth on any email auth error

    # Fall back to basic authentication
    try:
        if basic_credentials:
            return await verify_basic_credentials(basic_credentials)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No basic auth credentials provided",
                headers={"WWW-Authenticate": "Basic"},
            )
    except HTTPException:
        # If both methods fail, check if we should redirect browser users to login page
        if getattr(settings, "email_auth_enabled", False):
            accept_header = request.headers.get("accept", "")
            is_htmx = request.headers.get("hx-request") == "true"
            if "text/html" in accept_header or is_htmx:
                root_path = request.scope.get("root_path", "")
                raise HTTPException(status_code=status.HTTP_302_FOUND, detail="Authentication required", headers={"Location": f"{root_path}/admin/login"})
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required. Please login with email/password or use basic auth.", headers={"WWW-Authenticate": "Bearer"}
                )
        else:
            # Re-raise the basic auth error
            raise
