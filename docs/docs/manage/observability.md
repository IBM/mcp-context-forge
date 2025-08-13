# Observability

MCP Gateway includes built-in OpenTelemetry instrumentation for distributed tracing. This allows you to monitor performance, debug issues, and understand request flows across your gateway instances.

## Overview

The observability implementation is **vendor-agnostic** and supports any OTLP-compatible backend:
- **Arize Phoenix** - AI/LLM-focused observability
- **Jaeger** - Open source distributed tracing
- **Zipkin** - Distributed tracing system
- **Grafana Tempo** - High-scale distributed tracing backend
- **Datadog, New Relic, Honeycomb** - Commercial APM solutions
- **Console** - Debug output to stdout

## Quick Start

### 1. Install Dependencies

```bash
# For OTLP (Phoenix, Tempo, Datadog, etc.)
pip install mcp-contextforge-gateway[observability]

# For Jaeger (optional)
pip install opentelemetry-exporter-jaeger

# For Zipkin (optional)
pip install opentelemetry-exporter-zipkin
```

### 2. Start Your Backend

Choose your preferred backend:

#### Phoenix (AI/LLM Observability)
```bash
docker run -d \
  -p 6006:6006 \
  -p 4317:4317 \
  arizephoenix/phoenix:latest
```

#### Jaeger
```bash
docker run -d \
  -p 16686:16686 \
  -p 14268:14268 \
  jaegertracing/all-in-one
```

#### Zipkin
```bash
docker run -d \
  -p 9411:9411 \
  openzipkin/zipkin
```

#### Grafana Tempo
```bash
docker run -d \
  -p 4317:4317 \
  -p 3200:3200 \
  grafana/tempo:latest
```

### 3. Configure MCP Gateway

Set environment variables based on your backend:

#### For OTLP Backends (Phoenix, Tempo, etc.)
```bash
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=mcp-gateway
```

#### For Jaeger
```bash
export OTEL_TRACES_EXPORTER=jaeger
export OTEL_EXPORTER_JAEGER_ENDPOINT=http://localhost:14268/api/traces
export OTEL_SERVICE_NAME=mcp-gateway
```

#### For Zipkin
```bash
export OTEL_TRACES_EXPORTER=zipkin
export OTEL_EXPORTER_ZIPKIN_ENDPOINT=http://localhost:9411/api/v2/spans
export OTEL_SERVICE_NAME=mcp-gateway
```

### 4. Start the Gateway

```bash
# Using the helper script (supports multiple backends)
./serve-with-tracing.sh phoenix  # or jaeger, zipkin, tempo, console, none

# Or manually with environment variables
make serve
```

### 5. View Traces

- **Phoenix**: http://localhost:6006
- **Jaeger**: http://localhost:16686
- **Zipkin**: http://localhost:9411
- **Tempo**: Requires Grafana for visualization

## Configuration Reference

### Core Settings

| Environment Variable | Description | Default | Options |
|---------------------|-------------|---------|---------|
| `OTEL_ENABLE_OBSERVABILITY` | Enable/disable observability | `true` | `true`, `false` |
| `OTEL_TRACES_EXPORTER` | Trace exporter type | `otlp` | `otlp`, `jaeger`, `zipkin`, `console`, `none` |
| `OTEL_SERVICE_NAME` | Service name in traces | `mcp-gateway` | Any string |
| `OTEL_RESOURCE_ATTRIBUTES` | Additional resource attributes | - | `key1=value1,key2=value2` |

### OTLP Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint URL | - |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | OTLP protocol | `grpc` |
| `OTEL_EXPORTER_OTLP_INSECURE` | Use insecure connection | `true` |
| `OTEL_EXPORTER_OTLP_HEADERS` | OTLP headers | - |

### Jaeger Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `OTEL_EXPORTER_JAEGER_ENDPOINT` | Jaeger collector endpoint | `http://localhost:14268/api/traces` |
| `OTEL_EXPORTER_JAEGER_USER` | Jaeger auth username | - |
| `OTEL_EXPORTER_JAEGER_PASSWORD` | Jaeger auth password | - |

### Zipkin Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `OTEL_EXPORTER_ZIPKIN_ENDPOINT` | Zipkin endpoint | `http://localhost:9411/api/v2/spans` |

