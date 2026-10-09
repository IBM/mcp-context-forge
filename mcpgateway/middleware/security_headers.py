# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/security_headers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Security Headers Middleware for ContextForge.

This module implements essential security headers to prevent common attacks including
XSS, clickjacking, MIME sniffing, cross-origin attacks, and Web Cache Deception.

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): the header logic only
needs the request scope and the response-start message, so it runs without the
per-request task-group and body-streaming overhead BaseHTTPMiddleware adds.
"""

# Standard
import re
import secrets
from typing import Any, Callable, Optional, Protocol, Set

# Third-Party
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.asgi_utils import headers_to_dict, RawHeaderMutator
from mcpgateway.utils.paths import normalize_scope_path, replace_api_path_alias


class _HeaderMutator(Protocol):
    """Minimal get/set/delete surface the header logic operates against."""

    def get(self, name: str) -> Optional[str]:
        """Return the (case-insensitive) header value or None."""

    def set(self, name: str, value: str) -> None:
        """Set (replacing any existing) header value."""

    def delete(self, name: str) -> None:
        """Remove all instances of the header if present."""


class _ResponseHeaderMutator:
    """Mutator over a Starlette response's headers mapping."""

    def __init__(self, headers: Any) -> None:
        self._headers = headers

    def get(self, name: str) -> Optional[str]:
        """Return the header value or None."""
        return self._headers.get(name)

    def set(self, name: str, value: str) -> None:
        """Set the header, replacing any existing value."""
        self._headers[name] = value

    def delete(self, name: str) -> None:
        """Remove the header if present."""
        if name in self._headers:
            del self._headers[name]


