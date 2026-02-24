# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/ip_control.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

IP Access Control Middleware.

This middleware evaluates incoming requests against IP allowlist/blocklist rules
and optionally blocks denied IPs with a 403 response.

Examples:
    >>> from mcpgateway.middleware.ip_control import IPControlMiddleware  # doctest: +SKIP
    >>> app.add_middleware(IPControlMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
from typing import Callable

# Third-Party
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.ip_control_service import get_ip_control_service

logger = logging.getLogger(__name__)


class IPControlMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces IP-based access control.

    Evaluates each request's client IP against configured rules and temporary
    blocks. Denied requests receive a 403 JSON response unless log_only mode
    is enabled (dry-run).
    """

    def __init__(self, app, **kwargs):
        """Initialize middleware with skip paths from settings.

        Args:
            app: ASGI application.
            **kwargs: Additional middleware keyword arguments.
        """
        super().__init__(app, **kwargs)
        self._skip_paths: frozenset = frozenset(settings.ip_control_skip_paths)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through IP access control.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware/handler in chain.

        Returns:
            HTTP response.
        """
        # 1. Skip configured paths (health checks, etc.)
        if request.url.path in self._skip_paths:
            return await call_next(request)

        # 2. Extract client IP
        client_ip = self._extract_client_ip(request)

        # 3. Evaluate IP
        service = get_ip_control_service()
        allowed = service.evaluate_ip(client_ip, request.url.path)

        # 4. Store on request state
        request.state.client_ip = client_ip
        request.state.ip_control_result = allowed

        # 5. Handle denied
        if not allowed:
            if settings.ip_control_log_only:
                logger.warning(f"IP control: would deny {client_ip} for {request.url.path} (log-only mode)")
            else:
                logger.warning(f"IP control: denied {client_ip} for {request.url.path}")
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Access denied by IP access control policy",
                        "error": "ip_blocked",
                    },
                )

        return await call_next(request)

    def _extract_client_ip(self, request: Request) -> str:
        """Extract the client IP from the request.

        Checks proxy headers if trusted, then falls back to request.client.host.

        Args:
            request: HTTP request.

        Returns:
            Client IP address string.
        """
        if settings.ip_control_trust_proxy_headers:
            # X-Forwarded-For: client, proxy1, proxy2
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                # First IP is the original client
                return forwarded_for.split(",")[0].strip()

            # X-Real-IP (single IP)
            real_ip = request.headers.get("x-real-ip")
            if real_ip:
                return real_ip.strip()

        # Fallback to direct connection
        if request.client:
            return request.client.host
        return "unknown"
