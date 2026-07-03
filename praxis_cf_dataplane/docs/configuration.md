# Praxis MCP Dataplane Configuration Guide

This guide covers all configuration options for the Praxis MCP dataplane filter library.

## Deployment Model

The `praxis_cf_dataplane` crate is a **filter library** that is loaded by the standard `praxis-proxy` server:

1. Add `praxis_cf_dataplane` to the Praxis server's `Cargo.toml`:
   ```toml
   [dependencies]
   praxis_cf_dataplane = { path = "../praxis_cf_dataplane" }
   ```

2. Praxis build.rs auto-discovers filters via `[package.metadata.praxis-filters]` marker

3. Configure filters in `praxis_cf_dataplane.yaml`

4. Run: `praxis-proxy -c praxis_cf_dataplane.yaml`

## Configuration File

The dataplane is configured via `praxis_cf_dataplane.yaml`. All configuration values support environment variable substitution using `${VAR_NAME:-default}` syntax.

**Note:** Server-level configuration (host, port, TLS, logging) is handled by Praxis. This guide focuses on filter-specific configuration.

## Environment Variables

### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8080` | Server listen port |
| `WORKERS` | `4` | Number of worker threads |
| `MAX_CONNECTIONS` | `10000` | Maximum concurrent connections |

### TLS Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TLS_ENABLED` | `false` | Enable TLS/HTTPS |
| `TLS_CERT_PATH` | - | Path to TLS certificate file |
| `TLS_KEY_PATH` | - | Path to TLS private key file |

### Logging Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Log level: `trace`, `debug`, `info`, `warn`, `error` |
| `LOG_FORMAT` | `json` | Log format: `json` or `text` |

### Observability Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSERVABILITY_ENABLED` | `false` | Enable OpenTelemetry observability |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP exporter endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | OTLP protocol: `grpc` or `http` |
| `TRACING_ENABLED` | `true` | Enable distributed tracing |
| `TRACE_SAMPLE_RATE` | `1.0` | Trace sampling rate (0.0-1.0) |
| `OTEL_SERVICE_NAME` | `praxis_cf_dataplane` | Service name for traces |
| `METRICS_ENABLED` | `true` | Enable metrics collection |
| `METRICS_EXPORT_INTERVAL` | `60` | Metrics export interval (seconds) |

### Control Plane Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTROL_PLANE_GRPC_ENDPOINT` | `http://localhost:50051` | Control plane gRPC endpoint |
| `CONTROL_PLANE_CONNECT_TIMEOUT` | `5` | Connection timeout (seconds) |
| `CONTROL_PLANE_REQUEST_TIMEOUT` | `10` | Request timeout (seconds) |

### Session Cache Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_CACHE_ENABLED` | `true` | Enable session caching |
| `SESSION_CACHE_TTL` | `300` | Session cache TTL (seconds) |
| `SESSION_CACHE_MAX_SIZE` | `10000` | Maximum cached sessions |

### MCP Protocol Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_MAX_BODY_BYTES` | `1048576` | Maximum request body size (1MB) |

### Upstream Proxy Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `UPSTREAM_TIMEOUT` | `30` | Upstream request timeout (seconds) |
| `UPSTREAM_MAX_RETRIES` | `3` | Maximum retry attempts for upstream requests |

## Deployment Scenarios

### Development (Local)

```bash
# Minimal configuration for local development
export HOST=127.0.0.1
export PORT=8080
export LOG_LEVEL=debug
export LOG_FORMAT=text
export CONTROL_PLANE_GRPC_ENDPOINT=http://localhost:50051
export SESSION_CACHE_ENABLED=true

./praxis_cf_dataplane --config praxis_cf_dataplane.yaml
```

### Production (Docker)

