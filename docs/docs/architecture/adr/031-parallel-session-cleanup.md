# ADR-031: Parallel Session Cleanup with asyncio.gather()

- *Status:* Accepted
- *Date:* 2025-01-15
- *Deciders:* Platform Team

## Context

In multi-worker deployments with database-backed session registries, the session cleanup task runs every 5 minutes to:
1. Remove disconnected sessions from local memory
2. Refresh active session timestamps in the database

The original sequential implementation processed each session one at a time:

```python
# Original sequential approach
for session_id, transport in local_transports.items():
    if not await transport.is_connected():
        await self.remove_session(session_id)
    else:
        # Blocking database call for each session
        self._refresh_session_db(session_id)
```

**Problem**: With hundreds of active sessions and typical database latency of 50ms per operation, cleanup could take 5+ seconds, blocking other async operations and causing cleanup task overlap.

Related to: Performance optimization for high-session-count deployments.

## Decision

Implement a two-phase cleanup strategy using `asyncio.gather()` with bounded concurrency:

### 1. Two-Phase Strategy

**Phase 1: Sequential Connection Checks (Fast)**
- Quickly checks each session's connection status
- Immediately removes disconnected sessions
- Reduces workload for the parallel phase

**Phase 2: Parallel Database Refresh (Bounded)**
- Uses `asyncio.gather()` with a semaphore to refresh connected sessions
- Limits concurrent DB operations to prevent resource exhaustion (default: 20)
- Uses `asyncio.to_thread()` for blocking database operations

### 2. Implementation

**File:** `mcpgateway/cache/session_registry.py`

```python
async def _cleanup_database_sessions(self, max_concurrent: int = 20) -> None:
    """Clean up database sessions with parallel refresh for performance."""
    local_transports = dict(self._sessions)

    # Phase 1: Sequential connection checks (fast)
    connected: list[str] = []
    for session_id, transport in local_transports.items():
        if not await transport.is_connected():
            await self.remove_session(session_id)
        else:
            connected.append(session_id)

    # Phase 2: Parallel database refreshes with bounded concurrency
    if connected:
        semaphore = asyncio.Semaphore(max_concurrent)

        async def bounded_refresh(session_id: str) -> bool:
            """Refresh session with semaphore-bounded concurrency."""
            async with semaphore:
                return await asyncio.to_thread(self._refresh_session_db, session_id)

        refresh_tasks = [bounded_refresh(session_id) for session_id in connected]
        results = await asyncio.gather(*refresh_tasks, return_exceptions=True)

        for session_id, result in zip(connected, results):
            if isinstance(result, Exception):
                # Only log error, don't remove session on transient DB errors
                logger.error(f"Error refreshing session {session_id}: {result}")
            elif not result:
                # Session no longer in database, remove locally
                await self.remove_session(session_id)
```

### 3. Error Handling Strategy

- Uses `return_exceptions=True` to prevent one failed refresh from stopping others
- Transient errors (network blips, temporary DB issues) are logged but don't remove active sessions
- Sessions are only removed when explicitly confirmed to no longer exist in the database

## Performance Characteristics

### Time Complexity Comparison

- **Sequential Execution**: `N × (connection_check_time + db_refresh_time)`
- **Parallel Execution**: `N × connection_check_time + ceil(N / max_concurrent) × db_refresh_time`

### Benchmark Results

For 100 sessions with 50ms database latency and max_concurrent=20:

| Approach | Time | Notes |
|----------|------|-------|
| Sequential | ~5 seconds | 100 × 50ms |
| Parallel (unbounded) | ~50ms | All concurrent, risky |
| Parallel (bounded 20) | ~250ms | 5 batches × 50ms |

**Speedup**: 11-13x faster than sequential with bounded concurrency.

### Why Bound Concurrency?

Without limits, parallel cleanup can:
- Exhaust database connection pools under high session counts
- Cause DB timeouts when many operations queue simultaneously
- Create memory pressure from thousands of pending task objects

**Default Configuration**: `max_concurrent=20`
- Works well with typical DB pool sizes (50-200 connections)
- Can be tuned based on deployment requirements

## Consequences

### Positive

- **Scalability**: Handles thousands of concurrent sessions efficiently
- **Reliability**: Continues processing even when individual operations fail
- **Performance**: 11-13x reduction in cleanup time through parallelization
- **Resource Safety**: Bounded concurrency prevents DB/thread pool exhaustion
- **Consistency**: Maintains accurate session state across distributed workers
- **Graceful Degradation**: Transient errors logged but don't affect session state

### Negative

- **Memory Overhead**: Task objects created for each session (mitigated by bounded concurrency)
- **Thread Pool Usage**: Uses asyncio thread pool for blocking DB calls
- **Complexity**: More complex than simple sequential loop

### Neutral

- Runs every 5 minutes via `_db_cleanup_task()`
- Only affects database backend (not memory or Redis)
- No configuration changes required to benefit from optimization

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Unbounded parallelism | Risk of DB pool exhaustion, memory pressure |
| asyncio.Queue with workers | Over-engineered for cleanup task |
| Increase cleanup interval | Delays detection of disconnected sessions |
| Async database driver | Would require broader architectural changes |

## References

- `mcpgateway/cache/session_registry.py` - Implementation
- `docs/docs/manage/parallel-session-cleanup.md` - Detailed documentation
- `tests/performance/test_parallel_cleanup.py` - Performance test

## Status

Implemented and enabled by default for database-backed session registries.
