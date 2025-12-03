# Session Pooling Deployment Guide

This guide covers deploying and configuring session pooling in production environments.

## Prerequisites

- MCP Gateway version >= 1.5.0
- Database with Alembic migrations applied
- Redis (optional, for distributed pooling)
- Monitoring infrastructure (Prometheus/Grafana recommended)

## Deployment Checklist

- [ ] Database migrations applied
- [ ] Environment variables configured
- [ ] Pool sizing calculated
- [ ] Monitoring configured
- [ ] Health checks enabled
- [ ] Backup strategy defined
- [ ] Rollback plan prepared

## Database Migration

### Apply Migrations

Run Alembic migrations to add pooling tables:

```bash
# Navigate to gateway directory
cd /path/to/mcp-gateway

# Apply all pending migrations
alembic upgrade head
```

### Verify Migrations

Check that pooling tables exist:

```sql
-- Check session_pools table
SELECT * FROM session_pools LIMIT 1;

-- Check pool_strategy_metrics table
SELECT * FROM pool_strategy_metrics LIMIT 1;

-- Verify servers table has pooling columns
DESCRIBE servers;
```

### Migration Files

The following migrations are applied:

1. **`k5e6f7g8h9i0_add_session_pooling_to_servers.py`**
   - Adds pool configuration columns to servers table
   - Default: pooling disabled

2. **`l6f7g8h9i0j1_create_session_pools_table.py`**
   - Creates session_pools table
   - Stores pool state and configuration

3. **`m7g8h9i0j1k2_add_pooling_to_mcp_sessions.py`**
   - Adds pool_id, reuse_count, last_health_check to mcp_sessions
   - Links sessions to pools

4. **`n8h9i0j1k2l3_create_pool_strategy_metrics_table.py`**
   - Creates pool_strategy_metrics table
   - Stores performance metrics

## Configuration

### Environment Variables

Add to `.env` file:

```bash
# Pool Configuration
POOL_ENABLED=true
POOL_DEFAULT_STRATEGY=round_robin
POOL_DEFAULT_MIN_SIZE=2
POOL_DEFAULT_MAX_SIZE=10
POOL_DEFAULT_TIMEOUT=30
POOL_DEFAULT_RECYCLE_SECONDS=3600
POOL_DEFAULT_PRE_PING=true

# Pool Manager
POOL_MANAGER_CLEANUP_INTERVAL=300
POOL_MANAGER_HEALTH_CHECK_INTERVAL=60
POOL_MANAGER_METRICS_RETENTION_DAYS=7

# Redis (optional, for distributed pooling)
REDIS_ENABLED=false
REDIS_URL=redis://localhost:6379/0
REDIS_POOL_PREFIX=mcpgateway:pool:
```

### Configuration File

Alternative: Use `config.yaml`:

```yaml
pooling:
  enabled: true
  defaults:
    strategy: round_robin
    min_size: 2
    max_size: 10
    timeout: 30
    recycle_seconds: 3600
    pre_ping: true
  
  manager:
    cleanup_interval: 300
    health_check_interval: 60
    metrics_retention_days: 7
  
  redis:
    enabled: false
    url: redis://localhost:6379/0
    prefix: "mcpgateway:pool:"
```

### Per-Server Configuration

Configure pooling per server via API or database:

```bash
# Enable pooling for a server
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "pool_enabled": true,
    "pool_strategy": "least_connections",
    "pool_min_size": 3,
    "pool_max_size": 15,
    "pool_timeout": 45,
    "pool_recycle_seconds": 7200,
    "pool_pre_ping": true
  }' \
  https://gateway.example.com/api/servers/server-1
```

Or directly in database:

```sql
UPDATE servers
SET pool_enabled = true,
    pool_strategy = 'least_connections',
    pool_min_size = 3,
    pool_max_size = 15,
    pool_timeout = 45,
    pool_recycle_seconds = 7200,
    pool_pre_ping = true
WHERE id = 'server-1';
```

## Pool Sizing

### Calculation Formula

```
min_size = ceil(avg_concurrent_requests * 0.5)
max_size = ceil(peak_concurrent_requests * 1.2)
```

### Example Calculations

**Low Traffic Server** (10 avg, 25 peak requests):
```
min_size = ceil(10 * 0.5) = 5
max_size = ceil(25 * 1.2) = 30
```

**Medium Traffic Server** (50 avg, 150 peak requests):
```
min_size = ceil(50 * 0.5) = 25
max_size = ceil(150 * 1.2) = 180
```

**High Traffic Server** (200 avg, 500 peak requests):
```
min_size = ceil(200 * 0.5) = 100
max_size = ceil(500 * 1.2) = 600
```

### Resource Considerations

**Memory per Session**: ~1-2 MB
**CPU per Pool**: <1% overhead

**Example**: 10 servers with max_size=50 each:
```
Memory: 10 * 50 * 2MB = 1GB
CPU: 10 * 1% = 10% overhead
```

## Deployment Strategies

### Blue-Green Deployment

