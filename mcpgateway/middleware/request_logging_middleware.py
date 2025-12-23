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
"""

# Standard
import json
import logging
import time
from typing import Callable

# Third-Party
from fastapi.security import HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.utils.correlation_id import get_correlation_id

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize structured logger for gateway boundary logging
structured_logger = get_structured_logger("http_gateway")

SENSITIVE_KEYS = {"password", "secret", "token", "apikey", "access_token", "refresh_token", "client_secret", "authorization", "jwt_token"}


def mask_sensitive_data(data):
    """Recursively mask sensitive keys in dict/list payloads.

    Args:
        data: The data structure to mask (dict, list, or other)

    Returns:
        The data structure with sensitive values masked
    """
    if isinstance(data, dict):
        return {k: ("******" if k.lower() in SENSITIVE_KEYS else mask_sensitive_data(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_sensitive_data(i) for i in data]
    return data


def mask_jwt_in_cookies(cookie_header):
    """Mask JWT tokens in cookie header while preserving other cookies.

    Args:
        cookie_header: The cookie header string to process

    Returns:
        Cookie header string with JWT tokens masked
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
    """

    def __init__(
        self,
        app,
        enable_gateway_logging: bool = True,
        log_detailed_requests: bool = False,
        log_level: str = "DEBUG",
        max_body_size: int = 4096,
        log_request_start: bool = False,
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
        """
        super().__init__(app)
        self.enable_gateway_logging = enable_gateway_logging
        self.log_detailed_requests = log_detailed_requests
        self.log_level = log_level.upper()
        self.max_body_size = max_body_size  # Expected to be in bytes
        self.log_request_start = log_request_start

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

        # Get correlation ID and request metadata for boundary logging
        correlation_id = get_correlation_id()
        path = request.url.path
        method = request.method
        user_agent = request.headers.get("user-agent", "unknown")
        client_ip = request.client.host if request.client else "unknown"
        user_id, user_email = await self._resolve_user_identity(request)

        # Skip boundary logging for health checks and static assets
        skip_paths = ["/health", "/healthz", "/static", "/favicon.ico"]
        should_log_boundary = self.enable_gateway_logging and not any(path.startswith(skip_path) for skip_path in skip_paths)

        # Log gateway request started (optional - disabled by default for performance)
        if should_log_boundary and self.log_request_start:
            try:
                structured_logger.log(
                    level="INFO",
                    message=f"Request started: {method} {path}",
                    component="http_gateway",
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

        # Skip detailed logging if disabled
        if not self.log_detailed_requests:
            response = await call_next(request)

            # Still log request completed even if detailed logging is disabled
            if should_log_boundary:
                duration_ms = (time.time() - start_time) * 1000
                try:
                    log_level = "ERROR" if response.status_code >= 500 else "WARNING" if response.status_code >= 400 else "INFO"
                    structured_logger.log(
                        level=log_level,
                        message=f"Request completed: {method} {path} - {response.status_code}",
                        component="http_gateway",
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
                    json_payload = json.loads(payload)
                    payload_to_log = mask_sensitive_data(json_payload)
                    payload_str = json.dumps(payload_to_log, indent=2)
                except json.JSONDecodeError:
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
                        component="gateway",
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
                    component="gateway",
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
