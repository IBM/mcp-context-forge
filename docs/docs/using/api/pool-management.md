# Pool Management API Reference

This document provides detailed API reference for session pooling endpoints in MCP Gateway.

## Base URL

All endpoints are relative to the gateway base URL:

```
https://your-gateway.example.com
```

## Authentication

All pool management endpoints require authentication via Bearer token:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-gateway.example.com/api/servers/server-1/pool/stats
```

## Core Pool Management

### Get Pool Configuration

Retrieve the current pool configuration for a server.

**Endpoint**: `GET /api/servers/{server_id}/pool/config`

**Parameters**:
- `server_id` (path, required): Server identifier

**Response**: `200 OK`

```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "strategy": "round_robin",
  "min_size": 2,
  "max_size": 10,
  "timeout": 30,
  "recycle_seconds": 3600,
  "pre_ping": true,
  "status": "active",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Error Responses**:
- `404 Not Found`: Server or pool not found
- `401 Unauthorized`: Invalid or missing authentication

**Example**:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/server-1/pool/config
```

---

### Update Pool Configuration

Update pool configuration for a server.

**Endpoint**: `PUT /api/servers/{server_id}/pool/config`

**Parameters**:
- `server_id` (path, required): Server identifier

**Request Body**:

```json
{
  "strategy": "least_connections",
  "min_size": 3,
  "max_size": 15,
  "timeout": 45,
  "recycle_seconds": 7200,
  "pre_ping": true
}
```

**Field Descriptions**:
- `strategy`: Pooling strategy (see [Strategies](#pooling-strategies))
- `min_size`: Minimum pool size (1-100)
- `max_size`: Maximum pool size (min_size to 1000)
- `timeout`: Acquisition timeout in seconds (1-300)
- `recycle_seconds`: Session recycling interval (60-86400)
- `pre_ping`: Enable health checks before reuse

**Response**: `200 OK`

```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "strategy": "least_connections",
  "min_size": 3,
  "max_size": 15,
  "timeout": 45,
  "recycle_seconds": 7200,
  "pre_ping": true,
  "status": "active",
  "updated_at": "2024-01-15T11:00:00Z"
}
```

**Error Responses**:
- `400 Bad Request`: Invalid configuration values
- `404 Not Found`: Server not found
- `422 Unprocessable Entity`: Validation error

**Example**:

```bash
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"strategy":"least_connections","min_size":3,"max_size":15}' \
  https://gateway.example.com/api/servers/server-1/pool/config
```

---

### Get Pool Statistics

Retrieve current pool statistics and metrics.

**Endpoint**: `GET /api/servers/{server_id}/pool/stats`

**Parameters**:
- `server_id` (path, required): Server identifier

**Response**: `200 OK`

```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "status": "active",
  "total_sessions": 8,
  "active_sessions": 3,
  "available_sessions": 5,
  "unhealthy_sessions": 0,
  "acquisitions": 1523,
  "releases": 1520,
  "timeouts": 2,
  "creates": 8,
  "destroys": 0,
  "avg_wait_time_ms": 1.2,
  "avg_session_age_seconds": 1847.5,
  "strategy": "round_robin",
  "min_size": 2,
  "max_size": 10,
  "timestamp": "2024-01-15T12:00:00Z"
}
```

**Field Descriptions**:
- `total_sessions`: Total sessions in pool
- `active_sessions`: Currently in-use sessions
- `available_sessions`: Available for acquisition
- `unhealthy_sessions`: Failed health checks
- `acquisitions`: Total acquisition count
- `releases`: Total release count
- `timeouts`: Acquisition timeout count
- `creates`: New session creation count
- `destroys`: Session destruction count
- `avg_wait_time_ms`: Average acquisition wait time
- `avg_session_age_seconds`: Average session age

**Example**:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/server-1/pool/stats
```

---

### List Pool Sessions

List all sessions in a pool with their status.

**Endpoint**: `GET /api/servers/{server_id}/pool/sessions`

**Parameters**:
- `server_id` (path, required): Server identifier
- `status` (query, optional): Filter by status (active, available, unhealthy)

**Response**: `200 OK`

```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "sessions": [
    {
      "session_id": "sess-001",
      "created_at": "2024-01-15T10:30:00Z",
      "last_used": "2024-01-15T11:45:00Z",
      "reuse_count": 47,
      "is_healthy": true,
      "in_use": true,
      "age_seconds": 4500,
      "idle_seconds": 900
    },
    {
      "session_id": "sess-002",
      "created_at": "2024-01-15T10:30:00Z",
      "last_used": "2024-01-15T11:50:00Z",
      "reuse_count": 52,
      "is_healthy": true,
      "in_use": false,
      "age_seconds": 4500,
      "idle_seconds": 600
    }
  ],
  "total": 2
}
```

