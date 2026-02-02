# Worker Health Checks & Ownership Reclamation Implementation Plan

## Problem Summary

Current session affinity implementation has critical gaps when workers fail:
- No worker health monitoring
- Orphaned sessions locked to dead workers for 5 minutes (TTL)
- Forwarding failures fall back to local execution but fail with "session not found"
- User impact: 30s-5min degraded experience until TTL expires

## Solution: Hybrid Health Checks + Failure-Triggered Reclamation

### Design Approach

**Lightweight heartbeat mechanism** (30s interval) + **failure-triggered ownership reclamation** with heartbeat validation.

**Key principles:**
1. Minimize Redis overhead (30s intervals vs 1s = 30x fewer writes)
2. Fast failure detection (forwarding timeout + heartbeat check = ~30-60s)
3. No false positives (validate heartbeat before reclaiming)
4. Automatic session recreation on successful reclaim

## Implementation Details

### 1. Redis Key Schema (New)

```
mcpgw:worker_heartbeat:{worker_id} → {timestamp}  # TTL: 60s
mcpgw:worker_metadata:{worker_id} → json({...})   # TTL: 90s
```

Existing ownership keys remain unchanged:
```
mcpgw:pool_owner:{session_id} → {worker_id}  # TTL: 3600s
```

### 2. Configuration (New Settings)

Add to `mcpgateway/config.py`:

```python
mcpgateway_worker_heartbeat_enabled: bool = True
mcpgateway_worker_heartbeat_interval: int = 30  # seconds
mcpgateway_worker_heartbeat_ttl: int = 60  # seconds
mcpgateway_worker_heartbeat_stale_threshold: int = 70  # seconds
mcpgateway_ownership_reclaim_enabled: bool = True
mcpgateway_ownership_reclaim_max_attempts: int = 3
```

### 3. Core Implementation Changes

#### 3.1 Worker Heartbeat Task

**File:** `mcpgateway/services/mcp_session_pool.py`

**New methods to add:**

```python
class MCPSessionPool:
    def __init__(self):
        # Add new fields
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_stop_event: asyncio.Event = asyncio.Event()
        self._owned_sessions: Set[str] = set()
        self._owned_sessions_lock: asyncio.Lock = asyncio.Lock()

        # Metrics
        self._ownership_reclaims: int = 0
        self._ownership_reclaim_failures: int = 0
        self._heartbeat_write_failures: int = 0

    async def start_heartbeat(self) -> None:
        """Background task writing heartbeat every HEARTBEAT_INTERVAL seconds."""

    async def stop_heartbeat(self) -> None:
        """Stop heartbeat gracefully."""

    async def _write_heartbeat(self) -> None:
        """Write timestamp to mcpgw:worker_heartbeat:{WORKER_ID} with TTL."""

    async def _is_worker_healthy(self, worker_id: str) -> bool:
        """Check if worker's heartbeat is recent (< stale_threshold)."""

    async def _track_session_ownership(self, session_id: str) -> None:
        """Track session in _owned_sessions set."""

    async def _untrack_session_ownership(self, session_id: str) -> None:
        """Remove session from tracking."""
```

**Integration:**
- Call `_track_session_ownership()` after successful SETNX in `register_session_mapping()`
- Call `_untrack_session_ownership()` when session closes

#### 3.2 Ownership Reclamation

**File:** `mcpgateway/services/mcp_session_pool.py`

**New method:**

```python
async def _attempt_ownership_reclaim(
    self,
    mcp_session_id: str,
    current_owner_id: str,
) -> bool:
    """Reclaim ownership from dead worker.

    Process:
    1. Check if reclaim enabled
    2. Check if current owner's heartbeat is stale
    3. Atomically reclaim using Lua script (CAS)
    4. Invalidate local session if exists
    5. Track ownership

    Returns True if reclaimed, False otherwise.
    """
```

**Lua script for atomic reclaim:**

```lua
local owner_key = KEYS[1]
local current_owner = ARGV[1]
local new_owner = ARGV[2]
local ttl = tonumber(ARGV[3])

local actual_owner = redis.call('GET', owner_key)
if actual_owner == current_owner then
    redis.call('SETEX', owner_key, ttl, new_owner)
    return 1
end
return 0
```

**New helper method:**

```python
async def _invalidate_session_for_reclaim(self, mcp_session_id: str) -> None:
    """Remove pooled session so acquire() creates fresh upstream connection."""
```

#### 3.3 Modify Forwarding Methods

**File:** `mcpgateway/services/mcp_session_pool.py`

