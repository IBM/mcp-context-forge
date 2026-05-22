# Gateway Lifecycle Operations

## Overview

This guide covers operational procedures for managing gateway lifecycle with async operations (Issue #4565).

## Architecture

Gateway registration follows an async pattern:
- API returns 202 Accepted immediately
- Background worker processes registration with retry logic
- Status transitions: `pending` → `active` or `failed`
- Exponential backoff: 2s, 4s, 8s, 16s, 32s (max 5 attempts)

## Monitoring

### Key Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| `gateway_status_total{status="pending"}` | Pending gateways | > 10 for 5 minutes |
| `gateway_pending_duration` (p95) | Time in pending state | > 60 seconds |
| `gateway_registration_attempts{outcome="failure"}` | Failed attempts rate | > 5% of total |
| `gateway_retry_backoff` | Backoff duration distribution | p99 > 32 seconds |

### Grafana Dashboard

Access the Gateway Lifecycle dashboard:
- **URL**: `http://grafana:3000/d/gateway-lifecycle`
- **Panels**: Status distribution, pending duration, retry patterns, worker health
- **Refresh**: 10 seconds

### Alert Rules

**Pending Duration Alert**
```yaml
- alert: GatewayPendingTooLong
  expr: histogram_quantile(0.95, sum(rate(gateway_pending_duration_bucket[5m])) by (le)) > 60
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Gateway pending duration too high"
    description: "P95 pending duration is {{ $value }}s (threshold: 60s)"
```

**High Failure Rate Alert**
```yaml
- alert: GatewayRegistrationFailureRate
  expr: sum(rate(gateway_registration_attempts{outcome="failure"}[5m])) / sum(rate(gateway_registration_attempts[5m])) > 0.1
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "High gateway registration failure rate"
    description: "Failure rate is {{ $value | humanizePercentage }} (threshold: 10%)"
```

## Troubleshooting

### Stuck Pending Gateways

**Symptoms**: Gateways remain in `pending` status for > 2 minutes

**Diagnosis**:
```bash
# Check pending gateways
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/gateways | jq '.[] | select(.status=="pending")'

# Check worker logs
kubectl logs -l app=mcpgateway --tail=100 | grep "gateway_worker"

# Check metrics
curl http://localhost:4444/metrics | grep gateway_status_total
```

**Common Causes**:
1. **Upstream MCP server unreachable**
   - Verify URL is accessible: `curl -v <gateway_url>`
   - Check network policies/firewall rules
   - Verify DNS resolution

2. **Worker not running**
   - Check worker startup: `kubectl logs -l app=mcpgateway | grep "Gateway worker started"`
   - Verify no crash loops: `kubectl get pods -l app=mcpgateway`

3. **Database connection issues**
   - Check DB connectivity: `kubectl logs -l app=mcpgateway | grep "database"`
   - Verify connection pool not exhausted

**Resolution**:
```bash
# Manual retry (updates gateway to trigger re-processing)
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "<gateway_url>"}' \
  http://localhost:4444/gateways/<gateway_id>

# Force delete if unrecoverable
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/gateways/<gateway_id>
```

### High Failure Rate

**Symptoms**: `gateway_registration_attempts{outcome="failure"}` > 5%

**Diagnosis**:
```bash
# Find failing gateways
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/gateways | \
  jq '.[] | select(.status=="failed") | {id, url, status_message, registration_attempts}'

# Check error patterns in logs
kubectl logs -l app=mcpgateway --tail=500 | grep "gateway_registration_failure"
```

**Common Causes**:
1. **Invalid gateway URLs** - Check URL format and accessibility
2. **Authentication failures** - Verify credentials/tokens
3. **Timeout issues** - Increase `TOOL_TIMEOUT` if needed
4. **Resource limits** - Check if upstream servers are overloaded

**Resolution**:
```bash
# Update gateway with corrected URL/config
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "<corrected_url>"}' \
  http://localhost:4444/gateways/<gateway_id>
```

### Worker Not Processing

**Symptoms**: No status transitions, pending count not decreasing

**Diagnosis**:
```bash
# Check worker is running
kubectl logs -l app=mcpgateway | grep "Gateway worker"

# Check for errors
kubectl logs -l app=mcpgateway --tail=100 | grep -i error

# Verify worker processing rate
curl http://localhost:4444/metrics | grep gateway_registration_attempts
```

**Resolution**:
```bash
# Restart pods to restart worker
kubectl rollout restart deployment/mcpgateway

# Verify worker started
kubectl logs -l app=mcpgateway --tail=20 | grep "Gateway worker started"
```

## Maintenance Procedures

### Manual Cleanup of Failed Gateways

```sql
-- Connect to database
psql $DATABASE_URL

-- List failed gateways older than 24 hours
SELECT id, url, status_message, created_at, registration_attempts
FROM gateways
WHERE status = 'failed' AND created_at < NOW() - INTERVAL '24 hours';

-- Delete old failed gateways (after verification)
DELETE FROM gateways
WHERE status = 'failed' AND created_at < NOW() - INTERVAL '7 days';
```

### Reset Gateway to Pending

```sql
-- Reset a failed gateway to retry
UPDATE gateways
SET status = 'pending',
    status_message = NULL,
    registration_attempts = 0,
    last_attempt_at = NULL
WHERE id = '<gateway_id>';
```

### Bulk Status Check

```bash
# Get status distribution
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/gateways | \
  jq 'group_by(.status) | map({status: .[0].status, count: length})'

# Output:
# [
#   {"status": "active", "count": 45},
#   {"status": "pending", "count": 2},
#   {"status": "failed", "count": 1}
# ]
```

## Feature Flag Management

### Disable Async Lifecycle

To revert to synchronous behavior:

```bash
# Update environment variable
kubectl set env deployment/mcpgateway GATEWAY_ASYNC_LIFECYCLE_ENABLED=false

# Or via ConfigMap
kubectl edit configmap mcpgateway-config
# Set: GATEWAY_ASYNC_LIFECYCLE_ENABLED: "false"

# Restart deployment
kubectl rollout restart deployment/mcpgateway
```

**Impact**:
- New gateway registrations return 200 (synchronous)
- Existing pending gateways remain in DB (worker stops processing)
- No retry logic for new registrations

### Re-enable Async Lifecycle

```bash
# Update environment variable
kubectl set env deployment/mcpgateway GATEWAY_ASYNC_LIFECYCLE_ENABLED=true

# Restart deployment
kubectl rollout restart deployment/mcpgateway

# Verify worker started
kubectl logs -l app=mcpgateway | grep "Gateway worker started"
```

## Performance Tuning

### Worker Interval

Default: 10 seconds. Adjust for higher/lower throughput:

```python
# In mcpgateway/main.py
worker_interval = 5  # Process every 5 seconds (higher throughput)
# or
worker_interval = 30  # Process every 30 seconds (lower load)
```

### Retry Configuration

Modify retry behavior in `mcpgateway/services/gateway_worker.py`:

```python
MAX_ATTEMPTS = 5  # Increase for more retries
BASE_BACKOFF = 2  # Increase for longer backoff
```

### Database Connection Pool

For high-volume deployments:

```bash
# Increase pool size
DB_POOL_SIZE=500
DB_MAX_OVERFLOW=100
```

## API Usage

### Create Gateway (Async)

```bash
curl -X POST http://localhost:4444/gateways \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://mcp-server:8000",
    "name": "My Gateway"
  }'

# Response: 202 Accepted
{
  "id": "gw-123",
  "url": "http://mcp-server:8000",
  "name": "My Gateway",
  "status": "pending",
  "registration_attempts": 0
}
```

### Poll Gateway Status

```bash
# Poll until status is 'active' or 'failed'
while true; do
  STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" \
    http://localhost:4444/gateways/gw-123 | jq -r '.status')
  echo "Status: $STATUS"
  [[ "$STATUS" == "active" ]] && break
  [[ "$STATUS" == "failed" ]] && break
  sleep 2
done
```

### Update Gateway (Triggers Retry)

```bash
curl -X PUT http://localhost:4444/gateways/gw-123 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://mcp-server:8000",
    "name": "Updated Gateway"
  }'

# Response: 202 Accepted
# Gateway resets to 'pending' and retries
```

### Delete Gateway (Stops Retry)

```bash
curl -X DELETE http://localhost:4444/gateways/gw-123 \
  -H "Authorization: Bearer $TOKEN"

# Response: 202 Accepted
# Gateway is deleted, retry loop stops
```

## Migration Notes

### Upgrading from Synchronous to Async

1. **Database Migration**: Run Alembic migration
   ```bash
   cd mcpgateway && alembic upgrade head
   ```

2. **Verify Migration**: Check for new columns
   ```sql
   \d gateways
   -- Should show: status, status_message, registration_attempts, last_attempt_at
   ```

3. **Deploy New Version**: Rolling update
   ```bash
   kubectl set image deployment/mcpgateway mcpgateway=<new-image>
   ```

4. **Verify Worker**: Check logs for worker startup
   ```bash
   kubectl logs -l app=mcpgateway | grep "Gateway worker started"
   ```

### Rollback Procedure

If issues occur after deployment:

1. **Disable Feature Flag** (immediate, < 5 minutes)
   ```bash
   kubectl set env deployment/mcpgateway GATEWAY_ASYNC_LIFECYCLE_ENABLED=false
   ```

2. **Rollback Deployment** (if needed)
   ```bash
   kubectl rollout undo deployment/mcpgateway
   ```

3. **Clean Up Pending Gateways** (optional)
   ```sql
   UPDATE gateways SET status='failed', status_message='Rollback to sync mode'
   WHERE status='pending';
   ```

## Best Practices

1. **Monitor Pending Duration**: Alert if p95 > 60 seconds
2. **Set Failure Rate Alerts**: Alert if failure rate > 5%
3. **Regular Cleanup**: Delete failed gateways older than 7 days
4. **Capacity Planning**: Monitor worker processing rate vs. creation rate
5. **Graceful Degradation**: Use feature flag to disable async if needed

## Related Documentation

- [API Usage Guide](api-usage.md) - API endpoint documentation
- [Architecture: Async Gateway Lifecycle](../architecture/async-gateway-lifecycle.md) - Design details
- [Monitoring Guide](monitoring.md) - General monitoring setup
