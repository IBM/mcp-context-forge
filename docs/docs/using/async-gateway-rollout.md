# Asynchronous Gateway Lifecycle Rollout Guide

This guide provides step-by-step instructions for enabling and rolling out the asynchronous gateway lifecycle feature in production environments.

---

## Overview

The asynchronous gateway lifecycle feature provides HTTP 202 Accepted responses for long-running gateway operations (create, update, delete), with background worker processing and automatic retry logic. This prevents API timeouts and provides better visibility into operation progress.

### Benefits

- **No API timeouts** - Operations return immediately with 202 Accepted
- **Better visibility** - Track operation progress via status polling
- **Automatic retry** - Exponential backoff handles transient failures
- **Graceful cancellation** - DELETE stops pending operations
- **Zero breaking changes** - Feature flag controlled, synchronous behavior preserved when disabled

---

## Prerequisites

Before enabling the feature:

1. **Review the API reference** - [Gateway Lifecycle Async API](../manage/gateway-lifecycle-async.md)
2. **Verify worker configuration** - Ensure worker environment variables are set
3. **Check database compatibility** - PostgreSQL recommended for production (SQLite supported for dev/test)
4. **Plan monitoring** - Set up metrics and alerts for worker health

---

## Rollout Steps

### Step 1: Review Configuration

Check your current configuration in `.env` or environment variables:

```bash
# Feature flag (default: false)
GATEWAY_ASYNC_LIFECYCLE_ENABLED=false

# Worker configuration (defaults shown)
GATEWAY_WORKER_POLL_INTERVAL_SECONDS=5
GATEWAY_WORKER_BATCH_SIZE=10

# Database (PostgreSQL recommended for production)
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname
```

### Step 2: Enable Feature Flag

Update your environment configuration:

```bash
# .env or environment variables
GATEWAY_ASYNC_LIFECYCLE_ENABLED=true
```

**Deployment Methods:**

=== "Docker Compose"
    ```yaml
    # docker-compose.yml
    services:
      mcpgateway:
        environment:
          - GATEWAY_ASYNC_LIFECYCLE_ENABLED=true
          - GATEWAY_WORKER_POLL_INTERVAL_SECONDS=5
          - GATEWAY_WORKER_BATCH_SIZE=10
    ```

=== "Kubernetes"
    ```yaml
    # deployment.yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: mcpgateway
    spec:
      template:
        spec:
          containers:
          - name: mcpgateway
            env:
            - name: GATEWAY_ASYNC_LIFECYCLE_ENABLED
              value: "true"
            - name: GATEWAY_WORKER_POLL_INTERVAL_SECONDS
              value: "5"
            - name: GATEWAY_WORKER_BATCH_SIZE
              value: "10"
    ```

=== "Helm"
    ```yaml
    # values.yaml
    config:
      gatewayAsyncLifecycleEnabled: true
      gatewayWorkerPollIntervalSeconds: 5
      gatewayWorkerBatchSize: 10
    ```

=== "Direct"
    ```bash
    # Export environment variables
    export GATEWAY_ASYNC_LIFECYCLE_ENABLED=true
    export GATEWAY_WORKER_POLL_INTERVAL_SECONDS=5
    export GATEWAY_WORKER_BATCH_SIZE=10
    
    # Restart service
    make serve
    ```

### Step 3: Restart Application

Restart the ContextForge application to apply the configuration:

```bash
# Docker Compose
docker-compose restart mcpgateway

# Kubernetes
kubectl rollout restart deployment/mcpgateway

# Systemd
sudo systemctl restart mcpgateway

# Direct
# Stop current process (Ctrl+C) and restart
make serve
```

### Step 4: Verify Worker Startup

Check logs to confirm the worker started successfully:

```bash
# Docker Compose
docker-compose logs -f mcpgateway | grep -i "worker"

# Kubernetes
kubectl logs -f deployment/mcpgateway | grep -i "worker"

# Direct
tail -f logs/mcpgateway.log | grep -i "worker"
```

**Expected log output:**
```
INFO: Gateway worker started
INFO: Worker polling interval: 5 seconds
INFO: Worker batch size: 10
```

### Step 5: Test with Sample Gateway

Create a test gateway to verify async behavior:

```bash
# Set up authentication
export TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --admin \
  --exp 10080 \
  --secret your-jwt-secret 2>/dev/null | head -1)

export BASE_URL="http://localhost:4444"

# Create gateway (should return 202)
curl -X POST "$BASE_URL/admin/gateways" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-async-gateway",
    "url": "http://localhost:9000",
    "transport": "sse"
  }' | jq
```

