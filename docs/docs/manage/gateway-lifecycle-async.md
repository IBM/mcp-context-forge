# Asynchronous Gateway Lifecycle API

This document describes the asynchronous gateway lifecycle API, which provides HTTP 202 Accepted responses for long-running gateway operations (create, update, delete) when the `GATEWAY_ASYNC_LIFECYCLE_ENABLED` feature flag is enabled.

---

## Overview

When asynchronous lifecycle is enabled, gateway operations return immediately with a 202 Accepted response, and a background worker processes the operation asynchronously. This prevents API timeouts for slow MCP server connections and provides better visibility into operation progress.

### Key Features

- **202 Accepted responses** for create, update, and delete operations
- **Status polling** via GET endpoint to track operation progress
- **Idempotent operations** - duplicate requests return existing pending state
- **Exponential backoff retry** - automatic retry with increasing delays
- **Graceful cancellation** - DELETE stops pending operations

### Feature Flag

```bash
# Enable asynchronous lifecycle (default: false)
GATEWAY_ASYNC_LIFECYCLE_ENABLED=true
```

When disabled, all operations behave synchronously (200/201/204 responses).

---

## Gateway Status States

| Status | Description | User-Facing |
|--------|-------------|-------------|
| `pending` | Gateway registration/update in progress | Yes |
| `active` | Gateway operational and serving requests | Yes |
| `deleting` | Gateway deletion in progress | Yes |

### Status Transitions

```
┌─────────┐
│ pending │──────────────────────────────────────┐
└────┬────┘                                      │
     │                                           │
     │ Worker success                            │ DELETE
     ▼                                           │
┌─────────┐                                      │
│ active  │──────────────────────────────────────┤
└────┬────┘                                      │
     │                                           │
     │ PUT/PATCH (async update)                  │
     ▼                                           ▼
┌─────────┐                              ┌──────────┐
│ pending │                              │ deleting │
└─────────┘                              └────┬─────┘
                                              │
                                              │ Worker cleanup
                                              ▼
                                         [deleted]
```

---

## API Endpoints

### Create Gateway (POST /admin/gateways)

Creates a new gateway registration.

#### Synchronous Mode (Flag OFF)

**Request:**
```bash
curl -X POST "$BASE_URL/admin/gateways" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-gateway",
    "url": "http://localhost:9000",
    "transport": "sse"
  }'
```

**Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "url": "http://localhost:9000",
  "transport": "sse",
  "status": "active",
  "created_at": "2026-06-08T14:00:00Z"
}
```

#### Asynchronous Mode (Flag ON)

**Request:** Same as synchronous mode

**Response (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "url": "http://localhost:9000",
  "transport": "sse",
  "status": "pending",
  "status_message": "Gateway registration queued",
  "registration_attempts": 0,
  "next_retry_at": null,
  "created_at": "2026-06-08T14:00:00Z"
}
```

**Response Headers:**
```
HTTP/1.1 202 Accepted
Retry-After: 5
Location: /admin/gateways/my-gateway
```

#### Idempotent Behavior

**Duplicate create (pending gateway exists):**
```bash
# Second POST with same name returns existing pending gateway
curl -X POST "$BASE_URL/admin/gateways" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-gateway", "url": "http://localhost:9000", "transport": "sse"}'
```

**Response (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "status": "pending",
  "status_message": "Gateway registration queued",
  "registration_attempts": 2,
  "next_retry_at": "2026-06-08T14:00:10Z"
}
```

**Duplicate create (active gateway exists):**
```bash
# POST with name of active gateway returns conflict
curl -X POST "$BASE_URL/admin/gateways" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "active-gateway", "url": "http://localhost:9000", "transport": "sse"}'
```

**Response (409 Conflict):**
```json
{
  "detail": "Gateway with name 'active-gateway' already exists"
}
```

---

### Update Gateway (PUT/PATCH /admin/gateways/{name})

Updates an existing gateway configuration.

#### Synchronous Mode (Flag OFF)

**Request:**
```bash
curl -X PUT "$BASE_URL/admin/gateways/my-gateway" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://localhost:9001",
    "transport": "sse"
  }'
```

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "url": "http://localhost:9001",
  "transport": "sse",
  "status": "active",
  "updated_at": "2026-06-08T14:05:00Z"
}
```

#### Asynchronous Mode (Flag ON)

**Request:** Same as synchronous mode

**Response (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "url": "http://localhost:9001",
  "transport": "sse",
  "status": "pending",
  "status_message": "Gateway update queued",
  "registration_attempts": 0,
  "next_retry_at": null,
  "updated_at": "2026-06-08T14:05:00Z"
}
```

**Response Headers:**
```
HTTP/1.1 202 Accepted
Retry-After: 5
```

#### Update Behavior

- **Active gateway**: Transitions to `pending`, worker processes update
- **Already pending**: Returns 202 with existing pending state (idempotent)
- **Gateway stops serving** during update (brief downtime)
- **Configuration applied atomically** when worker completes

---

### Delete Gateway (DELETE /admin/gateways/{name})

Deletes a gateway and performs cleanup.

#### Synchronous Mode (Flag OFF)

**Request:**
```bash
curl -X DELETE "$BASE_URL/admin/gateways/my-gateway" \
  -H "Authorization: Bearer $TOKEN"
