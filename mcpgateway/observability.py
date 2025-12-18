# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/observability.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Vendor-agnostic OpenTelemetry instrumentation for MCP Gateway.
Supports any OTLP-compatible backend (Jaeger, Zipkin, Tempo, Phoenix, etc.).
"""

# Standard
from contextlib import nullcontext
from importlib import import_module as _im
import logging
import os
from typing import Any, Callable, cast, Dict, Optional

# Third-Party - Try to import OpenTelemetry core components - make them truly optional
OTEL_AVAILABLE = False
try:
    # Third-Party
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    # OpenTelemetry not installed - set to None for graceful degradation
    trace = None

    # Provide a lightweight shim so tests can patch Resource.create
    class _ResourceShim:
        """Minimal Resource shim used when OpenTelemetry SDK isn't installed.

        Exposes a static ``create`` method that simply returns the provided
        attributes mapping, enabling tests to patch and inspect the inputs
        without requiring the real OpenTelemetry classes.
        """

        @staticmethod
        def create(attrs: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
            """Return attributes unchanged to mimic ``Resource.create``.

            Args:
                attrs: Resource attribute dictionary.

            Returns:
                Dict[str, Any]: The same mapping passed in.
            """
            return attrs

    Resource = cast(Any, _ResourceShim)
    TracerProvider = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None
    SimpleSpanProcessor = None
    Status = None
    StatusCode = None

    # Provide minimal module shims so tests can patch ConsoleSpanExporter path
    try:
        # Standard
        import sys
        import types

        if ("pytest" in sys.modules) or (os.getenv("MCP_TESTING") == "1"):
            otel_root = types.ModuleType("opentelemetry")
            otel_sdk = types.ModuleType("opentelemetry.sdk")
            otel_trace = types.ModuleType("opentelemetry.sdk.trace")
            otel_export = types.ModuleType("opentelemetry.sdk.trace.export")

            class _ConsoleSpanExporterStub:  # pragma: no cover - test patch replaces this
                """Lightweight stub for ConsoleSpanExporter used in tests.

                Provides a placeholder class so unit tests can patch
                `opentelemetry.sdk.trace.export.ConsoleSpanExporter` even when
                the OpenTelemetry SDK is not installed in the environment.
                """

            setattr(otel_export, "ConsoleSpanExporter", _ConsoleSpanExporterStub)
            setattr(otel_trace, "export", otel_export)
            setattr(otel_sdk, "trace", otel_trace)
            setattr(otel_root, "sdk", otel_sdk)

            # Only register the exact chain needed by tests
            sys.modules.setdefault("opentelemetry", otel_root)
            sys.modules.setdefault("opentelemetry.sdk", otel_sdk)
            sys.modules.setdefault("opentelemetry.sdk.trace", otel_trace)
            sys.modules.setdefault("opentelemetry.sdk.trace.export", otel_export)
    except Exception as exc:  # nosec B110 - best-effort optional shim
        # Shimming is a non-critical, best-effort step for tests; log and continue.
        logging.getLogger(__name__).debug("Skipping OpenTelemetry shim setup: %s", exc)

# First-Party
from mcpgateway.utils.correlation_id import get_correlation_id  # noqa: E402  # pylint: disable=wrong-import-position

# Try to import optional exporters
try:
    OTLP_SPAN_EXPORTER = getattr(_im("opentelemetry.exporter.otlp.proto.grpc.trace_exporter"), "OTLPSpanExporter")
except Exception:
    try:
        OTLP_SPAN_EXPORTER = getattr(_im("opentelemetry.exporter.otlp.proto.http.trace_exporter"), "OTLPSpanExporter")
    except Exception:
        OTLP_SPAN_EXPORTER = None

try:
    JAEGER_EXPORTER = getattr(_im("opentelemetry.exporter.jaeger.thrift"), "JaegerExporter")
except Exception:
    JAEGER_EXPORTER = None

try:
    ZIPKIN_EXPORTER = getattr(_im("opentelemetry.exporter.zipkin.json"), "ZipkinExporter")
except Exception:
    ZIPKIN_EXPORTER = None

try:
    HTTP_EXPORTER = getattr(_im("opentelemetry.exporter.otlp.proto.http.trace_exporter"), "OTLPSpanExporter")
except Exception:
    HTTP_EXPORTER = None

logger = logging.getLogger(__name__)


# Global tracer instance - using UPPER_CASE for module-level constant
# pylint: disable=invalid-name
_TRACER = None


def init_telemetry() -> Optional[Any]:
    """Initialize OpenTelemetry with configurable backend.

    Supports multiple backends via environment variables:
    - OTEL_TRACES_EXPORTER: Exporter type (otlp, jaeger, zipkin, console, none)
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (for otlp exporter)
    - OTEL_EXPORTER_JAEGER_ENDPOINT: Jaeger endpoint (for jaeger exporter)
    - OTEL_EXPORTER_ZIPKIN_ENDPOINT: Zipkin endpoint (for zipkin exporter)
    - OTEL_ENABLE_OBSERVABILITY: Set to 'false' to disable completely

    Returns:
        The initialized tracer instance or None if disabled.
    """
    # pylint: disable=global-statement
    global _TRACER

    # Check if observability is explicitly disabled
    if os.getenv("OTEL_ENABLE_OBSERVABILITY", "true").lower() == "false":
        logger.info("Observability disabled via OTEL_ENABLE_OBSERVABILITY=false")
        return None

    # If OpenTelemetry isn't installed, continue gracefully.
    # Tests may patch required symbols; use fallbacks when absent.
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not installed. Proceeding with graceful fallbacks.")
        logger.info("To enable full telemetry, install: pip install mcp-contextforge-gateway[observability]")

    # Get exporter type from environment
    exporter_type = os.getenv("OTEL_TRACES_EXPORTER", "otlp").lower()

    # Handle 'none' exporter (tracing disabled)
    if exporter_type == "none":
        logger.info("Tracing disabled via OTEL_TRACES_EXPORTER=none")
        return None

    # Check if endpoint is configured for otlp
    if exporter_type == "otlp":
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            logger.info("OTLP endpoint not configured, skipping telemetry init")
            return None

    try:
        # Create resource attributes
        resource_attributes: Dict[str, Any] = {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "mcp-gateway"),
            "service.version": "1.0.0-BETA-1",
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
        }

        # Add custom resource attributes from environment
        custom_attrs = os.getenv("OTEL_RESOURCE_ATTRIBUTES", "")
        if custom_attrs:
            for attr in custom_attrs.split(","):
                if "=" in attr:
                    key, value = attr.split("=", 1)
                    resource_attributes[key.strip()] = value.strip()

        # Narrow types for mypy/pyrefly
        # Create resource if available, else skip
        resource: Optional[Any]
        if Resource is not None and hasattr(Resource, "create"):
            resource = cast(Any, Resource).create(resource_attributes)
        else:
            resource = None

        # Set up tracer provider with optional sampling
        # Initialize tracer provider (with resource if available)
        if resource is not None:
            provider = cast(Any, TracerProvider)(resource=resource)
        else:
            provider = cast(Any, TracerProvider)()

        # Register provider if trace API is present
        if trace is not None and hasattr(trace, "set_tracer_provider"):
            cast(Any, trace).set_tracer_provider(provider)

        # Create a custom span processor to copy resource attributes to span attributes
        # This is needed because Arize requires arize.project.name as a span attribute
        class ResourceAttributeSpanProcessor:
            """Span processor that copies specific resource attributes to span attributes."""

            def __init__(self, attributes_to_copy=None):
                self.attributes_to_copy = attributes_to_copy or ["arize.project.name", "model_id"]
                logger.info(f"ResourceAttributeSpanProcessor will copy: {self.attributes_to_copy}")

            def on_start(self, span, _parent_context=None):
                """Copy specified resource attributes to span attributes when span starts.

                Args:
                    span: The span being started.
                    _parent_context: The parent context (unused, required by interface).
                """
                if not hasattr(span, "resource") or span.resource is None:
                    return

                # Get resource attributes
                resource_attributes = getattr(span.resource, "attributes", {})

                # Copy specified attributes from resource to span
                for attr in self.attributes_to_copy:
                    if attr in resource_attributes:
                        value = resource_attributes[attr]
                        span.set_attribute(attr, value)
                        logger.debug(f"Copied resource attribute to span: {attr}={value}")

            def on_end(self, span):
                """Handle span end event.

                Required by the SpanProcessor interface but not used.

                Args:
                    span: The span being ended.
                """
                pass  # pylint: disable=unnecessary-pass

        # Add the custom span processor to copy resource attributes to spans
        # This is needed for Arize which requires certain attributes as span attributes
        # Enable via OTEL_COPY_RESOURCE_ATTRS_TO_SPANS=true (disabled by default)
        copy_resource_attrs = os.getenv("OTEL_COPY_RESOURCE_ATTRS_TO_SPANS", "false").lower() == "true"
        if resource is not None and copy_resource_attrs:
            logger.info("Adding ResourceAttributeSpanProcessor to copy resource attributes to spans")
            provider.add_span_processor(ResourceAttributeSpanProcessor())

        # Configure the appropriate exporter based on type
        exporter: Optional[Any] = None

        if exporter_type == "otlp":
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").lower()
            headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
            # Note: some versions of OTLP exporters may not accept 'insecure' kwarg; avoid passing it.
            # Use endpoint scheme or env to control TLS externally.

            # Parse headers if provided
            header_dict: Dict[str, str] = {}
            if headers:
                for header in headers.split(","):
                    if "=" in header:
                        key, value = header.split("=", 1)
                        header_dict[key.strip()] = value.strip()

            if protocol == "grpc" and OTLP_SPAN_EXPORTER:
                exporter = cast(Any, OTLP_SPAN_EXPORTER)(endpoint=endpoint, headers=header_dict or None)
            elif HTTP_EXPORTER:
                # Use HTTP exporter as fallback
                ep = str(endpoint) if endpoint is not None else ""
                http_ep = (ep.replace(":4317", ":4318") + "/v1/traces") if ":4317" in ep else ep
                exporter = cast(Any, HTTP_EXPORTER)(endpoint=http_ep, headers=header_dict or None)
            else:
                logger.error("No OTLP exporter available")
                return None

        elif exporter_type == "jaeger":
            if JAEGER_EXPORTER:
                endpoint = os.getenv("OTEL_EXPORTER_JAEGER_ENDPOINT", "http://localhost:14268/api/traces")
                exporter = JAEGER_EXPORTER(collector_endpoint=endpoint, username=os.getenv("OTEL_EXPORTER_JAEGER_USER"), password=os.getenv("OTEL_EXPORTER_JAEGER_PASSWORD"))
            else:
                logger.error("Jaeger exporter not available. Install with: pip install opentelemetry-exporter-jaeger")
                return None

        elif exporter_type == "zipkin":
            if ZIPKIN_EXPORTER:
                endpoint = os.getenv("OTEL_EXPORTER_ZIPKIN_ENDPOINT", "http://localhost:9411/api/v2/spans")
                exporter = ZIPKIN_EXPORTER(endpoint=endpoint)
            else:
                logger.error("Zipkin exporter not available. Install with: pip install opentelemetry-exporter-zipkin")
                return None

        elif exporter_type == "console":
            # Console exporter for debugging
            exporter = cast(Any, ConsoleSpanExporter)()

        else:
            logger.warning(f"Unknown exporter type: {exporter_type}. Using console exporter.")
            exporter = cast(Any, ConsoleSpanExporter)()

        if exporter:
            # Add batch processor for better performance (except for console)
            if exporter_type == "console":
                span_processor = cast(Any, SimpleSpanProcessor)(exporter)
            else:
                span_processor = cast(Any, BatchSpanProcessor)(
                    exporter,
                    max_queue_size=int(os.getenv("OTEL_BSP_MAX_QUEUE_SIZE", "2048")),
                    max_export_batch_size=int(os.getenv("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "512")),
                    schedule_delay_millis=int(os.getenv("OTEL_BSP_SCHEDULE_DELAY", "5000")),
                )
            provider.add_span_processor(span_processor)

        # Get tracer
        # Obtain a tracer if trace API available; otherwise create a no-op tracer
        if trace is not None and hasattr(trace, "get_tracer"):
            _TRACER = cast(Any, trace).get_tracer("mcp-gateway", "1.0.0-BETA-1", schema_url="https://opentelemetry.io/schemas/1.11.0")
        else:

            class _NoopTracer:
                """No-op tracer used when OpenTelemetry API isn't available."""

                def start_as_current_span(self, _name: str):  # type: ignore[override]
                    """Return a no-op context manager for span creation.

                    Args:
                        _name: Span name (ignored in no-op implementation).

                    Returns:
                        contextlib.AbstractContextManager: A null context.
                    """
                    return nullcontext()

            _TRACER = _NoopTracer()

        logger.info(f"✅ OpenTelemetry initialized with {exporter_type} exporter")
        if exporter_type == "otlp":
            logger.info(f"   Endpoint: {os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')}")
        elif exporter_type == "jaeger":
            logger.info(f"   Endpoint: {os.getenv('OTEL_EXPORTER_JAEGER_ENDPOINT', 'default')}")
        elif exporter_type == "zipkin":
            logger.info(f"   Endpoint: {os.getenv('OTEL_EXPORTER_ZIPKIN_ENDPOINT', 'default')}")

        return _TRACER

    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        return None