### Batch Processor Settings

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `OTEL_BSP_MAX_QUEUE_SIZE` | Max spans in queue | `2048` |
| `OTEL_BSP_MAX_EXPORT_BATCH_SIZE` | Max batch size | `512` |
| `OTEL_BSP_SCHEDULE_DELAY` | Export delay (ms) | `5000` |

## What's Traced

MCP Gateway automatically traces:

### Tool Operations
- Tool invocations with arguments
- Gateway routing decisions
- Plugin pre/post processing
- Execution timing and success status
- Error details with stack traces

### Prompt Operations
- Template rendering
- Argument processing
- Message generation
- User context

### Resource Operations
- Resource reading (file, HTTP, template)
- Cache hits/misses
- Content type detection
- Template variable substitution

### Federation Operations
- Cross-gateway requests
- Health checks (with nested spans)
- Request forwarding
- Error propagation

## Disabling Observability

To completely disable observability:

```bash
# Option 1: Disable via environment variable
export OTEL_ENABLE_OBSERVABILITY=false

# Option 2: Use 'none' exporter
export OTEL_TRACES_EXPORTER=none

# Option 3: Use the helper script
./serve-with-tracing.sh none
```

## Production Deployment

### Security

For production, enable TLS and authentication:

```bash
# OTLP with TLS
export OTEL_EXPORTER_OTLP_INSECURE=false
export OTEL_EXPORTER_OTLP_CERTIFICATE=/path/to/cert.pem

# Authentication headers
export OTEL_EXPORTER_OTLP_HEADERS="api-key=your-key,x-auth-token=token"
```

### Sampling

To reduce overhead, configure sampling (coming soon):

```bash
export OTEL_TRACES_SAMPLER=parentbased_traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.1  # Sample 10% of traces
```

### Resource Attributes

Add deployment metadata:

```bash
export OTEL_RESOURCE_ATTRIBUTES="environment=production,region=us-east-1,version=0.5.0"
```

## Troubleshooting

### No Traces Appearing

1. Check the backend is running:
   ```bash
   curl http://localhost:4317/health  # OTLP
   curl http://localhost:16686  # Jaeger UI
   curl http://localhost:9411  # Zipkin UI
   ```

2. Enable console exporter for debugging:
   ```bash
   export OTEL_TRACES_EXPORTER=console
   ```

3. Check logs for errors:
   ```bash
   grep "OpenTelemetry" logs/mcpgateway.log
   ```

### Performance Impact

- Tracing adds <1ms overhead per span
- Batch processor exports asynchronously
- No impact when disabled

### Missing Dependencies

If you see import errors:

```bash
# For OTLP
pip install opentelemetry-exporter-otlp-proto-grpc

# For Jaeger
pip install opentelemetry-exporter-jaeger

# For Zipkin
pip install opentelemetry-exporter-zipkin
```

## Advanced Usage

### Custom Instrumentation

Add tracing to your plugins or custom code:

```python
from mcpgateway.observability_simple import create_span

async def my_function():
    with create_span("custom.operation", {
        "custom.attribute": "value",
        "user.id": "123"
    }) as span:
        # Your code here
        result = await do_something()
        if span:
            span.set_attribute("result.size", len(result))
        return result
```

### Distributed Tracing

For federated deployments, trace context propagation is coming soon. This will allow you to see traces across multiple gateway instances.

## Examples

### Trace a Tool Invocation

```bash
# Make a request
curl -X POST http://localhost:4444/tools/invoke \
  -H "Content-Type: application/json" \
  -d '{"name": "calculator", "arguments": {"a": 1, "b": 2}}'

# View in your backend UI
# You'll see spans for:
# - HTTP request
# - tool.invoke
# - Plugin processing (if any)
# - Database queries
```

### Debug Slow Requests

Use the trace timeline to identify bottlenecks:
- Which operation took longest?
- Are there sequential operations that could be parallel?
- Is there excessive database querying?

### Monitor Error Rates

Traces with errors are marked and include:
- Exception type and message
- Stack trace
- Failed operation context

## See Also

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Phoenix Documentation](https://docs.arize.com/phoenix/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [Zipkin Documentation](https://zipkin.io/pages/documentation.html)
- [Tempo Documentation](https://grafana.com/docs/tempo/latest/)