1. **Deploy to Green Environment**:
   ```bash
   # Deploy new version with pooling
   kubectl apply -f deployment-green.yaml
   
   # Wait for pods to be ready
   kubectl wait --for=condition=ready pod -l app=mcpgateway-green
   ```

2. **Enable Pooling Gradually**:
   ```bash
   # Enable for 10% of servers
   ./scripts/enable-pooling.sh --percentage 10
   
   # Monitor metrics for 1 hour
   # If stable, increase to 50%
   ./scripts/enable-pooling.sh --percentage 50
   
   # Monitor, then enable for all
   ./scripts/enable-pooling.sh --percentage 100
   ```

3. **Switch Traffic**:
   ```bash
   # Update service to point to green
   kubectl patch service mcpgateway -p '{"spec":{"selector":{"version":"green"}}}'
   ```

### Canary Deployment

1. **Deploy Canary**:
   ```yaml
   # canary-deployment.yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: mcpgateway-canary
   spec:
     replicas: 1
     template:
       metadata:
         labels:
           app: mcpgateway
           version: canary
   ```

2. **Route 5% Traffic to Canary**:
   ```yaml
   # istio-virtual-service.yaml
   apiVersion: networking.istio.io/v1beta1
   kind: VirtualService
   metadata:
     name: mcpgateway
   spec:
     http:
     - match:
       - headers:
           x-canary:
             exact: "true"
       route:
       - destination:
           host: mcpgateway-canary
     - route:
       - destination:
           host: mcpgateway-stable
         weight: 95
       - destination:
           host: mcpgateway-canary
         weight: 5
   ```

3. **Monitor and Increase**:
   ```bash
   # Gradually increase canary traffic
   kubectl patch virtualservice mcpgateway --type merge -p '
   {
     "spec": {
       "http": [{
         "route": [
           {"destination": {"host": "mcpgateway-stable"}, "weight": 50},
           {"destination": {"host": "mcpgateway-canary"}, "weight": 50}
         ]
       }]
     }
   }'
   ```

### Rolling Update

1. **Update Deployment**:
   ```yaml
   # deployment.yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: mcpgateway
   spec:
     replicas: 10
     strategy:
       type: RollingUpdate
       rollingUpdate:
         maxSurge: 2
         maxUnavailable: 1
   ```

2. **Apply Update**:
   ```bash
   kubectl apply -f deployment.yaml
   
   # Watch rollout
   kubectl rollout status deployment/mcpgateway
   ```

3. **Enable Pooling Post-Deployment**:
   ```bash
   # Enable pooling via API after all pods updated
   for server in $(get-server-ids); do
     enable-pooling $server
   done
   ```

## Monitoring Setup

### Prometheus Metrics

