# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/header_size_middleware.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

RFC 6585 compliant header size validation middleware.

This middleware enforces RFC 6585 § 5 (431 Request Header Fields Too Large)
by validating total header size and individual header field sizes.

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): validation only
needs the request headers, so accepted requests stream through without the
task-group and body-buffering overhead BaseHTTPMiddleware adds, and the 431
short-circuit response is sent directly.

Examples:
    >>> from mcpgateway.middleware.header_size_middleware import HeaderSizeMiddleware  # doctest: +SKIP
    >>> app.add_middleware(HeaderSizeMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
from typing import Any, Callable, Dict, Optional

# Third-Party
from fastapi import Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class HeaderSizeMiddleware:
    """RFC 6585 compliant header size validation middleware.

    Enforces limits on:
    - Total header size (all headers combined)
    - Individual header field size
    - Number of headers

    Returns 431 (Request Header Fields Too Large) when limits are exceeded,
    per RFC 6585 § 5.
    """

    def __init__(self, app: Any):
        """Initialize header size middleware.

        Args:
            app: The ASGI application to wrap
        """
        self.app = app
        self.enabled = getattr(settings, "header_size_validation_enabled", True)
        self.max_total_size = getattr(settings, "max_header_total_size_bytes", 16384)  # 16KB default
        self.max_field_size = getattr(settings, "max_header_field_size_bytes", 8192)  # 8KB default
        self.max_header_count = getattr(settings, "max_header_count", 100)

        if self.enabled:
            logger.info(f"HeaderSizeMiddleware initialized: max_total={self.max_total_size}B, max_field={self.max_field_size}B, max_count={self.max_header_count}")

    def _validate_headers(self, headers: Headers, client_ip: str) -> Optional[JSONResponse]:
        """Validate header count and field sizes against the configured limits.

        Args:
            headers: The request headers to validate.
            client_ip: Client IP address for rejection log lines.

        Returns:
            None when the headers are within limits, or a 431 response
            describing the violation.
        """
        # Check header count
        header_count = len(headers)
        if header_count > self.max_header_count:
            logger.warning(f"Request rejected: too many headers ({header_count} > {self.max_header_count}) from {client_ip}")
            return self._create_431_response(f"Too many header fields ({header_count} > {self.max_header_count})", "header_count")

        # Calculate total header size and check individual field sizes
        total_size = 0
        for name, value in headers.items():
            # RFC 9110: header field = field-name ":" OWS field-value OWS
            field_size = len(name) + len(value) + 2  # +2 for ": "
            total_size += field_size

            if field_size > self.max_field_size:
                logger.warning(f"Request rejected: header field '{name}' too large ({field_size}B > {self.max_field_size}B) from {client_ip}")
                return self._create_431_response(f"Header field '{name}' exceeds maximum size ({field_size} > {self.max_field_size} bytes)", "field_size", field_name=name)

        # Check total header size
        if total_size > self.max_total_size:
            logger.warning(f"Request rejected: total header size too large ({total_size}B > {self.max_total_size}B) from {client_ip}")
            return self._create_431_response(f"Total header size exceeds maximum ({total_size} > {self.max_total_size} bytes)", "total_size")

        return None

    def _client_ip_from(self, headers: Headers, scope: Dict[str, Any]) -> str:
        """Extract client IP from headers and scope.

        Args:
            headers: The request headers (case-insensitive lookups).
            scope: The ASGI connection scope.

        Returns:
            Client IP address as string
        """
        if settings.trust_proxy_auth:
            forwarded = headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()

            real_ip = headers.get("X-Real-IP")
            if real_ip:
                return real_ip

        client = scope.get("client")
        if client:
            return client[0]

        return "unknown"

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        """Pure ASGI entry point — no BaseHTTPMiddleware task-group/body overhead.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        headers = Headers(raw=scope.get("headers") or [])
        rejection = self._validate_headers(headers, self._client_ip_from(headers, scope))
        if rejection is not None:
            await rejection(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """BaseHTTPMiddleware-compatible entry point retained for tests.

        Shares its validation logic with ``__call__`` via ``_validate_headers``.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware/handler in the chain

        Returns:
            Response from next handler, or 431 error if headers too large
        """
        if not self.enabled:
            return await call_next(request)

        rejection = self._validate_headers(request.headers, self._get_client_ip(request))
        if rejection is not None:
            return rejection

        return await call_next(request)

    def _create_431_response(self, message: str, violation_type: str, field_name: Optional[str] = None) -> JSONResponse:
        """Create RFC 6585 compliant 431 response.

        Args:
            message: Human-readable error message
            violation_type: Type of violation (header_count, field_size, total_size)
            field_name: Name of the problematic header field (if applicable)

        Returns:
            JSONResponse with 431 status code
        """
        content = {
            "error": "Request Header Fields Too Large",
            "message": message,
            "violation_type": violation_type,
            "limits": {
                "max_total_size_bytes": self.max_total_size,
                "max_field_size_bytes": self.max_field_size,
                "max_header_count": self.max_header_count,
            },
        }

        if field_name:
            content["field_name"] = field_name

        return JSONResponse(
            status_code=431,
            content=content,
            headers={
                "Connection": "close",  # RFC 6585 recommends closing connection
            },
        )

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request.

        Args:
            request: The HTTP request

        Returns:
            Client IP address as string
        """
        return self._client_ip_from(request.headers, request.scope)
