# CPU Spin Loop Mitigation Guide

This guide documents the CPU spin loop issue affecting MCP Gateway and the multi-layered mitigation strategy implemented to address it.

## Overview

**Issue**: [#2360](https://github.com/IBM/mcp-context-forge/issues/2360) - Gunicorn workers consume 100% CPU after load tests
**Root Cause**: [anyio#695](https://github.com/agronholm/anyio/issues/695) - `_deliver_cancellation` infinite loop
**Affected Versions**: All versions using anyio with MCP SDK
**Status**: Mitigated via configuration; awaiting upstream fix

## Problem Description

Under certain conditions (typically after high-load benchmarks or sustained traffic), Gunicorn workers can enter a state where they consume 90-100% CPU while appearing idle. This happens when:

1. An SSE/MCP connection is cancelled (client disconnect, timeout, etc.)
2. Internal tasks spawned by the MCP SDK don't respond to `CancelledError`
3. anyio's `_deliver_cancellation` method enters an infinite loop trying to cancel these tasks
4. The loop calls `call_soon()` repeatedly, scheduling callbacks that never complete

### Symptoms

- Workers at 90-100% CPU with no active requests
- `py-spy` shows spinning in `anyio/_backends/_asyncio.py:569-580`
- `strace` shows rapid `epoll_wait` with 0ms timeout
- Issue persists until worker is recycled or restarted

### Root Cause Analysis

The `_deliver_cancellation` method in anyio's `CancelScope` has no iteration limit:

```python
# anyio/_backends/_asyncio.py (simplified)
def _deliver_cancellation(self, origin: CancelScope) -> bool:
    # ... check if task should be cancelled ...
    if should_retry:
        self._host_task._task_state.cancel_scope._cancel_handle = (
            get_running_loop().call_soon(
                self._deliver_cancellation, origin  # Recursive scheduling
            )
        )
    return False
```

When tasks don't properly handle cancellation (e.g., MCP SDK's `post_writer` waiting on `MemoryObjectSendStream`), this creates an infinite loop.

## Mitigation Strategy

We implement a **defense-in-depth** approach with three layers:

```
┌─────────────────────────────────────────────────────────────┐
│                    Layer 1: Prevention                       │
│         Detect and close dead connections early              │
│   SSE_SEND_TIMEOUT, SSE_RAPID_YIELD_WINDOW_MS/MAX           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Layer 2: Containment                      │
│         Limit cleanup wait time for stuck tasks              │
│   MCP_SESSION_POOL_CLEANUP_TIMEOUT, SSE_TASK_GROUP_...      │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                Layer 3: Last Resort (Experimental)           │
│         Force-terminate infinite cancellation loops          │
│   ANYIO_CANCEL_DELIVERY_PATCH_ENABLED/MAX_ITERATIONS        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Layer 4: Recovery                         │
│         Worker recycling cleans up orphaned tasks            │
│   GUNICORN_MAX_REQUESTS, GUNICORN_MAX_REQUESTS_JITTER       │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 1: SSE Connection Protection

Detect and close dead SSE connections before they can trigger spin loops.

### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SSE_SEND_TIMEOUT` | `30.0` | Timeout in seconds for ASGI `send()` calls. Protects against connections that accept data but never complete. Set to `0` to disable. |
| `SSE_RAPID_YIELD_WINDOW_MS` | `1000` | Time window (milliseconds) for detecting rapid yield patterns that indicate a dead client. |
| `SSE_RAPID_YIELD_MAX` | `50` | Maximum number of yields allowed within the detection window. If exceeded, connection is closed. Set to `0` to disable. |

### How It Works

When an SSE client disconnects without properly closing the connection, the server may continue trying to send data. The rapid yield detection monitors how often the event loop yields during SSE operations:

```python
# Simplified detection logic
if yields_in_window > SSE_RAPID_YIELD_MAX:
    logger.warning("Client appears disconnected, closing SSE connection")
    raise ClientDisconnected()
```

### Recommended Settings

```bash
# Default (balanced)
SSE_SEND_TIMEOUT=30.0
SSE_RAPID_YIELD_WINDOW_MS=1000
SSE_RAPID_YIELD_MAX=50

# Aggressive (faster detection, may have false positives on slow networks)
SSE_SEND_TIMEOUT=10.0
SSE_RAPID_YIELD_WINDOW_MS=500
SSE_RAPID_YIELD_MAX=25
```

---

## Layer 2: Cleanup Timeouts

Limit how long the gateway waits for stuck tasks during connection cleanup.

### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SESSION_POOL_CLEANUP_TIMEOUT` | `5.0` | Timeout in seconds for `session.__aexit__()` when closing pooled MCP sessions. |
| `SSE_TASK_GROUP_CLEANUP_TIMEOUT` | `5.0` | Timeout in seconds for SSE task group cleanup when connections are cancelled. |

### How It Works

Instead of waiting indefinitely for tasks to respond to cancellation:

```python
# Before (could spin forever)
await pooled.session.__aexit__(None, None, None)

# After (bounded wait)
with anyio.move_on_after(cleanup_timeout) as scope:
    await pooled.session.__aexit__(None, None, None)
if scope.cancelled_caught:
    logger.warning("Session cleanup timed out after %s seconds", cleanup_timeout)
```

### Recommended Settings

```bash
# Default (reliable cleanup)
MCP_SESSION_POOL_CLEANUP_TIMEOUT=5.0
SSE_TASK_GROUP_CLEANUP_TIMEOUT=5.0

# Aggressive (faster recovery from spin loops)
MCP_SESSION_POOL_CLEANUP_TIMEOUT=0.5
SSE_TASK_GROUP_CLEANUP_TIMEOUT=0.5

# Conservative (for slow MCP servers)
MCP_SESSION_POOL_CLEANUP_TIMEOUT=10.0
SSE_TASK_GROUP_CLEANUP_TIMEOUT=10.0
```

### Trade-offs

| Setting | Pros | Cons |
|---------|------|------|
| Low (0.5-2s) | Fast spin loop recovery | May interrupt legitimate cleanup |
| Default (5s) | Balanced | Spin loops persist for 5s before timeout |
| High (10s+) | Reliable cleanup | Longer CPU waste during spin loops |

---

## Layer 3: anyio Monkey-Patch (Experimental)

Last resort: directly patch anyio to limit `_deliver_cancellation` iterations.

### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANYIO_CANCEL_DELIVERY_PATCH_ENABLED` | `false` | Enable the monkey-patch. Only enable if Layers 1-2 don't resolve the issue. |
| `ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS` | `100` | Maximum iterations before forcing termination of the cancellation loop. |

### How It Works

The patch wraps anyio's `_deliver_cancellation` method to add an iteration counter:

```python
def _patched_deliver_cancellation(self, origin):
    if not hasattr(origin, "_delivery_iterations"):
        origin._delivery_iterations = 0
    origin._delivery_iterations += 1

    if origin._delivery_iterations > max_iterations:
        logger.warning("anyio cancel delivery exceeded %d iterations, forcing termination", max_iterations)
        # Clear the cancel handle to break the loop
        if hasattr(self, "_cancel_handle") and self._cancel_handle is not None:
            self._cancel_handle = None
        return False

    return original_deliver_cancellation(self, origin)
```

### Warnings

!!! warning "Experimental Feature"
    This patch modifies internal anyio behavior and may:

    - Leave some tasks uncancelled (usually harmless, cleaned up by worker recycling)
    - Be removed when anyio or MCP SDK fix the upstream issue
    - Have unknown interactions with future anyio versions

### Recommended Settings

```bash
# Disabled by default (use Layers 1-2 first)
ANYIO_CANCEL_DELIVERY_PATCH_ENABLED=false

# If needed, start conservative
ANYIO_CANCEL_DELIVERY_PATCH_ENABLED=true
ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS=100

# More aggressive (faster termination, more orphaned tasks)
ANYIO_CANCEL_DELIVERY_PATCH_ENABLED=true
ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS=50
```

---

## Layer 4: Worker Recycling

Gunicorn worker recycling provides a safety net for any orphaned tasks.

### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GUNICORN_MAX_REQUESTS` | `5000` | Recycle workers after this many requests. |
| `GUNICORN_MAX_REQUESTS_JITTER` | `500` | Random jitter to prevent thundering herd. |

### Recommended Settings

```bash
# Production (regular recycling)
GUNICORN_MAX_REQUESTS=5000
GUNICORN_MAX_REQUESTS_JITTER=500

# High-traffic (more frequent recycling)
GUNICORN_MAX_REQUESTS=2000
GUNICORN_MAX_REQUESTS_JITTER=200
```

---

## Complete Configuration Examples

### Balanced (Recommended for Production)

```bash
# Layer 1: SSE Protection
SSE_SEND_TIMEOUT=30.0
SSE_RAPID_YIELD_WINDOW_MS=1000
SSE_RAPID_YIELD_MAX=50

# Layer 2: Cleanup Timeouts
MCP_SESSION_POOL_CLEANUP_TIMEOUT=5.0
SSE_TASK_GROUP_CLEANUP_TIMEOUT=5.0

# Layer 3: Disabled (use only if needed)
ANYIO_CANCEL_DELIVERY_PATCH_ENABLED=false

# Layer 4: Worker Recycling
GUNICORN_MAX_REQUESTS=5000
GUNICORN_MAX_REQUESTS_JITTER=500
```

### Aggressive (For Known Spin Loop Issues)

```bash
# Layer 1: Faster detection
SSE_SEND_TIMEOUT=10.0
SSE_RAPID_YIELD_WINDOW_MS=500
SSE_RAPID_YIELD_MAX=25

# Layer 2: Short timeouts
MCP_SESSION_POOL_CLEANUP_TIMEOUT=0.5
SSE_TASK_GROUP_CLEANUP_TIMEOUT=0.5

# Layer 3: Enabled
ANYIO_CANCEL_DELIVERY_PATCH_ENABLED=true
ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS=50

# Layer 4: Frequent recycling
GUNICORN_MAX_REQUESTS=2000
GUNICORN_MAX_REQUESTS_JITTER=200
```

### Conservative (For Slow Networks/Servers)

```bash
# Layer 1: Generous timeouts
SSE_SEND_TIMEOUT=60.0
SSE_RAPID_YIELD_WINDOW_MS=2000
SSE_RAPID_YIELD_MAX=100

# Layer 2: Allow time for cleanup
MCP_SESSION_POOL_CLEANUP_TIMEOUT=10.0
SSE_TASK_GROUP_CLEANUP_TIMEOUT=10.0

# Layer 3: Disabled
ANYIO_CANCEL_DELIVERY_PATCH_ENABLED=false

# Layer 4: Standard recycling
GUNICORN_MAX_REQUESTS=5000
GUNICORN_MAX_REQUESTS_JITTER=500
```

---

## Diagnosing Spin Loops

### Using py-spy

```bash
# Attach to spinning worker
py-spy top --pid <worker_pid>

# Look for high CPU in:
# - anyio/_backends/_asyncio.py:569-580 (_deliver_cancellation)
# - anyio/_backends/_asyncio.py:CancelScope._deliver_cancellation
```

### Using strace

```bash
# Attach to spinning worker
strace -p <worker_pid> -e epoll_wait

# Spin loop signature: rapid epoll_wait with 0ms timeout
# epoll_wait(5, [], 1024, 0) = 0
# epoll_wait(5, [], 1024, 0) = 0
# epoll_wait(5, [], 1024, 0) = 0
```

### Using top/htop

```bash
# Look for workers at 90-100% CPU with no active requests
top -p $(pgrep -d, -f "gunicorn.*mcpgateway")
```

---

## Files Changed

The following files were modified to implement this mitigation:

### Core Implementation

| File | Changes |
|------|---------|
| `mcpgateway/config.py` | Added configuration variables for all layers |
| `mcpgateway/transports/sse_transport.py` | Added anyio monkey-patch (Layer 3) |
| `mcpgateway/services/mcp_session_pool.py` | Added cleanup timeout (Layer 2) |
| `mcpgateway/translate.py` | Added cleanup timeout for streamable HTTP |

### Configuration Files

| File | Changes |
|------|---------|
| `.env.example` | Documented all mitigation variables |
| `docker-compose.yml` | Added mitigation section with all variables |
| `charts/mcp-stack/values.yaml` | Added mitigation section with all variables |
| `README.md` | Added "CPU Spin Loop Mitigation" section |

---

## Related Pull Requests

- **PR #XXXX**: Initial cleanup timeout implementation
- **PR #XXXX**: Added SSE rapid yield detection
- **PR #XXXX**: Added optional anyio monkey-patch
- **PR #XXXX**: Consolidated documentation

---

## Future Work

1. **Upstream Fix**: Monitor [anyio#695](https://github.com/agronholm/anyio/issues/695) for resolution
2. **MCP SDK**: Consider contributing fix to MCP SDK for proper task cancellation handling
3. **Remove Workarounds**: Once upstream is fixed, remove Layer 3 monkey-patch

---

## References

- [GitHub Issue #2360](https://github.com/IBM/mcp-context-forge/issues/2360) - Original bug report
- [anyio Issue #695](https://github.com/agronholm/anyio/issues/695) - Upstream issue
- [anyio CancelScope source](https://github.com/agronholm/anyio/blob/master/src/anyio/_backends/_asyncio.py) - Where the spin occurs
