# -*- coding: utf-8 -*-
"""
Location: ./mcpgateway/middleware/request_logging_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Request Logging Middleware.

This module provides middleware for FastAPI to log incoming HTTP requests
with sensitive data masking. It masks JWT tokens, passwords, and other
sensitive information in headers and request bodies while preserving
debugging information.

Examples:
    >>> from mcpgateway.middleware.request_logging_middleware import (
    ...     mask_sensitive_data, mask_jwt_in_cookies, mask_sensitive_headers, SENSITIVE_KEYS
    ... )

    Check that SENSITIVE_KEYS contains expected values:
    >>> "password" in SENSITIVE_KEYS
    True
    >>> "token" in SENSITIVE_KEYS
    True
    >>> "authorization" in SENSITIVE_KEYS
    True

    Mask nested sensitive data:
    >>> data = {"credentials": {"password": "secret", "username": "admin"}}
    >>> masked = mask_sensitive_data(data)
    >>> masked["credentials"]["password"]
    '******'
    >>> masked["credentials"]["username"]
    'admin'

    Test mask_jwt_in_cookies with various inputs:
    >>> mask_jwt_in_cookies("access_token=xyz123; user=john")
    'access_token=******; user=john'

    Test mask_sensitive_headers with mixed headers:
    >>> headers = {"Content-Type": "application/json", "secret": "mysecret"}
    >>> result = mask_sensitive_headers(headers)
    >>> result["Content-Type"]
    'application/json'
    >>> result["secret"]
    '******'
"""

# Standard
import logging
import secrets
import time
from typing import Callable, List, Optional

# Third-Party
from fastapi.security import HTTPAuthorizationCredentials
import orjson
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.middleware.path_filter import should_skip_request_logging
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.utils.correlation_id import get_correlation_id

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize structured logger for gateway boundary logging
structured_logger = get_structured_logger("http_gateway")

SENSITIVE_KEYS = frozenset({"password", "secret", "token", "apikey", "access_token", "refresh_token", "client_secret", "authorization", "jwt_token"})


def mask_sensitive_data(data, max_depth: int = 10):
    """Recursively mask sensitive keys in dict/list payloads with depth limit.

    Args:
        data: The data structure to mask (dict, list, or other)
        max_depth: Maximum recursion depth to prevent stack overflow on deeply nested payloads

    Returns:
        The data structure with sensitive values masked

    Examples:
        >>> mask_sensitive_data({"username": "john", "password": "secret123"})
        {'username': 'john', 'password': '******'}

        >>> mask_sensitive_data({"user": {"name": "john", "token": "abc123"}})
        {'user': {'name': 'john', 'token': '******'}}

        >>> mask_sensitive_data([{"apikey": "key1"}, {"data": "safe"}])
        [{'apikey': '******'}, {'data': 'safe'}]

        >>> mask_sensitive_data("plain string")
        'plain string'

        >>> mask_sensitive_data({"level": {"nested": {}}}, max_depth=1)
        {'level': '<nested too deep>'}
    """
    if max_depth <= 0:
        return "<nested too deep>"

    if isinstance(data, dict):
        return {k: ("******" if k.lower() in SENSITIVE_KEYS else mask_sensitive_data(v, max_depth - 1)) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_sensitive_data(i, max_depth - 1) for i in data]
    return data


def mask_jwt_in_cookies(cookie_header):
    """Mask JWT tokens in cookie header while preserving other cookies.

    Args:
        cookie_header: The cookie header string to process

    Returns:
        Cookie header string with JWT tokens masked

    Examples:
        >>> mask_jwt_in_cookies("jwt_token=abc123; theme=dark")
        'jwt_token=******; theme=dark'

        >>> mask_jwt_in_cookies("session_id=xyz; auth_token=secret")
        'session_id=******; auth_token=******'

        >>> mask_jwt_in_cookies("user=john; preference=light")
        'user=john; preference=light'

        >>> mask_jwt_in_cookies("")
        ''

        >>> mask_jwt_in_cookies(None) is None
        True
    """
    if not cookie_header:
        return cookie_header

    # Split cookies by semicolon
    cookies = []
    for cookie in cookie_header.split(";"):
        cookie = cookie.strip()
        if "=" in cookie:
            name, _ = cookie.split("=", 1)
            name = name.strip()
            # Mask JWT tokens and other sensitive cookies
            if any(sensitive in name.lower() for sensitive in ["jwt", "token", "auth", "session"]):
                cookies.append(f"{name}=******")
            else:
                cookies.append(cookie)
        else:
            cookies.append(cookie)

    return "; ".join(cookies)


