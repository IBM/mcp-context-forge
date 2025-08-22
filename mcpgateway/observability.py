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
import logging
import os

# Try to import OpenTelemetry core components - make them truly optional
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
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None
    SimpleSpanProcessor = None
    Status = None
    StatusCode = None

# Try to import optional exporters
try:
    # Third-Party
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
except ImportError:
    try:
        # Third-Party
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError:
        OTLPSpanExporter = None

try:
    # Third-Party
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
except ImportError:
    JaegerExporter = None

try:
    # Third-Party
    from opentelemetry.exporter.zipkin.json import ZipkinExporter
except ImportError:
    ZipkinExporter = None

try:
    # Third-Party
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
except ImportError:
    HTTPExporter = None

logger = logging.getLogger(__name__)

# Global tracer instance - using UPPER_CASE for module-level constant
# pylint: disable=invalid-name
_TRACER = None


def init_telemetry():
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

    # Check if OpenTelemetry is available
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not installed. Telemetry features will be disabled.")
        logger.info("To enable telemetry, install with: pip install mcp-contextforge-gateway[observability]")
        return None

    # Get exporter type from environment
    exporter_type = os.getenv("OTEL_TRACES_EXPORTER", "otlp").lower()

    # Handle 'none' exporter (tracing disabled)
    if exporter_type == "none":
        logger.info("Tracing disabled via OTEL_TRACES_EXPORTER=none")
        return None

    # Check if OTLP exporter is available for otlp type
    if exporter_type == "otlp" and OTLPSpanExporter is None:
        logger.info("OTLP exporter not available. Install with: pip install opentelemetry-exporter-otlp-proto-grpc")
        return None

    # Check if endpoint is configured for otlp
    if exporter_type == "otlp":
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            logger.info("OTLP endpoint not configured, skipping telemetry init")
            return None

    try:
        # Create resource attributes
        resource_attributes = {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "mcp-gateway"),
            "service.version": "0.5.0",
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
        }

        # Add custom resource attributes from environment
        custom_attrs = os.getenv("OTEL_RESOURCE_ATTRIBUTES", "")
        if custom_attrs:
            for attr in custom_attrs.split(","):
                if "=" in attr:
                    key, value = attr.split("=", 1)
                    resource_attributes[key.strip()] = value.strip()

        resource = Resource.create(resource_attributes)

        # Set up tracer provider with optional sampling
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        # Configure the appropriate exporter based on type
        exporter = None

        if exporter_type == "otlp":
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").lower()
            headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
            insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() == "true"

            # Parse headers if provided
            header_dict = {}
            if headers:
                for header in headers.split(","):
                    if "=" in header:
                        key, value = header.split("=", 1)
                        header_dict[key.strip()] = value.strip()

            if protocol == "grpc" and OTLPSpanExporter:
                exporter = OTLPSpanExporter(endpoint=endpoint, headers=header_dict or None, insecure=insecure)
            elif HTTPExporter:
                # Use HTTP exporter as fallback
                exporter = HTTPExporter(endpoint=endpoint.replace(":4317", ":4318") + "/v1/traces" if ":4317" in endpoint else endpoint, headers=header_dict or None)
            else:
                logger.error("No OTLP exporter available")
                return None

        elif exporter_type == "jaeger":
            if JaegerExporter:
                endpoint = os.getenv("OTEL_EXPORTER_JAEGER_ENDPOINT", "http://localhost:14268/api/traces")
                exporter = JaegerExporter(collector_endpoint=endpoint, username=os.getenv("OTEL_EXPORTER_JAEGER_USER"), password=os.getenv("OTEL_EXPORTER_JAEGER_PASSWORD"))
            else:
                logger.error("Jaeger exporter not available. Install with: pip install opentelemetry-exporter-jaeger")
                return None

        elif exporter_type == "zipkin":
            if ZipkinExporter:
                endpoint = os.getenv("OTEL_EXPORTER_ZIPKIN_ENDPOINT", "http://localhost:9411/api/v2/spans")
                exporter = ZipkinExporter(endpoint=endpoint)
            else:
                logger.error("Zipkin exporter not available. Install with: pip install opentelemetry-exporter-zipkin")
                return None

        elif exporter_type == "console":
            # Console exporter for debugging
            exporter = ConsoleSpanExporter()

        else:
            logger.warning(f"Unknown exporter type: {exporter_type}. Using console exporter.")
            exporter = ConsoleSpanExporter()

        if exporter:
            # Add batch processor for better performance (except for console)
            if exporter_type == "console":
                span_processor = SimpleSpanProcessor(exporter)
            else:
                span_processor = BatchSpanProcessor(
                    exporter,
                    max_queue_size=int(os.getenv("OTEL_BSP_MAX_QUEUE_SIZE", "2048")),
                    max_export_batch_size=int(os.getenv("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "512")),
                    schedule_delay_millis=int(os.getenv("OTEL_BSP_SCHEDULE_DELAY", "5000")),
                )
            provider.add_span_processor(span_processor)

        # Get tracer
        _TRACER = trace.get_tracer("mcp-gateway", "0.5.0", schema_url="https://opentelemetry.io/schemas/1.11.0")

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


def trace_operation(operation_name: str, attributes: dict = None):
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

    def decorator(func):
        """Decorator that wraps the function with tracing.

        Args:
            func: The async function to wrap with tracing.

        Returns:
            The wrapped function with tracing capabilities.
        """

        # If OpenTelemetry is not available, return the function unmodified
        if not OTEL_AVAILABLE:
            return func

        async def wrapper(*args, **kwargs):
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


def create_span(name: str, attributes: dict = None):
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
    if not _TRACER or not OTEL_AVAILABLE:
        # Return a no-op context manager if tracing is not configured or available
        return nullcontext()

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

            def __init__(self, span_context, attrs):
                """Initialize the span wrapper.

                Args:
                    span_context: The OpenTelemetry span context to wrap.
                    attrs: Dictionary of attributes to add to the span.
                """
                self.span_context = span_context
                self.attrs = attrs
                self.span = None

            def __enter__(self):
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

            def __exit__(self, exc_type, exc_val, exc_tb):
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
