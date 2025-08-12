"""
Simple OpenTelemetry instrumentation for MCP Gateway to send traces to Phoenix.
This is the minimal implementation to get observability working.
"""

# Standard
import logging
import os

# Third-Party
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

# Global tracer instance
tracer = None


def init_telemetry():
    """Initialize OpenTelemetry with Phoenix as the backend."""
    global tracer

    # Check if Phoenix endpoint is configured
    phoenix_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not phoenix_endpoint:
        logger.info("Phoenix endpoint not configured, skipping telemetry init")
        return

    try:
        # Create resource attributes
        resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "mcp-gateway"), "service.version": "0.5.0", "deployment.environment": os.getenv("DEPLOYMENT_ENV", "docker")})

        # Set up tracer provider
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        # Configure OTLP exporter to send to Phoenix
        otlp_exporter = OTLPSpanExporter(endpoint=phoenix_endpoint, insecure=True)  # Phoenix in Docker doesn't use TLS

        # Add batch processor for better performance
        span_processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(span_processor)

        # Get tracer
        tracer = trace.get_tracer("mcp-gateway")

        logger.info(f"✅ OpenTelemetry initialized with Phoenix endpoint: {phoenix_endpoint}")
        return tracer

    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        return None


def trace_operation(operation_name: str, attributes: dict = None):
    """
    Simple decorator to trace any operation.

    Usage:
        @trace_operation("tool.invoke", {"tool.name": "calculator"})
        async def invoke_tool():
            ...
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            if not tracer:
                # No tracing configured, just run the function
                return await func(*args, **kwargs)

            # Create span for this operation
            with tracer.start_as_current_span(operation_name) as span:
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

    Usage:
        with create_span("database.query", {"db.statement": "SELECT * FROM tools"}):
            # Your code here
            pass
    """
    if not tracer:
        # Return a no-op context manager if tracing is not configured
        # Standard
        from contextlib import nullcontext

        return nullcontext()

    # Start span and return the context manager
    span_context = tracer.start_as_current_span(name)

    # If we have attributes and the span context is entered, set them
    if attributes:
        # We need to set attributes after entering the context
        # So we'll create a wrapper that sets attributes
        class SpanWithAttributes:
            def __init__(self, span_context, attrs):
                self.span_context = span_context
                self.attrs = attrs
                self.span = None

            def __enter__(self):
                self.span = self.span_context.__enter__()
                if self.attrs and self.span:
                    for key, value in self.attrs.items():
                        if value is not None:  # Skip None values
                            self.span.set_attribute(key, value)
                return self.span

            def __exit__(self, exc_type, exc_val, exc_tb):
                return self.span_context.__exit__(exc_type, exc_val, exc_tb)

        return SpanWithAttributes(span_context, attributes)

    return span_context


# Initialize on module import
tracer = init_telemetry()
