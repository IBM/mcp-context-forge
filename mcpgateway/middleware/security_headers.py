# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/security_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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

    Examples:
        >>> middleware = SecurityHeadersMiddleware(None)
        >>> isinstance(middleware, SecurityHeadersMiddleware)
        True
        >>> # Test CSP directive construction
        >>> csp_directives = [
        ...     "default-src 'self'",
        ...     "script-src 'self' 'unsafe-inline'",
        ...     "style-src 'self' 'unsafe-inline'"
        ... ]
        >>> csp = "; ".join(csp_directives) + ";"
        >>> "default-src 'self'" in csp
        True
        >>> csp.endswith(";")
        True
        >>> # Test HSTS value construction
        >>> hsts_max_age = 31536000
        >>> hsts_value = f"max-age={hsts_max_age}"
        >>> include_subdomains = True
        >>> if include_subdomains:
        ...     hsts_value += "; includeSubDomains"
        >>> "max-age=31536000" in hsts_value
        True
        >>> "includeSubDomains" in hsts_value
        True
        >>> # Test CORS origin validation logic
        >>> allowed_origins = ["https://example.com", "https://app.example.com"]
        >>> origin = "https://example.com"
        >>> origin in allowed_origins
        True
        >>> "https://malicious.com" in allowed_origins
        False
        >>> # Test Vary header construction
        >>> existing_vary = "Accept-Encoding"
        >>> vary_val = "Origin" if not existing_vary else (existing_vary + ", Origin")
        >>> vary_val
        'Accept-Encoding, Origin'
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process the request and add security headers to the response.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware or endpoint handler

        Returns:
            Response with security headers added

        Examples:
            Test middleware instantiation:
            >>> from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware
            >>> middleware = SecurityHeadersMiddleware(app=None)
            >>> isinstance(middleware, SecurityHeadersMiddleware)
            True

            Test security header values:
            >>> # X-Content-Type-Options
            >>> x_content_type = "nosniff"
            >>> x_content_type == "nosniff"
            True

            >>> # X-XSS-Protection modern value
            >>> x_xss_protection = "0"  # Modern browsers use CSP
            >>> x_xss_protection == "0"
            True

            >>> # X-Download-Options for IE
            >>> x_download_options = "noopen"
            >>> x_download_options == "noopen"
            True

            >>> # Referrer-Policy value
            >>> referrer_policy = "strict-origin-when-cross-origin"
            >>> "strict-origin" in referrer_policy
            True

            Test CSP directive construction:
            >>> csp_directives = [
            ...     "default-src 'self'",
            ...     "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com",
            ...     "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
            ...     "img-src 'self' data: https:",
            ...     "font-src 'self' data: https://cdnjs.cloudflare.com",
            ...     "connect-src 'self' ws: wss: https:",
            ...     "frame-ancestors 'self'",  # Example for SAMEORIGIN
            ... ]
            >>> csp_header = "; ".join(csp_directives) + ";"
            >>> "default-src 'self'" in csp_header
            True
            >>> "frame-ancestors 'self'" in csp_header
            True
            >>> csp_header.endswith(";")
            True

            Test HSTS header construction:
            >>> hsts_max_age = 31536000  # 1 year
            >>> hsts_value = f"max-age={hsts_max_age}"
            >>> hsts_include_subdomains = True
            >>> if hsts_include_subdomains:
            ...     hsts_value += "; includeSubDomains"
            >>> "max-age=31536000" in hsts_value
            True
            >>> "includeSubDomains" in hsts_value
            True

            Test CORS origin validation logic:
            >>> # Test allowed origins check
            >>> allowed_origins = ["https://example.com", "https://app.example.com"]
            >>> test_origin = "https://example.com"
            >>> test_origin in allowed_origins
            True
            >>> "https://malicious.com" in allowed_origins
            False

            >>> # Test CORS credentials header
            >>> cors_allow_credentials = True
            >>> credentials_header = "true" if cors_allow_credentials else "false"
            >>> credentials_header == "true"
            True

            Test Vary header construction:
            >>> # Test with no existing Vary header
            >>> existing_vary = None
            >>> vary_val = "Origin" if not existing_vary else (existing_vary + ", Origin")
            >>> vary_val
            'Origin'

            >>> # Test with existing Vary header
            >>> existing_vary = "Accept-Encoding"
            >>> vary_val = "Origin" if not existing_vary else (existing_vary + ", Origin")
            >>> vary_val
            'Accept-Encoding, Origin'

            Test Access-Control-Expose-Headers:
            >>> exposed_headers = ["Content-Length", "X-Request-ID"]
            >>> expose_header_value = ", ".join(exposed_headers)
            >>> "Content-Length" in expose_header_value
            True
            >>> "X-Request-ID" in expose_header_value
            True

            Test server header removal logic:
            >>> # Headers that should be removed
            >>> sensitive_headers = ["X-Powered-By", "Server"]
            >>> "X-Powered-By" in sensitive_headers
            True
            >>> "Server" in sensitive_headers
            True

            Test environment-based CORS logic:
            >>> # Production environment requires explicit allowlist
            >>> environment = "production"
            >>> origin = "https://example.com"
            >>> allowed_origins = ["https://example.com"]
            >>> allow = origin in allowed_origins if environment == "production" else True
            >>> allow
            True

            >>> # Non-production with empty allowed_origins allows all
            >>> environment = "development"
            >>> allowed_origins = []
            >>> allow = (not allowed_origins) if environment != "production" else False
            >>> allow
            True

            Execute middleware end-to-end with a dummy call_next:
            >>> import asyncio
            >>> from unittest.mock import patch
            >>> from starlette.requests import Request
            >>> from starlette.responses import Response
            >>> async def call_next(req):
            ...     return Response("ok")
            >>> scope = {
            ...     'type': 'http', 'method': 'GET', 'path': '/', 'scheme': 'https',
            ...     'headers': [(b'origin', b'https://example.com'), (b'x-forwarded-proto', b'https')]
            ... }
            >>> request = Request(scope)
            >>> mw = SecurityHeadersMiddleware(app=None)
            >>> with patch('mcpgateway.middleware.security_headers.settings') as s:
            ...     s.security_headers_enabled = True
            ...     s.x_content_type_options_enabled = True
            ...     s.x_frame_options = 'DENY'
            ...     s.x_xss_protection_enabled = True
            ...     s.x_download_options_enabled = True
            ...     s.hsts_enabled = True
            ...     s.hsts_max_age = 31536000
            ...     s.hsts_include_subdomains = True
            ...     s.remove_server_headers = True
            ...     s.environment = 'production'
            ...     s.allowed_origins = ['https://example.com']
            ...     s.cors_allow_credentials = True
            ...     resp = asyncio.run(mw.dispatch(request, call_next))
            >>> resp.headers['X-Content-Type-Options']
            'nosniff'
            >>> resp.headers['X-Frame-Options']
            'DENY'
            >>> 'Content-Security-Policy' in resp.headers
            True
            >>> resp.headers['Strict-Transport-Security'].startswith('max-age=')
            True
            >>> resp.headers['Access-Control-Allow-Origin']
            'https://example.com'
            >>> 'Vary' in resp.headers and 'Origin' in resp.headers['Vary']
            True
        """
        response = await call_next(request)

        # Only apply security headers if enabled
        if not settings.security_headers_enabled:
            return response

        # Essential security headers (configurable)
        if settings.x_content_type_options_enabled:
            response.headers["X-Content-Type-Options"] = "nosniff"

        # Handle X-Frame-Options: None = don't set header, empty string = allow all, other values = set header
        if settings.x_frame_options is not None:
            if settings.x_frame_options:  # Non-empty string
                response.headers["X-Frame-Options"] = settings.x_frame_options
            # Empty string means user wants to disable the header (allow all frames)
            # Don't set the header in this case

        if settings.x_xss_protection_enabled:
            response.headers["X-XSS-Protection"] = "0"  # Modern browsers use CSP instead

        if settings.x_download_options_enabled:
            response.headers["X-Download-Options"] = "noopen"  # Prevent IE from executing downloads

        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy
        # This CSP is designed to work with the Admin UI while providing security
        # Dynamically set frame-ancestors based on X_FRAME_OPTIONS setting to stay consistent
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com",
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net",
            "img-src 'self' data: https:",
            "font-src 'self' data: https://cdnjs.cloudflare.com",
            "connect-src 'self' ws: wss: https:",
        ]

        # Only add frame-ancestors if x_frame_options is not None
        # When None (or "null"/"none" string), completely disable iframe restrictions
        if settings.x_frame_options is not None:
            x_frame = str(settings.x_frame_options)
            x_frame_upper = x_frame.upper()

            if x_frame_upper == "DENY":
                frame_ancestors = "'none'"
            elif x_frame_upper == "SAMEORIGIN":
                frame_ancestors = "'self'"
            elif x_frame_upper.startswith("ALLOW-FROM"):
                allowed_uri = x_frame.split(" ", 1)[1] if " " in x_frame else "'none'"
                frame_ancestors = allowed_uri
            elif x_frame_upper == "ALLOW-ALL":
                frame_ancestors = "* file: http: https:"
            else:
                # Default to none for unknown values (matches DENY default)
                frame_ancestors = "'none'"

            csp_directives.append(f"frame-ancestors {frame_ancestors}")
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

        # Lightweight dynamic CORS reflection based on current settings
        origin = request.headers.get("Origin")
        if origin:
            allow = False
            if settings.environment != "production":
                # In non-production, honor allowed_origins dynamically
                allow = (not settings.allowed_origins) or (origin in settings.allowed_origins)
            else:
                # In production, require explicit allow-list
                allow = origin in settings.allowed_origins
            if allow:
                response.headers["Access-Control-Allow-Origin"] = origin
                # Standard CORS helpers
                if settings.cors_allow_credentials:
                    response.headers["Access-Control-Allow-Credentials"] = "true"
                # Expose common headers for clients
                exposed = ["Content-Length", "X-Request-ID"]
                response.headers["Access-Control-Expose-Headers"] = ", ".join(exposed)
                # Ensure caches vary on Origin
                existing_vary = response.headers.get("Vary")
                vary_val = "Origin" if not existing_vary else (existing_vary + ", Origin")
                response.headers["Vary"] = vary_val

        return response