**Expected response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "test-async-gateway",
  "status": "pending",
  "status_message": "Gateway registration queued",
  "registration_attempts": 0
}
```

**Response headers should include:**
```
HTTP/1.1 202 Accepted
Retry-After: 5
Location: /admin/gateways/test-async-gateway
```

### Step 6: Monitor Operation Progress

Poll the gateway status to track progress:

```bash
# Poll every 5 seconds
watch -n 5 "curl -s -H 'Authorization: Bearer $TOKEN' \
  '$BASE_URL/admin/gateways/test-async-gateway' | jq '.status, .status_message, .registration_attempts'"
```

**Expected progression:**
```
# Initial
"pending"
"Gateway registration queued"
0

# After worker processes
"active"
"Gateway active"
0
```

### Step 7: Verify Cleanup

Delete the test gateway:

```bash
curl -X DELETE "$BASE_URL/admin/gateways/test-async-gateway" \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Expected response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "test-async-gateway",
  "status": "deleting",
  "status_message": "Gateway deletion queued"
}
```

---

## Monitoring Recommendations

### Metrics to Track

Monitor these key metrics for worker health:

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `gateway_status_total{status="pending"}` | Number of pending gateways | > 10 for > 5 minutes |
| `gateway_registration_attempts` | Retry attempts per gateway | > 10 attempts |
| `gateway_pending_duration_seconds` | Time in pending state | > 300 seconds |
| `gateway_registration_errors_total` | Total registration errors | Increasing trend |

### Prometheus Queries

```promql
# Pending gateways count
sum(gateway_status_total{status="pending"})

# Average pending duration
avg(gateway_pending_duration_seconds)

# Error rate
rate(gateway_registration_errors_total[5m])

# Gateways stuck in pending (>5 minutes)
count(gateway_pending_duration_seconds > 300)
```

### Alerting Rules

```yaml
# prometheus-alerts.yaml
groups:
- name: gateway_worker
  interval: 30s
  rules:
  - alert: GatewayWorkerStuck
    expr: sum(gateway_status_total{status="pending"}) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Multiple gateways stuck in pending state"
      description: "{{ $value }} gateways have been pending for >5 minutes"
  
  - alert: GatewayRegistrationFailures
    expr: rate(gateway_registration_errors_total[5m]) > 0.1
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "High gateway registration error rate"
      description: "Error rate: {{ $value }} errors/sec"
  
  - alert: GatewayWorkerDown
    expr: up{job="mcpgateway"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Gateway worker is down"
      description: "Worker has been down for >1 minute"
```

### Log Monitoring

Monitor worker logs for errors:

```bash
# Docker Compose
docker-compose logs -f mcpgateway | grep -E "(ERROR|WARN|worker)"

# Kubernetes
kubectl logs -f deployment/mcpgateway | grep -E "(ERROR|WARN|worker)"
```

**Key log patterns to watch:**

- `ERROR: Worker error:` - Worker processing errors
- `WARN: Gateway registration failed:` - MCP connection failures
- `INFO: Gateway worker stopped` - Unexpected worker shutdown

---

## Scaling Considerations

### Single Worker (SQLite)

**Recommended for:**
- Development environments
- Small deployments (<100 gateways)
- SQLite database

**Configuration:**
```bash
DATABASE_URL=sqlite:///./mcp.db
GATEWAY_WORKER_POLL_INTERVAL_SECONDS=5
GATEWAY_WORKER_BATCH_SIZE=10
```

**Limitations:**
- No concurrent worker support
- Status re-check prevents races (acceptable for dev/test)

### Multiple Workers (PostgreSQL)

**Recommended for:**
- Production environments
- Large deployments (>100 gateways)
- High availability requirements

**Configuration:**
```bash
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname
GATEWAY_WORKER_POLL_INTERVAL_SECONDS=5
GATEWAY_WORKER_BATCH_SIZE=10
```

**Deployment:**

=== "Kubernetes"
    ```yaml
    # deployment.yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: mcpgateway
    spec:
      replicas: 3  # Multiple workers
      template:
        spec:
          containers:
          - name: mcpgateway
            env:
            - name: GATEWAY_ASYNC_LIFECYCLE_ENABLED
              value: "true"
    ```

=== "Docker Compose"
    ```yaml
    # docker-compose.yml
    services:
      mcpgateway:
        deploy:
          replicas: 3  # Multiple workers
        environment:
          - GATEWAY_ASYNC_LIFECYCLE_ENABLED=true
    ```

**Benefits:**
- `FOR UPDATE SKIP LOCKED` prevents contention
- Each worker claims up to 10 gateways per cycle
- Horizontal scaling for high throughput

---

## Rollback Procedure

If issues arise, rollback is simple and safe:

### Step 1: Disable Feature Flag

```bash
# Update configuration
GATEWAY_ASYNC_LIFECYCLE_ENABLED=false
```

### Step 2: Restart Application

```bash
# Docker Compose
docker-compose restart mcpgateway

# Kubernetes
kubectl rollout restart deployment/mcpgateway

# Systemd
sudo systemctl restart mcpgateway
```

### Step 3: Verify Synchronous Behavior

Test that operations return synchronously:

```bash
# Create gateway (should return 201, not 202)
curl -X POST "$BASE_URL/admin/gateways" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "sync-test-gateway",
    "url": "http://localhost:9000",
    "transport": "sse"
  }' -i | grep "HTTP"
