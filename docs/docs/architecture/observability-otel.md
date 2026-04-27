# OpenTelemetry Integration

ContextForge integrates OpenTelemetry (OTEL) for distributed tracing, providing comprehensive observability across MCP operations, tool invocations, and plugin execution.

## Overview

The OTEL integration provides:

- **W3C Trace Context Propagation**: Automatic propagation of trace context via `traceparent` headers
- **W3C Baggage Support**: Optional extraction of allowlisted HTTP headers into OTEL baggage
- **Request-Root Spans**: Every HTTP request creates a root span in the observability middleware
- **MCP Client Spans**: Detailed tracing of MCP protocol operations (initialize, request, response)
- **Plugin Hook Spans**: Visibility into plugin execution lifecycle
- **Session Pool Awareness**: Non-pooled sessions propagate trace context and baggage; pooled sessions skip per-request propagation to prevent context pollution

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

Span attributes may also include request baggage dimensions, for example:
- `baggage.tenant.id`
- `baggage.user.id`
- `baggage.request.id`
```

### Trace Context Flow

1. **Inbound Request**: Extract `traceparent` header from incoming HTTP request
2. **Optional Baggage Extraction**: Convert configured request headers into OTEL baggage
3. **Root Span**: Create request-root span with extracted trace ID and baggage attributes
4. **Child Spans**: All operations inherit trace context automatically
5. **Outbound Requests**: Inject `traceparent` and optional `baggage` headers into MCP client calls
6. **Upstream Propagation**: Upstream MCP servers can attach their spans to the trace

## Configuration

### Environment Variables

```bash
# Enable OTEL tracing
OTEL_ENABLE_OBSERVABILITY=true

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

# Optional baggage extraction from inbound HTTP headers
OTEL_BAGGAGE_ENABLED=false
OTEL_BAGGAGE_HEADER_MAPPINGS='[
  {"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"},
  {"header_name": "X-User-ID", "baggage_key": "user.id"}
]'
OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL=false
OTEL_BAGGAGE_MAX_ITEMS=32
OTEL_BAGGAGE_MAX_SIZE_BYTES=8192
OTEL_BAGGAGE_LOG_REJECTED=true
OTEL_BAGGAGE_LOG_SANITIZATION=true
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

## W3C Baggage Support

### Purpose

W3C baggage carries low-cardinality request context alongside tracing information.
In ContextForge this is intended for metadata such as tenant, user, or request IDs
that improve trace filtering and cross-service diagnosis.

### Inbound Header Extraction

When baggage support is enabled, the gateway can map specific inbound HTTP headers
to baggage keys:


## Security-Enhanced Baggage Processing

### Dual Processing Model

ContextForge implements a **fail-closed security model** for baggage processing with two distinct input channels:

#### 1. Header Extraction (Gatekeeper)

Inbound HTTP headers are converted to baggage using an explicit allowlist:

```bash
OTEL_BAGGAGE_HEADER_MAPPINGS='[
  {"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"},
  {"header_name": "X-User-ID", "baggage_key": "user.id"}
]'
```

**Security Properties:**
- Only explicitly configured headers are processed
- Case-insensitive header matching prevents bypass
- Values are sanitized (control characters removed)
- Size limits prevent resource exhaustion
- Undefined headers are logged and rejected

#### 2. Inbound Baggage Header (Security Enhancement)

The W3C `baggage` header from upstream callers is also processed, but with strict filtering:

```http
GET /mcp/sse HTTP/1.1
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
baggage: tenant.id=tenant-123,user.id=user-456,malicious.key=attack
```

**Security Properties:**
- Only baggage keys matching configured `baggage_key` values are accepted
- Unauthorized keys (e.g., `malicious.key`) are filtered out
- Values undergo same sanitization as header-extracted baggage
- Same size and item limits apply
- Fail-closed: unknown keys are rejected, not propagated

### Configuration Approach

#### Production-Ready Example

```bash
# Enable baggage with security controls
OTEL_BAGGAGE_ENABLED=true

# Define allowlist: only these headers → baggage keys
OTEL_BAGGAGE_HEADER_MAPPINGS='[
  {"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"},
  {"header_name": "X-User-ID", "baggage_key": "user.id"},
  {"header_name": "X-Request-ID", "baggage_key": "request.id"},
  {"header_name": "X-Correlation-ID", "baggage_key": "correlation.id"}
]'

# Security: disable downstream propagation by default
OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL=false

# Resource limits
OTEL_BAGGAGE_MAX_ITEMS=32
OTEL_BAGGAGE_MAX_SIZE_BYTES=8192

# Audit logging
OTEL_BAGGAGE_LOG_REJECTED=true
OTEL_BAGGAGE_LOG_SANITIZATION=true
```

#### Multi-Tenant Example

