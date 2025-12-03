# Session Pooling

Session pooling in MCP Gateway improves performance and reduces connection overhead by reusing sessions across multiple requests. This feature is particularly beneficial for high-traffic deployments and stateful MCP servers.

## Overview

Session pooling maintains a pool of reusable connections to MCP servers, eliminating the overhead of creating and destroying connections for each request. The gateway supports multiple pooling strategies to optimize for different workload patterns.

## Key Benefits

- **Reduced Latency**: Reuse existing connections instead of creating new ones
- **Lower Resource Usage**: Fewer connection handshakes and teardowns
- **Better Scalability**: Handle more concurrent requests with fewer resources
- **State Continuity**: Maintain session state across requests (with sticky strategy)
- **Automatic Health Management**: Unhealthy sessions are automatically removed and replaced

## Pooling Strategies

### Round Robin
Distributes sessions evenly across all pool slots in circular order.

**Best for**: Balanced workloads with similar request durations

**Configuration**:
```json
{
  "pool_enabled": true,
  "pool_strategy": "round_robin",
  "pool_min_size": 2,
  "pool_max_size": 10
}
```

### Least Connections
Routes to the slot with fewest active connections.

**Best for**: Varying request durations where some requests take longer than others

**Configuration**:
```json
{
  "pool_enabled": true,
  "pool_strategy": "least_connections",
  "pool_min_size": 3,
  "pool_max_size": 15
}
```

### Sticky
Maintains user affinity to specific pool slots.

**Best for**: Stateful sessions where maintaining context is important

**Configuration**:
```json
{
  "pool_enabled": true,
  "pool_strategy": "sticky",
  "pool_min_size": 5,
  "pool_max_size": 20
}
```

### Weighted
Routes based on server performance metrics and health.

**Best for**: Heterogeneous servers with varying capabilities

**Configuration**:
```json
{
  "pool_enabled": true,
  "pool_strategy": "weighted",
  "pool_min_size": 3,
  "pool_max_size": 12
}
```

### None
No pooling, creates direct connections.

**Best for**: Low-traffic scenarios or when pooling overhead exceeds benefits

**Configuration**:
```json
{
  "pool_enabled": false
}
```

## Configuration

### Server-Level Configuration

Configure pooling per server via the Admin UI or API:

```bash
curl -X PUT http://localhost:8000/api/servers/{server_id}/pool/config \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "pool_enabled": true,
    "pool_strategy": "least_connections",
    "pool_min_size": 3,
    "pool_max_size": 10,
    "pool_timeout": 30,
    "pool_recycle_seconds": 3600,
    "pool_pre_ping": true
  }'
```

### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pool_enabled` | boolean | `false` | Enable/disable pooling for this server |
| `pool_strategy` | string | `"round_robin"` | Pooling strategy (see above) |
| `pool_min_size` | integer | `1` | Minimum sessions to maintain |
| `pool_max_size` | integer | `10` | Maximum sessions allowed |
| `pool_timeout` | integer | `30` | Timeout in seconds for acquiring a session |
| `pool_recycle_seconds` | integer | `3600` | Recycle sessions older than this (seconds) |
| `pool_pre_ping` | boolean | `true` | Ping sessions before returning them |

### Environment Variables

Global pooling defaults can be set via environment variables:

```bash
# Default pool settings
POOL_MIN_SIZE=2
POOL_MAX_SIZE=10
POOL_TIMEOUT=30
POOL_RECYCLE_SECONDS=3600
POOL_PRE_PING=true
```

## Monitoring

### Pool Statistics

Get real-time pool statistics:

```bash
curl http://localhost:8000/api/servers/{server_id}/pool/stats \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-456",
  "strategy": "least_connections",
  "status": "active",
  "total_sessions": 5,
  "active_sessions": 2,
  "available_sessions": 3,
  "unhealthy_sessions": 0,
  "min_size": 3,
  "max_size": 10,
  "total_acquisitions": 1523,
  "total_releases": 1520,
  "total_timeouts": 0,
  "total_creates": 5,
  "total_destroys": 0
}
```

### Health Dashboard

Access the pool health dashboard in the Admin UI:

1. Navigate to **Admin** → **Pool Health**
2. View global pool status across all servers
3. Monitor active sessions, timeouts, and errors
4. Identify performance bottlenecks

### Metrics

Pool metrics are exposed via Prometheus:

```
# Session pool metrics
mcpgateway_pool_sessions_total{server_id="server-456",status="active"} 5
mcpgateway_pool_acquisitions_total{server_id="server-456"} 1523
mcpgateway_pool_timeouts_total{server_id="server-456"} 0
mcpgateway_pool_session_age_seconds{server_id="server-456",quantile="0.5"} 245
```

## Management Operations

