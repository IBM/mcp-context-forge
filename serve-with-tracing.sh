#!/usr/bin/env bash
# Start MCP Gateway with OpenTelemetry tracing enabled
#
# Prerequisites (choose one):
#   pip install mcp-contextforge-gateway[observability]  # For OTLP
#   pip install opentelemetry-exporter-jaeger            # For Jaeger
#   pip install opentelemetry-exporter-zipkin            # For Zipkin

# Determine which backend to use (default: otlp)
BACKEND=${1:-otlp}

echo "Starting MCP Gateway with OpenTelemetry tracing..."
echo "Backend: $BACKEND"
echo ""

case $BACKEND in
    phoenix)
        # Phoenix (via OTLP gRPC)
        export OTEL_TRACES_EXPORTER=otlp
        export OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}
        export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-mcp-gateway}
        echo "  Phoenix OTLP Endpoint: $OTEL_EXPORTER_OTLP_ENDPOINT"
        echo "  Start Phoenix: docker-compose -f docker-compose.phoenix-simple.yml up -d"
        ;;

    jaeger)
        # Jaeger (native protocol)
        export OTEL_TRACES_EXPORTER=jaeger
        export OTEL_EXPORTER_JAEGER_ENDPOINT=${OTEL_EXPORTER_JAEGER_ENDPOINT:-http://localhost:14268/api/traces}
        export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-mcp-gateway}
        echo "  Jaeger Endpoint: $OTEL_EXPORTER_JAEGER_ENDPOINT"
        echo "  Start Jaeger: docker run -d -p 16686:16686 -p 14268:14268 jaegertracing/all-in-one"
        ;;

    zipkin)
        # Zipkin
        export OTEL_TRACES_EXPORTER=zipkin
        export OTEL_EXPORTER_ZIPKIN_ENDPOINT=${OTEL_EXPORTER_ZIPKIN_ENDPOINT:-http://localhost:9411/api/v2/spans}
        export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-mcp-gateway}
        echo "  Zipkin Endpoint: $OTEL_EXPORTER_ZIPKIN_ENDPOINT"
        echo "  Start Zipkin: docker run -d -p 9411:9411 openzipkin/zipkin"
        ;;

    tempo)
        # Grafana Tempo (via OTLP)
        export OTEL_TRACES_EXPORTER=otlp
        export OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}
        export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-mcp-gateway}
        echo "  Tempo OTLP Endpoint: $OTEL_EXPORTER_OTLP_ENDPOINT"
        echo "  Start Tempo: docker run -d -p 4317:4317 -p 3200:3200 grafana/tempo:latest"
        ;;

    otlp)
        # Generic OTLP (default)
        export OTEL_TRACES_EXPORTER=otlp
        export OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}
        export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-mcp-gateway}
        export OTEL_EXPORTER_OTLP_INSECURE=${OTEL_EXPORTER_OTLP_INSECURE:-true}
        echo "  OTLP Endpoint: $OTEL_EXPORTER_OTLP_ENDPOINT"
        ;;

    console)
        # Console output for debugging
        export OTEL_TRACES_EXPORTER=console
        export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-mcp-gateway}
        echo "  Output: Console (stdout)"
        ;;

    none)
        # Disable tracing
        export OTEL_ENABLE_OBSERVABILITY=false
        echo "  Tracing: DISABLED"
        ;;

    *)
        echo "Unknown backend: $BACKEND"
        echo "Supported backends: phoenix, jaeger, zipkin, tempo, otlp, console, none"
        exit 1
        ;;
esac

echo "  Service Name: $OTEL_SERVICE_NAME"
echo ""

# Optional: Set additional configuration
export OTEL_RESOURCE_ATTRIBUTES=${OTEL_RESOURCE_ATTRIBUTES:-"environment=development,team=platform"}
export OTEL_BSP_MAX_QUEUE_SIZE=${OTEL_BSP_MAX_QUEUE_SIZE:-2048}
export OTEL_BSP_MAX_EXPORT_BATCH_SIZE=${OTEL_BSP_MAX_EXPORT_BATCH_SIZE:-512}

# Run the gateway using make serve
make serve
