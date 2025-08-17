# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Security Headers Middleware for MCP Gateway.

This module implements essential security headers to prevent common attacks including
XSS, clickjacking, MIME sniffing, and cross-origin attacks.
"""

# Third-Party
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Security headers middleware that adds essential security headers to all responses.

    This middleware implements security best practices by adding headers that help
    prevent various types of attacks and security vulnerabilities.

    Security headers added:
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking attacks
    - X-XSS-Protection: Disables legacy XSS protection (modern browsers use CSP)
    - Referrer-Policy: Controls referrer information sent with requests
    - Content-Security-Policy: Prevents XSS and other code injection attacks
    - Strict-Transport-Security: Forces HTTPS connections (when appropriate)

    Sensitive headers removed:
    - X-Powered-By: Removes server technology disclosure
    - Server: Removes server version information
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process the request and add security headers to the response.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware or endpoint handler

        Returns:
            Response with security headers added
        """
        response = await call_next(request)

        # Only apply security headers if enabled
        if not settings.security_headers_enabled:
            return response

        # Essential security headers (configurable)
        if settings.x_content_type_options_enabled:
            response.headers["X-Content-Type-Options"] = "nosniff"

        if settings.x_frame_options:
            response.headers["X-Frame-Options"] = settings.x_frame_options

        if settings.x_xss_protection_enabled:
            response.headers["X-XSS-Protection"] = "0"  # Modern browsers use CSP instead

        if settings.x_download_options_enabled:
            response.headers["X-Download-Options"] = "noopen"  # Prevent IE from executing downloads

        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy
        # This CSP is designed to work with the Admin UI while providing security
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.tailwindcss.com https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self' ws: wss: https:",
            "frame-ancestors 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives) + ";"

        # HSTS for HTTPS connections (configurable)
        if settings.hsts_enabled and (request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https"):
            hsts_value = f"max-age={settings.hsts_max_age}"
            if settings.hsts_include_subdomains:
                hsts_value += "; includeSubDomains"
            response.headers["Strict-Transport-Security"] = hsts_value

        # Remove sensitive headers that might disclose server information (configurable)
        if settings.remove_server_headers:
            if "X-Powered-By" in response.headers:
                del response.headers["X-Powered-By"]
            if "Server" in response.headers:
                del response.headers["Server"]

        return response