### View Pool Sessions

List all sessions in a pool:

```bash
curl http://localhost:8000/api/servers/{server_id}/pool/sessions \
  -H "Authorization: Bearer $TOKEN"
```

### Drain Pool

Gracefully drain a pool (wait for active sessions to complete):

```bash
curl -X POST http://localhost:8000/api/servers/{server_id}/pool/drain \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timeout": 60}'
```

### Reset Pool

Reset a pool (clear all sessions and recreate):

```bash
curl -X POST http://localhost:8000/api/servers/{server_id}/pool/reset \
  -H "Authorization: Bearer $TOKEN"
```

### Optimize Strategy

Get strategy recommendations based on current metrics:

```bash
curl http://localhost:8000/api/servers/{server_id}/pool/optimize \
  -H "Authorization: Bearer $TOKEN"
```

## Best Practices

### Sizing Guidelines

**Minimum Size**:
- Start with `min_size = 2` for most workloads
- Increase to `min_size = 5` for high-traffic servers
- Set `min_size = 0` for rarely-used servers

**Maximum Size**:
- Set `max_size = 2-3x` your expected concurrent requests
- Monitor `total_timeouts` and increase if > 0
- Consider server resource limits (memory, connections)

### Strategy Selection

1. **Start with Round Robin**: Good default for most workloads
2. **Switch to Least Connections**: If requests have varying durations
3. **Use Sticky**: Only if your MCP server maintains important session state
4. **Try Weighted**: For heterogeneous server deployments

### Session Recycling

- Default `recycle_seconds = 3600` (1 hour) works for most cases
- Reduce to `1800` (30 min) for servers with memory leaks
- Increase to `7200` (2 hours) for stable, long-running servers

### Pre-Ping

- Keep `pre_ping = true` (default) for reliability
- Set `pre_ping = false` only if:
  - Your MCP server has very fast connection times
  - You're optimizing for absolute minimum latency
  - You have other health check mechanisms

## Troubleshooting

### High Timeout Rate

**Symptom**: `total_timeouts` increasing rapidly

**Solutions**:
1. Increase `pool_max_size`
2. Reduce `pool_timeout` to fail faster
3. Check server capacity and response times
4. Consider horizontal scaling

### Sessions Not Being Reused

**Symptom**: `total_creates` ≈ `total_acquisitions`

**Solutions**:
1. Verify `pool_enabled = true`
2. Check `pool_min_size > 0`
3. Review `recycle_seconds` (may be too low)
4. Check for unhealthy sessions being destroyed

### Memory Growth

**Symptom**: Gateway memory usage increasing over time

**Solutions**:
1. Reduce `pool_max_size`
2. Lower `recycle_seconds` to recycle sessions more frequently
3. Enable `pre_ping` to detect and remove unhealthy sessions
4. Monitor `unhealthy_sessions` metric

### Uneven Load Distribution

**Symptom**: Some sessions heavily used, others idle

**Solutions**:
1. Switch from `sticky` to `round_robin` or `least_connections`
2. Verify strategy is correctly configured
3. Check for client-side connection pooling interfering

## API Reference

See the [Pool Management API](../using/api/pool-management.md) documentation for complete API details.

## Architecture

For implementation details, see:
- [Architecture Decision Records](../architecture/adr/)
- [Session Pool Implementation](../architecture/session-pooling.md)

## Migration Guide

### Enabling Pooling on Existing Servers

1. **Test in Development**: Enable pooling on a test server first
2. **Start Small**: Begin with `min_size=1, max_size=5`
3. **Monitor Metrics**: Watch `total_timeouts` and response times
4. **Gradually Increase**: Scale up `max_size` based on load
5. **Optimize Strategy**: Use `/pool/optimize` endpoint for recommendations

### Disabling Pooling

To disable pooling on a server:

```bash
curl -X PUT http://localhost:8000/api/servers/{server_id}/pool/config \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pool_enabled": false}'
```

Existing sessions will be drained gracefully.

## Performance Impact

### Expected Improvements

- **Latency Reduction**: 30-50% for typical workloads
- **Throughput Increase**: 2-3x for connection-heavy operations
- **Resource Savings**: 40-60% reduction in connection overhead

### Overhead

- **Memory**: ~1-2 MB per pooled session
- **CPU**: Minimal (<1% for pool management)
- **Startup Time**: +100-500ms for pool warmup

## Security Considerations

- Sessions are isolated per server
- Authentication is validated on each request
- Unhealthy sessions are automatically removed
- Pool statistics don't expose sensitive data
- Admin operations require `servers.update` permission

## Related Documentation

- [Server Configuration](servers.md)
- [Performance Tuning](../operations/performance.md)
- [Monitoring Guide](../manage/observability/monitoring.md)