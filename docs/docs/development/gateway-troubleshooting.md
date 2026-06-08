# Gateway Lifecycle Troubleshooting Guide

This guide provides diagnostic procedures and solutions for common issues with asynchronous gateway lifecycle operations.

---

## Overview

The asynchronous gateway lifecycle feature uses a background worker to process gateway operations (create, update, delete) with automatic retry logic. This guide covers common failure modes, diagnostic techniques, and resolution steps.

---

## Quick Diagnostic Checklist

Before diving into specific issues, verify these basics:

- [ ] Feature flag enabled: `GATEWAY_ASYNC_LIFECYCLE_ENABLED=true`
- [ ] Worker started: Check logs for "Gateway worker started"
- [ ] Database accessible: Test connection with `psql` or SQLite CLI
- [ ] MCP server reachable: Test with `curl` or `telnet`
- [ ] Authentication valid: Verify JWT token not expired
- [ ] Permissions granted: User has required RBAC permissions

---

## Common Failure Modes

### 1. Gateway Stuck in Pending State

**Symptom:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway" | jq '.status, .status_message'

# Output:
"pending"
"Retrying after error (attempt 15)"
```

**Possible Causes:**

#### A. Worker Not Running

**Diagnostic:**
```bash
# Check for worker startup log
docker-compose logs mcpgateway | grep "Gateway worker started"

# If no output, worker is not running
```

**Resolution:**
```bash
# Verify feature flag
echo $GATEWAY_ASYNC_LIFECYCLE_ENABLED  # Should be "true"

# Restart application
docker-compose restart mcpgateway

# Verify worker started
docker-compose logs -f mcpgateway | grep -i worker
```

#### B. MCP Server Unreachable

**Diagnostic:**
```bash
# Check gateway configuration
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway" | jq '.url, .transport'

# Test MCP server directly
curl -v http://mcp-server:9000/sse
# or
telnet mcp-server 9000
```

**Common Issues:**
- Wrong hostname/port
- MCP server not started
- Network connectivity issues
- Firewall blocking connection

**Resolution:**
```bash
# Update gateway URL
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$BASE_URL/admin/gateways/my-gateway" \
  -d '{"url": "http://correct-host:9000", "transport": "sse"}'

# Or delete and recreate
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway"
```

#### C. Authentication Failure

**Diagnostic:**
```bash
# Check gateway auth configuration
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway" | jq '.auth_type, .auth_value'

# Test auth manually
curl -H "Authorization: Bearer <gateway-auth-token>" \
  http://mcp-server:9000/sse
```

**Common Issues:**
- Invalid auth token
- Expired credentials
- Wrong auth type (bearer vs basic)

**Resolution:**
```bash
# Update gateway auth
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$BASE_URL/admin/gateways/my-gateway" \
  -d '{
    "auth_type": "bearer",
    "auth_value": "new-valid-token"
  }'
```

#### D. MCP Protocol Error

**Diagnostic:**
```bash
# Check worker logs for protocol errors
docker-compose logs mcpgateway | grep -A 5 "registration failed"

# Look for:
# - "Invalid JSON-RPC response"
# - "Missing required field"
# - "Protocol version mismatch"
```

**Resolution:**
```bash
# Verify MCP server implements protocol correctly
curl -X POST http://mcp-server:9000/sse \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'

# Should return valid JSON-RPC response with capabilities
```

---

### 2. Worker Crash or Restart Loop

**Symptom:**
```bash
# Worker starts then immediately crashes
docker-compose logs mcpgateway | tail -20

# Output shows repeated startup/crash cycle:
INFO: Gateway worker started
ERROR: Worker error: ...
INFO: Gateway worker stopped
INFO: Gateway worker started
ERROR: Worker error: ...
```

**Possible Causes:**

#### A. Database Connection Failure

**Diagnostic:**
```bash
# Test database connection
psql $DATABASE_URL -c "SELECT 1"

# Or for SQLite
sqlite3 mcp.db "SELECT 1"
```

**Resolution:**
```bash
# Fix DATABASE_URL
export DATABASE_URL="postgresql+psycopg://user:pass@host:5432/dbname"