Add to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'mcpgateway-pools'
    static_configs:
      - targets: ['gateway:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Key Metrics to Monitor

```promql
# Pool health
mcpgateway_pool_health_score{server_id="server-1"}

# Session utilization
mcpgateway_pool_sessions_total{server_id="server-1",status="active"} /
mcpgateway_pool_sessions_total{server_id="server-1"}

# Acquisition latency
histogram_quantile(0.95, 
  rate(mcpgateway_pool_wait_time_seconds_bucket[5m])
)

# Timeout rate
rate(mcpgateway_pool_timeouts_total[5m])

# Session reuse rate
rate(mcpgateway_pool_releases_total[5m]) /
rate(mcpgateway_pool_creates_total[5m])
```

### Grafana Dashboard

Import dashboard from `deployment/grafana/pool-dashboard.json`:

```bash
# Import via API
curl -X POST \
  -H "Authorization: Bearer $GRAFANA_TOKEN" \
  -H "Content-Type: application/json" \
  -d @deployment/grafana/pool-dashboard.json \
  https://grafana.example.com/api/dashboards/db
```

### Alerting Rules

Add to `prometheus-alerts.yml`:

```yaml
groups:
  - name: pool_alerts
    interval: 30s
    rules:
      - alert: PoolHealthDegraded
        expr: mcpgateway_pool_health_score < 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Pool {{ $labels.server_id }} health degraded"
          description: "Health score: {{ $value }}"
      
      - alert: PoolHighTimeouts
        expr: rate(mcpgateway_pool_timeouts_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High timeout rate for {{ $labels.server_id }}"
      
      - alert: PoolExhausted
        expr: |
          mcpgateway_pool_sessions_total{status="active"} /
          mcpgateway_pool_sessions_total >= 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Pool {{ $labels.server_id }} near capacity"
```

## Health Checks

### Kubernetes Liveness Probe

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

### Kubernetes Readiness Probe

```yaml
readinessProbe:
  httpGet:
    path: /api/servers/pools/health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  successThreshold: 1
  failureThreshold: 3
```

### Custom Health Check Script

```bash
#!/bin/bash
# check-pool-health.sh

GATEWAY_URL="http://localhost:8000"
TOKEN="your-token"

# Get global pool health
HEALTH=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$GATEWAY_URL/api/servers/pools/health")

# Check overall health status
STATUS=$(echo $HEALTH | jq -r '.overall_health')

if [ "$STATUS" != "healthy" ]; then
  echo "CRITICAL: Pool health is $STATUS"
  exit 2
fi

# Check for degraded pools
DEGRADED=$(echo $HEALTH | jq -r '.degraded_pools')

if [ "$DEGRADED" -gt 0 ]; then
  echo "WARNING: $DEGRADED pools degraded"
  exit 1
fi

echo "OK: All pools healthy"
exit 0
```

## Backup and Recovery

### Database Backup

```bash
# Backup pool configuration
pg_dump -h localhost -U postgres -d mcpgateway \
  -t session_pools \
  -t pool_strategy_metrics \
  > pool-backup-$(date +%Y%m%d).sql

# Backup with compression
pg_dump -h localhost -U postgres -d mcpgateway \
  -t session_pools \
  -t pool_strategy_metrics \
  | gzip > pool-backup-$(date +%Y%m%d).sql.gz
```

### Configuration Backup

```bash
# Export pool configurations via API
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/pools \
  > pool-configs-$(date +%Y%m%d).json
```

### Recovery Procedure

1. **Restore Database**:
   ```bash
   # Restore from backup
   psql -h localhost -U postgres -d mcpgateway \
     < pool-backup-20240115.sql
   ```

2. **Restart Gateway**:
   ```bash
   # Kubernetes
   kubectl rollout restart deployment/mcpgateway
   
   # Docker
   docker-compose restart mcpgateway
   
   # Systemd
   systemctl restart mcpgateway
   ```

3. **Verify Pools**:
   ```bash
   # Check pool status
   curl -H "Authorization: Bearer $TOKEN" \
     https://gateway.example.com/api/servers/pools/health
   ```

## Rollback Plan

### Disable Pooling

```bash
# Disable pooling for all servers
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pool_enabled": false}' \
  https://gateway.example.com/api/servers/bulk-update

# Or via database
UPDATE servers SET pool_enabled = false;
```

### Rollback Deployment

```bash
# Kubernetes
kubectl rollout undo deployment/mcpgateway

# Docker Compose
docker-compose down
docker-compose -f docker-compose.old.yml up -d
```

### Rollback Database

```bash
# Downgrade migrations
alembic downgrade -1  # One step back
alembic downgrade k5e6f7g8h9i0  # To specific version
```

## Performance Tuning

### Connection Pool Tuning

```bash
# For high-throughput servers
export POOL_DEFAULT_MIN_SIZE=10
export POOL_DEFAULT_MAX_SIZE=100
export POOL_DEFAULT_TIMEOUT=60

# For low-latency servers
export POOL_DEFAULT_MIN_SIZE=5
export POOL_DEFAULT_MAX_SIZE=20
export POOL_DEFAULT_TIMEOUT=10
```

### Database Connection Pool

```bash
# Increase database pool size
export DB_POOL_SIZE=50
export DB_MAX_OVERFLOW=100
export DB_POOL_TIMEOUT=30
```

### Redis Configuration

```bash
# For distributed pooling
export REDIS_POOL_SIZE=20
export REDIS_POOL_TIMEOUT=5
export REDIS_SOCKET_KEEPALIVE=true
```

## Security Considerations

### TLS Configuration

```bash
# Enable TLS for pool connections
export POOL_TLS_ENABLED=true
export POOL_TLS_CERT_PATH=/etc/certs/pool.crt
export POOL_TLS_KEY_PATH=/etc/certs/pool.key
export POOL_TLS_CA_PATH=/etc/certs/ca.crt
```

### Authentication

```bash
# Require authentication for pool management
export POOL_ADMIN_AUTH_REQUIRED=true
export POOL_ADMIN_ROLES=admin,operator
```

### Audit Logging

```bash
# Enable audit logging for pool operations
export POOL_AUDIT_ENABLED=true
export POOL_AUDIT_LOG_PATH=/var/log/mcpgateway/pool-audit.log
```

## Troubleshooting

### Common Issues

**Issue**: Pools not initializing
```bash
# Check logs
kubectl logs -f deployment/mcpgateway | grep -i pool

# Check database connectivity
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT 1"

# Verify migrations
alembic current
```

**Issue**: High timeout rate
```bash
# Increase pool size
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"max_size": 20}' \
  https://gateway.example.com/api/servers/server-1/pool/config

# Check server health
curl https://gateway.example.com/api/servers/server-1/health
```

**Issue**: Memory exhaustion
```bash
# Reduce pool sizes
export POOL_DEFAULT_MAX_SIZE=10

# Enable session recycling
export POOL_DEFAULT_RECYCLE_SECONDS=1800

# Restart gateway
kubectl rollout restart deployment/mcpgateway
```

## Related Documentation

- [User Guide](../using/session-pooling.md)
- [Architecture](../architecture/session-pooling.md)
- [API Reference](../using/api/pool-management.md)
- [Operations Guide](../operations/pool-operations.md)

## Support

For deployment assistance:
- GitHub Issues: https://github.com/your-org/mcp-gateway/issues
- Slack: #mcp-gateway-support
- Email: support@mcp-gateway.example.com