```

**Expected:** `HTTP/1.1 201 Created` (not 202 Accepted)

### Step 4: Handle Pending Gateways

Pending gateways will remain in pending state after rollback. Options:

**Option A: Manual cleanup (recommended)**
```bash
# List pending gateways
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways?status=pending" | jq

# Delete each pending gateway
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/{name}"
```

**Option B: Database migration rollback**
```bash
# Rollback migration (drops async columns)
cd mcpgateway && alembic downgrade -1
```

**Note:** Migration rollback preserves core gateway records but loses async metadata (`status_message`, `registration_attempts`, `next_retry_at`, `last_error`).

---

## Troubleshooting

### Worker Not Starting

**Symptom:** No "Gateway worker started" log message

**Causes:**
- Feature flag not enabled
- Database connection failure
- Configuration error

**Resolution:**
```bash
# Check feature flag
echo $GATEWAY_ASYNC_LIFECYCLE_ENABLED

# Check database connection
psql $DATABASE_URL -c "SELECT 1"

# Check logs for errors
docker-compose logs mcpgateway | grep -i error
```

### Gateways Stuck in Pending

**Symptom:** Gateways remain in `pending` status for >5 minutes

**Causes:**
- Worker not running
- MCP server unreachable
- Network connectivity issues

**Resolution:**
```bash
# Check worker logs
docker-compose logs mcpgateway | grep -i worker

# Check gateway status
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/{name}" | jq '.status_message, .registration_attempts'

# Cancel stuck gateway
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/{name}"
```

### High Error Rate

**Symptom:** `gateway_registration_errors_total` metric increasing

**Causes:**
- MCP server configuration errors
- Authentication failures
- Network timeouts

**Resolution:**
```bash
# Check worker logs for error details
docker-compose logs mcpgateway | grep "registration failed"

# Review gateway configuration
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/{name}" | jq

# Test MCP server directly
curl -v http://mcp-server:9000/sse
```

---

## Best Practices

### For Production Deployments

1. **Use PostgreSQL** - Required for multiple workers and `FOR UPDATE SKIP LOCKED`
2. **Enable monitoring** - Set up Prometheus metrics and alerts
3. **Scale workers** - Deploy 2-5 workers for high availability
4. **Set appropriate timeouts** - Configure MCP operation timeouts
5. **Monitor pending duration** - Alert on gateways stuck >5 minutes

### For Development Environments

1. **SQLite is acceptable** - Single worker sufficient for dev/test
2. **Lower poll interval** - Use 2-3 seconds for faster feedback
3. **Enable verbose logging** - Set `LOG_LEVEL=DEBUG` for troubleshooting
4. **Test rollback** - Practice disabling feature flag

### For API Clients

1. **Handle both 200 and 202** - Support forward compatibility
2. **Poll with backoff** - Respect `Retry-After` header
3. **Monitor status_message** - Display progress to users
4. **Implement timeouts** - Don't poll indefinitely
5. **Use DELETE to cancel** - Stop unwanted pending operations

---

## Related Documentation

- [API Reference](../manage/gateway-lifecycle-async.md) - Complete API documentation
- [Troubleshooting Guide](../development/gateway-troubleshooting.md) - Common failure modes and debugging
- [RBAC Configuration](../manage/rbac.md) - Permission model and token scoping
- [Observability](../manage/observability.md) - Metrics and tracing configuration