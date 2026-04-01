# OpenTelemetry Integration

ContextForge integrates OpenTelemetry (OTEL) for distributed tracing, providing comprehensive observability across MCP operations, tool invocations, and plugin execution.

## Overview

The OTEL integration provides:

- **W3C Trace Context Propagation**: Automatic propagation of trace context via `traceparent` headers
- **Request-Root Spans**: Every HTTP request creates a root span in the observability middleware
- **MCP Client Spans**: Detailed tracing of MCP protocol operations (initialize, request, response)
- **Plugin Hook Spans**: Visibility into plugin execution lifecycle
- **Session Pool Compatibility**: Trace context flows through pooled MCP sessions

## Architecture

### Span Hierarchy

```
http.request (root span)
├── mcp.client.call
│   ├── mcp.client.initialize
│   ├── mcp.client.request
│   └── mcp.client.response
├── plugin.hook.prompt_pre_fetch
├── plugin.hook.tool_pre_invoke
└── plugin.hook.tool_post_invoke
```

### Trace Context Flow

1. **Inbound Request**: Extract `traceparent` header from incoming HTTP request
2. **Root Span**: Create request-root span with extracted trace ID
3. **Child Spans**: All operations inherit trace context automatically
4. **Outbound Requests**: Inject `traceparent` header into MCP client calls
5. **Upstream Propagation**: Upstream MCP servers can attach their spans to the trace

## Configuration

### Environment Variables

```bash
# Enable OTEL tracing
OBSERVABILITY_ENABLED=true

# Exporter configuration
OTEL_EXPORTER_TYPE=otlp                           # otlp, jaeger, zipkin, console
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc                  # grpc or http

# Service identification
OTEL_SERVICE_NAME=mcp-gateway
OTEL_SERVICE_VERSION=1.0.0

# Resource attributes (comma-separated key=value pairs)
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production,service.namespace=mcp

# Batch processor tuning
OTEL_BSP_MAX_QUEUE_SIZE=2048
OTEL_BSP_MAX_EXPORT_BATCH_SIZE=512
OTEL_BSP_SCHEDULE_DELAY=5000

# Copy resource attributes to span attributes (for Arize compatibility)
OTEL_COPY_RESOURCE_ATTRS_TO_SPANS=false
```

### Langfuse Integration

For Langfuse observability, use the OTLP endpoint:

```bash
OTEL_EXPORTER_TYPE=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer sk-lf-...
```

## W3C Trace Context Propagation

### Inbound Propagation

The observability middleware automatically extracts W3C trace context from incoming requests:

```http
GET /mcp/sse HTTP/1.1
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

The middleware:
1. Parses the `traceparent` header
2. Extracts `trace-id` and `parent-span-id`
3. Creates a new span as a child of the external trace
4. Stores trace context in request state

### Outbound Propagation

When making MCP client calls, trace context is automatically injected:

```python
# Automatic injection in tool_service.py
pooled_headers = inject_trace_context_headers(headers)
```

This ensures:
- Upstream MCP servers receive `traceparent` header
- Distributed traces span multiple services
- End-to-end visibility across the call chain

## Session Pooling with Tracing

### Design Decision

**Previous Behavior (Incorrect):**
```python
# Session pool was disabled during tracing
if settings.mcp_session_pool_enabled and not tracing_active:
    use_pool = True
```

**Current Behavior (Correct):**
```python
# Session pool works with tracing
if settings.mcp_session_pool_enabled:
    pooled_headers = inject_trace_context_headers(headers)
    async with pool.session(url=server_url, headers=pooled_headers) as pooled:
        # Trace context flows through pooled session
```

### Why This Matters

1. **Performance**: Session pooling provides 10-20x latency improvement
2. **Trace Continuity**: Trace context must propagate through pooled sessions
3. **Header Pinning**: MCP SDK pins headers at transport creation, so trace headers must be injected before pooling

### Implementation Details

The session pool:
- Accepts trace headers at session creation time
- Pins headers to the transport for the session lifetime
- Reuses sessions across requests with the same identity
- Maintains trace context across pooled operations

## Security Considerations

### Sanitization

All sensitive data is sanitized before adding to OTEL spans:

```python
# Query string sanitization
"url.query": sanitize_trace_text(str(request.url.query))

