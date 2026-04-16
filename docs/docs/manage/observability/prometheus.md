# Prometheus Metrics

ContextForge exposes Prometheus metrics for monitoring gateway performance, request rates, error rates, and latency distributions.

## Overview

The Prometheus metrics endpoint provides:

- **Request metrics** - HTTP request counts, rates, and status codes
- **Latency metrics** - Request duration histograms with percentiles
- **Error tracking** - Error rates and types
- **Custom labels** - Static labels for environment identification
- **Gzip compression** - Reduced network usage for large metric sets

## Quick Start

### 1. Enable Metrics

```bash
# Enable Prometheus metrics endpoint
export ENABLE_METRICS=true

# Optional: Add custom labels (low-cardinality only)
export METRICS_CUSTOM_LABELS="env=production,region=us-east-1"

# Optional: Exclude high-frequency paths
export METRICS_EXCLUDED_HANDLERS="/servers/.*/sse,/static/.*"
```

### 2. Generate Scrape Token

Create a non-expiring JWT token for Prometheus to authenticate:

```bash
export METRICS_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username prometheus@monitoring \
  --exp 0 \
  --secret $JWT_SECRET_KEY \
  --algo HS256)

# Save to file for Prometheus
echo -n "$METRICS_TOKEN" > /path/to/metrics-token.jwt
```

### 3. Start ContextForge

```bash
mcpgateway
```

The metrics endpoint will be available at:

```
http://localhost:4444/metrics/prometheus
```

### 4. Verify Metrics

```bash
# Test the endpoint
curl -sS -H "Authorization: Bearer $METRICS_TOKEN" \
  http://localhost:4444/metrics/prometheus | head -n 20
```

## Prometheus Configuration

### Scrape Job

Add this job to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'mcp-gateway'
    metrics_path: /metrics/prometheus
    authorization:
      type: Bearer
      credentials_file: /path/to/metrics-token.jwt
    static_configs:
      - targets: ['localhost:4444']
```

### Docker Compose

If Prometheus runs in Docker, adjust the target:

```yaml
scrape_configs:
  - job_name: 'mcp-gateway'
    metrics_path: /metrics/prometheus
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/metrics-token.jwt
    static_configs:
      - targets: ['gateway:4444']  # Use service name
```

Mount the token file:

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - ./metrics-token.jwt:/etc/prometheus/metrics-token.jwt:ro
```

## Configuration Reference

### Environment Variables

| Variable | Description | Default | Options |
|----------|-------------|---------|---------|
| `ENABLE_METRICS` | Enable Prometheus endpoint | `false` | `true`, `false` |
| `METRICS_EXCLUDED_HANDLERS` | Regex patterns to exclude | (empty) | comma-separated |
| `METRICS_NAMESPACE` | Metrics namespace prefix | `default` | string |
| `METRICS_SUBSYSTEM` | Metrics subsystem prefix | (empty) | string |
| `METRICS_CUSTOM_LABELS` | Static labels for app_info | (empty) | `key=value,...` |

### Excluded Handlers

Exclude high-frequency or high-cardinality paths:

```bash
# Exclude SSE streams and static assets
METRICS_EXCLUDED_HANDLERS="/servers/.*/sse,/static/.*,/health.*"
```

Patterns are compiled as regular expressions and matched against request paths.

### Custom Labels

Add static labels to the `app_info` gauge:

```bash
# Low-cardinality labels only
METRICS_CUSTOM_LABELS="env=production,region=us-east-1,team=platform"
```

**Warning**: Never use high-cardinality values (user IDs, request IDs, timestamps) as labels.

## Available Metrics

### Request Metrics

```
# Total HTTP requests
http_requests_total{method="POST",handler="/tools/invoke",status="200"}

# Request rate (requests per second)
rate(http_requests_total[1m])
```

### Latency Metrics

```
# Request duration histogram
http_request_duration_seconds_bucket{le="0.1"}
http_request_duration_seconds_bucket{le="0.5"}
http_request_duration_seconds_bucket{le="1.0"}

# P50 latency
histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

# P95 latency
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

# P99 latency
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))
```

### Error Metrics

```
# Error rate (5xx responses)
rate(http_requests_total{status=~"5.."}[5m])

# Error percentage
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100
```

### Application Info

```
# Application metadata
app_info{env="production",region="us-east-1",version="1.0.0"}
```

## Grafana Dashboards

### Example Queries

**Request Rate**:
```promql
rate(http_requests_total[1m])
```

**Error Rate**:
```promql
rate(http_requests_total{status=~"5.."}[5m])
```

**P99 Latency**:
```promql
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))
```

**Success Rate**:
```promql
sum(rate(http_requests_total{status=~"2.."}[5m])) / sum(rate(http_requests_total[5m])) * 100
```

### Dashboard Panels

Create panels for:

1. **Request Rate** - Line graph of requests per second
2. **Error Rate** - Line graph of 5xx errors per second
3. **Latency Percentiles** - Multi-line graph (P50, P95, P99)
4. **Status Code Distribution** - Pie chart or bar graph
5. **Top Endpoints** - Table sorted by request count

### Import Dashboards

Use community dashboards for common components:

- **Kubernetes**: Dashboard ID 315
- **PostgreSQL**: Dashboard ID 9628
- **Redis**: Dashboard ID 11835

## Production Deployment

### Kubernetes