# Restart application
docker-compose restart mcpgateway
```

#### B. Configuration Error

**Diagnostic:**
```bash
# Check worker configuration
echo $GATEWAY_WORKER_POLL_INTERVAL_SECONDS
echo $GATEWAY_WORKER_BATCH_SIZE

# Check for invalid values (negative, zero, non-numeric)
```

**Resolution:**
```bash
# Set valid configuration
export GATEWAY_WORKER_POLL_INTERVAL_SECONDS=5
export GATEWAY_WORKER_BATCH_SIZE=10

# Restart application
docker-compose restart mcpgateway
```

#### C. Memory/Resource Exhaustion

**Diagnostic:**
```bash
# Check container memory usage
docker stats mcpgateway

# Check for OOM kills
docker-compose logs mcpgateway | grep -i "killed"
dmesg | grep -i "out of memory"
```

**Resolution:**
```bash
# Increase container memory limit
# docker-compose.yml
services:
  mcpgateway:
    mem_limit: 2g
    mem_reservation: 1g

# Restart
docker-compose up -d mcpgateway
```

---

### 3. High Registration Attempt Count

**Symptom:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway" | jq '.registration_attempts'

# Output: 50+ attempts
```

**Diagnostic:**

Check `status_message` for clues:
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway" | jq '.status_message'

# Common messages:
# "Retrying after error (attempt N)" - Generic failure
# "Connection timeout" - Network issue
# "Authentication failed" - Auth problem
# "Invalid response" - Protocol error
```

**Resolution:**

The worker retries indefinitely until DELETE. To stop retry loop:

```bash
# Cancel pending gateway
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway"

# Fix underlying issue (URL, auth, etc.)
# Recreate gateway with correct configuration
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$BASE_URL/admin/gateways" \
  -d '{
    "name": "my-gateway",
    "url": "http://correct-host:9000",
    "transport": "sse",
    "auth_type": "bearer",
    "auth_value": "valid-token"
  }'
```

---

### 4. DELETE Not Stopping Retry Loop

**Symptom:**
```bash
# DELETE returns 202
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway"

# But gateway still shows pending after 30+ seconds
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway" | jq '.status'

# Output: "pending" (should be "deleting" or deleted)
```

**Possible Causes:**

#### A. Worker Not Processing Deleting Status

**Diagnostic:**
```bash
# Check worker logs for status check
docker-compose logs mcpgateway | grep -i "deleting"

# Should see:
# "Gateway status changed to deleting, stopping retry"
```

**Resolution:**
```bash
# Restart worker to force status re-check
docker-compose restart mcpgateway

# Verify gateway transitions to deleting
watch -n 2 "curl -s -H 'Authorization: Bearer $TOKEN' \
  '$BASE_URL/admin/gateways/my-gateway' | jq '.status'"
```

#### B. Database Transaction Conflict

**Diagnostic:**
```bash
# Check for database locks (PostgreSQL)
psql $DATABASE_URL -c "
  SELECT pid, state, query 
  FROM pg_stat_activity 
  WHERE state = 'active' AND query LIKE '%gateways%'
"
```

**Resolution:**
```bash
# Kill blocking queries (PostgreSQL)
psql $DATABASE_URL -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid = <blocking-pid>"

# Restart application
docker-compose restart mcpgateway
```

---

### 5. Duplicate Gateway Creation (409 Conflict)

**Symptom:**
```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$BASE_URL/admin/gateways" \
  -d '{"name": "existing-gateway", "url": "http://localhost:9000", "transport": "sse"}'

# Output:
{
  "detail": "Gateway with name 'existing-gateway' already exists"
}
```

**Expected Behavior:**

- **Pending gateway exists**: Returns 202 with existing pending gateway (idempotent)
- **Active gateway exists**: Returns 409 Conflict (name collision)

**Resolution:**

```bash
# Check existing gateway status
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/existing-gateway" | jq '.status'

# If active, use different name or delete first
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/existing-gateway"

# If pending, wait for completion or cancel
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/existing-gateway"
```

---

### 6. Status Message Not Updating

**Symptom:**
```bash
# status_message stuck on old value
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway" | jq '.status_message, .status_updated_at'

