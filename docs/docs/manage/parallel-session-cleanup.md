# Parallel Session Cleanup with asyncio.gather()

## Overview

The MCP Gateway implements a high-performance parallel session cleanup mechanism using `asyncio.gather()` with bounded concurrency to optimize database operations in multi-worker deployments. This document explains the implementation and performance benefits.

## Implementation

### Two-Phase Strategy

The `_cleanup_database_sessions()` method uses a two-phase approach:

1. **Connection Check Phase** (Sequential)

   - Quickly checks each session's connection status
   - Immediately removes disconnected sessions
   - Reduces workload for the parallel phase

2. **Database Refresh Phase** (Parallel with Bounded Concurrency)

   - Uses `asyncio.gather()` with a semaphore to refresh connected sessions
   - Limits concurrent DB operations to prevent resource exhaustion (default: 20)
   - Each refresh updates the `last_accessed` timestamp in the database
   - Prevents sessions from being marked as expired

### Code Structure

```python
async def _cleanup_database_sessions(self, max_concurrent: int = 20) -> None:
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
            async with semaphore:
                return await asyncio.to_thread(self._refresh_session_db, session_id)

        refresh_tasks = [bounded_refresh(session_id) for session_id in connected]
        results = await asyncio.gather(*refresh_tasks, return_exceptions=True)
```

## Performance Benefits

### Time Complexity Comparison

- **Sequential Execution**: `N × (connection_check_time + db_refresh_time)`
- **Parallel Execution**: `N × connection_check_time + ceil(N / max_concurrent) × db_refresh_time`

### Real-World Example

For 100 sessions with 50ms database latency and max_concurrent=20:

- **Sequential**: ~5 seconds total
- **Parallel**: ~250ms (5 batches × 50ms)

## Bounded Concurrency

### Why Limit Concurrency?

Without limits, parallel cleanup can:

- Exhaust database connection pools under high session counts
- Cause DB timeouts when many operations queue simultaneously
- Create memory pressure from thousands of pending task objects

### Default Configuration

- `max_concurrent=20`: Balances parallelism with resource usage
- Works well with typical DB pool sizes (50-200 connections)
- Can be tuned based on deployment requirements

## Error Handling

### Robust Exception Management

- Uses `return_exceptions=True` to prevent one failed refresh from stopping others
- Processes results individually to handle mixed success/failure scenarios
- Maintains session registry consistency even when database operations fail

### Graceful Degradation

```python
for session_id, result in zip(connected, results):
    if isinstance(result, Exception):
        # Only log error, don't remove session on transient DB errors
        logger.error(f"Error refreshing session {session_id}: {result}")
    elif not result:
        # Session no longer in database, remove locally
        await self.remove_session(session_id)
```

Transient errors (network blips, temporary DB issues) are logged but don't remove active sessions. Sessions are only removed when explicitly confirmed to no longer exist in the database.

## Benefits

1. **Scalability**: Handles thousands of concurrent sessions efficiently
2. **Reliability**: Continues processing even when individual operations fail
3. **Performance**: Dramatically reduces cleanup time through parallelization
4. **Resource Safety**: Bounded concurrency prevents DB/thread pool exhaustion
5. **Consistency**: Maintains accurate session state across distributed workers

## Usage

This optimization is automatically applied in database-backed session registries and runs every 5 minutes as part of the cleanup task. No configuration changes are required to benefit from the parallel implementation.

## Related Documentation

- [Scaling Guide](scale.md) - High availability and horizontal scaling
- [ADR-031: Parallel Session Cleanup](../architecture/adr/031-parallel-session-cleanup.md) - Architecture decision record
