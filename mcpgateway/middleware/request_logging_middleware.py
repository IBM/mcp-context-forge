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
from typing import Callable

# Third-Party
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

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

    def __init__(self, app, log_requests: bool = True, log_level: str = "DEBUG", max_body_size: int = 4096):
        """Initialize the request logging middleware.

        Args:
            app: The FastAPI application instance
            log_requests: Whether to enable request logging
            log_level: The log level for requests (not used, logs at INFO)
            max_body_size: Maximum request body size to log in bytes
        """
        super().__init__(app)
        self.log_requests = log_requests
        self.log_level = log_level.upper()
        self.max_body_size = max_body_size  # Expected to be in bytes

    async def dispatch(self, request: Request, call_next: Callable):
        """Process incoming request and log details with sensitive data masked.

        Args:
            request: The incoming HTTP request
            call_next: Function to call the next middleware/handler

        Returns:
            Response: The HTTP response from downstream handlers
        """
        # Skip logging if disabled
        if not self.log_requests:
            return await call_next(request)

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

        response: Response = await call_next(new_request)
        return response
