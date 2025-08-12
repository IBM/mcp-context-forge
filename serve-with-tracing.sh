#!/usr/bin/env bash
# Start MCP Gateway with OpenTelemetry tracing enabled
#
# Prerequisites:
#   pip install mcp-contextforge-gateway[observability]
#   or
#   pip install opentelemetry-exporter-otlp-proto-grpc

# Set OpenTelemetry environment variables
export OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}
export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-mcp-gateway}
export OTEL_TRACES_EXPORTER=otlp

echo "Starting MCP Gateway with OpenTelemetry tracing..."
echo "  OTLP Endpoint: $OTEL_EXPORTER_OTLP_ENDPOINT"
echo "  Service Name: $OTEL_SERVICE_NAME"
echo ""
echo "Note: Ensure Phoenix is running at localhost:4317"
echo "      docker-compose -f docker-compose.phoenix-simple.yml up -d"
echo ""

# Run the gateway using make serve
make serve
