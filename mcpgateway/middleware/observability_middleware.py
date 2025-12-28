# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/observability_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Observability Middleware for automatic request/response tracing.

This middleware automatically captures HTTP requests and responses as observability traces,
providing comprehensive visibility into all gateway operations.

Examples:
    >>> from mcpgateway.middleware.observability_middleware import ObservabilityMiddleware  # doctest: +SKIP
    >>> app.add_middleware(ObservabilityMiddleware)  # doctest: +SKIP
"""

# Standard
import logging
import time
import traceback
from typing import Callable

# Third-Party
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal
from mcpgateway.instrumentation.sqlalchemy import attach_trace_to_session
from mcpgateway.services.observability_service import current_trace_id, ObservabilityService, parse_traceparent

logger = logging.getLogger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware for automatic HTTP request/response tracing.

    Captures every HTTP request as a trace with timing, status codes,
    and user context. Automatically creates spans for the request lifecycle.

    This middleware is disabled by default and can be enabled via the
    MCPGATEWAY_OBSERVABILITY_ENABLED environment variable.
    """

    def __init__(self, app, enabled: bool = None):
        """Initialize the observability middleware.

        Args:
            app: ASGI application
            enabled: Whether observability is enabled (defaults to settings)
        """
        super().__init__(app)
        self.enabled = enabled if enabled is not None else getattr(settings, "observability_enabled", False)
        self.service = ObservabilityService()
        logger.info(f"Observability middleware initialized (enabled={self.enabled})")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and create observability trace.

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
        if request.url.path in ["/health", "/healthz", "/ready", "/metrics"] or request.url.path.startswith("/static/"):
            return await call_next(request)

        # Extract request context
        http_method = request.method
        http_url = str(request.url)
        user_email = None
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

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

        db = None
        trace_id = None
        span_id = None
        start_time = time.time()

        try:
            # Create database session
            db = SessionLocal()

            # Start trace (use external trace_id if provided for distributed tracing)
            trace_id = self.service.start_trace(
                db=db,
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
                    "http.query": str(request.url.query) if request.url.query else None,
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

            # Attach trace_id to database session for SQL query instrumentation
            attach_trace_to_session(db, trace_id)

            # Start request span
            span_id = self.service.start_span(db=db, trace_id=trace_id, name="http.request", kind="server", attributes={"http.method": http_method, "http.url": http_url})

        except Exception as e:
            # If trace setup failed, log and continue without tracing
            logger.warning(f"Failed to setup observability trace: {e}")
            # Close db if it was created
            if db:
                try:
                    db.rollback()  # Error path - rollback any partial transaction
                    db.close()
                except Exception as close_error:
                    logger.debug(f"Failed to close database session during cleanup: {close_error}")
            # Continue without tracing
            return await call_next(request)

        # Process request (trace is set up at this point)
        try:
            response = await call_next(request)
            status_code = response.status_code

            # End span successfully
            if span_id:
                self.service.end_span(
                    db, span_id, status="ok" if status_code < 400 else "error", attributes={"http.status_code": status_code, "http.response_size": response.headers.get("content-length")}
                )

            # End trace
            if trace_id:
                duration_ms = (time.time() - start_time) * 1000
                self.service.end_trace(db, trace_id, status="ok" if status_code < 400 else "error", http_status_code=status_code, attributes={"response_time_ms": duration_ms})

            return response

        except Exception as e:
            # Log exception in span
            if span_id:
                try:
                    self.service.end_span(db, span_id, status="error", status_message=str(e), attributes={"exception.type": type(e).__name__, "exception.message": str(e)})

                    # Add exception event
                    self.service.add_event(
                        db,
                        span_id,
                        name="exception",
                        severity="error",
                        message=str(e),
                        exception_type=type(e).__name__,
                        exception_message=str(e),
                        exception_stacktrace=traceback.format_exc(),
                    )
                except Exception as log_error:
                    logger.warning(f"Failed to log exception in span: {log_error}")

            # End trace with error
            if trace_id:
                try:
                    self.service.end_trace(db, trace_id, status="error", status_message=str(e), http_status_code=500)
                except Exception as trace_error:
                    logger.warning(f"Failed to end trace: {trace_error}")

            # Re-raise the original exception
            raise

        finally:
            # Always close database session - observability service handles its own commits
            if db:
                try:
                    db.commit()  # End transaction cleanly
                    db.close()
                except Exception as close_error:
                    logger.warning(f"Failed to close database session: {close_error}")
