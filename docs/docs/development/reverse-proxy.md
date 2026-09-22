# Reverse Proxy Service (Developer Guide)

This page is for developers working on the gateway-side reverse-proxy service. It covers how the service is put together and where the tests live.

For client usage and deployment, see the [MCP Reverse Proxy user guide](../using/reverse-proxy.md).

---

## What the service is

The reverse-proxy service lets an external, separately maintained client ([contextforge-org/mcp-reverse-proxy](https://github.com/contextforge-org/mcp-reverse-proxy)) connect a downstream MCP server to the gateway without inbound network access. The client dials out over an authenticated WebSocket to `mcpgateway/routers/reverse_proxy.py`, registers its downstream server, and the gateway persists that registration as an internal `PROXIED` gateway with a stable identity derived from owner, scope, and the normalized server name.

Key pieces:

- **Typed wire protocol** (`mcpgateway/services/reverse_proxy_protocol.py`): the message contract between client and gateway. Registration, invocation, heartbeat, and teardown frames are validated against this protocol.
- **Session manager** (`mcpgateway/services/reverse_proxy_sessions.py`): process-local and the sole authority for session routing. It owns the mapping from session to client WebSocket inside one worker.
- **PROXIED dispatch**: `tools/call`, `resources/read`, and `prompts/get` against a reverse-proxied server are dispatched over the owning WebSocket rather than an outbound HTTP connection. Stored downstream credentials are decrypted at dispatch time and forwarded to the downstream server; they are never logged.
- **Heartbeat freshness and reaper**: client heartbeats keep a session fresh. A reaper evicts sessions that go silent past `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT`, which drives the reachability state of the catalog gateway.
- **Distributed relay** (`mcpgateway/services/reverse_proxy_relay*.py`): optional Redis-backed relay for multi-worker deployments. When `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED=true`, a call landing on a non-owner worker is routed to the worker that owns the client WebSocket. Redis holds short-lived owner generations, worker heartbeats, and signed request/response envelopes; the WebSocket itself stays local to its owner worker.

Both `MCPGATEWAY_REVERSE_PROXY_ENABLED` and `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED` default to off. The distributed flag is strict in both directions: with it off, `get_reverse_proxy_relay()` in `mcpgateway/services/reverse_proxy_relay_runtime.py` returns the local-only wrapper and no Redis client is created; with it on, the factory fails fast when the canonical Redis connection is unavailable, so a misconfigured worker never starts half-distributed.

### Security posture

- **Two layers, always.** Layer 1 is token scoping, driven by the exact `_PERMISSION_PATTERNS` mappings on the reverse-proxy routes. Layer 2 is RBAC. Neither substitutes for the other.
- **Fail-closed dispatch.** If ownership is not authoritative (for example, the client disconnected, was evicted, or Redis is unavailable in distributed mode), dispatch fails closed instead of guessing.
- **Server-owned identity.** The `PROXIED` gateway identity (owner, scope, normalized name) is derived server-side and cannot be overridden by the client.

---

## Distributed routing and the Redis lease

The distributed relay is split across three modules:

- `mcpgateway/services/reverse_proxy_relay.py`: the relay state machine. Its `_RedisLease` helper parameterizes the registration and owner leases over key, holder value, and TTL; acquire, refresh, promote, and release are generation-fenced Lua scripts, so a stale generation can never overwrite or delete a newer owner.
- `mcpgateway/services/reverse_proxy_relay_runtime.py`: `reverse_proxy_relay_lifespan()` supervises the signed-envelope listener and the worker-heartbeat refresh with readiness and deterministic cleanup. Worker identity is regenerated after a process fork.
- `mcpgateway/services/reverse_proxy_lifecycle.py`: the lease seams. Registration claims, maintains, and promotes the registration lease around the catalog commits; teardown and registration compensation release exact owner generations best-effort through fenced compare-delete, so a Redis cleanup failure never strands routing state.
- `mcpgateway/services/reverse_proxy_relay_io.py` and `reverse_proxy_relay_models.py`: the signed HMAC envelopes and the typed Redis models behind them.

One registration walks the lease lifecycle in order: `claim_registration` (single-writer claim) → a `maintain_registration` heartbeat task → `heartbeat_registration` as the commit gate → `promote_registration` (only the claim holder can promote to owner) → `release_registration`. Eviction on a dead worker reclaims the owner generation by compare-delete only after the worker heartbeat is confirmed absent, and an unreachable-write guard keeps eviction persistence from racing a live owner or an in-flight replacement registration.

---

## Unit test surface

The reverse-proxy code is covered by focused unit tests:

| Path | Covers |
| ---- | ------ |
| `tests/unit/mcpgateway/routers/test_reverse_proxy.py` | WebSocket endpoint admission and lifecycle |
| `tests/unit/mcpgateway/services/test_reverse_proxy_*.py` | Protocol, sessions, catalog, discovery, and relay services (`test_reverse_proxy_relay.py` pins the Redis lease fencing, owner claims, and signed-envelope relay) |
| `tests/unit/mcpgateway/services/test_{tool,resource,prompt}_service_reverse_proxy.py` | PROXIED dispatch from the tool, resource, and prompt services |
| `tests/unit/mcpgateway/middleware/test_token_scoping.py` | Layer-1 token scoping on the reverse-proxy routes |

The distributed lifecycle also has deterministic race and compensation regression tests, so ordering-sensitive bugs (concurrent registration, relay failover, dead-owner reclaim, eviction) are pinned without needing live infrastructure.

---

## Related documentation

- [MCP Reverse Proxy user guide](../using/reverse-proxy.md) - client usage, deployment, and gateway-side configuration
- [Testing ContextForge](../testing/index.md) - the wider testing strategy
