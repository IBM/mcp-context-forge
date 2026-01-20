# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/observability_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Observability Service Implementation.
This module provides OpenTelemetry-style observability for MCP Gateway,
capturing traces, spans, events, and metrics for all operations.

It includes:
- Trace creation and management
- Span tracking with hierarchical nesting
- Event logging within spans
- Metrics collection and storage
- Query and filtering capabilities
- Integration with FastAPI middleware

Examples:
    >>> from mcpgateway.services.observability_service import ObservabilityService  # doctest: +SKIP
    >>> service = ObservabilityService()  # doctest: +SKIP
    >>> trace_id = service.start_trace(db, "GET /tools", http_method="GET", http_url="/tools")  # doctest: +SKIP
    >>> span_id = service.start_span(db, trace_id, "database_query", resource_type="database")  # doctest: +SKIP
    >>> service.end_span(db, span_id, status="ok")  # doctest: +SKIP
    >>> service.end_trace(db, trace_id, status="ok", http_status_code=200)  # doctest: +SKIP
"""

# Standard
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import logging
import re
import traceback
from typing import Any, Dict, List, Optional, Pattern, Tuple
import uuid

# Third-Party
from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, Session

# First-Party
from mcpgateway.db import ObservabilityEvent, ObservabilityMetric, ObservabilitySpan, ObservabilityTrace

logger = logging.getLogger(__name__)

# Precompiled regex for W3C Trace Context traceparent header parsing
# Format: version-trace_id-parent_id-trace_flags
_TRACEPARENT_RE: Pattern[str] = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")

# Context variable for tracking the current trace_id across async calls
current_trace_id: ContextVar[Optional[str]] = ContextVar("current_trace_id", default=None)


def utc_now() -> datetime:
    """Return current UTC time with timezone.

    Returns:
        datetime: Current time in UTC with timezone info
    """
    return datetime.now(timezone.utc)


def ensure_timezone_aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UTC).

    SQLite returns naive datetimes even when stored with timezone info.
    This helper ensures consistency for datetime arithmetic.

    Args:
        dt: Datetime that may be naive or aware

    Returns:
        Timezone-aware datetime in UTC
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_traceparent(traceparent: str) -> Optional[Tuple[str, str, str]]:
    """Parse W3C Trace Context traceparent header.

    Format: version-trace_id-parent_id-trace_flags
    Example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01

    Args:
        traceparent: W3C traceparent header value

    Returns:
        Tuple of (trace_id, parent_span_id, trace_flags) or None if invalid

    Examples:
        >>> parse_traceparent("00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")  # doctest: +SKIP
        ('0af7651916cd43dd8448eb211c80319c', 'b7ad6b7169203331', '01')
    """
    # W3C Trace Context format: 00-trace_id(32hex)-parent_id(16hex)-flags(2hex)
    # Uses precompiled regex for performance
    match = _TRACEPARENT_RE.match(traceparent.lower())

    if not match:
        logger.warning(f"Invalid traceparent format: {traceparent}")
        return None

    version, trace_id, parent_id, flags = match.groups()

    # Only support version 00 for now
    if version != "00":
        logger.warning(f"Unsupported traceparent version: {version}")
        return None

    # Validate trace_id and parent_id are not all zeros
    if trace_id == "0" * 32 or parent_id == "0" * 16:
        logger.warning("Invalid traceparent with zero trace_id or parent_id")
        return None

    return (trace_id, parent_id, flags)


def generate_w3c_trace_id() -> str:
    """Generate a W3C compliant trace ID (32 hex characters).

    Returns:
        32-character lowercase hex string

    Examples:
        >>> trace_id = generate_w3c_trace_id()  # doctest: +SKIP
        >>> len(trace_id)  # doctest: +SKIP
        32
    """
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]


def generate_w3c_span_id() -> str:
    """Generate a W3C compliant span ID (16 hex characters).

    Returns:
        16-character lowercase hex string

    Examples:
        >>> span_id = generate_w3c_span_id()  # doctest: +SKIP
        >>> len(span_id)  # doctest: +SKIP
        16
    """
    return uuid.uuid4().hex[:16]


def format_traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    """Format a W3C traceparent header value.

    Args:
        trace_id: 32-character hex trace ID
        span_id: 16-character hex span ID
        sampled: Whether the trace is sampled (affects trace-flags)

    Returns:
        W3C traceparent header value

    Examples:
        >>> format_traceparent("0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331")  # doctest: +SKIP
        '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01'
    """
    flags = "01" if sampled else "00"
    return f"00-{trace_id}-{span_id}-{flags}"


class ObservabilityService:
    """Service for managing observability traces, spans, events, and metrics.

    This service provides comprehensive observability capabilities similar to
    OpenTelemetry, allowing tracking of request flows through the system.

    Examples:
        >>> service = ObservabilityService()  # doctest: +SKIP
        >>> trace_id = service.start_trace(db, "POST /tools/invoke")  # doctest: +SKIP
        >>> span_id = service.start_span(db, trace_id, "tool_execution")  # doctest: +SKIP
        >>> service.end_span(db, span_id, status="ok")  # doctest: +SKIP
        >>> service.end_trace(db, trace_id, status="ok")  # doctest: +SKIP
    """

    def _safe_commit(self, db: Session, context: str) -> bool:
        """Commit and rollback on failure without raising.

        Args:
            db: SQLAlchemy session for the current operation.
            context: Short label for the commit context (used in logs).

        Returns:
            True when commit succeeds, False when a rollback was performed.
        """
        try:
            db.commit()
            return True
        except SQLAlchemyError as exc:
            logger.warning(f"Observability commit failed ({context}): {exc}")
            try:
                db.rollback()
            except SQLAlchemyError as rollback_exc:
                logger.debug(f"Observability rollback failed ({context}): {rollback_exc}")
            return False

    # ==============================
    # Trace Management
    # ==============================

    def start_trace(
        self,
        db: Session,
        name: str,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        http_method: Optional[str] = None,
        http_url: Optional[str] = None,
        user_email: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        resource_attributes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a new trace.

        Args:
            db: Database session
            name: Trace name (e.g., "POST /tools/invoke")
            trace_id: External trace ID (for distributed tracing, W3C format)
            parent_span_id: Parent span ID from upstream service
            http_method: HTTP method (GET, POST, etc.)
            http_url: Full request URL
            user_email: Authenticated user email
            user_agent: Client user agent string
            ip_address: Client IP address
            attributes: Additional trace attributes
            resource_attributes: Resource attributes (service name, version, etc.)

        Returns:
            Trace ID (UUID string or W3C format)

        Examples:
            >>> trace_id = service.start_trace(  # doctest: +SKIP
            ...     db,
            ...     "POST /tools/invoke",
            ...     http_method="POST",
            ...     http_url="https://api.example.com/tools/invoke",
            ...     user_email="user@example.com"
            ... )
        """
        # Use provided trace_id or generate new UUID
        if not trace_id:
            trace_id = str(uuid.uuid4())

        # Add parent context to attributes if provided
        attrs = attributes or {}
        if parent_span_id:
            attrs["parent_span_id"] = parent_span_id

        trace = ObservabilityTrace(
            trace_id=trace_id,
            name=name,
            start_time=utc_now(),
            status="unset",
            http_method=http_method,
            http_url=http_url,
            user_email=user_email,
            user_agent=user_agent,
            ip_address=ip_address,
            attributes=attrs,
            resource_attributes=resource_attributes or {},
            created_at=utc_now(),
        )
        db.add(trace)
        self._safe_commit(db, "start_trace")
        logger.debug(f"Started trace {trace_id}: {name}")
        return trace_id

    def end_trace(
        self,
        db: Session,
        trace_id: str,
        status: str = "ok",
        status_message: Optional[str] = None,
        http_status_code: Optional[int] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """End a trace.

        Args:
            db: Database session
            trace_id: Trace ID to end
            status: Trace status (ok, error)
            status_message: Optional status message
            http_status_code: HTTP response status code
            attributes: Additional attributes to merge

        Examples:
            >>> service.end_trace(  # doctest: +SKIP
            ...     db,
            ...     trace_id,
            ...     status="ok",
            ...     http_status_code=200
            ... )
        """
        trace = db.query(ObservabilityTrace).filter_by(trace_id=trace_id).first()
        if not trace:
            logger.warning(f"Trace {trace_id} not found")
            return

        end_time = utc_now()
        duration_ms = (end_time - ensure_timezone_aware(trace.start_time)).total_seconds() * 1000

        trace.end_time = end_time
        trace.duration_ms = duration_ms
        trace.status = status
        trace.status_message = status_message
        if http_status_code is not None:
            trace.http_status_code = http_status_code
        if attributes:
            trace.attributes = {**(trace.attributes or {}), **attributes}

        self._safe_commit(db, "end_trace")
        logger.debug(f"Ended trace {trace_id}: {status} ({duration_ms:.2f}ms)")

    def get_trace(self, db: Session, trace_id: str, include_spans: bool = False) -> Optional[ObservabilityTrace]:
        """Get a trace by ID.

        Args:
            db: Database session
            trace_id: Trace ID
            include_spans: Whether to load spans eagerly

        Returns:
            Trace object or None if not found

        Examples:
            >>> trace = service.get_trace(db, trace_id, include_spans=True)  # doctest: +SKIP
            >>> if trace:  # doctest: +SKIP
            ...     print(f"Trace: {trace.name}, Spans: {len(trace.spans)}")  # doctest: +SKIP
        """
        query = db.query(ObservabilityTrace).filter_by(trace_id=trace_id)
        if include_spans:
            query = query.options(joinedload(ObservabilityTrace.spans))
        return query.first()

    # ==============================
    # Span Management
    # ==============================

    def start_span(
        self,
        db: Session,
        trace_id: str,
        name: str,
        parent_span_id: Optional[str] = None,
        kind: str = "internal",
        resource_name: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        commit: bool = True,
    ) -> str:
        """Start a new span within a trace.

        Args:
            db: Database session
            trace_id: Parent trace ID
            name: Span name (e.g., "database_query", "tool_invocation")
            parent_span_id: Parent span ID (for nested spans)
            kind: Span kind (internal, server, client, producer, consumer)
            resource_name: Resource name being operated on
            resource_type: Resource type (tool, resource, prompt, etc.)
            resource_id: Resource ID
            attributes: Additional span attributes
            commit: Whether to commit the transaction (default True).
                Set to False when using fresh_db_session() which handles commits.

        Returns:
            Span ID (UUID string)

        Examples:
            >>> span_id = service.start_span(  # doctest: +SKIP
            ...     db,
            ...     trace_id,
            ...     "tool_invocation",
            ...     resource_type="tool",
            ...     resource_name="get_weather"
            ... )
        """
        span_id = str(uuid.uuid4())
        span = ObservabilitySpan(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
            start_time=utc_now(),
            status="unset",
            resource_name=resource_name,
            resource_type=resource_type,
            resource_id=resource_id,
            attributes=attributes or {},
            created_at=utc_now(),
        )
        db.add(span)
        if commit:
            self._safe_commit(db, "start_span")
        logger.debug(f"Started span {span_id}: {name} (trace={trace_id})")
        return span_id

    def end_span(
        self,
        db: Session,
        span_id: str,
        status: str = "ok",
        status_message: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        commit: bool = True,
    ) -> None:
        """End a span.

        Args:
            db: Database session
            span_id: Span ID to end
            status: Span status (ok, error)
            status_message: Optional status message
            attributes: Additional attributes to merge
            commit: Whether to commit the transaction (default True).
                Set to False when using fresh_db_session() which handles commits.

        Examples:
            >>> service.end_span(db, span_id, status="ok")  # doctest: +SKIP
        """
        span = db.query(ObservabilitySpan).filter_by(span_id=span_id).first()
        if not span:
            logger.warning(f"Span {span_id} not found")
            return

        end_time = utc_now()
        duration_ms = (end_time - ensure_timezone_aware(span.start_time)).total_seconds() * 1000

        span.end_time = end_time
        span.duration_ms = duration_ms
        span.status = status
        span.status_message = status_message
        if attributes:
            span.attributes = {**(span.attributes or {}), **attributes}

        if commit:
            self._safe_commit(db, "end_span")
        logger.debug(f"Ended span {span_id}: {status} ({duration_ms:.2f}ms)")

    @contextmanager
    def trace_span(
        self,
        db: Session,
        trace_id: str,
        name: str,
        parent_span_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Context manager for automatic span lifecycle management.

        Args:
            db: Database session
            trace_id: Parent trace ID
            name: Span name
            parent_span_id: Parent span ID (optional)
            resource_type: Resource type
            resource_name: Resource name
            attributes: Additional attributes

        Yields:
            Span ID

        Raises:
            Exception: Re-raises any exception after logging it in the span

        Examples:
            >>> with service.trace_span(db, trace_id, "database_query") as span_id:  # doctest: +SKIP
            ...     results = db.query(Tool).all()  # doctest: +SKIP
        """
        span_id = self.start_span(db, trace_id, name, parent_span_id, resource_type=resource_type, resource_name=resource_name, attributes=attributes)
        try:
            yield span_id
            self.end_span(db, span_id, status="ok")
        except Exception as e:
            self.end_span(db, span_id, status="error", status_message=str(e))
            self.add_event(db, span_id, "exception", severity="error", message=str(e), exception_type=type(e).__name__, exception_message=str(e), exception_stacktrace=traceback.format_exc())
            raise

    @contextmanager
    def trace_tool_invocation(
        self,
        db: Session,
        tool_name: str,
        arguments: Dict[str, Any],
        integration_type: Optional[str] = None,
    ):
        """Context manager for tracing MCP tool invocations.

        This automatically creates a span for tool execution, capturing timing,
        arguments, results, and errors.

        Args:
            db: Database session
            tool_name: Name of the tool being invoked
            arguments: Tool arguments (will be sanitized)
            integration_type: Integration type (MCP, REST, A2A, etc.)

        Yields:
            Tuple of (span_id, result_dict) - update result_dict with tool results

        Raises:
            Exception: Re-raises any exception from tool invocation after logging

        Examples:
            >>> with service.trace_tool_invocation(db, "weather", {"city": "NYC"}) as (span_id, result):  # doctest: +SKIP
            ...     response = await http_client.post(...)  # doctest: +SKIP
            ...     result["status_code"] = response.status_code  # doctest: +SKIP
            ...     result["response_size"] = len(response.content)  # doctest: +SKIP
        """
        trace_id = current_trace_id.get()
        if not trace_id:
            # No active trace, yield a no-op
            result_dict: Dict[str, Any] = {}
            yield (None, result_dict)
            return

        # Sanitize arguments (remove sensitive data)
        safe_args = {k: ("***REDACTED***" if any(sensitive in k.lower() for sensitive in ["password", "token", "key", "secret"]) else v) for k, v in arguments.items()}

        # Start tool invocation span
        span_id = self.start_span(
            db=db,
            trace_id=trace_id,
            name=f"tool.invoke.{tool_name}",
            kind="client",
            resource_type="tool",
            resource_name=tool_name,
            attributes={
                "tool.name": tool_name,
                "tool.integration_type": integration_type,
                "tool.argument_count": len(arguments),
                "tool.arguments": safe_args,
            },
        )

        result_dict = {}
        try:
            yield (span_id, result_dict)

            # End span with results
            self.end_span(
                db=db,
                span_id=span_id,
                status="ok",
                attributes={
                    "tool.result": result_dict,
                },
            )
        except Exception as e:
            # Log error in span
            self.end_span(db=db, span_id=span_id, status="error", status_message=str(e))

            self.add_event(
                db=db,
                span_id=span_id,
                name="tool.error",
                severity="error",
                message=str(e),
                exception_type=type(e).__name__,
                exception_message=str(e),
                exception_stacktrace=traceback.format_exc(),
            )
            raise

    # ==============================
    # Event Management
    # ==============================

    def add_event(
        self,
        db: Session,
        span_id: str,
        name: str,
        severity: Optional[str] = None,
        message: Optional[str] = None,
        exception_type: Optional[str] = None,
        exception_message: Optional[str] = None,
        exception_stacktrace: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Add an event to a span.

        Args:
            db: Database session
            span_id: Parent span ID
            name: Event name
            severity: Log severity (debug, info, warning, error, critical)
            message: Event message
            exception_type: Exception class name
            exception_message: Exception message
            exception_stacktrace: Exception stacktrace
            attributes: Additional event attributes

        Returns:
            Event ID

        Examples:
            >>> event_id = service.add_event(  # doctest: +SKIP
            ...     db,  # doctest: +SKIP
            ...     span_id,  # doctest: +SKIP
            ...     "database_connection_error",  # doctest: +SKIP
            ...     severity="error",  # doctest: +SKIP
            ...     message="Failed to connect to database"  # doctest: +SKIP
            ... )  # doctest: +SKIP
        """
        event = ObservabilityEvent(
            span_id=span_id,
            name=name,
            timestamp=utc_now(),
            severity=severity,
            message=message,
            exception_type=exception_type,
            exception_message=exception_message,
            exception_stacktrace=exception_stacktrace,
            attributes=attributes or {},
            created_at=utc_now(),
        )
        db.add(event)
        if not self._safe_commit(db, "add_event"):
            return 0
        db.refresh(event)
        logger.debug(f"Added event to span {span_id}: {name}")
        return event.id

    # ==============================
    # Token Usage Tracking
    # ==============================

    def record_token_usage(
        self,
        db: Session,
        span_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        model: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: Optional[int] = None,
        estimated_cost_usd: Optional[float] = None,
        provider: Optional[str] = None,
    ) -> None:
        """Record token usage for LLM calls.

        Args:
            db: Database session
            span_id: Span ID to attach token usage to
            trace_id: Trace ID (will use current context if not provided)
            model: Model name (e.g., "gpt-4", "claude-3-opus")
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens
            total_tokens: Total tokens (calculated if not provided)
            estimated_cost_usd: Estimated cost in USD
            provider: LLM provider (openai, anthropic, etc.)

        Examples:
            >>> service.record_token_usage(  # doctest: +SKIP
            ...     db, span_id="abc123",
            ...     model="gpt-4",
            ...     input_tokens=100,
            ...     output_tokens=50,
            ...     estimated_cost_usd=0.015
            ... )
        """
        if not trace_id:
            trace_id = current_trace_id.get()

        if not trace_id:
            logger.warning("Cannot record token usage: no active trace")
            return

        # Calculate total if not provided
        if total_tokens is None:
            total_tokens = input_tokens + output_tokens

        # Estimate cost if not provided and we have model info
        if estimated_cost_usd is None and model:
            estimated_cost_usd = self._estimate_token_cost(model, input_tokens, output_tokens)

        # Store in span attributes if span_id provided
        if span_id:
            span = db.query(ObservabilitySpan).filter_by(span_id=span_id).first()
            if span:
                attrs = span.attributes or {}
                attrs.update(
                    {
                        "llm.model": model,
                        "llm.provider": provider,
                        "llm.input_tokens": input_tokens,
                        "llm.output_tokens": output_tokens,
                        "llm.total_tokens": total_tokens,
                        "llm.estimated_cost_usd": estimated_cost_usd,
                    }
                )
                span.attributes = attrs
                self._safe_commit(db, "record_token_usage")

        # Also record as metrics for aggregation
        if input_tokens > 0:
            self.record_metric(
                db=db,
                name="llm.tokens.input",
                value=float(input_tokens),
                metric_type="counter",
                unit="tokens",
                trace_id=trace_id,
                attributes={"model": model, "provider": provider},
            )

        if output_tokens > 0:
            self.record_metric(
                db=db,
                name="llm.tokens.output",
                value=float(output_tokens),
                metric_type="counter",
                unit="tokens",
                trace_id=trace_id,
                attributes={"model": model, "provider": provider},
            )

        if estimated_cost_usd:
            self.record_metric(
                db=db,
                name="llm.cost",
                value=estimated_cost_usd,
                metric_type="counter",
                unit="usd",
                trace_id=trace_id,
                attributes={"model": model, "provider": provider},
            )

        logger.debug(f"Recorded token usage: {input_tokens} in, {output_tokens} out, ${estimated_cost_usd:.6f}")

    def _estimate_token_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on model and token counts.

        Pricing as of January 2025 (prices may change).

        Args:
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count

        Returns:
            Estimated cost in USD
        """
        # Pricing per 1M tokens (input, output)
        pricing = {
            # OpenAI
            "gpt-4": (30.0, 60.0),
            "gpt-4-turbo": (10.0, 30.0),
            "gpt-4o": (2.5, 10.0),
            "gpt-4o-mini": (0.15, 0.60),
            "gpt-3.5-turbo": (0.50, 1.50),
            # Anthropic
            "claude-3-opus": (15.0, 75.0),
            "claude-3-sonnet": (3.0, 15.0),
            "claude-3-haiku": (0.25, 1.25),
            "claude-3.5-sonnet": (3.0, 15.0),
            "claude-3.5-haiku": (0.80, 4.0),
            # Fallback for unknown models
            "default": (1.0, 3.0),
        }

        # Find matching pricing (case-insensitive, partial match)
        model_lower = model.lower()
        input_price, output_price = pricing.get("default")

        for model_key, prices in pricing.items():
            if model_key in model_lower:
                input_price, output_price = prices
                break

        # Calculate cost (pricing is per 1M tokens)
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price

        return input_cost + output_cost

    # ==============================
    # Agent-to-Agent (A2A) Tracing
    # ==============================

    @contextmanager
    def trace_a2a_request(
        self,
        db: Session,
        agent_id: str,
        agent_name: Optional[str] = None,
        operation: Optional[str] = None,
        request_data: Optional[Dict[str, Any]] = None,
    ):
        """Context manager for tracing Agent-to-Agent requests.

        This automatically creates a span for A2A communication, capturing timing,
        request/response data, and errors.

        Args:
            db: Database session
            agent_id: Target agent ID
            agent_name: Human-readable agent name
            operation: Operation being performed (e.g., "query", "execute", "status")
            request_data: Request payload (will be sanitized)

        Yields:
            Tuple of (span_id, result_dict) - update result_dict with A2A results

        Raises:
            Exception: Re-raises any exception from A2A call after logging

        Examples:
            >>> with service.trace_a2a_request(db, "agent-123", "WeatherAgent", "query") as (span_id, result):  # doctest: +SKIP
            ...     response = await http_client.post(...)  # doctest: +SKIP
            ...     result["status_code"] = response.status_code  # doctest: +SKIP
            ...     result["response_time_ms"] = 45.2  # doctest: +SKIP
        """
        trace_id = current_trace_id.get()
        if not trace_id:
            # No active trace, yield a no-op
            result_dict: Dict[str, Any] = {}
            yield (None, result_dict)
            return

        # Sanitize request data
        safe_data = {}
        if request_data:
            safe_data = {k: ("***REDACTED***" if any(sensitive in k.lower() for sensitive in ["password", "token", "key", "secret", "auth"]) else v) for k, v in request_data.items()}

        # Start A2A span
        span_id = self.start_span(
            db=db,
            trace_id=trace_id,
            name=f"a2a.call.{agent_name or agent_id}",
            kind="client",
            resource_type="agent",
            resource_name=agent_name or agent_id,
            attributes={
                "a2a.agent_id": agent_id,
                "a2a.agent_name": agent_name,
                "a2a.operation": operation,
                "a2a.request_data": safe_data,
            },
        )

        result_dict = {}
        try:
            yield (span_id, result_dict)

            # End span with results
            self.end_span(
                db=db,
                span_id=span_id,
                status="ok",
                attributes={
                    "a2a.result": result_dict,
                },
            )
        except Exception as e:
            # Log error in span
            self.end_span(db=db, span_id=span_id, status="error", status_message=str(e))

            self.add_event(
                db=db,
                span_id=span_id,
                name="a2a.error",
                severity="error",
                message=str(e),
                exception_type=type(e).__name__,
                exception_message=str(e),
                exception_stacktrace=traceback.format_exc(),
            )
            raise

    # ==============================
    # Transport Metrics
    # ==============================

    def record_transport_activity(
        self,
        db: Session,
        transport_type: str,
        operation: str,
        message_count: int = 1,
        bytes_sent: Optional[int] = None,
        bytes_received: Optional[int] = None,
        connection_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Record transport-specific activity metrics.

        Args:
            db: Database session
            transport_type: Transport type (sse, websocket, stdio, http)
            operation: Operation type (connect, disconnect, send, receive, error)
            message_count: Number of messages processed
            bytes_sent: Bytes sent (if applicable)
            bytes_received: Bytes received (if applicable)
            connection_id: Connection/session identifier
            error: Error message if operation failed

        Examples:
            >>> service.record_transport_activity(  # doctest: +SKIP
            ...     db, transport_type="sse",
            ...     operation="send",
            ...     message_count=1,
            ...     bytes_sent=1024
            ... )
        """
        trace_id = current_trace_id.get()

        # Record message count
        if message_count > 0:
            self.record_metric(
                db=db,
                name=f"transport.{transport_type}.messages",
                value=float(message_count),
                metric_type="counter",
                unit="messages",
                trace_id=trace_id,
                attributes={
                    "transport": transport_type,
                    "operation": operation,
                    "connection_id": connection_id,
                },
            )

        # Record bytes sent
        if bytes_sent:
            self.record_metric(
                db=db,
                name=f"transport.{transport_type}.bytes_sent",
                value=float(bytes_sent),
                metric_type="counter",
                unit="bytes",
                trace_id=trace_id,
                attributes={
                    "transport": transport_type,
                    "operation": operation,
                    "connection_id": connection_id,
                },
            )

        # Record bytes received
        if bytes_received:
            self.record_metric(
                db=db,
                name=f"transport.{transport_type}.bytes_received",
                value=float(bytes_received),
                metric_type="counter",
                unit="bytes",
                trace_id=trace_id,
                attributes={
                    "transport": transport_type,
                    "operation": operation,
                    "connection_id": connection_id,
                },
            )

        # Record errors
        if error:
            self.record_metric(
                db=db,
                name=f"transport.{transport_type}.errors",
                value=1.0,
                metric_type="counter",
                unit="errors",
                trace_id=trace_id,
                attributes={
                    "transport": transport_type,
                    "operation": operation,
                    "connection_id": connection_id,
                    "error": error,
                },
            )

        logger.debug(f"Recorded {transport_type} transport activity: {operation} ({message_count} messages)")

    # ==============================
    # Metric Management
    # ==============================

    def record_metric(
        self,
        db: Session,
        name: str,
        value: float,
        metric_type: str = "gauge",
        unit: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record a metric.

        Args:
            db: Database session
            name: Metric name (e.g., "http.request.duration")
            value: Metric value
            metric_type: Metric type (counter, gauge, histogram)
            unit: Metric unit (ms, count, bytes, etc.)
            resource_type: Resource type
            resource_id: Resource ID
            trace_id: Associated trace ID
            attributes: Additional metric attributes/labels

        Returns:
            Metric ID

        Examples:
            >>> metric_id = service.record_metric(  # doctest: +SKIP
            ...     db,  # doctest: +SKIP
            ...     "http.request.duration",  # doctest: +SKIP
            ...     123.45,  # doctest: +SKIP
            ...     metric_type="histogram",  # doctest: +SKIP
            ...     unit="ms",  # doctest: +SKIP
            ...     trace_id=trace_id  # doctest: +SKIP
            ... )  # doctest: +SKIP
        """
        metric = ObservabilityMetric(
            name=name,
            value=value,
            metric_type=metric_type,
            timestamp=utc_now(),
            unit=unit,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=trace_id,
            attributes=attributes or {},
            created_at=utc_now(),
        )
        db.add(metric)
        if not self._safe_commit(db, "record_metric"):
            return 0
        db.refresh(metric)
        logger.debug(f"Recorded metric: {name} = {value} {unit or ''}")
        return metric.id

    # ==============================
    # Query Methods
    # ==============================

    # pylint: disable=too-many-positional-arguments,too-many-arguments,too-many-locals
    def query_traces(
        self,
        db: Session,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        min_duration_ms: Optional[float] = None,
        max_duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        status_in: Optional[List[str]] = None,
        status_not_in: Optional[List[str]] = None,
        http_status_code: Optional[int] = None,
        http_status_code_in: Optional[List[int]] = None,
        http_method: Optional[str] = None,
        http_method_in: Optional[List[str]] = None,
        user_email: Optional[str] = None,
        user_email_in: Optional[List[str]] = None,
        attribute_filters: Optional[Dict[str, Any]] = None,
        attribute_filters_or: Optional[Dict[str, Any]] = None,
        attribute_search: Optional[str] = None,
        name_contains: Optional[str] = None,
        order_by: str = "start_time_desc",
        limit: int = 100,
        offset: int = 0,
    ) -> List[ObservabilityTrace]:
        """Query traces with advanced filters.

        Supports both simple filters (single value) and list filters (multiple values with OR logic).
        All top-level filters are combined with AND logic unless using _or suffix.

        Args:
            db: Database session
            start_time: Filter traces after this time
            end_time: Filter traces before this time
            min_duration_ms: Filter traces with duration >= this value (milliseconds)
            max_duration_ms: Filter traces with duration <= this value (milliseconds)
            status: Filter by single status (ok, error)
            status_in: Filter by multiple statuses (OR logic)
            status_not_in: Exclude these statuses (NOT logic)
            http_status_code: Filter by single HTTP status code
            http_status_code_in: Filter by multiple HTTP status codes (OR logic)
            http_method: Filter by single HTTP method (GET, POST, etc.)
            http_method_in: Filter by multiple HTTP methods (OR logic)
            user_email: Filter by single user email
            user_email_in: Filter by multiple user emails (OR logic)
            attribute_filters: JSON attribute filters (AND logic - all must match)
            attribute_filters_or: JSON attribute filters (OR logic - any must match)
            attribute_search: Free-text search within JSON attributes (partial match)
            name_contains: Filter traces where name contains this substring
            order_by: Sort order (start_time_desc, start_time_asc, duration_desc, duration_asc)
            limit: Maximum results (1-1000)
            offset: Result offset

        Returns:
            List of traces

        Raises:
            ValueError: If invalid parameters are provided

        Examples:
            >>> # Find slow errors from multiple endpoints
            >>> traces = service.query_traces(  # doctest: +SKIP
            ...     db,
            ...     status="error",
            ...     min_duration_ms=100.0,
            ...     http_method_in=["POST", "PUT"],
            ...     attribute_filters={"http.route": "/api/tools"},
            ...     limit=50
            ... )
            >>> # Exclude health checks and find slow requests
            >>> traces = service.query_traces(  # doctest: +SKIP
            ...     db,
            ...     min_duration_ms=1000.0,
            ...     name_contains="api",
            ...     status_not_in=["ok"],
            ...     order_by="duration_desc"
            ... )
        """
        # Third-Party
        # pylint: disable=import-outside-toplevel
        from sqlalchemy import cast, or_, String

        # pylint: enable=import-outside-toplevel
        # Validate limit
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

        # Validate order_by
        valid_orders = ["start_time_desc", "start_time_asc", "duration_desc", "duration_asc"]
        if order_by not in valid_orders:
            raise ValueError(f"order_by must be one of: {', '.join(valid_orders)}")

        query = db.query(ObservabilityTrace)

        # Time range filters
        if start_time:
            query = query.filter(ObservabilityTrace.start_time >= start_time)
        if end_time:
            query = query.filter(ObservabilityTrace.start_time <= end_time)

        # Duration filters
        if min_duration_ms is not None:
            query = query.filter(ObservabilityTrace.duration_ms >= min_duration_ms)
        if max_duration_ms is not None:
            query = query.filter(ObservabilityTrace.duration_ms <= max_duration_ms)

        # Status filters (with OR and NOT support)
        if status:
            query = query.filter(ObservabilityTrace.status == status)
        if status_in:
            query = query.filter(ObservabilityTrace.status.in_(status_in))
        if status_not_in:
            query = query.filter(~ObservabilityTrace.status.in_(status_not_in))

        # HTTP status code filters (with OR support)
        if http_status_code:
            query = query.filter(ObservabilityTrace.http_status_code == http_status_code)
        if http_status_code_in:
            query = query.filter(ObservabilityTrace.http_status_code.in_(http_status_code_in))

        # HTTP method filters (with OR support)
        if http_method:
            query = query.filter(ObservabilityTrace.http_method == http_method)
        if http_method_in:
            query = query.filter(ObservabilityTrace.http_method.in_(http_method_in))

        # User email filters (with OR support)
        if user_email:
            query = query.filter(ObservabilityTrace.user_email == user_email)
        if user_email_in:
            query = query.filter(ObservabilityTrace.user_email.in_(user_email_in))

        # Name substring filter
        if name_contains:
            query = query.filter(ObservabilityTrace.name.ilike(f"%{name_contains}%"))

        # Attribute-based filtering with AND logic (all filters must match)
        if attribute_filters:
            for key, value in attribute_filters.items():
                # Use JSON path access for filtering
                # Supports both SQLite (via json_extract) and PostgreSQL (via ->>)
                query = query.filter(ObservabilityTrace.attributes[key].astext == str(value))

        # Attribute-based filtering with OR logic (any filter must match)
        if attribute_filters_or:
            or_conditions = []
            for key, value in attribute_filters_or.items():
                or_conditions.append(ObservabilityTrace.attributes[key].astext == str(value))
            if or_conditions:
                query = query.filter(or_(*or_conditions))

        # Free-text search across all attribute values
        if attribute_search:
            # Cast JSON attributes to text and search for substring
            # Works with both SQLite and PostgreSQL
            # Escape special characters to prevent SQL injection
            safe_search = attribute_search.replace("%", "\\%").replace("_", "\\_")
            query = query.filter(cast(ObservabilityTrace.attributes, String).ilike(f"%{safe_search}%"))

        # Apply ordering
        if order_by == "start_time_desc":
            query = query.order_by(desc(ObservabilityTrace.start_time))
        elif order_by == "start_time_asc":
            query = query.order_by(ObservabilityTrace.start_time)
        elif order_by == "duration_desc":
            query = query.order_by(desc(ObservabilityTrace.duration_ms))
        elif order_by == "duration_asc":
            query = query.order_by(ObservabilityTrace.duration_ms)

        # Apply pagination
        query = query.limit(limit).offset(offset)

        return query.all()

    # pylint: disable=too-many-positional-arguments,too-many-arguments,too-many-locals
    def query_spans(
        self,
        db: Session,
        trace_id: Optional[str] = None,
        trace_id_in: Optional[List[str]] = None,
        resource_type: Optional[str] = None,
        resource_type_in: Optional[List[str]] = None,
        resource_name: Optional[str] = None,
        resource_name_in: Optional[List[str]] = None,
        name_contains: Optional[str] = None,
        kind: Optional[str] = None,
        kind_in: Optional[List[str]] = None,
        status: Optional[str] = None,
        status_in: Optional[List[str]] = None,
        status_not_in: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        min_duration_ms: Optional[float] = None,
        max_duration_ms: Optional[float] = None,
        attribute_filters: Optional[Dict[str, Any]] = None,
        attribute_search: Optional[str] = None,
        order_by: str = "start_time_desc",
        limit: int = 100,
        offset: int = 0,
    ) -> List[ObservabilitySpan]:
        """Query spans with advanced filters.

        Supports filtering by trace, resource, kind, status, duration, and attributes.
        All top-level filters are combined with AND logic. List filters use OR logic.

        Args:
            db: Database session
            trace_id: Filter by single trace ID
            trace_id_in: Filter by multiple trace IDs (OR logic)
            resource_type: Filter by single resource type (tool, database, plugin, etc.)
            resource_type_in: Filter by multiple resource types (OR logic)
            resource_name: Filter by single resource name
            resource_name_in: Filter by multiple resource names (OR logic)
            name_contains: Filter spans where name contains this substring
            kind: Filter by span kind (client, server, internal)
            kind_in: Filter by multiple kinds (OR logic)
            status: Filter by single status (ok, error)
            status_in: Filter by multiple statuses (OR logic)
            status_not_in: Exclude these statuses (NOT logic)
            start_time: Filter spans after this time
            end_time: Filter spans before this time
            min_duration_ms: Filter spans with duration >= this value (milliseconds)
            max_duration_ms: Filter spans with duration <= this value (milliseconds)
            attribute_filters: JSON attribute filters (AND logic)
            attribute_search: Free-text search within JSON attributes
            order_by: Sort order (start_time_desc, start_time_asc, duration_desc, duration_asc)
            limit: Maximum results (1-1000)
            offset: Result offset

        Returns:
            List of spans

        Raises:
            ValueError: If invalid parameters are provided

        Examples:
            >>> # Find slow database queries
            >>> spans = service.query_spans(  # doctest: +SKIP
            ...     db,
            ...     resource_type="database",
            ...     min_duration_ms=100.0,
            ...     order_by="duration_desc",
            ...     limit=50
            ... )
            >>> # Find tool invocation errors
            >>> spans = service.query_spans(  # doctest: +SKIP
            ...     db,
            ...     resource_type="tool",
            ...     status="error",
            ...     name_contains="invoke"
            ... )
        """
        # Third-Party
        # pylint: disable=import-outside-toplevel
        from sqlalchemy import cast, String

        # pylint: enable=import-outside-toplevel
        # Validate limit
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

        # Validate order_by
        valid_orders = ["start_time_desc", "start_time_asc", "duration_desc", "duration_asc"]
        if order_by not in valid_orders:
            raise ValueError(f"order_by must be one of: {', '.join(valid_orders)}")

        query = db.query(ObservabilitySpan)

        # Trace ID filters (with OR support)
        if trace_id:
            query = query.filter(ObservabilitySpan.trace_id == trace_id)
        if trace_id_in:
            query = query.filter(ObservabilitySpan.trace_id.in_(trace_id_in))

        # Resource type filters (with OR support)
        if resource_type:
            query = query.filter(ObservabilitySpan.resource_type == resource_type)
        if resource_type_in:
            query = query.filter(ObservabilitySpan.resource_type.in_(resource_type_in))

        # Resource name filters (with OR support)
        if resource_name:
            query = query.filter(ObservabilitySpan.resource_name == resource_name)
        if resource_name_in:
            query = query.filter(ObservabilitySpan.resource_name.in_(resource_name_in))

        # Name substring filter
        if name_contains:
            query = query.filter(ObservabilitySpan.name.ilike(f"%{name_contains}%"))

        # Kind filters (with OR support)
        if kind:
            query = query.filter(ObservabilitySpan.kind == kind)
        if kind_in:
            query = query.filter(ObservabilitySpan.kind.in_(kind_in))

        # Status filters (with OR and NOT support)
        if status:
            query = query.filter(ObservabilitySpan.status == status)
        if status_in:
            query = query.filter(ObservabilitySpan.status.in_(status_in))
        if status_not_in:
            query = query.filter(~ObservabilitySpan.status.in_(status_not_in))

        # Time range filters
        if start_time:
            query = query.filter(ObservabilitySpan.start_time >= start_time)
        if end_time:
            query = query.filter(ObservabilitySpan.start_time <= end_time)

        # Duration filters
        if min_duration_ms is not None:
            query = query.filter(ObservabilitySpan.duration_ms >= min_duration_ms)
        if max_duration_ms is not None:
            query = query.filter(ObservabilitySpan.duration_ms <= max_duration_ms)

        # Attribute-based filtering with AND logic
        if attribute_filters:
            for key, value in attribute_filters.items():
                query = query.filter(ObservabilitySpan.attributes[key].astext == str(value))

        # Free-text search across all attribute values
        if attribute_search:
            safe_search = attribute_search.replace("%", "\\%").replace("_", "\\_")
            query = query.filter(cast(ObservabilitySpan.attributes, String).ilike(f"%{safe_search}%"))

        # Apply ordering
        if order_by == "start_time_desc":
            query = query.order_by(desc(ObservabilitySpan.start_time))
        elif order_by == "start_time_asc":
            query = query.order_by(ObservabilitySpan.start_time)
        elif order_by == "duration_desc":
            query = query.order_by(desc(ObservabilitySpan.duration_ms))
        elif order_by == "duration_asc":
            query = query.order_by(ObservabilitySpan.duration_ms)

        # Apply pagination
        query = query.limit(limit).offset(offset)

        return query.all()

    def get_trace_with_spans(self, db: Session, trace_id: str) -> Optional[ObservabilityTrace]:
        """Get a complete trace with all spans and events.

        Args:
            db: Database session
            trace_id: Trace ID

        Returns:
            Trace with spans and events loaded

        Examples:
            >>> trace = service.get_trace_with_spans(db, trace_id)  # doctest: +SKIP
            >>> if trace:  # doctest: +SKIP
            ...     for span in trace.spans:  # doctest: +SKIP
            ...         print(f"Span: {span.name}, Events: {len(span.events)}")  # doctest: +SKIP
        """
        return db.query(ObservabilityTrace).filter_by(trace_id=trace_id).options(joinedload(ObservabilityTrace.spans).joinedload(ObservabilitySpan.events)).first()

    def delete_old_traces(self, db: Session, before_time: datetime) -> int:
        """Delete traces older than a given time.

        Args:
            db: Database session
            before_time: Delete traces before this time

        Returns:
            Number of traces deleted

        Examples:
            >>> from datetime import timedelta  # doctest: +SKIP
            >>> cutoff = utc_now() - timedelta(days=30)  # doctest: +SKIP
            >>> deleted = service.delete_old_traces(db, cutoff)  # doctest: +SKIP
            >>> print(f"Deleted {deleted} old traces")  # doctest: +SKIP
        """
        deleted = db.query(ObservabilityTrace).filter(ObservabilityTrace.start_time < before_time).delete()
        if not self._safe_commit(db, "delete_old_traces"):
            return 0
        logger.info(f"Deleted {deleted} traces older than {before_time}")
        return deleted
