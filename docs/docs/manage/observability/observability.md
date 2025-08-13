# MCP Gateway Observability with Phoenix

## Overview

MCP Gateway integrates with [Arize Phoenix](https://github.com/Arize-ai/phoenix) for distributed tracing and observability. This provides visibility into:

- Tool invocations
- Prompt rendering
- Resource fetching
- Gateway federation
- Plugin execution
- Error tracking and performance metrics

## Quick Start

### 1. Start Phoenix

Using Docker Compose:
```bash
docker-compose -f docker-compose.phoenix-simple.yml up -d
```

Or with the gateway:
```bash
docker-compose -f docker-compose.yml -f docker-compose.with-phoenix.yml up -d
```

### 2. Configure MCP Gateway

Set environment variables:
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=mcp-gateway
export OTEL_TRACES_EXPORTER=otlp
```

### 3. Start Gateway with Tracing

```bash
# Using make
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
OTEL_SERVICE_NAME=mcp-gateway \
make serve

# Or use the helper script
./serve-with-tracing.sh

# Or with uvicorn directly
uvicorn mcpgateway.main:app --host 0.0.0.0 --port 4444
```

### 4. View Traces

Open Phoenix UI: http://localhost:6006

## What Gets Traced

### Tool Operations
- **Span name**: `tool.invoke`
- **Attributes**:
  - `tool.name` - Tool identifier
  - `tool.id` - Database ID
  - `tool.integration_type` - REST or MCP
  - `tool.gateway_id` - Associated gateway
  - `arguments_count` - Number of arguments
  - `http.status_code` - Response status (REST tools)
  - `duration.ms` - Execution time
  - `error` - Error flag if failed
  - `error.message` - Error details

### Prompt Rendering
- **Span name**: `prompt.render`
- **Attributes**:
  - `prompt.name` - Prompt template name
  - `arguments_count` - Template arguments
  - `user` - User identifier
  - `server_id` - Server context
  - `messages.count` - Rendered messages
  - `duration.ms` - Render time

### Resource Fetching
- **Span name**: `resource.read`
- **Attributes**:
  - `resource.uri` - Resource identifier
  - `resource.type` - template or static
  - `content.size` - Content size in bytes
  - `http.url` - URL if HTTP resource
  - `duration.ms` - Fetch time

### Gateway Federation
- **Span name**: `gateway.forward_request`
- **Attributes**:
  - `gateway.name` - Target gateway
  - `gateway.url` - Gateway endpoint
  - `rpc.method` - RPC method name
  - `rpc.service` - Service identifier
  - `http.status_code` - Response status
  - `peer.service` - Remote service name

### Health Checks
- **Span name**: `gateway.health_check`
- **Attributes**:
  - `gateway.name` - Gateway being checked
  - `gateway.transport` - SSE or StreamableHTTP
  - `health.status` - healthy/unhealthy
  - `http.status_code` - Response code

## Error Tracking

All spans automatically record exceptions with:
- Full stack traces
- Error types and messages
- Failed operation context
- OpenTelemetry status codes

Example error attributes:
```
error: true
error.type: "ToolInvocationError"
error.message: "Connection timeout"
```

## Performance Monitoring

Key metrics tracked:
- `duration.ms` - Operation duration
- `success` - Success/failure flag
- Response sizes and counts
- HTTP status codes
- Queue depths (future)

## Distributed Tracing

### Trace Context Propagation

When MCP Gateway calls other services, trace context is propagated via:
- W3C Trace Context headers
- OpenTelemetry baggage
- Custom correlation IDs

### Parent-Child Relationships

Operations create nested spans:
```
gateway.health_check_batch
  └── gateway.health_check (gateway-1)
  └── gateway.health_check (gateway-2)
  └── gateway.health_check (gateway-3)
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Phoenix OTLP endpoint | None (tracing disabled) |
| `OTEL_SERVICE_NAME` | Service identifier | mcp-gateway |
| `OTEL_TRACES_EXPORTER` | Exporter type | otlp |
| `OTEL_RESOURCE_ATTRIBUTES` | Additional attributes | None |

### Sampling Configuration

Control trace sampling (future implementation):
```bash
# Sample 10% of traces
export OTEL_TRACES_SAMPLER=traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.1
```

## Phoenix UI Features

### Trace Explorer
- Search traces by operation, service, or attributes
- Filter by time range, status, or duration
- Visualize trace waterfall diagrams

### Service Map
- View service dependencies
- Identify bottlenecks
- Monitor service health

### Metrics Dashboard
- Operation latencies (P50, P95, P99)
- Error rates and types
- Throughput and volume

### LLM-Specific Features
- Token usage tracking
- Prompt/completion analysis
- Model performance comparison
- Cost estimation

## Troubleshooting

### No Traces Appearing

1. Check Phoenix is running:
```bash
docker ps | grep phoenix
curl http://localhost:6006/health
```

2. Verify environment variables:
```bash
env | grep OTEL
```

3. Check gateway logs for initialization:
```
✅ OpenTelemetry initialized with Phoenix endpoint: http://localhost:4317
```

4. Test with sample traces:
```bash
python test_phoenix_integration.py
```

### Connection Errors

If you see "Failed to export spans":
- Verify Phoenix is accessible
- Check firewall/network settings
- Ensure correct OTLP endpoint

### Performance Impact

Tracing adds minimal overhead (~1-3ms per operation). To reduce impact:
- Use sampling in production
- Batch span exports
- Filter noisy operations

## Advanced Usage

### Custom Spans

Add tracing to custom code:

```python
from mcpgateway.observability import create_span

async def my_operation():
    with create_span("custom.operation", {
        "custom.attribute": "value",
        "user.id": user_id
    }) as span:
        result = await do_work()
        span.set_attribute("result.size", len(result))
        return result
```

### Trace Decorators

Use decorators for cleaner code:

```python
from mcpgateway.observability import trace_operation

@trace_operation("database.query", {"db.system": "postgresql"})
async def query_database(sql):
    return await db.execute(sql)
```

### Manual Context Propagation

For external service calls:

```python
from opentelemetry import trace
from opentelemetry.propagate import inject

headers = {}
inject(headers)  # Adds trace context headers
await httpx.post(url, headers=headers)
```

## Best Practices

1. **Use semantic conventions** - Follow OpenTelemetry standards for attribute names
2. **Add meaningful attributes** - Include context that helps debugging
3. **Handle errors properly** - Record exceptions with full context
4. **Batch operations** - Group related operations under parent spans
5. **Sample in production** - Use sampling to control costs and performance
6. **Secure sensitive data** - Don't include passwords, tokens, or PII in traces
7. **Monitor continuously** - Set up alerts for error rates and latencies

## Integration with Other Tools

Phoenix integrates with:
- **Grafana** - Import traces for visualization
- **Prometheus** - Export metrics
- **Datadog** - Forward traces
- **New Relic** - Send telemetry data
- **Jaeger** - Alternative trace viewer

## Resources

- [Phoenix Documentation](https://docs.arize.com/phoenix)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
- [MCP Gateway Plugins](./plugins.md)
- [Performance Tuning](./performance.md)