**Modify `forward_request_to_owner()` (SSE transport):**

```python
async def forward_request_to_owner(...) -> Optional[Dict[str, Any]]:
    # Existing forwarding logic...
    try:
        # Pub/sub forwarding...
    except asyncio.TimeoutError:
        logger.warning(f"Timeout forwarding to {owner_id}, attempting reclaim")
        reclaimed = await self._attempt_ownership_reclaim(mcp_session_id, owner_id)
        if reclaimed:
            return None  # Execute locally
        raise
    except Exception as e:
        logger.warning(f"Error forwarding: {e}, attempting reclaim")
        reclaimed = await self._attempt_ownership_reclaim(mcp_session_id, owner_id)
        if reclaimed:
            return None  # Execute locally
        return None
```

**Modify `forward_streamable_http_to_owner()` (HTTP transport):**

```python
async def forward_streamable_http_to_owner(...) -> Optional[Dict[str, Any]]:
    try:
        # HTTP forwarding...
    except httpx.TimeoutException:
        logger.warning(f"HTTP timeout to {owner_worker_id}, attempting reclaim")
        reclaimed = await self._attempt_ownership_reclaim(mcp_session_id, owner_worker_id)
        if reclaimed:
            return {"reclaimed": True, "status": 503, "headers": {}, "body": b""}
        return None
    except Exception as e:
        logger.warning(f"HTTP error: {e}, attempting reclaim")
        reclaimed = await self._attempt_ownership_reclaim(mcp_session_id, owner_worker_id)
        if reclaimed:
            return {"reclaimed": True, "status": 503, "headers": {}, "body": b""}
        return None
```

#### 3.4 Handle Reclaimed Responses

**File:** `mcpgateway/transports/streamablehttp_transport.py`

**Modify `handle_streamable_http()`:**

```python
async def handle_streamable_http(self, scope, receive, send):
    # ... existing ownership check ...

    response = await pool.forward_streamable_http_to_owner(...)

    if response:
        if response.get("reclaimed"):
            logger.info(f"Ownership reclaimed for {mcp_session_id[:8]}, retrying locally")
            # Fall through to local execution
        else:
            # Forward response to client
            await send({"type": "http.response.start", ...})
            await send({"type": "http.response.body", ...})
            return

    # Execute locally (forwarding failed or reclaimed)
    # Existing /rpc routing...
```

#### 3.5 Startup Integration

**File:** `mcpgateway/main.py`

**Modify `lifespan()` function:**

```python
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Existing startup...

    if settings.mcpgateway_session_affinity_enabled:
        pool = get_mcp_session_pool()

        # Existing RPC listener
        pool._rpc_listener_task = asyncio.create_task(pool.start_rpc_listener())

        # NEW: Start heartbeat
        if settings.mcpgateway_worker_heartbeat_enabled:
            pool._heartbeat_task = asyncio.create_task(pool.start_heartbeat())
            logger.info(f"Started worker heartbeat for {WORKER_ID}")

    yield

    # Shutdown
    if settings.mcpgateway_session_affinity_enabled:
        pool = get_mcp_session_pool()

        # NEW: Stop heartbeat
        if pool._heartbeat_task:
            await pool.stop_heartbeat()

        # Existing cleanup...
```

#### 3.6 Metrics

**File:** `mcpgateway/services/mcp_session_pool.py`

**Update `get_metrics()` method:**

```python
def get_metrics(self) -> Dict[str, Any]:
    return {
        # Existing metrics...
        "session_affinity": {
            # Existing...
            "ownership_reclaims": self._ownership_reclaims,
            "ownership_reclaim_failures": self._ownership_reclaim_failures,
        },
        "worker_health": {
            "heartbeat_enabled": settings.mcpgateway_worker_heartbeat_enabled,
            "heartbeat_write_failures": self._heartbeat_write_failures,
            "owned_sessions_count": len(self._owned_sessions),
        },
    }
```

### 4. Edge Cases Handled

| Scenario | Mitigation |
|----------|-----------|
| Multiple workers reclaim simultaneously | Lua script with CAS ensures only one succeeds |
| Worker crashes during reclamation | Redis TTL ensures cleanup; atomic Lua prevents partial state |
| Network partitions | Heartbeat stops → ownership reclaimed; TTL ensures eventual consistency |
| Session recreation after reclaim | `_invalidate_session_for_reclaim()` forces fresh upstream session |
| Heartbeat lag under load | 40s buffer (60s TTL - 30s interval) + 70s stale threshold |
| Redis temporarily unavailable | Heartbeat writes fail non-fatally; reclamation disabled gracefully |

