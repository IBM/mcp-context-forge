# Session Pooling & Stateful Sessions in MCP Gateway

## Overview

MCP Gateway supports **session pooling** and **stateful session reuse** for SSE and WebSocket transports. This feature dramatically improves performance and enables stateful workflows by reusing a single MCP session across multiple tool calls for the same user and server.

---

## Why Session Pooling?

- **Performance**: Reduces network round-trips and memory usage by reusing sessions.
- **State Continuity**: Maintains conversational or tool state across calls.
- **Resource Efficiency**: Fewer open connections and lower backend load.
- **Protocol Compliance**: Aligns with MCP spec expectations for stateful sessions.

---

## How It Works

- When enabled, the gateway will reuse a session for the same `(user, server)` pair across requests.
- Sessions are pooled and tracked with idle timeouts and per-user limits.
- Pooling can be enabled globally or per-server.
- Idle sessions are evicted automatically.
- Auth context and user isolation are always enforced.

---

## Configuration

Add these to your `.env` or config:

```env
SESSION_POOLING_ENABLED=true
SESSION_POOLING_SERVERS=server1,server2  # (optional, comma-separated)
SESSION_POOL_MAX_IDLE=600                # (seconds, default 600)
SESSION_POOL_USER_LIMIT=10               # (default 10)
```

---

## Observability

- Pool hit/miss/evict metrics are tracked and can be exposed for monitoring.
- Idle session cleanup runs automatically.

---

## Compatibility & Recommendations

- **Redis backend** (`CACHE_TYPE=redis`): Best for multi-worker deployments.
- **Database backend**: Works, but may increase DB load.
- **Memory backend**: Only for single-process/dev.

---

## Example: Enabling Session Pooling

1. Set `SESSION_POOLING_ENABLED=true` in your `.env`.
2. (Optional) List specific servers in `SESSION_POOLING_SERVERS`.
3. Restart the gateway.

---

## Backward Compatibility

- With pooling disabled, the gateway behaves as before (per-request sessions).
- All isolation and security boundaries are preserved.

---

## See Also
- [Features](features.md)
- [Quick Start](quick_start.md)
- [FAQ](../faq/index.md)