**Example**:

```bash
# List all sessions
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/server-1/pool/sessions

# List only active sessions
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/server-1/pool/sessions?status=active
```

---

### Drain Pool

Gracefully drain a pool, preventing new acquisitions while allowing active sessions to complete.

**Endpoint**: `POST /api/servers/{server_id}/pool/drain`

**Parameters**:
- `server_id` (path, required): Server identifier

**Request Body** (optional):

```json
{
  "timeout": 60
}
```

**Response**: `200 OK`

```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "status": "draining",
  "active_sessions": 3,
  "message": "Pool draining started. 3 active sessions will complete."
}
```

**Error Responses**:
- `404 Not Found`: Pool not found
- `409 Conflict`: Pool already draining

**Example**:

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"timeout":60}' \
  https://gateway.example.com/api/servers/server-1/pool/drain
```

---

### Reset Pool

Reset a pool by draining and reinitializing with current configuration.

**Endpoint**: `POST /api/servers/{server_id}/pool/reset`

**Parameters**:
- `server_id` (path, required): Server identifier

**Response**: `200 OK`

```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "status": "active",
  "total_sessions": 2,
  "message": "Pool reset successfully"
}
```

**Error Responses**:
- `404 Not Found`: Pool not found
- `500 Internal Server Error`: Reset failed

**Example**:

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/server-1/pool/reset
```

---

### Get Strategy Recommendations

Get recommended pooling strategy based on server metrics.

**Endpoint**: `GET /api/servers/{server_id}/pool/optimize`

**Parameters**:
- `server_id` (path, required): Server identifier

**Response**: `200 OK`

```json
{
  "server_id": "server-1",
  "current_strategy": "round_robin",
  "recommended_strategy": "least_connections",
  "reason": "High average response time (1.2s) detected",
  "metrics": {
    "avg_response_time": 1.2,
    "failure_rate": 0.02,
    "has_state": false
  },
  "confidence": "high"
}
```

**Recommendation Logic**:
- `sticky`: Server has stateful operations
- `weighted`: High failure rate (>10%)
- `least_connections`: High latency (>1s)
- `round_robin`: Default for stable servers

**Example**:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/server-1/pool/optimize
```

---

### Update Pool Strategy

Update only the pooling strategy for a server.

**Endpoint**: `PUT /api/servers/{server_id}/pool/strategy`

**Parameters**:
- `server_id` (path, required): Server identifier

**Request Body**:

```json
{
  "strategy": "weighted"
}
```

**Response**: `200 OK`

```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "strategy": "weighted",
  "updated_at": "2024-01-15T12:30:00Z"
}
```

**Example**:

```bash
curl -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"strategy":"weighted"}' \
  https://gateway.example.com/api/servers/server-1/pool/strategy
```

---

## Monitoring Endpoints

### List All Pools

List all active pools across all servers.

**Endpoint**: `GET /api/servers/pools`

**Query Parameters**:
- `status` (optional): Filter by status (active, degraded, inactive, draining)
- `strategy` (optional): Filter by strategy

**Response**: `200 OK`

```json
{
  "pools": [
    {
      "pool_id": "pool-abc123",
      "server_id": "server-1",
      "server_name": "Production API",
      "strategy": "round_robin",
      "status": "active",
      "total_sessions": 8,
      "active_sessions": 3,
      "health_score": 0.95
    },
    {
      "pool_id": "pool-def456",
      "server_id": "server-2",
      "server_name": "Analytics Service",
      "strategy": "least_connections",
      "status": "active",
      "total_sessions": 5,
      "active_sessions": 2,
      "health_score": 1.0
    }
  ],
  "total": 2
}
```

**Example**:

```bash
# List all pools
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/pools

# List only active pools
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/pools?status=active
```

---

### Get Global Pool Health

Get aggregated health metrics across all pools.

**Endpoint**: `GET /api/servers/pools/health`

**Response**: `200 OK`

```json
{
  "overall_health": "healthy",
  "total_pools": 5,
  "healthy_pools": 4,
  "degraded_pools": 1,
  "unhealthy_pools": 0,
  "total_sessions": 42,
  "active_sessions": 18,
  "unhealthy_sessions": 2,
  "avg_health_score": 0.92,
  "timestamp": "2024-01-15T12:00:00Z"
}
```

**Health Status**:
- `healthy`: All pools operational (health_score >= 0.9)
- `degraded`: Some pools experiencing issues (0.7 <= health_score < 0.9)
- `unhealthy`: Critical issues detected (health_score < 0.7)

**Example**:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/pools/health
```

---

### Get Pool Performance Metrics

Get detailed performance metrics for pools.

**Endpoint**: `GET /api/servers/pools/metrics`

