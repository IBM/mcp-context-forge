# ADR-052: GET /mcp Stream and Server-Initiated Request Correlation

- *Status:* Proposed
- *Date:* 2026-04-19
- *Deciders:* Platform Team
- *Related:* [ADR-038: Multi-Worker Session Affinity](038-multi-worker-session-affinity.md), [ADR-043: Rust MCP Runtime Sidecar](043-rust-mcp-runtime-sidecar-mode-model.md), [Issue #4205: GET /mcp 405 fallback](https://github.com/IBM/mcp-context-forge/issues/4205), [Issue #4299: Per-session upstream isolation](https://github.com/IBM/mcp-context-forge/issues/4299), [MCP spec — Listening for messages from the server](https://modelcontextprotocol.io/specification/draft/basic/transports#listening-for-messages-from-the-server)

## Context

The MCP Streamable HTTP spec defines a server-to-client stream: the client opens `GET /mcp` with `Accept: text/event-stream`, optionally carrying `Last-Event-Id`, and the server returns an SSE stream that delivers server-initiated JSON-RPC messages — notifications (logging, progress, list-changed) and *requests* the server makes of the client (sampling/createMessage, elicitation/create, roots/list).

**What we have today (post-#4205, #4299).** Both the Python gateway (`streamablehttp_transport.py:3004-3031`) and the Rust runtime (`crates/mcp_runtime/src/lib.rs:4654-4706`) return `405 Method Not Allowed` on `GET /mcp` whenever stateful sessions are disabled OR no `Mcp-Session-Id` header is present. The 405 was correct under #4205 because there was no infrastructure to deliver server-initiated messages to a downstream listener — the per-session message handler in `services/notification_service.py:369-431` consumes upstream notifications only to trigger internal list-refresh, and `routers/reverse_proxy.py:532` carries an explicit `# TODO: Implement message queue for SSE delivery`.

**Why we need it back.** Restoring the GET stream is a prerequisite for several upcoming features that all depend on server-to-client delivery: structured logging visible to the client, progress notifications, sampling/elicitation passthrough (extending the work in [ADR-022](022-elicitation-passthrough.md) to streamable HTTP), and list-changed notifications that today are absorbed into refresh logic instead of forwarded.

**The multi-node problem.** The downstream client opens GET on whatever node the load balancer picks (call it node A). The upstream MCP session lives on the worker that owns it via the affinity machinery (ADR-038) — call it node B. Notifications from upstream arrive at node B, but the client is listening on node A. We need cross-node delivery without forcing the GET to land on the affinity owner.

## Decision

The GET stream is **node-agnostic**: any node accepts the GET, validates the session, and tails a Redis-backed per-session event channel. The affinity invariant from ADR-038 still pins POST/DELETE to one worker (because the upstream `ClientSession` lives in that worker's memory), but GET deliberately does not participate in affinity.

Three concrete pieces:

### 1. Server event bus — Pub/Sub + event store

A new module `mcpgateway/transports/server_event_bus.py` exposes a small `ServerEventBus` interface:

- `publish(session_id, message) -> str` — appends to a per-session ring buffer; returns the new event ID. Then signals listeners.
- `subscribe(session_id, *, last_event_id) -> AsyncIterator[Event]` — replays from the buffer starting after `last_event_id` (or current head if absent), then tails new events. Yields `(event_id, message)` tuples shaped for SSE framing.

Two implementations behind the same interface, selected by `cache_type`:

- **`RedisServerEventBus`** (`cache_type == "redis"`) — `publish` writes to the existing `RedisEventStore` (Lua-atomic per-session ring buffer) and `PUBLISH`es on `mcp:session:{session_id}:events`. `subscribe` replays from the store, then `SUBSCRIBE`s the channel and tails. Pub/Sub provides the wake-up signal; the event store is the durable source of truth for ordering and replay. Standard Postgres `LISTEN/NOTIFY` + table pattern.
- **`InMemoryServerEventBus`** (default — `cache_type` ∈ `{memory, none, database}`) — `publish` appends to a process-local `dict[session_id, deque]` (same ring-buffer semantics as the Redis store) and notifies waiting subscribers via `asyncio.Event`. `subscribe` replays the deque, then awaits new events. Identical observable behavior for a single-process gateway.

The factory in `server_event_bus.py` reads `settings.cache_type` once at startup and binds the singleton. Same-shape interface means call sites — `notification_service.py`, the GET handler, the request-correlation sweeper — never branch on backend.

### 2. Single-listener claim — new `SessionAffinity` methods

The MCP spec mandates one GET stream per session ("If the client has opened a single SSE stream … the server SHOULD NOT open a new SSE stream"). The claim API:

- `SessionAffinity.claim_listener(session_id, connection_id) -> bool` — atomic claim. Returns `True` on success, `False` if a live listener already exists.
- `SessionAffinity.heartbeat_listener(session_id, connection_id)` — refreshes the claim while the GET handler holds the connection.
- `SessionAffinity.release_listener(session_id, connection_id)` — releases on disconnect, conditional on `connection_id` match (don't release someone else's claim).

Two backends behind the same API, parallel to the event bus:

- **Multi-node** (`cache_type == "redis"`) — `SET NX EX` on `mcp:session:{session_id}:listener` with value `{node_id, connection_id, ts}`. Same Redis primitive `register_session_mapping()` already uses for worker ownership.
- **Single-node** — process-local `dict[session_id, ClaimEntry]` guarded by an `asyncio.Lock`. Same atomicity guarantee within the process; no cross-process coordination needed because there is only one process.

A second GET on the same session sees the claim and returns `409 Conflict` with `Retry-After`.

### 3. Server-initiated request correlation — worker-local

When the upstream `ClientSession` produces a `RequestResponder` (sampling/elicitation/roots-list), the per-session message handler in `notification_service.py`:

1. Builds a JSON-RPC envelope keyed by the responder's `request_id`.
2. Registers `(session_id, request_id) -> asyncio.Future` in a worker-local `dict` under lock.
3. Spawns a **holder task** that owns the `RequestResponder` as a context manager and `await`s the future under `asyncio.wait_for(..., timeout=_pending_request_ttl_seconds)`.
4. Publishes the envelope on the event bus.

When the downstream client POSTs the JSON-RPC response on `/mcp` (still affinity-routed to the worker holding the upstream session — that's the whole point of ADR-038 for POST), the POST handler intercepts: if the body is a JSON-RPC response whose ID matches a local pending entry, `complete_request` resolves the future and the holder task calls `responder.respond(...)`. Timeout handling is per-task via `wait_for` — **there is no background sweeper scanning the dict**; each holder cleans its own entry in its `finally` block.

**This is intentionally worker-local state.** The pending `RequestResponder` future *is* a worker-local object — it can't be resolved on any other node, so there is nothing to gain by putting the dispatch table in Redis. Affinity routing of the POST already gets us to the right worker.

## Why we skip affinity for GET

Affinity exists because the upstream `ClientSession` lives in one worker's memory. POSTs that need to invoke that session must reach that worker. GET is different: the GET handler doesn't touch the upstream session — it only reads from the event bus. Pub/Sub fanout means every node already sees every event for every session it's listening for. Routing GET through affinity would add a hop with no benefit and would force a single node to fan out streams it has no other reason to serve.

The single-listener claim is what enforces uniqueness, not affinity. Where the listener happens to land is irrelevant.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       GET /mcp DATA FLOW                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Client (Last-Event-Id: e42)                                           │
│        │                                                                │
│        ▼                                                                │
│   ┌─────────┐                                ┌──────────────────────┐   │
│   │ NODE A  │  GET /mcp                      │  NODE B (affinity    │   │
│   │ (any)   │  ─────────────────────────►    │  owner of session)   │   │
│   │         │                                │                      │   │
│   │ claim_  │   SET NX                       │  upstream            │   │
│   │ listener├──────────────►┌────────┐       │  ClientSession       │   │
│   │         │               │ Redis  │       │       │              │   │
│   │ subscribe (sid)         │        │  ◄────┤  notification        │   │
│   │  │  ┌────────────────── │ EventStore     │  arrives             │   │
│   │  │  │ replay e43..      │ (ring) │       │       │              │   │
│   │  │  │                   │        │       │       ▼              │   │
│   │  │  │  PUB e44 ◄────────┤Pub/Sub │ ◄──── │  publish(sid, msg)   │   │
│   │  ▼  ▼                   └────────┘       │                      │   │
│   │ SSE stream ──────────► client            │                      │   │
│   └─────────┘                                └──────────────────────┘   │
│                                                                         │
│   Server-initiated request (sampling): same path, plus correlation      │
│        ┌────────────────────────────────────────────────────────────┐   │
│        │ NODE B stores (sid, req_id) → RequestResponder locally     │   │
│        │ Client POSTs response → affinity routes to NODE B → match  │   │
│        │ → resolve RequestResponder                                 │   │
│        └────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Configuration

Two new settings in `mcpgateway/config.py`:

- `mcp_get_stream_enabled: bool = True` — master switch; when `False`, retains the current 405 behavior. Default on.
- `mcp_get_stream_listener_ttl_seconds: int = 30` — TTL for the listener claim; refreshed by heartbeat.

The `cache_type` setting (existing) implicitly chooses single-node vs. multi-node mode for both the event bus and the listener claim — no separate flag.

Existing prerequisite still applies: `use_stateful_sessions=True` is required.

## Single-node vs. multi-node — fallback contract

The gateway must run correctly with no Redis. The two backends are functionally equivalent for a single process; what they cost is cross-process delivery, which is meaningless in a single-process deployment.

| Concern | `cache_type == "redis"` (multi-node) | otherwise (single-node) |
|---|---|---|
| Event bus | `RedisEventStore` + Pub/Sub | In-memory deque + `asyncio.Event` |
| Listener claim | Redis `SET NX EX` | In-process dict + `asyncio.Lock` |
| Replay (`Last-Event-Id`) | From Redis ring buffer | From in-memory deque |
| Pending request correlation | Worker-local dict (same in both modes) | Same |

**Backend selection is at startup**, not per call. The factory reads `cache_type` once and caches the singleton. Switching `cache_type` requires a restart — same as every other Redis-dependent feature in the codebase.

**Failure mode in multi-node.** If `cache_type == "redis"` is configured but Redis is unreachable when a GET arrives, we close the stream with `503 Service Unavailable` so the client reconnects. We deliberately do NOT silently fall back to in-memory: that would silently lose cross-node delivery and produce sessions that work on whichever node happens to hold both the upstream and the listener — a partition we'd rather surface as an error.

**Failure mode in single-node.** No remote dependency to fail. The deque grows bounded by the same `max_events_per_stream` setting that bounds the Redis ring buffer, so memory is bounded.

**Multi-worker single-node (gunicorn -w 4 with `cache_type=memory`)** is not a supported configuration for the GET stream — the in-memory bus is per-process. Operators running multiple workers should set `cache_type=redis`. The 405 behavior remains as a documented fallback if `mcp_get_stream_enabled=False`.

## Consequences

### Positive

- **Restores spec-conformant server-to-client streaming.** Notifications, progress, sampling, elicitation, roots-list all flow.
- **Unblocks downstream features** that depend on server-initiated messages (visible logging, progress, elicitation passthrough on streamable HTTP).
- **No new infrastructure.** Reuses `RedisEventStore` (already there for resume) and the Redis `SET NX` claim pattern (already there for affinity).
- **Cleaner load distribution.** GET streams can land on any node; we are not pinning long-lived connections to the affinity owner.
- **Worker-local request correlation is the simplest model that works.** No distributed dispatch table; affinity already routes the response to the right worker.

### Negative

- **`SessionAffinity` accumulates a second responsibility.** It now manages both worker ownership (where requests route) and listener claims (which connection holds the GET stream). These are conceptually distinct and the module name is starting to over-fit. We accept this debt for v1 (see "Naming debt" below) rather than churn the module surface in the same change that adds the feature.
- **Pub/Sub fanout has at-least-once semantics under network partition.** Subscribers may briefly miss messages; the event store + `Last-Event-Id` resume covers this when the client reconnects, but a client that holds a single connection through a Redis blip may see a gap. Acceptable for v1 — the spec assumes reconnection-with-resume as the recovery model.
- **Single-listener claim adds one Redis round trip per GET.** Negligible for the workload, but worth naming.

### Neutral

- **Affinity invariant from ADR-038 narrows in scope.** Still applies to POST/DELETE; explicitly does not apply to GET. ADR-038 should get a one-paragraph cross-reference to this ADR.
- **`reverse_proxy.py:532` TODO is resolved by the same event bus** if reverse-proxy SSE wants to participate; out of scope for this change.

## Naming debt

`SessionAffinity` (`mcpgateway/services/session_affinity.py`) was named when its sole job was "pin a session to a worker." With this ADR it gains the listener-claim methods, which are not affinity at all — they are presence/uniqueness state that any node consults. A future PR should split:

- `SessionAffinity` → keeps `register_session_mapping`, `forward_request_to_owner`, worker heartbeat, RPC listener.
- `SessionPresence` (new) → owns `claim_listener`, `heartbeat_listener`, `release_listener`, plus any future "is this session live anywhere?" queries.

Both would share the same Redis namespace conventions and TTL settings. For this ADR we add the methods to `SessionAffinity` and document the debt; the split is a name-only refactor that is safer to do separately.

## Single-listener invariant — declaration

The MCP spec requires that a server SHOULD NOT open a second SSE stream for the same session. Until now, no code in this repo asserted this — the 405 guard only checked for session-ID *presence*, not for an existing live stream. This ADR introduces the invariant and locates its enforcement in `SessionAffinity.claim_listener`. Cite this section when adding tests or downstream features that depend on the one-listener guarantee.

## Session ownership on GET

The GET stream gates on session ownership the same way POST and DELETE do: `_validate_streamable_session_access()` runs before the SSE response opens. Treating the `Mcp-Session-Id` header as a bearer (i.e. "anyone who knows it can subscribe") is **not** the model — that would let any authenticated caller attach to another user's server-initiated traffic (notifications, sampling/elicitation requests, progress, logs) and would also let an attacker who claims the single-listener slot first pin the rightful owner out of the session until TTL expiry.

Concrete rules:

- The session id must belong to the authenticated caller, or the caller must be a platform admin. Mirrors the POST gate (`mcpgateway/transports/streamablehttp_transport.py:_validate_streamable_session_access`).
- Unknown / made-up session ids return `404`, not `200 SSE`.
- Non-owner access returns `403`, recorded under the `session_denied` outcome of `transport_get_rejected_total`.
- Per-server OAuth enforcement (`oauth_enabled`) runs in the auth middleware before the GET branch is reached, so an unauthenticated GET to an oauth-required server still gets the spec-conformant `401` with `WWW-Authenticate: Bearer resource_metadata=...`.

Tests in `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py`:

- `test_handle_streamable_http_get_denies_non_owner_session` — wrong-owner deny path.
- `test_handle_streamable_http_get_denies_unknown_session` — unknown-id 404 path.
- `test_streamable_http_auth_rejects_unauthenticated_oauth_server_on_get` — middleware 401.
- `test_streamable_http_auth_allows_authenticated_oauth_server_on_get` — symmetric authenticated path.

## Migration and rollout

- **Default on.** `mcp_get_stream_enabled=True` ships in the same release as the implementation. Operators can revert to 405 behavior with a single env var if a regression appears.
- **Tests.** The current happy-path 405 tests in `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py:6490+` are converted to assert SSE is returned for valid sessions; the negative cases (stateless mode, missing/invalid session ID) keep their 405 assertions. New tests cover `Last-Event-Id` resume, multi-worker fanout against a mock Redis, and the 409 response on second listener.
- **Compliance harness.** Connect → notification fanout → `Last-Event-Id` resume exercised end-to-end by the protocol-compliance matrix in docker-compose; a dedicated transport-core test for the GET stream can be added later when a stable harness anchor exists (not required for this ADR to ship).
- **Rust runtime.** The `session_id.is_none()` 405 branch in
  `crates/mcp_runtime/src/lib.rs` (`forward_transport_request`) **stays** —
  it's spec-mandated (GET requires a session id) and applies in both
  Python-served and Rust-relayed configurations. What changed for ADR-052
  is that the GET-with-session path now relays a real SSE stream end to
  end (Python's GET handler returns events instead of 405). The Rust
  relay code itself needed no behavior change — comments around the 405
  branch were updated to point at ADR-052, and `crates/mcp_runtime/DEVELOPING.md`
  § "GET /mcp Stream Relay" documents the unchanged data flow for relay-mode
  developers.

## Trying it out

See [GET /mcp Stream Quickstart](../get-stream-quickstart.md) for hands-on
verification across three deployment tiers — bare `make dev`, single-replica
compose, and `make testing-up` (3-replica multi-node with Redis).

## References

- Implementation:
  - `mcpgateway/transports/server_event_bus.py` (new)
  - `mcpgateway/transports/streamablehttp_transport.py` (replace 405 branch)
  - `mcpgateway/services/session_affinity.py` (add listener-claim methods)
  - `mcpgateway/services/notification_service.py` (publish to event bus, request correlation)
  - `mcpgateway/config.py` (`mcp_get_stream_enabled`)
  - `crates/mcp_runtime/src/lib.rs` (drop 405 branch in live-stream path)
- Tests:
  - `tests/unit/mcpgateway/transports/test_streamablehttp_transport.py`
  - `tests/unit/mcpgateway/services/test_session_affinity.py`
  - `tests/unit/mcpgateway/transports/test_server_event_bus.py` (new)
  - `tests/unit/mcpgateway/transports/test_redis_event_store.py` (cross-stream, evicted-cursor, no-cursor replay)
  - `tests/unit/mcpgateway/services/test_notification_service.py` (request correlation, id-collision, publish-failure telemetry, shutdown timeout)
- Spec: [Streamable HTTP — Listening for messages from the server](https://modelcontextprotocol.io/specification/draft/basic/transports#listening-for-messages-from-the-server)
- Prior ADRs: [ADR-022](022-elicitation-passthrough.md), [ADR-038](038-multi-worker-session-affinity.md), [ADR-043](043-rust-mcp-runtime-sidecar-mode-model.md)