# Exception message sanitization
sanitized_error = sanitize_for_log(sanitize_trace_text(str(e)))
"exception.message": sanitized_error
```

This prevents:
- Leaking credentials in query parameters
- Exposing sensitive error details
- Bypassing existing sanitization flows

### Data Minimization

Only essential attributes are exported:
- HTTP method, path, status code
- Tool names and IDs (not arguments)
- Timing information
- Error types (not full stack traces in production)

## Span Naming Conventions

All spans follow the `<domain>.<operation>` pattern:

| Domain | Operations | Example |
|--------|-----------|---------|
| `http` | `request` | `http.request` |
| `mcp.client` | `call`, `initialize`, `request`, `response` | `mcp.client.call` |
| `tool` | `invoke`, `list` | `tool.invoke` |
| `prompt` | `render`, `list` | `prompt.render` |
| `resource` | `invoke`, `list` | `resource.invoke` |
| `plugin.hook` | `prompt_pre_fetch`, `tool_pre_invoke`, etc. | `plugin.hook.tool_pre_invoke` |

## Semantic Attributes

### Standard Attributes

Following OpenTelemetry semantic conventions:

```python
{
    "http.method": "POST",
    "http.route": "/tools/invoke",
    "http.status_code": 200,
    "network.protocol.name": "mcp",
    "server.address": "localhost",
    "server.port": 8000,
    "url.path": "/mcp/sse",
    "url.full": "http://localhost:8000/mcp/sse",
}
```

### Custom Attributes

ContextForge-specific attributes use the `contextforge.` prefix:

```python
{
    "contextforge.tool.id": "tool-123",
    "contextforge.gateway_id": "gateway-456",
    "contextforge.runtime": "python",
    "contextforge.transport": "sse",
    "contextforge.user.email": "user@example.com",
    "contextforge.team.id": "team-789",
}
```

## Plugin Server Tracing

External plugin servers can enable OTEL tracing:

```bash
# In plugin server environment
OTEL_ENABLE_OBSERVABILITY=true
OTEL_SERVICE_NAME=my-plugin-server
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

**Important**: The `OTEL_SERVICE_NAME` must be set **before** importing `mcpgateway.observability`, as the tracer is initialized at import time.

## Performance Impact

### Overhead

- **Minimal**: ~1-2ms per request for span creation
- **Batch Export**: Spans are batched and exported asynchronously
- **Configurable**: Adjust batch size and delay via environment variables

### Optimization

```bash
# Increase batch size for high-throughput scenarios
OTEL_BSP_MAX_EXPORT_BATCH_SIZE=1024
OTEL_BSP_SCHEDULE_DELAY=10000  # 10 seconds

# Increase queue size to prevent drops
OTEL_BSP_MAX_QUEUE_SIZE=4096
```

## Troubleshooting

### No Traces Appearing

1. **Check OTEL is enabled**: `OBSERVABILITY_ENABLED=true`
2. **Verify exporter endpoint**: Test connectivity to OTLP endpoint
3. **Check service name**: Ensure `OTEL_SERVICE_NAME` is set correctly
4. **Review logs**: Look for "OpenTelemetry initialized" message

### Broken Trace Context

1. **Verify header injection**: Check that `inject_trace_context_headers()` is called
2. **Session pool headers**: Ensure headers are injected before `pool.session()`
3. **Upstream support**: Verify upstream MCP server supports W3C trace context

### Performance Issues

1. **Reduce batch delay**: Lower `OTEL_BSP_SCHEDULE_DELAY` for faster export
2. **Increase batch size**: Raise `OTEL_BSP_MAX_EXPORT_BATCH_SIZE` to reduce export frequency
3. **Check exporter**: Ensure OTLP endpoint is responsive

## Examples

### Basic Tracing

```python
from mcpgateway.observability import create_span, set_span_attribute

with create_span("custom.operation", {"custom.attr": "value"}):
    # Your code here
    set_span_attribute("result.count", 42)
```

### Distributed Tracing

```python
# Service A (ContextForge)
headers = inject_trace_context_headers(base_headers)
response = await httpx_client.post(upstream_url, headers=headers)

# Service B (Upstream MCP Server)
# Automatically extracts traceparent and attaches to trace
```

### Plugin Hook Tracing

```python
# Automatic tracing in plugin framework
async def tool_pre_invoke(self, payload, context):
    # This hook execution is automatically traced
    # Span name: plugin.hook.tool_pre_invoke
    return PluginResult(continue_processing=True)
```

## References

- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
- [Langfuse OTEL Integration](https://langfuse.com/docs/integrations/opentelemetry)