# Output:
"Gateway registration queued"
"2026-06-08T10:00:00Z"  # 30 minutes ago
```

**Diagnostic:**
```bash
# Check if worker is processing
docker-compose logs mcpgateway | grep "my-gateway"

# Check registration_attempts (should be increasing)
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/my-gateway" | jq '.registration_attempts'
```

**Possible Causes:**

- Worker not running
- Gateway filtered out by token scoping
- Database update failure

**Resolution:**
```bash
# Restart worker
docker-compose restart mcpgateway

# Force status update by triggering operation
curl -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$BASE_URL/admin/gateways/my-gateway" \
  -d '{"url": "http://localhost:9000", "transport": "sse"}'
```

---

## Diagnostic Commands

### Check Worker Health

```bash
# Worker startup
docker-compose logs mcpgateway | grep "Gateway worker started"

# Worker processing
docker-compose logs mcpgateway | grep -E "(claim|process|retry)" | tail -20

# Worker errors
docker-compose logs mcpgateway | grep -i error | tail -20
```

### Check Gateway Status

```bash
# Single gateway
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways/{name}" | jq

# All pending gateways
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways?status=pending" | jq

# All deleting gateways
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/admin/gateways?status=deleting" | jq
```

### Check Database State

```bash
# PostgreSQL
psql $DATABASE_URL -c "
  SELECT name, status, status_message, registration_attempts, next_retry_at 
  FROM gateways 
  WHERE status IN ('pending', 'deleting')
  ORDER BY created_at DESC
"

# SQLite
sqlite3 mcp.db "
  SELECT name, status, status_message, registration_attempts, next_retry_at 
  FROM gateways 
  WHERE status IN ('pending', 'deleting')
  ORDER BY created_at DESC
"
```

### Check Metrics

```bash
# Prometheus metrics endpoint
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/metrics/prometheus" | grep gateway

# Key metrics:
# gateway_status_total{status="pending"}
# gateway_registration_attempts
# gateway_pending_duration_seconds
# gateway_registration_errors_total
```

---

## Internal Debugging Fields

### last_error Field

The `last_error` field stores technical error details for debugging but is **NOT exposed** in API responses. To access it, query the database directly:

```bash
# PostgreSQL
psql $DATABASE_URL -c "
  SELECT name, status, status_message, last_error 
  FROM gateways 
  WHERE name = 'my-gateway'
"

# SQLite
sqlite3 mcp.db "
  SELECT name, status, status_message, last_error 
  FROM gateways 
  WHERE name = 'my-gateway'
"
```

**Example output:**
```
name         | status  | status_message                    | last_error
-------------|---------|-----------------------------------|----------------------------------
my-gateway   | pending | Retrying after error (attempt 5)  | ConnectionError: [Errno 111] Connection refused
```

**Security Note:** The `last_error` field may contain sensitive information (URLs, auth tokens, stack traces). Only expose to authorized operators via direct database access, never via API responses.

---

## Status Message Reference

### Common Status Messages

| Message | Status | Meaning |
|---------|--------|---------|
| `"Gateway registration queued"` | pending | Initial state, waiting for worker |
| `"Retrying after error (attempt N)"` | pending | Worker encountered error, will retry |
| `"Gateway active"` | active | Registration successful, serving requests |
| `"Gateway update queued"` | pending | Update operation queued |
| `"Gateway deletion queued"` | deleting | Deletion operation queued |

### Interpreting Retry Messages

```bash
# Low attempt count (1-5): Transient network issue
"Retrying after error (attempt 3)"

# Medium attempt count (6-15): Configuration problem
"Retrying after error (attempt 10)"
# Action: Check gateway URL, auth, MCP server status