```bash
# Multi-tenant SaaS with user context
OTEL_BAGGAGE_HEADER_MAPPINGS='[
  {"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"},
  {"header_name": "X-Organization-ID", "baggage_key": "org.id"},
  {"header_name": "X-User-ID", "baggage_key": "user.id"},
  {"header_name": "X-User-Email", "baggage_key": "user.email"},
  {"header_name": "X-Session-ID", "baggage_key": "session.id"}
]'
```

#### Distributed Tracing Example

```bash
# Enable downstream propagation for distributed tracing
OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL=true

# Minimal context for cross-service correlation
OTEL_BAGGAGE_HEADER_MAPPINGS='[
  {"header_name": "X-Request-ID", "baggage_key": "request.id"},
  {"header_name": "X-Trace-ID", "baggage_key": "trace.id"}
]'
```

### Security Implications of `PROPAGATE_TO_EXTERNAL`

#### When Disabled (Default - Recommended)

```bash
OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL=false
```

**Behavior:**
- Baggage is recorded on internal spans only
- Downstream MCP servers do NOT receive `baggage` header
- Trace context (`traceparent`) still propagates
- Prevents leaking tenant/user metadata to external services

**Use When:**
- Downstream services are untrusted or third-party
- Baggage contains sensitive tenant/user identifiers
- You want observability without metadata exposure
- Compliance requires data minimization

#### When Enabled (Opt-In)

```bash
OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL=true
```

**Behavior:**
- Baggage is sent to downstream MCP servers via `baggage` header
- Enables end-to-end correlation across service boundaries
- Downstream services can attach baggage to their spans

**Use When:**
- All downstream services are trusted and internal
- Cross-service correlation is required
- Downstream services need tenant/user context
- You control the entire service mesh

**Security Considerations:**
- Review what metadata is being propagated
- Ensure downstream services sanitize baggage
- Consider data residency and compliance requirements
- Monitor for baggage size explosion

### Validation and Constraints

#### Header Name Validation

```python
# Valid header names (RFC 7230)
X-Tenant-ID      ✅
X-User-ID        ✅
X-Request-ID     ✅

# Invalid header names
X-Tenant@ID      ❌ (special characters)
1-Tenant-ID      ❌ (starts with number)
X Tenant ID      ❌ (contains spaces)
```

#### Baggage Key Validation

```python
# Valid baggage keys (W3C spec)
tenant.id        ✅
user.id          ✅
request-id       ✅
user_email       ✅

# Invalid baggage keys
tenant@id        ❌ (special characters)
1tenant.id       ❌ (starts with number)
tenant id        ❌ (contains spaces)
```

#### Size Limits

| Limit | Default | Purpose |
|-------|---------|---------|
| Max Items | 32 | Prevent cardinality explosion |
| Max Size | 8192 bytes | Prevent resource exhaustion |
| Max Key Length | 256 chars | W3C spec compliance |
| Max Value Length | 4096 chars | Prevent header bloat |

### Sanitization Process

All baggage values undergo sanitization:

```python
# Control characters removed
"value\x00\x01\x02" → "value"

# Whitespace normalized
"value   with   spaces" → "value with spaces"

# Empty after sanitization → rejected
"\x00\x01\x02" → (rejected)
```

### Monitoring and Auditing

Enable logging to track security events:

```bash
OTEL_BAGGAGE_LOG_REJECTED=true      # Log rejected headers/keys
OTEL_BAGGAGE_LOG_SANITIZATION=true  # Log sanitized values
```

**Logged Events:**
- Rejected undefined headers (not in allowlist)
- Rejected unauthorized baggage keys (not in allowlist)
- Values sanitized (control characters removed)
- Size limit violations
- Item limit violations

### Best Practices

1. **Minimize Baggage Keys**: Only include essential correlation metadata
2. **Disable External Propagation**: Keep `PROPAGATE_TO_EXTERNAL=false` unless required
3. **Use Low-Cardinality Values**: Avoid high-cardinality data (e.g., timestamps, UUIDs in values)
4. **Enable Audit Logging**: Monitor rejected headers and sanitization events
5. **Review Regularly**: Audit configured mappings and remove unused entries
6. **Test Limits**: Verify size and item limits match your use case
7. **Document Mappings**: Maintain documentation of header → baggage key mappings



```http
GET /mcp/sse HTTP/1.1
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
X-Tenant-ID: tenant-123
X-User-ID: user-456
```

With this configuration:

```bash
OTEL_BAGGAGE_ENABLED=true
OTEL_BAGGAGE_HEADER_MAPPINGS='[
  {"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"},
  {"header_name": "X-User-ID", "baggage_key": "user.id"}
]'
```

the request context will carry baggage similar to:

```text
tenant.id=tenant-123,user.id=user-456
```

The baggage middleware runs before the request-root tracing middleware, so the root
request span and child spans can all see the same baggage values.

### Outbound Propagation

Outbound propagation of baggage is opt-in:

```bash
OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL=true
```

When enabled, outbound MCP client requests include a W3C `baggage` header in
addition to `traceparent`. When disabled, baggage remains internal to the gateway
and is recorded only on spans.

### Existing Inbound `baggage` Header