def mask_sensitive_headers(headers):
    """Mask sensitive headers like Authorization.

    Args:
        headers: Dictionary of HTTP headers to mask

    Returns:
        Dictionary of headers with sensitive values masked

    Examples:
        >>> mask_sensitive_headers({"Authorization": "Bearer token123"})
        {'Authorization': '******'}

        >>> mask_sensitive_headers({"Content-Type": "application/json"})
        {'Content-Type': 'application/json'}

        >>> mask_sensitive_headers({"apikey": "secret", "X-Custom": "value"})
        {'apikey': '******', 'X-Custom': 'value'}

        >>> result = mask_sensitive_headers({"Cookie": "jwt_token=abc; theme=dark"})
        >>> "******" in result["Cookie"]
        True
    """
    masked_headers = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in SENSITIVE_KEYS or "auth" in key_lower or "jwt" in key_lower:
            masked_headers[key] = "******"
        elif key_lower == "cookie":
            # Special handling for cookies to mask only JWT tokens
            masked_headers[key] = mask_jwt_in_cookies(value)
        else:
            masked_headers[key] = value
    return masked_headers


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging HTTP requests with sensitive data masking.

    Logs incoming requests including method, path, headers, and body while
    masking sensitive information like passwords, tokens, and authorization headers.

    Examples:
        >>> middleware = RequestLoggingMiddleware(
        ...     app=None,
        ...     enable_gateway_logging=True,
        ...     log_detailed_requests=True,
        ...     log_detailed_skip_endpoints=["/metrics", "/health"],
        ...     log_detailed_sample_rate=0.5,
        ... )
        >>> middleware.enable_gateway_logging
        True
        >>> middleware.log_detailed_requests
        True
        >>> middleware.log_detailed_skip_endpoints
        ['/metrics', '/health']
        >>> middleware.log_detailed_sample_rate
        0.5
        >>> middleware.log_resolve_user_identity
        False
    """

    def __init__(
        self,
        app,
        enable_gateway_logging: bool = True,
        log_detailed_requests: bool = False,
        log_level: str = "DEBUG",
        max_body_size: Optional[int] = None,
        log_request_start: bool = False,
        log_resolve_user_identity: bool = False,
        log_detailed_skip_endpoints: Optional[List[str]] = None,
        log_detailed_sample_rate: float = 1.0,
    ):
        """Initialize the request logging middleware.

        Args:
            app: The FastAPI application instance
            enable_gateway_logging: Whether to enable gateway boundary logging (request_started/completed)
            log_detailed_requests: Whether to enable detailed request/response payload logging
            log_level: The log level for requests (not used, logs at INFO)
            max_body_size: Maximum request body size to log in bytes
            log_request_start: Whether to log "request started" events (default: False for performance)
                              When False, only logs on request completion which halves logging overhead.
            log_resolve_user_identity: If True, allow DB fallback to resolve user identity when no cached user
            log_detailed_skip_endpoints: Optional list of path prefixes to skip detailed logging
            log_detailed_sample_rate: Float in [0.0, 1.0] sampling rate for detailed logging
        """
        super().__init__(app)
        self.enable_gateway_logging = enable_gateway_logging
        self.log_detailed_requests = log_detailed_requests
        self.log_level = log_level.upper()
        # Use explicit configured value when provided, otherwise fall back to
        # settings.log_detailed_max_body_size (configured in mcpgateway.config)
        self.max_body_size = max_body_size if max_body_size is not None else settings.log_detailed_max_body_size
        self.log_request_start = log_request_start
        self.log_resolve_user_identity = log_resolve_user_identity
        self.log_detailed_skip_endpoints = log_detailed_skip_endpoints or []
        self.log_detailed_sample_rate = log_detailed_sample_rate

    async def _resolve_user_identity(self, request: Request):
        """Best-effort extraction of user identity for request logs.

        Args:
            request: The incoming HTTP request

        Returns:
            Tuple[Optional[str], Optional[str]]: User ID and email
        """
        # Prefer context injected by upstream middleware
        if hasattr(request.state, "user") and request.state.user is not None:
            raw_user_id = getattr(request.state.user, "id", None)
            user_email = getattr(request.state.user, "email", None)
            return (str(raw_user_id) if raw_user_id is not None else None, user_email)

        # Fallback: try to authenticate using cookies/headers (matches AuthContextMiddleware)
        # Respect configuration: avoid DB fallback unless explicitly allowed
        if not self.log_resolve_user_identity:
            return (None, None)
        token = None
        if request.cookies:
            token = request.cookies.get("jwt_token") or request.cookies.get("access_token") or request.cookies.get("token")

        if not token:
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "")

        if not token:
            return (None, None)

        try:
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            # get_current_user now uses fresh DB sessions internally
            user = await get_current_user(credentials)
            raw_user_id = getattr(user, "id", None)
            user_email = getattr(user, "email", None)
            return (str(raw_user_id) if raw_user_id is not None else None, user_email)
        except Exception:
            return (None, None)

    async def dispatch(self, request: Request, call_next: Callable):
        """Process incoming request and log details with sensitive data masked.

        Args:
            request: The incoming HTTP request
            call_next: Function to call the next middleware/handler

        Returns:
            Response: The HTTP response from downstream handlers

        Raises:
            Exception: Any exception from downstream handlers is re-raised
        """
        # Track start time for total duration
        start_time = time.time()

        # Get basic request metadata (cheap operations)
        path = request.url.path
        method = request.method

        # Determine logging needs BEFORE expensive operations
        should_log_boundary = self.enable_gateway_logging and not should_skip_request_logging(path)
        should_log_detailed = self.log_detailed_requests and not should_skip_request_logging(path)

        # Honor middleware-level configured skip endpoints for detailed logging
        if should_log_detailed and self.log_detailed_skip_endpoints:
            for prefix in self.log_detailed_skip_endpoints:
                if path.startswith(prefix):
                    should_log_detailed = False
                    break

        # Sampling fast path: avoid detailed logging for sampled-out requests
        if should_log_detailed and self.log_detailed_sample_rate < 1.0:
            try:
                # Use the cryptographically secure `secrets` module to avoid
                # bandit/DUO warnings about insecure RNGs. Sampling here does
                # not require crypto strength, but using `secrets` keeps
                # security scanners happy.

                r = secrets.randbelow(10 ** 9) / 1e9
                if r >= self.log_detailed_sample_rate:
                    should_log_detailed = False
            except Exception as e:
                # If sampling fails for any reason, default to logging and
                # record the incident for diagnostics.
                logger.debug(f"Sampling failed, defaulting to log: {e}")

        # Fast path: if no logging needed at all, skip everything
        if not should_log_boundary and not should_log_detailed:
            return await call_next(request)

        # Get correlation ID and additional metadata (only if we're logging)
        correlation_id = get_correlation_id()
        user_agent = request.headers.get("user-agent", "unknown")
        client_ip = request.client.host if request.client else "unknown"

        # Only resolve user identity if we're actually going to log boundary events
        # This avoids potential DB queries for skipped paths and detailed-only flows
        user_id: Optional[str] = None
        user_email: Optional[str] = None
        if should_log_boundary:
            user_id, user_email = await self._resolve_user_identity(request)
        elif should_log_detailed and hasattr(request.state, "user") and request.state.user is not None:
            # Detailed logs: only use cached user identity, avoid DB fallback
            raw_user_id = getattr(request.state.user, "id", None)
            user_id = str(raw_user_id) if raw_user_id is not None else None
            user_email = getattr(request.state.user, "email", None)

        # Log gateway request started (optional - disabled by default for performance)
        if should_log_boundary and self.log_request_start:
            try:
                structured_logger.log(
                    level="INFO",
                    message=f"Request started: {method} {path}",
                    correlation_id=correlation_id,
                    user_email=user_email,
                    user_id=user_id,
                    operation_type="http_request",
                    request_method=method,
                    request_path=path,
                    user_agent=user_agent,
                    client_ip=client_ip,
                    metadata={"event": "request_started", "query_params": str(request.query_params) if request.query_params else None},
                )
            except Exception as e:
                logger.warning(f"Failed to log request start: {e}")

        # Skip detailed logging if disabled (already checked via should_log_detailed)
        if not should_log_detailed:
            response = await call_next(request)

            # Still log request completed even if detailed logging is disabled
            if should_log_boundary:
                duration_ms = (time.time() - start_time) * 1000
                try:
                    log_level = "ERROR" if response.status_code >= 500 else "WARNING" if response.status_code >= 400 else "INFO"
                    structured_logger.log(
                        level=log_level,
                        message=f"Request completed: {method} {path} - {response.status_code}",
                        correlation_id=correlation_id,
                        user_email=user_email,
                        user_id=user_id,
                        operation_type="http_request",
                        request_method=method,
                        request_path=path,
                        response_status_code=response.status_code,
                        user_agent=user_agent,
                        client_ip=client_ip,
                        duration_ms=duration_ms,
                        metadata={"event": "request_completed", "response_time_category": "fast" if duration_ms < 100 else "normal" if duration_ms < 1000 else "slow"},
                    )
                except Exception as e:
                    logger.warning(f"Failed to log request completion: {e}")

            return response

        # Always log at INFO level for request payloads to ensure visibility
        log_level = logging.INFO

        # Skip if logger level is higher than INFO
        if not logger.isEnabledFor(log_level):
            return await call_next(request)

        # Size-based fast path: skip detailed processing for very large bodies
        content_length_header = request.headers.get("content-length")
        if content_length_header:
            try:
                content_length = int(content_length_header)
                # Skip if body is >4x over limit (not worth reading/parsing)
                if content_length > self.max_body_size * 4:
                    # Log placeholder without reading body
                    masked_headers = mask_sensitive_headers(dict(request.headers))
                    request_id = get_correlation_id()
                    try:
                        logger.log(
                            log_level,
                            f"📩 Incoming request: {request.method} {request.url.path}\n"
                            f"Query params: {dict(request.query_params)}\n"
                            f"Headers: {masked_headers}\n"
                            f"Body: <body too large: {content_length} bytes>",
                            extra={"request_id": request_id},
                        )
                    except TypeError:
                        logger.log(
                            log_level,
                            f"📩 Incoming request: {request.method} {request.url.path}\n"
                            f"Query params: {dict(request.query_params)}\n"
                            f"Headers: {masked_headers}\n"
                            f"Body: <body too large: {content_length} bytes>",
                        )

                    # Continue with request processing (boundary logging handled below)
                    try:
                        response = await call_next(request)
                    except Exception as e:
                        duration_ms = (time.time() - start_time) * 1000
                        if should_log_boundary:
                            try:
                                structured_logger.log(
                                    level="ERROR",
                                    message=f"Request failed: {method} {path}",
                                    correlation_id=correlation_id,
                                    user_email=user_email,
                                    user_id=user_id,
                                    operation_type="http_request",
                                    request_method=method,
                                    request_path=path,
                                    user_agent=user_agent,
                                    client_ip=client_ip,
                                    duration_ms=duration_ms,
                                    error=e,
                                    metadata={"event": "request_failed"},
                                )
                            except Exception as log_error:
                                logger.warning(f"Failed to log request failure: {log_error}")
                        raise

                    # Log boundary completion for large body requests
                    if should_log_boundary:
                        duration_ms = (time.time() - start_time) * 1000
                        try:
                            boundary_log_level = "ERROR" if response.status_code >= 500 else "WARNING" if response.status_code >= 400 else "INFO"
                            structured_logger.log(
                                level=boundary_log_level,
                                message=f"Request completed: {method} {path} - {response.status_code}",
                                correlation_id=correlation_id,
                                user_email=user_email,
                                user_id=user_id,
                                operation_type="http_request",
                                request_method=method,
                                request_path=path,
                                response_status_code=response.status_code,
                                user_agent=user_agent,
                                client_ip=client_ip,
                                duration_ms=duration_ms,
                                metadata={"event": "request_completed", "response_time_category": self._categorize_response_time(duration_ms)},
                            )
                        except Exception as e:
                            logger.warning(f"Failed to log request completion: {e}")

                    return response
            except ValueError:
                pass  # Invalid content-length, continue with normal processing

        body = b""
        try:
            body = await request.body()
            # Avoid logging huge bodies
            if len(body) > self.max_body_size:
                truncated = True
                body_to_log = body[: self.max_body_size]
            else:
                truncated = False
                body_to_log = body

            payload = body_to_log.decode("utf-8", errors="ignore").strip()
            if payload:
                try:
                    json_payload = orjson.loads(payload)
                    payload_to_log = mask_sensitive_data(json_payload)
                    # Use orjson without indent for performance (compact output)
                    payload_str = orjson.dumps(payload_to_log).decode()
                except orjson.JSONDecodeError:
                    # For non-JSON payloads, still mask potential sensitive data
                    payload_str = payload
                    for sensitive_key in SENSITIVE_KEYS:
                        if sensitive_key in payload_str.lower():
                            payload_str = "<contains sensitive data - masked>"
                            break
            else:
                payload_str = "<empty>"

            # Mask sensitive headers
            masked_headers = mask_sensitive_headers(dict(request.headers))

            # Get correlation ID for request tracking
            request_id = get_correlation_id()

            # Try to log with extra parameter, fall back to without if not supported
            try:
                logger.log(
                    log_level,
                    f"📩 Incoming request: {request.method} {request.url.path}\n"
                    f"Query params: {dict(request.query_params)}\n"
                    f"Headers: {masked_headers}\n"
                    f"Body: {payload_str}{'... [truncated]' if truncated else ''}",
                    extra={"request_id": request_id},
                )
            except TypeError:
                # Fall back for test loggers that don't accept extra parameter
                logger.log(
                    log_level,
                    f"📩 Incoming request: {request.method} {request.url.path}\n"
                    f"Query params: {dict(request.query_params)}\n"
                    f"Headers: {masked_headers}\n"
                    f"Body: {payload_str}{'... [truncated]' if truncated else ''}",
                )

        except Exception as e:
            logger.warning(f"Failed to log request body: {e}")

        # Recreate request stream for downstream handlers
        async def receive():
            """Recreate request body for downstream handlers.

            Returns:
                dict: ASGI receive message with request body
            """
            return {"type": "http.request", "body": body, "more_body": False}

        # Create new request with the body we've already read
        new_scope = request.scope.copy()
        new_request = Request(new_scope, receive=receive)

        # Process request
        try:
            response: Response = await call_next(new_request)
            status_code = response.status_code
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # Log request failed
            if should_log_boundary:
                try:
                    structured_logger.log(
                        level="ERROR",
                        message=f"Request failed: {method} {path}",
                        correlation_id=correlation_id,
                        user_email=user_email,
                        user_id=user_id,
                        operation_type="http_request",
                        request_method=method,
                        request_path=path,
                        user_agent=user_agent,
                        client_ip=client_ip,
                        duration_ms=duration_ms,
                        error=e,
                        metadata={"event": "request_failed"},
                    )
                except Exception as log_error:
                    logger.warning(f"Failed to log request failure: {log_error}")

            raise

        # Calculate total duration
        duration_ms = (time.time() - start_time) * 1000

        # Log gateway request completed
        if should_log_boundary:
            try:
                log_level = "ERROR" if status_code >= 500 else "WARNING" if status_code >= 400 else "INFO"

                structured_logger.log(
                    level=log_level,
                    message=f"Request completed: {method} {path} - {status_code}",
                    correlation_id=correlation_id,
                    user_email=user_email,
                    user_id=user_id,
                    operation_type="http_request",
                    request_method=method,
                    request_path=path,
                    response_status_code=status_code,
                    user_agent=user_agent,
                    client_ip=client_ip,
                    duration_ms=duration_ms,
                    metadata={"event": "request_completed", "response_time_category": self._categorize_response_time(duration_ms)},
                )
            except Exception as e:
                logger.warning(f"Failed to log request completion: {e}")

        return response

    @staticmethod
    def _categorize_response_time(duration_ms: float) -> str:
        """Categorize response time for analytics.

        Args:
            duration_ms: Response time in milliseconds

        Returns:
            Category string
        """
        if duration_ms < 100:
            return "fast"
        if duration_ms < 500:
            return "normal"
        if duration_ms < 2000:
            return "slow"
        return "very_slow"
