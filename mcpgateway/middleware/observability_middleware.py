# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/observability_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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

Examples:
    >>> from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware  # doctest: +SKIP
    >>> app.add_middleware(ObservabilityMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
import time
import traceback
from typing import Callable, Optional

# Third-Party
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.config import settings
from mcpgateway.instrumentation.sqlalchemy import attach_trace_to_session
from mcpgateway.middleware.path_filter import should_skip_observability
from mcpgateway.plugins.framework.observability import current_trace_id as plugins_trace_id
from mcpgateway.services.observability_service import current_trace_id, ObservabilityService, parse_traceparent
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


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware for automatic HTTP request/response tracing.

    Captures every HTTP request as a trace with timing, status codes,
    and user context. Automatically creates spans for the request lifecycle.

    This middleware is disabled by default and can be enabled via the
    MCPGATEWAY_OBSERVABILITY_ENABLED environment variable.
    """

    def __init__(self, app, enabled: bool = None, service: Optional[ObservabilityService] = None):
        """Initialize the observability middleware.

        Args:
            app: ASGI application
            enabled: Whether observability is enabled (defaults to settings)
            service: Optional ObservabilityService instance
        """
        super().__init__(app)
        self.enabled = enabled if enabled is not None else getattr(settings, "observability_enabled", False)
        self.service = service or ObservabilityService()
        logger.info(f"Observability middleware initialized (enabled={self.enabled})")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and create observability trace.

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

        trace_id = None
        span_id = None
        start_time = time.time()

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

            # Set trace_id in context variable for access throughout async call stack
            current_trace_id.set(trace_id)
            # Bridge: also set the framework's ContextVar so the plugin executor sees it
            plugins_trace_id.set(trace_id)

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

        except Exception as e:
            # If trace setup failed, log and continue without tracing
            logger.warning(f"Failed to setup observability trace: {e}")
            # Continue without tracing
            return await call_next(request)

        # Process request (trace is set up at this point)
        try:
            response = await call_next(request)
            status_code = response.status_code

            # End span successfully (creates independent observability session)
            if span_id:
                try:
                    self.service.end_span(
                        span_id,
                        status="ok" if status_code < 400 else "error",
                        attributes={
                            "http.status_code": status_code,
                            "http.response_size": response.headers.get("content-length"),
                        },
                    )
                except Exception as end_span_error:
                    logger.warning(f"Failed to end span {span_id}: {end_span_error}")

            # End trace (creates independent observability session)
            if trace_id:
                duration_ms = (time.time() - start_time) * 1000
                try:
                    self.service.end_trace(
                        trace_id,
                        status="ok" if status_code < 400 else "error",
                        http_status_code=status_code,
                        attributes={"response_time_ms": duration_ms},
                    )
                except Exception as end_trace_error:
                    logger.warning(f"Failed to end trace {trace_id}: {end_trace_error}")

            return response

        except Exception as e:
            # Log exception in span
            if span_id:
                try:
                    sanitized_error = sanitize_for_log(sanitize_trace_text(str(e)))
                    self.service.end_span(
                        span_id,
                        status="error",
                        status_message=sanitized_error,
                        attributes={
                            "exception.type": type(e).__name__,
                            "exception.message": sanitized_error,
                        },
                    )

                    # Add exception event (creates independent observability session)
                    self.service.add_event(
                        span_id,
                        name="exception",
                        severity="error",
                        message=sanitized_error,
                        exception_type=type(e).__name__,
                        exception_message=sanitized_error,
                        exception_stacktrace=traceback.format_exc(),
                    )
                except Exception as log_error:
                    logger.warning(f"Failed to log exception in span: {log_error}")

            # End trace with error (creates independent observability session)
            if trace_id:
                try:
                    sanitized_error = sanitize_for_log(sanitize_trace_text(str(e)))
                    self.service.end_trace(
                        trace_id,
                        status="error",
                        status_message=sanitized_error,
                        http_status_code=500,
                    )
                except Exception as trace_error:
                    logger.warning(f"Failed to end trace: {trace_error}")

            # Re-raise the original exception
            raise