# High attempt count (16+): Persistent failure
"Retrying after error (attempt 25)"
# Action: Cancel with DELETE, fix root cause, recreate
```

---

## Worker Log Analysis

### Normal Operation

```
INFO: Gateway worker started
INFO: Worker polling interval: 5 seconds
INFO: Worker batch size: 10
INFO: Claimed 3 pending gateways
INFO: Processing gateway: my-gateway-1
INFO: Gateway my-gateway-1 status changed to active
INFO: Processing gateway: my-gateway-2
INFO: Gateway my-gateway-2 status changed to active
INFO: Processing gateway: my-gateway-3
INFO: Gateway my-gateway-3 status changed to active
```

### Failure Patterns

**Connection Refused:**
```
ERROR: Gateway registration failed: my-gateway
ERROR: ConnectionError: [Errno 111] Connection refused
INFO: Gateway my-gateway retry scheduled for 2026-06-08T14:00:10Z (attempt 3)
```

**Authentication Failed:**
```
ERROR: Gateway registration failed: my-gateway
ERROR: HTTPError: 401 Unauthorized
INFO: Gateway my-gateway retry scheduled for 2026-06-08T14:00:20Z (attempt 5)
```

**Protocol Error:**
```
ERROR: Gateway registration failed: my-gateway
ERROR: ValueError: Invalid JSON-RPC response: missing 'result' field
INFO: Gateway my-gateway retry scheduled for 2026-06-08T14:00:40Z (attempt 7)
```

**Timeout:**
```
ERROR: Gateway registration failed: my-gateway
ERROR: TimeoutError: MCP initialization timeout after 30s
INFO: Gateway my-gateway retry scheduled for 2026-06-08T14:01:20Z (attempt 9)
```

---

## Recovery Procedures

### Force Gateway Cleanup

If a gateway is stuck and DELETE doesn't work:

```bash
# 1. Stop worker
docker-compose stop mcpgateway

# 2. Delete gateway directly from database
psql $DATABASE_URL -c "DELETE FROM gateways WHERE name = 'stuck-gateway'"

# Or SQLite
sqlite3 mcp.db "DELETE FROM gateways WHERE name = 'stuck-gateway'"

# 3. Restart worker
docker-compose start mcpgateway
```

### Reset All Pending Gateways

To reset all pending gateways to active (emergency recovery):

```bash
# 1. Stop worker
docker-compose stop mcpgateway

# 2. Update all pending gateways to active
psql $DATABASE_URL -c "
  UPDATE gateways 
  SET status = 'active', 
      status_message = 'Gateway active',
      registration_attempts = 0,
      next_retry_at = NULL
  WHERE status = 'pending'
"

# Or SQLite
sqlite3 mcp.db "
  UPDATE gateways 
  SET status = 'active', 
      status_message = 'Gateway active',
      registration_attempts = 0,
      next_retry_at = NULL
  WHERE status = 'pending'
"

# 3. Restart worker
docker-compose start mcpgateway
```

**Warning:** This bypasses worker validation. Only use in emergencies.

### Disable Async Feature

To revert to synchronous behavior:

```bash
# 1. Set feature flag to false
export GATEWAY_ASYNC_LIFECYCLE_ENABLED=false

# 2. Restart application
docker-compose restart mcpgateway

# 3. Verify synchronous behavior
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$BASE_URL/admin/gateways" \
  -d '{"name": "test", "url": "http://localhost:9000", "transport": "sse"}' -i

# Should return 201 Created (not 202 Accepted)
```

---

## Prevention Best Practices

### For Operators

1. **Monitor worker health** - Set up alerts for worker downtime
2. **Track pending duration** - Alert on gateways pending >5 minutes
3. **Validate MCP servers** - Test connectivity before registration
4. **Use correct auth** - Verify credentials before creating gateways
5. **Set resource limits** - Prevent worker OOM crashes

### For Developers

1. **Handle 202 responses** - Don't assume immediate success
2. **Poll with backoff** - Respect `Retry-After` header
3. **Monitor status_message** - Display progress to users
4. **Implement timeouts** - Don't poll indefinitely
5. **Use DELETE to cancel** - Stop unwanted operations

### For MCP Server Authors

1. **Implement protocol correctly** - Follow MCP specification
2. **Return valid JSON-RPC** - Include required fields
3. **Handle auth properly** - Validate bearer tokens
4. **Set reasonable timeouts** - Don't hang indefinitely
5. **Log errors clearly** - Help diagnose issues

---

## Related Documentation

- [API Reference](../manage/gateway-lifecycle-async.md) - Complete API documentation
- [Rollout Guide](../using/async-gateway-rollout.md) - Feature enablement and monitoring
- [RBAC Configuration](../manage/rbac.md) - Permission model and token scoping
- [Observability](../manage/observability.md) - Metrics and tracing configuration