# Observability

MCP Gateway includes production-grade OpenTelemetry instrumentation for distributed tracing, enabling you to monitor performance, debug issues, and understand request flows.

## Documentation

- **[Observability Overview](observability/observability.md)** - Complete guide to configuring and using observability
- **[Phoenix Integration](observability/phoenix.md)** - AI/LLM-focused observability with Arize Phoenix

## Quick Start

```bash
# Enable observability (enabled by default)
export OTEL_ENABLE_OBSERVABILITY=true
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Start Phoenix for AI/LLM observability
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest

# Run MCP Gateway
mcpgateway
```

View traces at http://localhost:6006