```

**Response (204 No Content):**
```
HTTP/1.1 204 No Content
```

#### Asynchronous Mode (Flag ON)

**Request:** Same as synchronous mode

**Response (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "status": "deleting",
  "status_message": "Gateway deletion queued"
}
```

**Response Headers:**
```
HTTP/1.1 202 Accepted
Retry-After: 5
```

#### Idempotent Behavior

**Repeated delete:**
```bash
# Second DELETE returns same 202 response
curl -X DELETE "$BASE_URL/admin/gateways/my-gateway" \
  -H "Authorization: Bearer $TOKEN"
```

**Response (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "status": "deleting",
  "status_message": "Gateway deletion queued"
}
```

**Gateway not found:**
```bash
curl -X DELETE "$BASE_URL/admin/gateways/nonexistent" \
  -H "Authorization: Bearer $TOKEN"
```

**Response (404 Not Found):**
```json
{
  "detail": "Gateway not found"
}
```

#### DELETE on Pending Gateway

When DELETE is called on a pending gateway, the worker stops retry attempts and performs cleanup:

```bash
# DELETE pending gateway
curl -X DELETE "$BASE_URL/admin/gateways/pending-gateway" \
  -H "Authorization: Bearer $TOKEN"
```

**Response (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "pending-gateway",
  "status": "deleting",
  "status_message": "Gateway deletion queued"
}
```

Worker behavior:
1. Detects `status="deleting"` on next retry check
2. Stops retry loop
3. Performs cleanup (closes MCP connection if exists)
4. Deletes gateway record

---

### Get Gateway Status (GET /admin/gateways/{name})

Retrieves gateway details including async operation status.

**Request:**
```bash
curl -X GET "$BASE_URL/admin/gateways/my-gateway" \
  -H "Authorization: Bearer $TOKEN"
```

**Response (200 OK) - Pending:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "url": "http://localhost:9000",
  "transport": "sse",
  "status": "pending",
  "status_message": "Retrying after error (attempt 3)",
  "status_updated_at": "2026-06-08T14:00:15Z",
  "registration_attempts": 3,
  "next_retry_at": "2026-06-08T14:00:23Z",
  "created_at": "2026-06-08T14:00:00Z"
}
```

**Response (200 OK) - Active:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "url": "http://localhost:9000",
  "transport": "sse",
  "status": "active",
  "status_message": "Gateway active",
  "status_updated_at": "2026-06-08T14:00:30Z",
  "registration_attempts": 0,
  "next_retry_at": null,
  "created_at": "2026-06-08T14:00:00Z"
}
```

**Response (200 OK) - Deleting:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "my-gateway",
  "status": "deleting",
  "status_message": "Gateway deletion queued",
  "status_updated_at": "2026-06-08T14:05:00Z"
}
```

---

## Status Message Field

The `status_message` field provides user-facing descriptions of gateway state:

| Status | Typical Messages |
|--------|------------------|
| `pending` | `"Gateway registration queued"` (initial) |
| `pending` | `"Retrying after error (attempt N)"` (after failure) |
| `active` | `"Gateway active"` |
| `deleting` | `"Gateway deletion queued"` |

**Security Note:** The `last_error` field (technical error details) is stored internally but **NOT exposed** in API responses. Only `status_message` is visible to users.

---

## Retry Metadata

When a gateway is in `pending` status, retry metadata is included:

| Field | Type | Description |
|-------|------|-------------|
| `registration_attempts` | integer | Number of retry attempts (0 = first attempt) |
| `next_retry_at` | datetime | ISO 8601 timestamp of next retry (null if immediate) |

### Exponential Backoff Schedule

Retry delays follow the formula: `min(2^(attempt-1), 300)` seconds

| Attempt | Delay |
|---------|-------|
| 1 | 1s |
| 2 | 2s |
| 3 | 4s |
| 4 | 8s |
| 5 | 16s |
| 6 | 32s |
| 7 | 64s |
| 8 | 128s |
| 9 | 256s |
| 10+ | 300s (capped) |

---

## Polling Pattern

Clients should poll the GET endpoint to track operation progress:

```bash
#!/bin/bash
# Poll until gateway is active or deleted

GATEWAY_NAME="my-gateway"
MAX_ATTEMPTS=60
POLL_INTERVAL=5

