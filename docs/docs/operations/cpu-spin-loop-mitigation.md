# CPU Spin Loop Mitigation Guide

This guide documents the CPU spin loop issue affecting ContextForge and the multi-layered mitigation strategy implemented to address it.

## Overview

**Issue**: [#2360](https://github.com/IBM/mcp-context-forge/issues/2360) - Gunicorn workers consume 100% CPU after load tests
**Root Cause**: [anyio#695](https://github.com/agronholm/anyio/issues/695) - `_deliver_cancellation` infinite loop
**Affected Versions**: All versions using anyio with MCP SDK
**Status**: Upstream fix shipped in anyio 4.15.0 (pinned as `anyio>=4.15.0`); residual mitigations retained for defense in depth

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

The upstream root cause was fixed in anyio 4.15.0 (anyio#1111), and this project pins `anyio>=4.15.0`. We retain a **defense-in-depth** pair of layers:

```
┌─────────────────────────────────────────────────────────────┐
│                    Layer 1: Prevention                       │
│         Detect and close dead connections early              │
│   SSE_SEND_TIMEOUT, SSE_RAPID_YIELD_WINDOW_MS/MAX           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Layer 2: Recovery                         │
│         Worker recycling cleans up orphaned tasks            │
│   GUNICORN_MAX_REQUESTS, GUNICORN_MAX_REQUESTS_JITTER       │
└─────────────────────────────────────────────────────────────┘
```

> **Removed (anyio ≥ 4.15.0):** the containment layer — the SSE task-group cancel
> deadline (`SSE_TASK_GROUP_CLEANUP_TIMEOUT`), the session-pool cleanup timeout
> (`MCP_SESSION_POOL_CLEANUP_TIMEOUT`), and the experimental anyio monkey-patch
> (`ANYIO_CANCEL_DELIVERY_*`). Cleanup waits remain bounded internally (fixed
> 5-second windows).

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

## Bounded Cleanup (built in)

Connection cleanup no longer waits indefinitely for stuck tasks: the session-pool
and streamable-HTTP shutdown paths wrap `__aexit__()` in a fixed 5-second
`anyio.move_on_after` window and log a warning if it expires. This is not
operator-tunable — the former `MCP_SESSION_POOL_CLEANUP_TIMEOUT` and
`SSE_TASK_GROUP_CLEANUP_TIMEOUT` knobs were removed (no deployment tuned them in
practice, and the upstream anyio fix removed the need).

---

## Layer 2: Worker Recycling

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

# Layer 2: Worker Recycling
GUNICORN_MAX_REQUESTS=5000
GUNICORN_MAX_REQUESTS_JITTER=500
```

### Aggressive (For Known Spin Loop Issues)

```bash
# Layer 1: Faster detection
SSE_SEND_TIMEOUT=10.0
SSE_RAPID_YIELD_WINDOW_MS=500
SSE_RAPID_YIELD_MAX=25

# Layer 2: Frequent recycling
GUNICORN_MAX_REQUESTS=2000
GUNICORN_MAX_REQUESTS_JITTER=200
```

### Conservative (For Slow Networks/Servers)

```bash
# Layer 1: Generous timeouts
SSE_SEND_TIMEOUT=60.0
SSE_RAPID_YIELD_WINDOW_MS=2000
SSE_RAPID_YIELD_MAX=100

# Layer 2: Standard recycling
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
| `mcpgateway/config.py` | SSE connection protection settings (Layer 1) |
| `mcpgateway/transports/sse_transport.py` | SSE connection protection (send timeout, rapid-yield detection) |
| `mcpgateway/services/mcp_session_pool.py` | Bounded session-pool cleanup (fixed 5s window) |
| `mcpgateway/translate.py` | Bounded streamable-HTTP cleanup (fixed 5s window) |

### Configuration Files

| File | Changes |
|------|---------|
| `.env.example` | Documented the SSE protection variables |
| `docker-compose.yml` | Added the mitigation section (SSE protection) |
| `charts/mcp-stack/values.yaml` | Added the mitigation section (SSE protection) |

---

## Related Pull Requests

- **PR #XXXX**: Initial cleanup timeout implementation
- **PR #XXXX**: Added SSE rapid yield detection
- **PR #XXXX**: Consolidated documentation
- **PR #5427**: Removed the anyio monkey-patch and the SSE cancel-deadline override after the upstream anyio 4.15.0 fix

---

## Future Work

1. **Upstream Fix**: Shipped — anyio 4.15.0 fixes the `_deliver_cancellation` spin (anyio#1111). This project pins `anyio>=4.15.0`; the containment workarounds were removed in #5427
2. **MCP SDK**: Consider contributing fix to MCP SDK for proper task cancellation handling

---

## References

- [GitHub Issue #2360](https://github.com/IBM/mcp-context-forge/issues/2360) - Original bug report
- [anyio Issue #695](https://github.com/agronholm/anyio/issues/695) - Upstream issue
- [anyio CancelScope source](https://github.com/agronholm/anyio/blob/master/src/anyio/_backends/_asyncio.py) - Where the spin occurs