**Query Parameters**:
- `server_id` (optional): Filter by server
- `strategy` (optional): Filter by strategy
- `start_time` (optional): Start of time range (ISO 8601)
- `end_time` (optional): End of time range (ISO 8601)
- `limit` (optional): Maximum results (default: 100)

**Response**: `200 OK`

```json
{
  "metrics": [
    {
      "pool_id": "pool-abc123",
      "server_id": "server-1",
      "strategy": "round_robin",
      "timestamp": "2024-01-15T12:00:00Z",
      "response_time": 0.85,
      "success": true,
      "session_reused": true,
      "wait_time": 0.002
    },
    {
      "pool_id": "pool-abc123",
      "server_id": "server-1",
      "strategy": "round_robin",
      "timestamp": "2024-01-15T12:00:05Z",
      "response_time": 0.92,
      "success": true,
      "session_reused": true,
      "wait_time": 0.001
    }
  ],
  "total": 2,
  "aggregates": {
    "avg_response_time": 0.885,
    "success_rate": 1.0,
    "reuse_rate": 1.0,
    "avg_wait_time": 0.0015
  }
}
```

**Example**:

```bash
# Get metrics for last hour
curl -H "Authorization: Bearer $TOKEN" \
  "https://gateway.example.com/api/servers/pools/metrics?start_time=2024-01-15T11:00:00Z&end_time=2024-01-15T12:00:00Z"

# Get metrics for specific server
curl -H "Authorization: Bearer $TOKEN" \
  "https://gateway.example.com/api/servers/pools/metrics?server_id=server-1"
```

---

### Get Server Pool Health

Get health status for a specific server's pool.

**Endpoint**: `GET /api/servers/{server_id}/pool/health`

**Parameters**:
- `server_id` (path, required): Server identifier

**Response**: `200 OK`

```json
{
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "status": "active",
  "health_score": 0.95,
  "health_status": "healthy",
  "total_sessions": 8,
  "healthy_sessions": 8,
  "unhealthy_sessions": 0,
  "recent_errors": 0,
  "uptime_seconds": 7200,
  "last_health_check": "2024-01-15T12:00:00Z",
  "issues": []
}
```

**Health Score Calculation**:
```
health_score = (healthy_sessions / total_sessions) * 
               (1 - min(recent_errors / 100, 0.5))
```

**Example**:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://gateway.example.com/api/servers/server-1/pool/health
```

---

## Pooling Strategies

### Available Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `round_robin` | Circular distribution | Balanced load, stateless |
| `least_connections` | Minimum active connections | High latency servers |
| `sticky` | User/session affinity | Stateful operations |
| `weighted` | Performance-based routing | Mixed server performance |
| `none` | No pooling | Testing, debugging |

### Strategy Selection Guide

```python
# Pseudo-code for strategy selection
if server.has_state:
    strategy = "sticky"
elif server.failure_rate > 0.1:
    strategy = "weighted"
elif server.avg_response_time > 1.0:
    strategy = "least_connections"
else:
    strategy = "round_robin"
```

---

## Error Codes

| Code | Description | Resolution |
|------|-------------|------------|
| 400 | Bad Request | Check request parameters |
| 401 | Unauthorized | Verify authentication token |
| 404 | Not Found | Verify server/pool exists |
| 409 | Conflict | Pool in incompatible state |
| 422 | Validation Error | Check field constraints |
| 500 | Internal Error | Check server logs |
| 503 | Service Unavailable | Pool temporarily unavailable |

---

## Rate Limiting

Pool management endpoints are rate-limited:

- **Configuration Updates**: 10 requests/minute per server
- **Statistics Queries**: 60 requests/minute per server
- **Monitoring Endpoints**: 120 requests/minute globally

Rate limit headers:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1705320000
```

---

## Webhooks

Configure webhooks for pool events:

**Event Types**:
- `pool.created`: New pool initialized
- `pool.degraded`: Pool health degraded
- `pool.recovered`: Pool health recovered
- `pool.drained`: Pool drained
- `pool.error`: Pool error occurred

**Webhook Payload**:
```json
{
  "event": "pool.degraded",
  "pool_id": "pool-abc123",
  "server_id": "server-1",
  "timestamp": "2024-01-15T12:00:00Z",
  "data": {
    "health_score": 0.75,
    "unhealthy_sessions": 2,
    "reason": "Multiple session failures"
  }
}
```

---

## Related Documentation

- [User Guide](../using/session-pooling.md)
- [Architecture](../architecture/session-pooling.md)
- [Configuration Reference](../operations/configuration.md)

## Support

For issues or questions:
- GitHub Issues: https://github.com/your-org/mcp-gateway/issues
- Documentation: https://docs.mcp-gateway.example.com
- Community: https://community.mcp-gateway.example.com