def trace_operation(operation_name: str, attributes: Optional[Dict[str, Any]] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Simple decorator to trace any operation.

    Args:
        operation_name: Name of the operation to trace (e.g., "tool.invoke").
        attributes: Optional dictionary of attributes to add to the span.

    Returns:
        Decorator function that wraps the target function with tracing.

    Usage:
        @trace_operation("tool.invoke", {"tool.name": "calculator"})
        async def invoke_tool():
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator that wraps the function with tracing.

        Args:
            func: The async function to wrap with tracing.

        Returns:
            The wrapped function with tracing capabilities.
        """

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Async wrapper that adds tracing to the decorated function.

            Args:
                *args: Positional arguments passed to the wrapped function.
                **kwargs: Keyword arguments passed to the wrapped function.

            Returns:
                The result of the wrapped function.

            Raises:
                Exception: Any exception raised by the wrapped function.
            """
            if not _TRACER:
                # No tracing configured, just run the function
                return await func(*args, **kwargs)

            # Create span for this operation
            with _TRACER.start_as_current_span(operation_name) as span:
                # Add attributes if provided
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)

                try:
                    # Run the actual function
                    result = await func(*args, **kwargs)
                    span.set_attribute("status", "success")
                    return result
                except Exception as e:
                    # Record error in span
                    span.set_attribute("status", "error")
                    span.set_attribute("error.message", str(e))
                    span.record_exception(e)
                    raise

        return wrapper

    return decorator


