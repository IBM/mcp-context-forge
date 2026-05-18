# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/header_size_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan-Marius Catanus

RFC 6585 compliant header size validation middleware.

This middleware enforces RFC 6585 5 (431 Request Header Fields Too Large)
by validating total header size and individual header field sizes.

Examples:
    >>> from mcpgateway.middleware.header_size_middleware import HeaderSizeMiddleware  # doctest: +SKIP
    >>> app.add_middleware(HeaderSizeMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


class HeaderSizeMiddleware(BaseHTTPMiddleware):
    """RFC 6585 compliant header size validation middleware.

    Enforces limits on:
    - Total header size (all headers combined)
    - Individual header field size
    - Number of headers

    Returns 431 (Request Header Fields Too Large) when limits are exceeded,
    per RFC 6585 § 5.
    """

    def __init__(self, app):
        """Initialize header size middleware.

        Args:
            app: The ASGI application to wrap
        """
        super().__init__(app)
        self.enabled = getattr(settings, "header_size_validation_enabled", True)
        self.max_total_size = getattr(settings, "max_header_total_size_bytes", 16384)  # 16KB default
        self.max_field_size = getattr(settings, "max_header_field_size_bytes", 8192)  # 8KB default
        self.max_header_count = getattr(settings, "max_header_count", 100)

        if self.enabled:
            logger.info(f"HeaderSizeMiddleware initialized: max_total={self.max_total_size}B, " f"max_field={self.max_field_size}B, max_count={self.max_header_count}")

    async def dispatch(self, request: Request, call_next):
        """Validate header sizes before processing request.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware/handler in the chain

        Returns:
            Response from next handler, or 431 error if headers too large
        """
        if not self.enabled:
            return await call_next(request)

        # Check header count
        header_count = len(request.headers)
        if header_count > self.max_header_count:
            logger.warning(f"Request rejected: too many headers ({header_count} > {self.max_header_count}) " f"from {self._get_client_ip(request)}")
            return self._create_431_response(f"Too many header fields ({header_count} > {self.max_header_count})", "header_count")

        # Calculate total header size and check individual field sizes
        total_size = 0
        for name, value in request.headers.items():
            # RFC 9110: header field = field-name ":" OWS field-value OWS
            field_size = len(name) + len(value) + 2  # +2 for ": "
            total_size += field_size

            if field_size > self.max_field_size:
                logger.warning(f"Request rejected: header field '{name}' too large ({field_size}B > {self.max_field_size}B) " f"from {self._get_client_ip(request)}")
                return self._create_431_response(f"Header field '{name}' exceeds maximum size ({field_size} > {self.max_field_size} bytes)", "field_size", field_name=name)

        # Check total header size
        if total_size > self.max_total_size:
            logger.warning(f"Request rejected: total header size too large ({total_size}B > {self.max_total_size}B) " f"from {self._get_client_ip(request)}")
            return self._create_431_response(f"Total header size exceeds maximum ({total_size} > {self.max_total_size} bytes)", "total_size")

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
        if settings.trust_proxy_auth:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()

            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip

        client = request.scope.get("client")
        if client:
            return client[0]

        return "unknown"