class SecurityHeadersMiddleware:
    """
    Security headers middleware that adds essential security headers to all responses.

    This middleware implements security best practices by adding headers that help
    prevent various types of attacks and security vulnerabilities.

    Security headers added:
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking attacks
    - X-XSS-Protection: Disables legacy XSS protection (modern browsers use CSP)
    - Referrer-Policy: Controls referrer information sent with requests
    - Content-Security-Policy: Nonce-based CSP prevents XSS and code injection
    - Strict-Transport-Security: Forces HTTPS connections (when appropriate)
    - Cache-Control: Prevents Web Cache Deception on authenticated endpoints (no-store, private)
    - Vary: Authorization - Prevents cache key collisions on authenticated endpoints

    CSP Implementation:
    - Uses cryptographically secure nonces (secrets.token_urlsafe(16))
    - script-src-elem: nonce-based, no unsafe-inline (primary defense for modern browsers)
    - script-src: strict policy, no unsafe-eval or unsafe-inline
    - style-src: uses 'unsafe-inline' for style attributes (documented configuration for animations and positioning)
    - Nonce stored in request.state.csp_nonce for template access
    - Inline scripts must include nonce="{{ csp_nonce(request) }}" attribute
    - All HTMX hx-vals and hx-on attributes migrated to JavaScript event handlers

    Sensitive headers removed:
    - X-Powered-By: Removes server technology disclosure
    - Server: Removes server version information

    Web Cache Deception Protection:
    Authenticated API endpoints receive Cache-Control: no-store, private to prevent
    intermediary caching (CDN, reverse proxy, load balancer) that could expose
    sensitive data to unauthenticated users. The Vary: Authorization header ensures
    cache keys include authentication context.

    Examples:
        >>> middleware = SecurityHeadersMiddleware(None)
        >>> isinstance(middleware, SecurityHeadersMiddleware)
        True
        >>> # Test CSP directive construction with nonce
        >>> import secrets
        >>> csp_nonce = secrets.token_urlsafe(16)
        >>> csp_directives = [
        ...     "default-src 'self'",
        ...     f"script-src 'self' 'nonce-{csp_nonce}'",
        ...     f"style-src 'self' 'nonce-{csp_nonce}'"
        ... ]
        >>> csp = "; ".join(csp_directives) + ";"
        >>> "default-src 'self'" in csp
        True
        >>> csp.endswith(";")
        True
        >>> "'nonce-" in csp
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

    # Paths that should have strict no-cache headers (authenticated endpoints)
    # These are API endpoints that return user-specific or sensitive data
    PROTECTED_PATH_PATTERNS: Set[str] = {
        r"^/tools(/.*)?$",
        r"^/servers(/.*)?$",
        r"^/resources(/.*)?$",
        r"^/gateways(/.*)?$",
        r"^/prompts(/.*)?$",
        r"^/tags(/.*)?$",
        r"^/roots(/.*)?$",
        r"^/protocol(/.*)?$",
        r"^/metrics(/.*)?$",
        r"^/admin(/.*)?$",
        r"^/api(/.*)?$",
        r"^/_internal(/.*)?$",
        r"^/mcp(/.*)?$",
        r"^/auth(/.*)?$",
        r"^/oauth(/.*)?$",
        r"^/sso(/.*)?$",
        r"^/teams(/.*)?$",
        r"^/tokens(/.*)?$",
        r"^/users(/.*)?$",
        r"^/rbac(/.*)?$",
        r"^/observability(/.*)?$",
        r"^/llm(/.*)?$",
        r"^/a2a(/.*)?$",
    }

    # Paths that can be cached (public, static content).
    # NOTE: /docs, /redoc, /openapi.json are intentionally NOT here — they are
    # auth-protected by DocsAuthMiddleware and must receive no-store/private.
    EXEMPTED_PATH_PATTERNS: Set[str] = {
        r"^/static/.*$",
        r"^/health$",
        r"^/ready$",
        r"^/\.well-known/.*$",
        r"^/servers/[^/]+/\.well-known/.*$",
    }

    def __init__(self, app: Any) -> None:
        """Initialize the security headers middleware."""
        self.app = app
        # Compile regex patterns for performance
        self._protected_patterns = [re.compile(pattern) for pattern in self.PROTECTED_PATH_PATTERNS]
        self._exempted_patterns = [re.compile(pattern) for pattern in self.EXEMPTED_PATH_PATTERNS]

    def _is_protected_path(self, path: str) -> bool:
        """
        Check if the path should have strict no-cache headers.

        Args:
            path: The request path to check

        Returns:
            True if the path should have no-cache headers, False otherwise
        """
        path = replace_api_path_alias(path)

        # First check if path is exempted (can be cached)
        for pattern in self._exempted_patterns:
            if pattern.match(path):
                return False

        # Then check if path is protected (must not be cached)
        for pattern in self._protected_patterns:
            if pattern.match(path):
                return True

        # SECURITY: Hardened default - treat unmatched paths as protected (fail-secure).
        # New endpoints inherit protection automatically until explicitly exempted.
        return True

    def _prepare(self, scope: dict) -> dict:
        """Compute the per-request context shared by both entry paths.

        Sets the CSP nonce into the scope state (visible downstream as
        ``request.state.csp_nonce``) and extracts the routing-relevant fields.

        Args:
            scope: The ASGI connection scope.

        Returns:
            A context dict with nonce, normalized path, scheme, and headers.
        """
        csp_nonce = secrets.token_urlsafe(16)
        # Starlette's request.state is backed by scope["state"]; assigning here
        # keeps templates working without constructing a Request.
        scope.setdefault("state", {})["csp_nonce"] = csp_nonce

        path = normalize_scope_path(scope.get("path", ""), scope.get("root_path", ""))

        return {"csp_nonce": csp_nonce, "path": path, "scheme": scope.get("scheme", "http"), "headers": headers_to_dict(scope.get("headers"))}

    def _apply_headers(self, ctx: dict, out: _HeaderMutator) -> None:
        """Apply all security header mutations to a response header mutator.

        Args:
            ctx: The context dict from ``_prepare``.
            out: Header mutator for the outgoing response.
        """
        if not settings.security_headers_enabled:
            return

        csp_nonce = ctx["csp_nonce"]
        path = ctx["path"]
        headers = ctx["headers"]

        # Essential security headers (configurable)
        if settings.x_content_type_options_enabled:
            out.set("X-Content-Type-Options", "nosniff")

        # Handle X-Frame-Options: None/empty = don't set header (allow embedding), other values = set header
        # Note: config validator normalizes ""/"null"/"none" to None, but we guard here too for safety
        x_frame = settings.x_frame_options
        if isinstance(x_frame, str) and not x_frame.strip():
            x_frame = None
        if x_frame is not None:
            out.set("X-Frame-Options", x_frame)

        if settings.x_xss_protection_enabled:
            out.set("X-XSS-Protection", "0")  # Modern browsers use CSP instead

        if settings.x_download_options_enabled:
            out.set("X-Download-Options", "noopen")  # Prevent IE from executing downloads

        out.set("Referrer-Policy", "strict-origin-when-cross-origin")

        # FastAPI's built-in /docs and /redoc pages use inline scripts without nonces
        # to initialise SwaggerUIBundle.  Skipping CSP on these endpoints lets the
        # documentation UI render while keeping strict CSP everywhere else.
        skip_csp_for_docs = path in ("/docs", "/redoc", "/openapi.json")

        # CSP directives with strict nonce-based security (CSP Level 3)
        #
        # script-src-elem: Controls <script> tags - requires nonces for inline scripts.
        #   This prevents XSS via injected <script> blocks while allowing legitimate
        #   inline scripts that have the matching nonce attribute.
        #
        # script-src-attr: 'none' blocks inline on* event handler attributes, so
        #   injected markup cannot become script execution.
        #
        # script-src: Fallback for older browsers. No unsafe-eval or unsafe-inline.
        #   All HTMX hx-vals="js:{...}" have been migrated to htmx:configRequest handlers.
        #   All hx-on:* event handlers have been migrated to addEventListener.
        #   Alpine.js has been migrated to @alpinejs/csp build (no eval required).
        #   Tailwind CSS uses precompiled CSS (no eval required).
        #
        # style-src: 'unsafe-inline' for style attributes (documented configuration).
        #   Inline style attributes (style="...") are used for animation delays,
        #   positioning, and dynamic styling throughout the application.
        #   This is acceptable per CSP Level 3 guidance since CSS cannot execute
        #   JavaScript directly. While CSS injection can be used for clickjacking
        #   or UI redressing attacks, these are mitigated by:
        #   1. X-Frame-Options/frame-ancestors preventing iframe embedding
        #   2. All inline styles are server-rendered (no user-controlled content)
        #   3. Authentication required for admin UI (not publicly exposed)
        #   This is a documented trade-off between security strictness and
        #   implementation complexity (visual-only impact vs. code-execution risk).
        #   Note: Nonce cannot be used alongside 'unsafe-inline' in style-src because
        #   the nonce takes precedence and causes the browser to ignore 'unsafe-inline',
        #   which would block all style attributes since nonces can only apply to <style> blocks.
        #
        # CDN Allowlist Rationale:
        #   - cdnjs.cloudflare.com: Font Awesome 7.0.1 icons, CodeMirror 5.65.20 (code editor)
        #   - cdn.jsdelivr.net: Chart.js 4.5.1 (metrics charts), Marked 18.0.3 (markdown rendering),
        #                       DOMPurify 3.4.2 (XSS sanitization)
        #   - unpkg.com: Reserved for future use (Alpine.js, HTMX updates)
        #   All CDN resources use SRI (Subresource Integrity) hashes where supported.
        if not skip_csp_for_docs:
            csp_directives = [
                "default-src 'self'",
                f"script-src-elem 'self' 'nonce-{csp_nonce}'",
                "script-src-attr 'none'",
                "script-src 'self'",
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data: https:",
                "font-src 'self' data:",
                "connect-src 'self' ws: wss: https:",
            ]

            # Only add frame-ancestors if x_frame is set (None/empty = allow all embedding)
            if x_frame is not None:
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
            out.set("Content-Security-Policy", "; ".join(csp_directives) + ";")

        # HSTS for HTTPS connections (configurable)
        if settings.hsts_enabled and (ctx["scheme"] == "https" or headers.get("x-forwarded-proto") == "https"):
            hsts_value = f"max-age={settings.hsts_max_age}"
            if settings.hsts_include_subdomains:
                hsts_value += "; includeSubDomains"
            out.set("Strict-Transport-Security", hsts_value)

        # Remove sensitive headers that might disclose server information (configurable)
        if settings.remove_server_headers:
            out.delete("X-Powered-By")
            out.delete("Server")

        # Lightweight dynamic CORS reflection based on current settings
        origin = headers.get("origin")
        if origin:
            # Reflecting an origin with credentials requires an explicit allowlist in every
            # environment; an empty allowlist must never mean "allow any origin".
            if origin in settings.allowed_origins:
                out.set("Access-Control-Allow-Origin", origin)
                # Standard CORS helpers
                if settings.cors_allow_credentials:
                    out.set("Access-Control-Allow-Credentials", "true")
                # Expose common headers for clients
                exposed = ["Content-Length", "X-Request-ID"]
                out.set("Access-Control-Expose-Headers", ", ".join(exposed))
                # Ensure caches vary on Origin
                existing_vary = out.get("Vary")
                vary_val = "Origin" if not existing_vary else (existing_vary + ", Origin")
                out.set("Vary", vary_val)

        # Hardened Cache Control for Protected Endpoints
        if self._is_protected_path(path):
            # Strict cache control: no-store prevents intermediary caching, private restricts to user agent
            out.set("Cache-Control", "no-store, private")

            # Legacy protocol compatibility for defense-in-depth
            out.set("Pragma", "no-cache")
            out.set("Expires", "0")

            # Cache variance control for proper request isolation
            existing_vary = out.get("Vary") or ""
            vary_parts = [v.strip() for v in existing_vary.split(",") if v.strip()] if existing_vary else []
            if "Authorization" not in vary_parts:
                vary_parts.append("Authorization")
            out.set("Vary", ", ".join(vary_parts))

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """ASGI entry point.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        ctx = self._prepare(scope)

        async def send_with_security_headers(message: dict) -> None:
            """Apply security headers to the response-start message, then forward."""
            if message.get("type") == "http.response.start":
                self._apply_headers(ctx, RawHeaderMutator(message.setdefault("headers", [])))
            await send(message)

        await self.app(scope, receive, send_with_security_headers)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        """BaseHTTPMiddleware-compatible entry point retained for tests and doctests.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware or endpoint handler

        Returns:
            Response with security headers added
        """
        ctx = self._prepare(request.scope)
        response = await call_next(request)
        self._apply_headers(ctx, _ResponseHeaderMutator(response.headers))
        return response