```dockerfile
FROM rust:1.85 as builder
WORKDIR /app
COPY . .
RUN cargo build --release --bin praxis_cf_dataplane

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/praxis_cf_dataplane /usr/local/bin/
COPY --from=builder /app/praxis_cf_dataplane/praxis_cf_dataplane.yaml /etc/praxis/
COPY --from=builder /app/praxis_cf_dataplane/policies /etc/praxis/policies/

ENV HOST=0.0.0.0
ENV PORT=8080
ENV WORKERS=8
ENV LOG_LEVEL=info
ENV LOG_FORMAT=json
ENV OBSERVABILITY_ENABLED=true
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317

EXPOSE 8080
CMD ["praxis_cf_dataplane", "--config", "/etc/praxis/praxis_cf_dataplane.yaml"]
```

### Production (Kubernetes)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: praxis-cf-dataplane
spec:
  replicas: 3
  selector:
    matchLabels:
      app: praxis-cf-dataplane
  template:
    metadata:
      labels:
        app: praxis-cf-dataplane
    spec:
      containers:
      - name: dataplane
        image: contextforge/praxis-cf-dataplane:latest
        ports:
        - containerPort: 8080
          name: http
        env:
        - name: HOST
          value: "0.0.0.0"
        - name: PORT
          value: "8080"
        - name: WORKERS
          value: "8"
        - name: MAX_CONNECTIONS
          value: "50000"
        - name: LOG_LEVEL
          value: "info"
        - name: LOG_FORMAT
          value: "json"
        - name: OBSERVABILITY_ENABLED
          value: "true"
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://otel-collector:4317"
        - name: CONTROL_PLANE_GRPC_ENDPOINT
          value: "http://control-plane:50051"
        - name: SESSION_CACHE_TTL
          value: "300"
        - name: SESSION_CACHE_MAX_SIZE
          value: "50000"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: praxis-cf-dataplane
spec:
  selector:
    app: praxis-cf-dataplane
  ports:
  - port: 8080
    targetPort: 8080
    name: http
  type: ClusterIP
```

## Filter Configuration

### McpFilter (Praxis Built-in)

Validates MCP protocol and extracts metadata.

```yaml
- filter: mcp
  config:
    max_body_bytes: 1048576  # 1MB
    on_invalid: reject
    metadata:
      method: mcp.method
      name: mcp.name
      jsonrpc_id: mcp.jsonrpc_id
```

### cf_control_plane_data (Custom)

Fetches session and virtual server configuration.

```yaml
- filter: cf_control_plane_data
  config:
    grpc_endpoint: http://localhost:50051
    session_cache_ttl: 300
    session_cache_size: 10000
    connect_timeout: 5
    request_timeout: 10
```

### CPEX Policy Filters

Evaluate OPA/Rego policies for authorization.

```yaml
- filter: cpex_policy
  name: pre_routing_authz
  config:
    policy_file: policies/pre_routing.rego
    policy_package: contextforge.pre_routing
    decision_rule: allow
    input_metadata:
      method: mcp.method
      user_email: mcp.user_email
      teams: mcp.teams
    on_deny:
      status: 403
      body: '{"error": "Access denied"}'
```

### cf_tools_router (Custom)

Routes requests to gateway or upstream.

```yaml
- filter: cf_tools_router
  config:
    grpc_endpoint: http://localhost:50051
    input_metadata:
      method: mcp.method
      virtual_server_id: mcp.virtual_server_id
    output_metadata:
      route: mcp.route
      gateway_id: mcp.gateway_id
```

### cf_mcp_broker (Custom)

Executes gateway tools (conditional on route=gateway).

```yaml
- filter: cf_mcp_broker
  config:
    grpc_endpoint: http://localhost:50051
    condition:
      metadata_equals:
        mcp.route: gateway
```

### cf_upstream_proxy (Custom)

Forwards to upstream servers (conditional on route=upstream).

```yaml
- filter: cf_upstream_proxy
  config:
    timeout_seconds: 30
    max_retries: 3
    condition:
      metadata_equals:
        mcp.route: upstream
