#!/usr/bin/env bash
# Start MCP Gateway with OpenTelemetry tracing enabled

# Set OpenTelemetry environment variables
export OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}
export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-mcp-gateway}
export OTEL_TRACES_EXPORTER=otlp

echo "Starting MCP Gateway with OpenTelemetry tracing..."
echo "  OTLP Endpoint: $OTEL_EXPORTER_OTLP_ENDPOINT"
echo "  Service Name: $OTEL_SERVICE_NAME"

# Run the gateway using make serve
make serve