for i in $(seq 1 $MAX_ATTEMPTS); do
  RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/admin/gateways/$GATEWAY_NAME")
  
  STATUS=$(echo "$RESPONSE" | jq -r '.status')
  
  if [ "$STATUS" = "active" ]; then
    echo "Gateway is active"
    exit 0
  elif [ "$STATUS" = "null" ]; then
    echo "Gateway deleted"
    exit 0
  fi
  
  echo "Status: $STATUS (attempt $i/$MAX_ATTEMPTS)"
  sleep $POLL_INTERVAL
done

echo "Timeout waiting for gateway"
exit 1
```

---

## Security and Authorization

### Token Scoping (Layer 1)

The `status_message` field visibility respects token scoping:

- **Admin tokens** (`teams: null`): See all gateways
- **Team tokens** (`teams: ["team-a"]`): See only team-owned gateways
- **Public scope** (`teams: []`): See only public gateways

### RBAC Permissions (Layer 2)

| Operation | Required Permission |
|-----------|-------------------|
| POST /admin/gateways | `gateways.create` |
| PUT/PATCH /admin/gateways/{name} | `gateways.update` |
| DELETE /admin/gateways/{name} | `gateways.delete` |
| GET /admin/gateways/{name} | `gateways.read` |

### Authorization Timing

- **Permissions checked at acceptance time** (POST/PUT/DELETE)
- **Worker executes with system authority** (not user context)
- **Audit fields preserved** (`created_by`, `team_id`) for forensics

---

## Error Responses

### Unauthorized (401)

```bash
curl -X GET "$BASE_URL/admin/gateways/my-gateway"
# No Authorization header
```

**Response:**
```json
{
  "detail": "Not authenticated"
}
```

### Wrong Team (404)

```bash
# Token scoped to team-a, gateway owned by team-b
curl -X GET "$BASE_URL/admin/gateways/team-b-gateway" \
  -H "Authorization: Bearer $TEAM_A_TOKEN"
```

**Response:**
```json
{
  "detail": "Gateway not found"
}
```

### Insufficient Permissions (403)

```bash
# Token with viewer role (no gateways.delete permission)
curl -X DELETE "$BASE_URL/admin/gateways/my-gateway" \
  -H "Authorization: Bearer $VIEWER_TOKEN"
```

**Response:**
```json
{
  "detail": "Insufficient permissions"
}
```

---

## Worker Behavior

### Background Processing

The gateway worker:

1. **Polls database** every 5 seconds (configurable via `GATEWAY_WORKER_POLL_INTERVAL_SECONDS`)
2. **Claims pending gateways** (up to 10 per cycle via `GATEWAY_WORKER_BATCH_SIZE`)
3. **Processes each gateway**:
   - Re-checks status (prevents race with DELETE)
   - Performs MCP operation (initialize/update/cleanup)
   - Updates status based on result
4. **Handles failures**:
   - Increments `registration_attempts`
   - Calculates `next_retry_at` using exponential backoff
   - Updates `status_message` with attempt count
   - Stores technical error in `last_error` (internal only)

### Graceful Shutdown

The worker handles SIGTERM/SIGINT signals:

1. Sets `shutdown_requested = True`
2. Completes current processing cycle
3. Commits in-flight transactions
4. Releases database connections
5. Exits cleanly (exit code 0)

### Crash Recovery

If the worker crashes:

- Gateways remain in `pending` state with retry metadata
- On restart, worker resumes from `next_retry_at` timestamps
- No state loss (all state persisted in database)

---

## Comparison: Sync vs Async

| Aspect | Synchronous (Flag OFF) | Asynchronous (Flag ON) |
|--------|----------------------|----------------------|
| Response Code | 200/201/204 | 202 |
| Response Time | Blocks until complete | Immediate |
| Status Field | Always `"active"` | `"pending"` → `"active"` |
| Retry Logic | None (fails immediately) | Exponential backoff |
| Timeout Risk | High (slow MCP servers) | None (background worker) |
| Progress Visibility | None | Via GET polling |
| Cancellation | Not applicable | DELETE stops retry |

---

## Best Practices

### For API Clients

1. **Check feature flag** before assuming async behavior
2. **Poll with exponential backoff** (respect `Retry-After` header)
3. **Handle both 200 and 202 responses** for forward compatibility
4. **Monitor `status_message`** for user-facing progress updates
5. **Use DELETE to cancel** pending operations

### For Operators

1. **Enable async for production** (prevents API timeouts)
2. **Monitor worker health** (ensure worker is running)
3. **Set appropriate timeouts** for MCP operations
4. **Scale workers horizontally** (PostgreSQL only, use `FOR UPDATE SKIP LOCKED`)
5. **Alert on stuck pending gateways** (via `registration_attempts` metric)

---

## Related Documentation

- [Rollout Guide](../using/async-gateway-rollout.md) - Feature flag enablement and monitoring
- [Troubleshooting Guide](../development/gateway-troubleshooting.md) - Common failure modes and debugging
- [RBAC Configuration](rbac.md) - Permission model and token scoping
- [API Usage Guide](api-usage.md) - General API patterns and authentication