Deploy Prometheus with the gateway:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: prometheus-token
type: Opaque
stringData:
  token: <base64-encoded-jwt>
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
data:
  prometheus.yml: |
    scrape_configs:
      - job_name: 'mcp-gateway'
        metrics_path: /metrics/prometheus
        authorization:
          type: Bearer
          credentials: <token-from-secret>  # pragma: allowlist secret
        kubernetes_sd_configs:
          - role: pod
            namespaces:
              names:
                - mcp-gateway
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_label_app]
            action: keep
            regex: mcp-gateway
```

### High Availability

For HA deployments:

1. **Multiple Prometheus instances** - Scrape all gateway replicas
2. **Federation** - Aggregate metrics from multiple Prometheus servers
3. **Remote Write** - Send metrics to long-term storage (Thanos, Cortex)

### Retention

Configure Prometheus retention:

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

# Command line flags
--storage.tsdb.retention.time=30d
--storage.tsdb.retention.size=50GB
```

## Security Best Practices

### Token Management

1. **Non-expiring tokens** - Use `--exp 0` for service accounts
2. **Rotate regularly** - Update tokens quarterly
3. **Restrict permissions** - Token only needs read access
4. **Secure storage** - Store tokens in secrets management

### Network Security

1. **Internal network** - Keep Prometheus on private network
2. **Firewall rules** - Restrict access to metrics endpoint
3. **TLS** - Use HTTPS for production deployments
4. **Authentication** - Always require JWT authentication

## Performance Considerations

### High-Cardinality Labels

**Never use** high-cardinality values as labels:

```bash
# BAD - Explodes time series
http_requests_total{user_id="12345",request_id="abc-123"}

# GOOD - Low cardinality
http_requests_total{method="POST",status="200"}
```

High-cardinality labels can:
- Crash Prometheus with OOM errors
- Slow down queries significantly
- Increase storage requirements exponentially

### Compression

The metrics endpoint supports gzip compression:

```bash
# Prometheus automatically uses compression
curl -H "Accept-Encoding: gzip" \
     -H "Authorization: Bearer $TOKEN" \
     http://localhost:4444/metrics/prometheus
```

**Trade-off**: Compression reduces network usage but increases CPU on scrape.

### Scrape Interval

Balance freshness vs. load:

```yaml
# High frequency (more load)
scrape_interval: 5s

# Standard (recommended)
scrape_interval: 15s

# Low frequency (less load)
scrape_interval: 30s
```

### Excluded Handlers

Reduce metric cardinality by excluding paths:

```bash
# Exclude high-frequency endpoints
METRICS_EXCLUDED_HANDLERS="/health,/healthz,/ready,/metrics,/static/.*"
```

## Troubleshooting

### No Metrics Appearing

1. **Check metrics are enabled**:
   ```bash
   echo $ENABLE_METRICS  # Should be "true"
   ```

2. **Verify endpoint is accessible**:
   ```bash
   curl -v http://localhost:4444/metrics/prometheus
   # Should return 401 without token
   ```

3. **Test with token**:
   ```bash
   curl -H "Authorization: Bearer $METRICS_TOKEN" \
     http://localhost:4444/metrics/prometheus
   ```

4. **Check gateway logs**:
   ```bash
   docker logs mcpgateway | grep -i metrics
   ```

### Metrics Disabled Response

If metrics are disabled, the endpoint returns:

```json
{
  "detail": "Metrics endpoint is disabled. Set ENABLE_METRICS=true to enable."
}
```

Status code: 503 Service Unavailable

### Authentication Errors

```json
{
  "detail": "Not authenticated"
}
```

**Solutions**:
1. Verify token is valid: `python -m mcpgateway.utils.verify_jwt_token --token $METRICS_TOKEN`
2. Check token hasn't expired
3. Ensure `JWT_SECRET_KEY` matches between token generation and gateway

### High Memory Usage

If Prometheus uses excessive memory:

1. **Reduce retention**: `--storage.tsdb.retention.time=7d`
2. **Increase scrape interval**: `scrape_interval: 30s`
3. **Exclude high-cardinality paths**: `METRICS_EXCLUDED_HANDLERS`
4. **Review custom labels**: Remove high-cardinality labels

### Duplicate Collectors

Error: "Collector already registered"

**Cause**: Instrumentation registered multiple times (tests, reloads)

**Solution**: Restart the gateway process or clear the registry in test fixtures

## Integration with Other Systems

### Datadog

Forward Prometheus metrics to Datadog:

```yaml
# datadog-agent.yaml
prometheus_scrape:
  enabled: true
  configs:
    - configurations:
        - url: http://gateway:4444/metrics/prometheus
          headers:
            Authorization: Bearer <token>
```

### New Relic

Use the Prometheus OpenMetrics integration:

```yaml
# newrelic-infrastructure.yml
integrations:
  - name: nri-prometheus
    config:
      urls:
        - http://gateway:4444/metrics/prometheus
      bearer_token: <token>
```

### Splunk

Use the Splunk OpenTelemetry Collector:

```yaml
# otel-collector-config.yaml
receivers:
  prometheus:
    config:
      scrape_configs:
        - job_name: 'mcp-gateway'
          authorization:
            type: Bearer
            credentials: <token>  # pragma: allowlist secret
          static_configs:
            - targets: ['gateway:4444']
```

## Next Steps

- [Internal Observability](internal.md) - Built-in database-backed tracing
- [OpenTelemetry](opentelemetry.md) - Distributed tracing with OTLP
- [Grafana Setup](../scale.md#grafana-dashboards) - Dashboard configuration

## Related Documentation

- [Configuration Reference](../configuration.md#prometheus-metrics) - All metrics settings
- [Scaling Guide](../scale.md) - Production deployment patterns
- [Security Features](../../architecture/security-features.md) - Authentication and authorization