### 5. Performance Impact

**Redis Load:**
- 10 workers × 2 writes/30s = **0.67 writes/second** (negligible)

**Latency:**
- Normal case: No change (heartbeat runs in background)
- Failure case: 30s forward timeout + 30ms reclaim overhead = acceptable

**Memory:**
- Per worker: <15KB (task + owned sessions set)
- Redis: ~250 bytes per worker

### 6. Testing Strategy

#### Unit Tests (New File: `tests/unit/test_mcp_session_pool_health.py`)

```python
test_heartbeat_written_on_startup()
test_is_worker_healthy_returns_true_for_recent_heartbeat()
test_is_worker_healthy_returns_false_for_stale_heartbeat()
test_ownership_reclaim_succeeds_for_dead_worker()
test_ownership_reclaim_fails_for_healthy_worker()
test_ownership_reclaim_atomic_with_multiple_workers()
```

#### Integration Tests (New File: `tests/integration/test_session_affinity_failover.py`)

```python
test_sse_request_succeeds_after_owner_worker_dies()
test_streamable_http_request_succeeds_after_owner_dies()
test_session_state_reset_after_reclaim()
```

#### Manual Testing

```bash
# Start 2 workers on different ports
gunicorn -w 1 -b 127.0.0.1:4444 mcpgateway.main:app &
gunicorn -w 1 -b 127.0.0.1:4445 mcpgateway.main:app &

# Create session on worker A
curl -X POST http://localhost:4444/sse -H "Authorization: Bearer TOKEN"

# Send request to worker B (forwards to A)
curl -X POST http://localhost:4445/message -H "mcp-session-id: SESSION_ID"

# Kill worker A
kill <pid>

# Retry on worker B (should reclaim and execute)
curl -X POST http://localhost:4445/message -H "mcp-session-id: SESSION_ID"
# Expected: Success after ~30s timeout + reclaim
```

### 7. Rollout Strategy

**Phase 1: Heartbeat Only** (Deploy with reclaim disabled)
- Add heartbeat task
- Monitor metrics for 1 week
- Verify no performance impact

**Phase 2: Enable Reclamation**
- Set `MCPGATEWAY_OWNERSHIP_RECLAIM_ENABLED=true`
- Monitor reclaim rates and error logs
- Test rolling upgrades

**Phase 3: Optimization**
- Tune intervals based on metrics
- Add Grafana dashboards
- Document operational runbooks

### 8. Critical Files

| File | Changes |
|------|---------|
| `mcpgateway/services/mcp_session_pool.py` | Add heartbeat task, reclamation logic, health checks (core implementation) |
| `mcpgateway/config.py` | Add 6 new configuration settings |
| `mcpgateway/main.py` | Modify `lifespan()` to start/stop heartbeat |
| `mcpgateway/transports/streamablehttp_transport.py` | Handle reclaimed responses, retry locally |
| `mcpgateway/cache/session_registry.py` | Optional: Add heartbeat awareness for SSE |
| `.env.example` | Document new environment variables |
| `docs/docs/architecture/adr/038-multi-worker-session-affinity.md` | Add worker health and reclamation sections |

### 9. Verification Plan

**End-to-End Test:**
1. Deploy 2-worker setup with heartbeat enabled
2. Create SSE session on worker A
3. Send tool call that forwards from worker B to A
4. Kill worker A (simulate crash)
5. Retry tool call from worker B
6. Verify: Request succeeds after ~30s (timeout + reclaim)
7. Check metrics: `ownership_reclaims` incremented
8. Check logs: "Successfully reclaimed ownership" message
9. Verify new upstream session created (not reused)

**Success Criteria:**
- ✅ Forwarding failure detected within 30s
- ✅ Ownership reclaimed automatically
- ✅ Request succeeds on retrying worker
- ✅ Fresh upstream session created
- ✅ No session state leakage
- ✅ Metrics and logs confirm reclamation

## Benefits

1. **Fast failure detection:** 30-60s (vs 5 minutes with TTL only)
2. **Automatic recovery:** No manual intervention required
3. **Minimal overhead:** 0.67 Redis writes/second for 10 workers
4. **Backward compatible:** Graceful degradation if Redis unavailable
5. **Production ready:** Atomic operations, comprehensive error handling

## Estimated Effort

- Core implementation: 2-3 days
- Testing: 1-2 days
- Documentation: 0.5 day
- **Total: 4-6 days**