```

## Policy Configuration

### Pre-Routing Policy (policies/pre_routing.rego)

Controls virtual server access.

**Input:**
- `input.method` - MCP method
- `input.name` - Tool name (for tools/call)
- `input.user_email` - User email
- `input.teams` - User teams
- `input.is_admin` - Admin flag
- `input.virtual_server_tools` - Exposed tools
- `input.virtual_server_access_policy` - RBAC rules

**Output:**
- `allow` - Boolean authorization decision
- `reason` - Denial reason (if denied)

### Post-Routing Policy (policies/post_routing.rego)

Controls gateway/upstream access.

**Input:**
- `input.route` - Routing decision (gateway/upstream)
- `input.gateway_id` - Gateway ID
- `input.upstream_url` - Upstream URL
- `input.user_email` - User email
- `input.teams` - User teams
- `input.is_admin` - Admin flag
- `input.user_allowed_gateways` - Allowed gateways
- `input.user_allowed_upstreams` - Allowed upstreams

**Output:**
- `allow` - Boolean authorization decision
- `reason` - Denial reason (if denied)

## Performance Tuning

### Worker Threads

Set `WORKERS` based on CPU cores:
- Development: 2-4 workers
- Production: 1-2 workers per CPU core

### Connection Limits

Set `MAX_CONNECTIONS` based on expected load:
- Low traffic: 1,000-5,000
- Medium traffic: 10,000-25,000
- High traffic: 50,000-100,000

### Session Cache

Tune cache size based on active users:
- Small deployment: 1,000-5,000
- Medium deployment: 10,000-25,000
- Large deployment: 50,000-100,000

Cache TTL should match JWT expiration:
- Short-lived tokens: 300s (5 minutes)
- Long-lived tokens: 3600s (1 hour)

### Upstream Timeouts

Set based on upstream server response times:
- Fast upstreams: 10-30 seconds
- Slow upstreams: 60-120 seconds
- Long-running operations: 300+ seconds

## Monitoring

### Health Endpoints

- `GET /health` - Liveness probe (always returns 200)
- `GET /ready` - Readiness probe (checks control plane connectivity)
- `GET /metrics` - Prometheus metrics (if enabled)

### Key Metrics

- `praxis_requests_total` - Total requests processed
- `praxis_request_duration_seconds` - Request latency histogram
- `praxis_filter_duration_seconds` - Per-filter latency
- `praxis_control_plane_requests_total` - Control plane gRPC calls
- `praxis_session_cache_hits_total` - Session cache hit rate
- `praxis_upstream_requests_total` - Upstream proxy requests

### Tracing

Enable distributed tracing for request flow visibility:

```bash
export OBSERVABILITY_ENABLED=true
export TRACING_ENABLED=true
export TRACE_SAMPLE_RATE=0.1  # Sample 10% of requests
export OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

## Security Considerations

### TLS Configuration

Always enable TLS in production:

```bash
export TLS_ENABLED=true
export TLS_CERT_PATH=/etc/tls/cert.pem
export TLS_KEY_PATH=/etc/tls/key.pem
```

### Control Plane Security

Use TLS for control plane communication:

```bash
export CONTROL_PLANE_GRPC_ENDPOINT=https://control-plane:50051
```

### Policy Updates

Policies can be updated without restart by mounting them as ConfigMaps in Kubernetes:

```yaml
volumes:
- name: policies
  configMap:
    name: praxis-policies
volumeMounts:
- name: policies
  mountPath: /etc/praxis/policies
  readOnly: true
```

## Troubleshooting

### High Latency

1. Check control plane response times
2. Increase worker threads
3. Tune session cache size
4. Enable request tracing

### Connection Errors

1. Verify control plane endpoint
2. Check network connectivity
3. Increase connection timeout
4. Review firewall rules

### Policy Denials

1. Enable debug logging
2. Review policy evaluation traces
3. Check metadata values
4. Validate policy logic with OPA REPL

### Memory Usage

1. Reduce session cache size
2. Decrease worker threads
3. Lower max connections
4. Enable memory profiling