The gateway also parses inbound W3C `baggage` headers from upstream callers, but
it does not trust them blindly. Incoming baggage is filtered to the configured
baggage-key allowlist and is subject to sanitization and size limits before it is
merged into the active request context.

## Baggage Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_BAGGAGE_ENABLED` | `false` | Enables baggage extraction and span enrichment |
| `OTEL_BAGGAGE_HEADER_MAPPINGS` | `[]` | JSON array of `header_name` to `baggage_key` mappings |
| `OTEL_BAGGAGE_PROPAGATE_TO_EXTERNAL` | `false` | Sends baggage to downstream services when enabled |
| `OTEL_BAGGAGE_MAX_ITEMS` | `32` | Maximum accepted baggage items per request |
| `OTEL_BAGGAGE_MAX_SIZE_BYTES` | `8192` | Maximum combined baggage size from untrusted request input |
| `OTEL_BAGGAGE_LOG_REJECTED` | `true` | Logs rejected headers and baggage keys |
| `OTEL_BAGGAGE_LOG_SANITIZATION` | `true` | Logs when values are altered by sanitization |

## Session Pooling with Tracing

### Design Decision and Trade-off

**Current Behavior:**
```python
# Session pool enabled only when tracing context is inactive
if settings.mcp_session_pool_enabled and not otel_context_active():
    # Use base headers without trace context injection
    async with pool.session(url=server_url, headers=headers) as pooled:
        # Pool provides 10-20x latency improvement
        # But per-request trace context and baggage do NOT propagate upstream
```

### Why Trace Headers Are Not Injected

The MCP SDK pins headers at transport creation time. If we inject per-request
trace headers (`traceparent`, `X-Correlation-ID`) or baggage before pooling:

1. **Trace Corruption**: The first request's trace context gets pinned to the transport
2. **Context Leakage**: Later unrelated requests reuse the same trace ID
3. **Broken Distributed Tracing**: Upstream servers see wrong parent spans
4. **Correlation ID Leakage**: Different requests appear correlated when they're not
5. **Baggage Leakage**: Tenant or request metadata from one request bleeds into another

### The Trade-off

| Aspect | Pooled Sessions | Non-Pooled Sessions |
|--------|----------------|---------------------|
| **Latency** | 10-20x faster (reuse connection) | Slower (new connection each time) |
| **Trace Propagation** | ❌ No upstream propagation | ✅ Full W3C trace context |
| **Baggage Propagation** | ❌ No upstream propagation | ✅ Optional W3C baggage propagation |
| **Correlation IDs** | ❌ Not sent to upstream | ✅ Sent per-request |
| **Use Case** | High-throughput, internal tracing | Distributed tracing across services |

### When to Use Each

**Use Session Pooling** (default):
- High request volume to same MCP servers
- Internal observability is sufficient
- 10-20x latency improvement is critical
- Upstream servers don't need trace context or baggage

**Disable Session Pooling** (for distributed tracing):
```bash
MCP_SESSION_POOL_ENABLED=false
```
- Need end-to-end distributed tracing
- Upstream MCP servers participate in traces
- Need downstream baggage propagation
- Correlation IDs must reach upstream
- Latency is acceptable trade-off

### Implementation Details

The session pool:
- Reuses transports with pinned headers (base headers only)
- Does NOT inject per-request trace headers or baggage
- Provides 10-20x latency improvement
- Maintains internal trace context within gateway
- Upstream servers do not receive trace or baggage propagation

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

### Baggage Hardening

Header-to-baggage conversion uses a fail-closed model:

- Only explicitly configured headers are processed
- Only configured baggage keys are accepted from inbound `baggage` headers
- Values are sanitized before use and before downstream propagation
- Untrusted request input is constrained by item-count and size limits
- Downstream propagation is disabled by default

This reduces the risk of:
- High-cardinality baggage exploding span dimensions
- Propagating attacker-controlled metadata to downstream services
- Cross-request leakage through pooled transports
- Using observability channels to exfiltrate sensitive request content

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
    "baggage.tenant.id": "tenant-123",
    "baggage.user.id": "user-456",
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

## Related Documentation

### User Guides

- [Observability Overview](../manage/observability.md) - Choosing the right observability approach
- [OpenTelemetry Integration](../manage/observability/opentelemetry.md) - User-facing OTEL setup guide
- [Internal Observability](../manage/observability/internal.md) - Built-in database-backed tracing
- [Prometheus Metrics](../manage/observability/prometheus.md) - Time-series monitoring
- [Langfuse Integration](../manage/observability/langfuse.md) - LLM observability platform
- [Phoenix Integration](../manage/observability/phoenix.md) - AI/LLM-focused observability

### Technical References

- [OTEL Span Attributes Reference](otel-span-attributes.md) - Complete list of span attributes used in ContextForge
- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [W3C Baggage](https://www.w3.org/TR/baggage/)
- [Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
- [Langfuse OTEL Integration](https://langfuse.com/docs/integrations/opentelemetry)
