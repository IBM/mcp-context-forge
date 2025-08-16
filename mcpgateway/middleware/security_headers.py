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

        # Essential security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"  # Modern browsers use CSP instead
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy
        # This CSP is designed to work with the Admin UI while providing security
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self' ws: wss: https:",
            "frame-ancestors 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives) + ";"

        # HSTS for HTTPS connections
        # Check both the request scheme and X-Forwarded-Proto header for proxy scenarios
        if request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Remove sensitive headers that might disclose server information
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]
        if "Server" in response.headers:
            del response.headers["Server"]

        return response
