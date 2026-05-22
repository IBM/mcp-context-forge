# Async Gateway Lifecycle

**Issue:** [#4565](https://github.com/IBM/mcp-context-forge/issues/4565)
**Status:** Implemented
**Version:** 1.0.0

## Overview

Gateway create/update/delete operations return `202 Accepted` immediately and process work in background with exponential backoff retry. This eliminates client timeouts during MCP server initialization and provides visibility into retry progress.

## Design Goals

- **Non-blocking API**: Return 202 immediately, process async
- **Retry resilience**: Exponential backoff for transient failures
- **Idempotent operations**: Gateway name = deduplication key
- **Zero breaking changes**: Existing clients work unchanged
- **Observable**: Metrics, logs, traces for retry progress

## State Machine

```
┌─────────┐
│ pending │──────────────────┐
└────┬────┘                  │
     │                       │
     │ (retry success)       │ (DELETE request)
     │                       │
     ▼                       ▼
┌────────┐            ┌──────────┐
│ active │            │ deleting │
└────────┘            └─────┬────┘
                            │
                            │ (cleanup complete)
                            ▼
                       (removed)
```

### Status Values

| Status | Description |
|--------|-------------|
| `pending` | MCP initialization in progress, retrying with backoff |
| `active` | Gateway operational, tools/resources available |
| `deleting` | Deletion in progress, stops retry loop |

## Exponential Backoff Schedule

Worker retries failed initialization with exponential backoff (2^attempt seconds, max 300s):

| Attempt | Delay | Cumulative Time |
|---------|-------|-----------------|
| 1 | 2s | 2s |
| 2 | 4s | 6s |
| 3 | 8s | 14s |
| 4 | 16s | 30s |
| 5 | 32s | 62s |
| 6 | 64s | 126s |
| 7 | 128s | 254s |
| 8+ | 300s | capped at 5min |

## API Contract

### POST /admin/gateways - Create Gateway

**Request:**
```http
POST /admin/gateways
Content-Type: application/json
Authorization: Bearer <token>

{
  "name": "my-gateway",
  "url": "http://localhost:9000/mcp",
  "transport": "STREAMABLEHTTP"
}
```

**Response (202 Accepted):**
```json
{
  "id": "abc123",
  "name": "my-gateway",
  "url": "http://localhost:9000/mcp",
  "status": "pending",
  "status_message": null,
  "registration_attempts": 0,
  "next_retry_at": null,
  "last_error": null,
  "created_at": "2026-05-07T19:00:00Z"
}
```

### GET /admin/gateways/{name} - Poll Status

**Request:**
```http
GET /admin/gateways/my-gateway
Authorization: Bearer <token>
```

**Response (pending):**
```json
{
  "id": "abc123",
  "name": "my-gateway",
  "status": "pending",
  "registration_attempts": 3,
  "next_retry_at": "2026-05-07T19:00:14Z",
  "last_error": "Connection refused",
  "status_message": "Initialization failed: Connection refused"
}
```

**Response (active):**
```json
{
  "id": "abc123",
  "name": "my-gateway",
  "status": "active",
  "registration_attempts": 4,
  "next_retry_at": null,
  "last_error": null,
  "status_message": "Gateway successfully initialized",
  "capabilities": {...}
}
```

### PUT /admin/gateways/{name} - Update Gateway

**Behavior:** Sets `status=pending`, resets retry counter, triggers re-initialization.

**Response:** 202 Accepted with pending status.

### DELETE /admin/gateways/{name} - Delete Gateway

**Behavior:** Sets `status=deleting`, stops retry loop, triggers cleanup.

**Response:** 202 Accepted.

```json
{
  "message": "deletion accepted"
}
```

## Idempotency

Gateway name is the deduplication key. Retry with same name returns existing gateway:

```bash
# First request
POST /admin/gateways {"name": "test", "url": "..."}
→ 202 {"id": "abc123", "status": "pending"}

# Retry with same name
POST /admin/gateways {"name": "test", "url": "..."}
→ 202 {"id": "abc123", "status": "pending"}  # Same gateway

# After activation
POST /admin/gateways {"name": "test", "url": "..."}
→ 409 {"error": "gateway exists"}  # Conflict
```

## Background Worker

### Worker Loop

```python
async def run_forever(self):
    while self._running:
        await self.process_pending_gateways()
        await asyncio.sleep(5)  # Poll every 5s
```

### Retry Logic

```python
async def retry_gateway_init(self, gateway: DbGateway, db: Session):
    # Check if deleted during retry
    if gateway.status == "deleting":
        await self.cleanup_gateway(gateway, db)
        return

    try:
        # Attempt MCP initialization
        capabilities = await initialize_mcp_server(gateway.url)

        # Success: update to active
        gateway.status = "active"
        gateway.capabilities = capabilities
        gateway.registration_attempts += 1
        gateway.next_retry_at = None
        gateway.last_error = None
        db.commit()

    except Exception as e:
        # Failure: increment attempts, calculate backoff
        gateway.registration_attempts += 1
        backoff_seconds = min(2 ** gateway.registration_attempts, 300)
        gateway.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)
        gateway.last_error = str(e)
        db.commit()
```

### Graceful Shutdown

Worker stops accepting new work and completes current retry cycle:

```python
@app.on_event("shutdown")
async def stop_gateway_worker():
    worker.stop()
    await worker.wait_for_completion(timeout=30)
```

## Observability

### Prometheus Metrics

```python
# Gateway count by status
gateway_status_total{status="pending|active|deleted"}

# Registration attempts by outcome
gateway_registration_attempts_total{gateway_name="...", outcome="success|failure"}

# Time spent in pending state
gateway_pending_duration_seconds{gateway_name="..."}

# Current backoff delay
gateway_retry_backoff_seconds{gateway_name="..."}

# Registration failures by error type
gateway_registration_errors_total{error_type="ConnectionError|TimeoutError|..."}
```

### Structured Logs

**Success:**
```json
{
  "event": "gateway_registration_success",
  "gateway_name": "my-gateway",
  "gateway_id": "abc123",
  "gateway_url": "http://localhost:9000/mcp",
  "attempts": 4,
  "pending_duration_seconds": 30.5,
  "status": "active"
}
```

**Failure:**
```json
{
  "event": "gateway_registration_failure",
  "gateway_name": "my-gateway",
  "gateway_id": "abc123",
  "gateway_url": "http://localhost:9000/mcp",
  "attempt": 3,
  "backoff_seconds": 8,
  "next_retry_at": "2026-05-07T19:00:14Z",
  "error": "Connection refused",
  "error_type": "ConnectionError",
  "status": "pending"
}
```

### OpenTelemetry Traces

**Span: `gateway.registration_retry`**

Attributes:
- `gateway.name` - Gateway name
- `gateway.id` - Gateway ID
- `gateway.attempt` - Current attempt number
- `gateway.url` - MCP server URL
- `gateway.status` - Result status (active/pending)
- `gateway.backoff_seconds` - Backoff delay on failure
- `gateway.next_retry_at` - Next retry timestamp
- `gateway.registration_attempts` - Total attempts on success

**Span: `gateway.cleanup`**

Attributes:
- `gateway.name` - Gateway name
- `gateway.id` - Gateway ID
- `gateway.status` - "deleting"
- `gateway.deleted` - true on success

## Client Usage

### Polling Pattern

```bash
# Create gateway
RESPONSE=$(curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-gateway", "url": "http://localhost:9000/mcp"}' \
  $BASE_URL/admin/gateways)

GATEWAY_NAME=$(echo $RESPONSE | jq -r '.name')

# Poll until active (max 60s)
for i in {1..60}; do
  STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" \
    $BASE_URL/admin/gateways/$GATEWAY_NAME | jq -r '.status')

  if [ "$STATUS" = "active" ]; then
    echo "Gateway active!"
    break
  fi

  echo "Status: $STATUS (attempt $i/60)"
  sleep 1
done
```

### Monitoring Retry Progress

```bash
# Get retry metadata
curl -s -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/admin/gateways/my-gateway | jq '{
    status: .status,
    attempts: .registration_attempts,
    next_retry: .next_retry_at,
    last_error: .last_error
  }'
```

Output:
```json
{
  "status": "pending",
  "attempts": 3,
  "next_retry": "2026-05-07T19:00:14Z",
  "last_error": "Connection refused"
}
```

## Database Schema

```sql
-- Gateway table columns
ALTER TABLE gateway ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE gateway ADD COLUMN status_message TEXT;
ALTER TABLE gateway ADD COLUMN registration_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE gateway ADD COLUMN next_retry_at TIMESTAMP;
ALTER TABLE gateway ADD COLUMN last_error TEXT;

-- Index for worker queries
CREATE INDEX ix_gateway_status_next_retry ON gateway(status, next_retry_at);
```

## Error Handling

### Transient Failures

Worker retries automatically with exponential backoff:
- Network errors (connection refused, timeout)
- MCP server not ready
- Temporary resource exhaustion

### Permanent Failures

Worker continues retrying until:
- DELETE request (sets `status=deleting`)
- Manual intervention (update gateway URL, disable)
- Operator alert on high retry count

### Client Errors

| Error | Status | Description |
|-------|--------|-------------|
| Gateway exists | 409 | Name conflict with active gateway |
| Invalid URL | 422 | Malformed gateway URL |
| Unauthorized | 401 | Missing/invalid auth token |

## Rollback Plan

If issues arise:

1. **Disable feature flag** (future): `GATEWAY_ASYNC_LIFECYCLE_ENABLED=false`
2. **Existing pending gateways**: Continue retrying (no data loss)
3. **New requests**: Use sync behavior (block until init complete)
4. **No schema rollback needed**: New columns nullable, backward compatible

## Performance Characteristics

- **API latency**: <100ms (immediate 202 response)
- **Worker poll interval**: 5s
- **Max retry delay**: 300s (5min)
- **Database load**: Minimal (indexed queries, 5s poll)
- **Concurrent gateways**: No limit (worker processes all pending)

## Security Considerations

- **Authorization**: All endpoints require JWT auth
- **RBAC**: Gateway operations require `gateways.create/update/delete` permissions
- **Audit trail**: All state changes logged with user context
- **Secrets**: Auth credentials encrypted at rest

## Related Documentation

- [Gateway Management API](../manage/api-usage.md#gateway-management)
- [Observability](observability-otel.md)
- [Multi-tenancy](multitenancy.md)
- [RBAC](../manage/rbac.md)

## References

- Issue: [#4565](https://github.com/IBM/mcp-context-forge/issues/4565)
- Implementation: `mcpgateway/services/gateway_worker.py`
- Migration: `mcpgateway/alembic/versions/47609bcf093a_add_gateway_async_status.py`
