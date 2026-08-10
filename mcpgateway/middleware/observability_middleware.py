# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/observability_middleware.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Observability Middleware for automatic request/response tracing.

This middleware automatically captures HTTP requests and responses as observability traces,
providing comprehensive visibility into all gateway operations.

Session Management (Issue #3883):
    This middleware does NOT create or manage request.state.db. Each observability
    operation (start_trace, start_span, end_span, end_trace) creates its own short-lived
    independent database session that commits immediately on a best-effort basis.

    This separation ensures observability data persists even when main request transactions
    fail, providing visibility into partial failures. SQL query instrumentation is handled
    separately via attach_trace_to_session() (see instrumentation/sqlalchemy.py).

Implemented as pure ASGI middleware (no BaseHTTPMiddleware): the trace lifecycle only
needs the request scope and the response-start message (status + headers), so
responses stream unbuffered without BaseHTTPMiddleware's per-request task-group
overhead. A ``dispatch`` shim is retained for tests and doctests.

Examples:
    >>> from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware  # doctest: +SKIP
    >>> app.add_middleware(ObservabilityMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
import time
import traceback
from typing import Any, Callable, Dict, Optional

# Third-Party
from cpex.framework.observability import current_trace_id as plugins_trace_id
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# First-Party
from mcpgateway.config import settings
from mcpgateway.instrumentation.sqlalchemy import attach_trace_to_session
from mcpgateway.middleware.path_filter import should_skip_observability
from mcpgateway.services.observability_service import current_span_id, current_trace_id, ObservabilityService, parse_traceparent
from mcpgateway.utils.log_sanitizer import sanitize_for_log
from mcpgateway.utils.trace_redaction import sanitize_trace_text

logger = logging.getLogger(__name__)


def sanitize_header_for_storage(value: Optional[str], max_length: int = 500) -> str:
    """Sanitize header value for safe database storage.

    Removes control characters and truncates to prevent:
    - Log injection attacks (newlines, ANSI codes)
    - DoS via large headers (10MB user-agent)
    - Storage exhaustion

    Args:
        value: Header value to sanitize
        max_length: Maximum length to truncate to (default: 500)

    Returns:
        Sanitized header value, truncated to max_length

    Examples:
        >>> sanitize_header_for_storage("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        >>> sanitize_header_for_storage("Evil\\x00\\nInjection")
        'EvilInjection'
        >>> len(sanitize_header_for_storage("A" * 1000, max_length=100))
        100
        >>> sanitize_header_for_storage(None)
        'unknown'
    """
    if not value:
        return "unknown"
    # Remove control characters except space and tab
    clean = "".join(c for c in value if c.isprintable() or c in " \t")
    # Truncate to max length
    if len(clean) > max_length:
        return clean[:max_length]
    return clean


class ObservabilityMiddleware:
    """Middleware for automatic HTTP request/response tracing.

    Captures every HTTP request as a trace with timing, status codes,
    and user context. Automatically creates spans for the request lifecycle.

    This middleware is disabled by default and can be enabled via the
    MCPGATEWAY_OBSERVABILITY_ENABLED environment variable.
    """

    def __init__(self, app: ASGIApp, enabled: bool = None, service: Optional[ObservabilityService] = None):
        """Initialize the observability middleware.

        Args:
            app: ASGI application
            enabled: Whether observability is enabled (defaults to settings)
            service: Optional ObservabilityService instance
        """
        self.app = app
        self.enabled = enabled if enabled is not None else getattr(settings, "observability_enabled", False)
        self.service = service or ObservabilityService()
        logger.info(f"Observability middleware initialized (enabled={self.enabled})")

    async def _setup_trace(self, request: Request) -> Optional[Dict[str, Any]]:
        """Create the trace and request span for an incoming request.

        On success the returned context dict carries the trace/span IDs, the
        start timestamp, and the ContextVar tokens that must be reset when the
        request finishes. On failure the partially-set ContextVars are rolled
        back and None is returned, meaning the request proceeds untraced.

        Observability uses independent database sessions (issue #3883) that commit
        immediately on a best-effort basis, separate from the main request transaction.

        Args:
            request: Incoming HTTP request

        Returns:
            Trace context dict, or None if trace setup failed
        """
        # Extract request context
        http_method = request.method
        http_url = sanitize_header_for_storage(str(request.url), max_length=2000)
        user_email = None
        ip_address = request.client.host if request.client else None
        user_agent = sanitize_header_for_storage(request.headers.get("user-agent"), max_length=500)

        # Try to extract user from request state (set by auth middleware)
        if hasattr(request.state, "user") and hasattr(request.state.user, "email"):
            user_email = request.state.user.email

        # Extract W3C Trace Context from headers (for distributed tracing)
        external_trace_id = None
        external_parent_span_id = None
        traceparent_header = request.headers.get("traceparent")
        if traceparent_header:
            parsed = parse_traceparent(traceparent_header)
            if parsed:
                external_trace_id, external_parent_span_id, _flags = parsed
                logger.debug(f"Extracted W3C trace context: trace_id={external_trace_id}, parent_span_id={external_parent_span_id}")

        ctx: Dict[str, Any] = {
            "trace_id": None,
            "span_id": None,
            "start_time": time.time(),
            "trace_id_token": None,
            "plugins_trace_id_token": None,
            "span_id_token": None,
        }

        try:
            # Start trace (creates independent observability session)
            trace_id = self.service.start_trace(
                name=f"{http_method} {request.url.path}",
                trace_id=external_trace_id,  # Use external trace ID if provided
                parent_span_id=external_parent_span_id,  # Track parent span from upstream
                http_method=http_method,
                http_url=http_url,
                user_email=user_email,
                user_agent=user_agent,
                ip_address=ip_address,
                attributes={
                    "http.route": request.url.path,
                    "http.query": sanitize_trace_text(str(request.url.query)) if request.url.query else None,
                },
                resource_attributes={
                    "service.name": "mcp-gateway",
                    "service.version": getattr(settings, "version", "unknown"),
                },
            )

            # Store trace_id in request state for use in route handlers
            request.state.trace_id = trace_id
            ctx["trace_id"] = trace_id

            # Set trace_id in context variable for access throughout async call stack.
            # Tokens are reset when the request finishes so stale trace/span context
            # never bleeds into later requests that reuse the same task/context.
            ctx["trace_id_token"] = current_trace_id.set(trace_id)
            # Bridge: also set the framework's ContextVar so the plugin executor sees it
            ctx["plugins_trace_id_token"] = plugins_trace_id.set(trace_id)

            # If another middleware created request session, attach trace for SQL instrumentation
            # SQL instrumentation creates its own observability sessions (instrumentation/sqlalchemy.py:58)
            if hasattr(request.state, "db") and request.state.db is not None:
                attach_trace_to_session(request.state.db, trace_id)

            # Start request span (creates independent observability session)
            span_id = self.service.start_span(
                trace_id=trace_id,
                name="http.request",
                kind="server",
                attributes={"http.method": http_method, "http.url": http_url},
            )

            # Store span_id in request state for use in route handlers / plugin hook call sites
            request.state.span_id = span_id
            ctx["span_id"] = span_id

            # Set span_id in context variable for access throughout async call stack
            # (mirrors current_trace_id.set() above) — deep service-layer call sites
            # (e.g. tool_service.py, prompt_service.py invoke_hook() sites) don't have
            # access to the Request object and read this instead.
            ctx["span_id_token"] = current_span_id.set(span_id)

        except Exception as e:
            # If trace setup failed, log and continue without tracing
            logger.warning(f"Failed to setup observability trace: {e}")
            # Reset whichever ContextVars were set before the failure, then continue without tracing
            if ctx["span_id_token"] is not None:
                current_span_id.reset(ctx["span_id_token"])
            if ctx["plugins_trace_id_token"] is not None:
                plugins_trace_id.reset(ctx["plugins_trace_id_token"])
            if ctx["trace_id_token"] is not None:
                current_trace_id.reset(ctx["trace_id_token"])
            return None

        return ctx

    def _finish_success(self, ctx: Dict[str, Any], status_code: int, response_size: Optional[str]) -> None:
        """End the span and trace for a completed response.

        Both endings create independent observability sessions and are
        best-effort: failures are logged and never affect the response.

        Args:
            ctx: Trace context from ``_setup_trace``
            status_code: Final HTTP status code
            response_size: Value of the response Content-Length header, if any
        """
        span_id = ctx["span_id"]
        trace_id = ctx["trace_id"]

        # End span successfully (creates independent observability session)
        if span_id:
            try:
                self.service.end_span(
                    span_id,
                    status="ok" if status_code < 400 else "error",
                    attributes={
                        "http.status_code": status_code,
                        "http.response_size": response_size,
                    },
                )
            except Exception as end_span_error:
                logger.warning(f"Failed to end span {span_id}: {end_span_error}")

        # End trace (creates independent observability session)
        if trace_id:
            duration_ms = (time.time() - ctx["start_time"]) * 1000
            try:
                self.service.end_trace(
                    trace_id,
                    status="ok" if status_code < 400 else "error",
                    http_status_code=status_code,
                    attributes={"response_time_ms": duration_ms},
                )
            except Exception as end_trace_error:
                logger.warning(f"Failed to end trace {trace_id}: {end_trace_error}")

    def _finish_error(self, ctx: Dict[str, Any], error: Exception) -> None:
        """Record an exception on the span and end the trace with error status.

        All writes create independent observability sessions and are
        best-effort: failures are logged and never mask the original exception.

        Args:
            ctx: Trace context from ``_setup_trace``
            error: The exception raised while processing the request
        """
        span_id = ctx["span_id"]
        trace_id = ctx["trace_id"]

        # Log exception in span
        if span_id:
            try:
                sanitized_error = sanitize_for_log(sanitize_trace_text(str(error)))
                self.service.end_span(
                    span_id,
                    status="error",
                    status_message=sanitized_error,
                    attributes={
                        "exception.type": type(error).__name__,
                        "exception.message": sanitized_error,
                    },
                )

                # Add exception event (creates independent observability session)
                self.service.add_event(
                    span_id,
                    name="exception",
                    severity="error",
                    message=sanitized_error,
                    exception_type=type(error).__name__,
                    exception_message=sanitized_error,
                    exception_stacktrace=traceback.format_exc(),
                )
            except Exception as log_error:
                logger.warning(f"Failed to log exception in span: {log_error}")

        # End trace with error (creates independent observability session)
        if trace_id:
            try:
                sanitized_error = sanitize_for_log(sanitize_trace_text(str(error)))
                self.service.end_trace(
                    trace_id,
                    status="error",
                    status_message=sanitized_error,
                    http_status_code=500,
                )
            except Exception as trace_error:
                logger.warning(f"Failed to end trace: {trace_error}")

    @staticmethod
    def _reset_context_vars(ctx: Dict[str, Any]) -> None:
        """Reset the trace/span ContextVars using the tokens captured during setup.

        Always reset so trace/span context never leaks into whatever request
        or task reuses this context next.

        Args:
            ctx: Trace context from ``_setup_trace``
        """
        current_span_id.reset(ctx["span_id_token"])
        plugins_trace_id.reset(ctx["plugins_trace_id_token"])
        current_trace_id.reset(ctx["trace_id_token"])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pure ASGI entry point — no BaseHTTPMiddleware task-group/body overhead.

        The span and trace are ended when the response-start message carries
        the final status code; response bodies stream through unbuffered.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        Raises:
            Exception: Re-raises any exception from request processing after logging
        """
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Skip if observability is disabled
        if not self.enabled:
            await self.app(scope, receive, send)
            return

        # The request object is only used for scope-backed attribute access
        # (url, headers, client, state); the body is never read here.
        request = Request(scope)

        # Skip health checks and static files to reduce noise
        if should_skip_observability(request.url.path):
            await self.app(scope, receive, send)
            return

        ctx = await self._setup_trace(request)
        if ctx is None:
            await self.app(scope, receive, send)
            return

        async def send_with_trace_finish(message: Message) -> None:
            """End span/trace once the response start carries the final status, then forward."""
            if message.get("type") == "http.response.start":
                response_headers = {}
                for item in message.get("headers") or []:
                    if not isinstance(item, (tuple, list)) or len(item) != 2:
                        continue
                    key, value = item
                    if isinstance(key, (bytes, bytearray)) and isinstance(value, (bytes, bytearray)):
                        response_headers[key.decode("latin-1").lower()] = value.decode("latin-1")
                self._finish_success(ctx, message.get("status", 500), response_headers.get("content-length"))
            await send(message)

        # Process request (trace is set up at this point)
        try:
            try:
                await self.app(scope, receive, send_with_trace_finish)
            except Exception as e:
                self._finish_error(ctx, e)
                # Re-raise the original exception
                raise
        finally:
            # Always reset ContextVars so trace/span context never leaks into
            # whatever request or task reuses this context next.
            self._reset_context_vars(ctx)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """BaseHTTPMiddleware-compatible entry point retained for tests and doctests.

        Observability uses independent database sessions (issue #3883) that commit
        immediately on a best-effort basis, separate from the main request transaction.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response

        Raises:
            Exception: Re-raises any exception from request processing after logging
        """
        # Skip if observability is disabled
        if not self.enabled:
            return await call_next(request)

        # Skip health checks and static files to reduce noise
        if should_skip_observability(request.url.path):
            return await call_next(request)

        ctx = await self._setup_trace(request)
        if ctx is None:
            return await call_next(request)

        # Process request (trace is set up at this point)
        try:
            try:
                response = await call_next(request)
                self._finish_success(ctx, response.status_code, response.headers.get("content-length"))
                return response
            except Exception as e:
                self._finish_error(ctx, e)
                # Re-raise the original exception
                raise
        finally:
            # Always reset ContextVars so trace/span context never leaks into
            # whatever request or task reuses this context next.
            self._reset_context_vars(ctx)