def create_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Any:
    """
    Create a span for manual instrumentation.

    Args:
        name: Name of the span to create (e.g., "database.query").
        attributes: Optional dictionary of attributes to add to the span.

    Returns:
        Context manager that creates and manages the span lifecycle.

    Usage:
        with create_span("database.query", {"db.statement": "SELECT * FROM tools"}):
            # Your code here
            pass
    """
    if not _TRACER:
        # Return a no-op context manager if tracing is not configured or available
        return nullcontext()

    # Auto-inject correlation ID into all spans for request tracing
    try:
        correlation_id = get_correlation_id()
        if correlation_id:
            if attributes is None:
                attributes = {}
            # Add correlation ID if not already present
            if "correlation_id" not in attributes:
                attributes["correlation_id"] = correlation_id
            if "request_id" not in attributes:
                attributes["request_id"] = correlation_id  # Alias for compatibility
    except Exception as exc:
        # Correlation ID not available or error getting it, continue without it
        logger.debug("Failed to add correlation_id to span: %s", exc)

    # Start span and return the context manager
    span_context = _TRACER.start_as_current_span(name)

    # If we have attributes and the span context is entered, set them
    if attributes:
        # We need to set attributes after entering the context
        # So we'll create a wrapper that sets attributes
        class SpanWithAttributes:
            """Context manager wrapper that adds attributes to a span.

            This class wraps an OpenTelemetry span context and adds attributes
            when entering the context. It also handles exception recording when
            exiting the context.
            """

            def __init__(self, span_context: Any, attrs: Dict[str, Any]):
                """Initialize the span wrapper.

                Args:
                    span_context: The OpenTelemetry span context to wrap.
                    attrs: Dictionary of attributes to add to the span.
                """
                self.span_context: Any = span_context
                self.attrs: Dict[str, Any] = attrs
                self.span: Any = None

            def __enter__(self) -> Any:
                """Enter the context and set span attributes.

                Returns:
                    The OpenTelemetry span with attributes set.
                """
                self.span = self.span_context.__enter__()
                if self.attrs and self.span:
                    for key, value in self.attrs.items():
                        if value is not None:  # Skip None values
                            self.span.set_attribute(key, value)
                return self.span

            def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Any) -> Any:
                """Exit the context and record any exceptions.

                Args:
                    exc_type: The exception type if an exception occurred.
                    exc_val: The exception value if an exception occurred.
                    exc_tb: The exception traceback if an exception occurred.

                Returns:
                    The result of the wrapped span context's __exit__ method.
                """
                # Record exception if one occurred
                if exc_type is not None and self.span:
                    self.span.record_exception(exc_val)
                    if OTEL_AVAILABLE and Status and StatusCode:
                        self.span.set_status(Status(StatusCode.ERROR, str(exc_val)))
                    self.span.set_attribute("error", True)
                    self.span.set_attribute("error.type", exc_type.__name__)
                    self.span.set_attribute("error.message", str(exc_val))
                elif self.span:
                    if OTEL_AVAILABLE and Status and StatusCode:
                        self.span.set_status(Status(StatusCode.OK))
                return self.span_context.__exit__(exc_type, exc_val, exc_tb)

        return SpanWithAttributes(span_context, attributes)

    return span_context


# Initialize on module import
_TRACER = init_telemetry()
