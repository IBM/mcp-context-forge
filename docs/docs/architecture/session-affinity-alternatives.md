# Session-Affinity — Candidate Solutions for #4557

[Issue #4557](https://github.com/IBM/mcp-context-forge/issues/4557) reports a severe multi-worker session-affinity regression: throughput on the 3 × 24 reference stack collapses from ~180 RPS down to ~9 RPS, with `tools/call` p99 pinned at the 30-second forward timeout. The [#4674](https://github.com/IBM/mcp-context-forge/pull/4674) reproducer hinted at an amplification — a single user issuing 1 request per second drove the per-user rate-limiter counter up by ~24× the expected rate, suggesting each request was being processed by ~24 workers instead of one.

This doc lays out the candidate solutions, walks through where each one shines and breaks down, and recommends a starting point with a path for further improvement.

---

## The Core Problem

A stateful MCP request carrying `Mcp-Session-Id` can land on any of N workers, but only one worker holds the live upstream session — the `UpstreamSessionRegistry` entry contains a live `ClientSession` with an open connection, which is not serializable and not movable. When the request lands on the wrong worker, the architecture has exactly three structural choices:

1. **Route correctly upstream**, so the request always lands on the right worker.
2. **Externalize session ownership**, so any worker can serve any session.
3. **Forward across workers**, accepting that the wrong worker may receive the request and pass it along.

The three approaches below walk through each option in turn.

### What any candidate solution must preserve

- The **#4205 upstream-session isolation invariant**: one upstream session per downstream session, no cross-session state leakage.
- Multi-worker / multi-container deployment shape (`SO_REUSEPORT`, gunicorn `--preload`, nginx fronting multiple replicas).
- All authentication shapes that `streamable_http_auth()` validates: ContextForge JWT, virtual-server OAuth verifier (RFC 9728), and `MCP_REQUIRE_AUTH=false` public-only mode.
- Existing observability: structured logs, OTEL spans, the `mcpgw:*` Redis state surface that operators read.
- Graceful behaviour on worker failure (no cluster-wide outage when one worker dies).

---

## Approach 1 — Sticky Load Balancing on `Mcp-Session-Id`

Stop forwarding at the application layer. Route correctly at the LB layer.

```
   Client      Mcp-Session-Id: sess-abc
     │
     ▼
   nginx     hash $http_mcp_session_id consistent;   ◄── Layer-1: pin to container
     │
     ▼
   Container N  (deterministic from session id)
     │
     ▼
   Worker M     ◄── Layer-2: need intra-container stickiness too
     │             (disable SO_REUSEPORT, OR run 1 worker per container)
     ▼
   /rpc executes — session is always here, no forward needed, no Redis pub/sub
```

**Pros**
- Removes the entire forward path. No pub/sub. No `WORKER_ID`. No `post_fork` hook.
- Lower steady-state latency — no Redis round-trip on the hot path.
- The simplest possible architecture once it's wired up.
- Easier to reason about: "session X lives on worker Y, always."

**Cons**
- **Two layers of stickiness** required. nginx handles Layer-1 easily (`hash ... consistent;`). Layer-2 (intra-container, between gunicorn workers sharing the socket via `SO_REUSEPORT`) is hard. Two paths:
  - Disable `SO_REUSEPORT` and use one worker per container (then scale by running more containers). Costs you the per-container parallelism.
  - Add an intra-container router. Adds complexity and a new failure mode.
- **Worker failures reshuffle sessions.** Consistent hashing re-pins sessions when a worker dies. The new target worker doesn't have the live `UpstreamSession`, so requests fail until the session is re-established. Today's pub/sub model handles this via heartbeat-based dead-worker reclaim — transparently.
- **SSE doesn't benefit.** Long-lived GET streams have their own connection-ownership problem (#4334) that sticky LB doesn't touch.
- **Capacity planning gets coupled to stickiness ratio.** If one popular session pins to one worker, that worker becomes hot while others sit idle.

**When to pick**
If you're willing to constrain the deployment shape (one worker per container, more containers) and accept failover behaviour that's coarser than dead-worker reclaim, this is the cleanest answer. Works well for edge/appliance deployments. Pushes back against the "many workers per container" pattern most teams default to.

---

## Approach 2 — Coordinator-Worker Model

Move session ownership out of workers entirely. A single coordinator process per replica owns all upstream MCP sessions. Workers become stateless and proxy through the coordinator via cheap local IPC.

```
                       ┌─────────────────────────────────┐
                       │   Coordinator (1 per replica)   │
                       │   owns UpstreamSessionRegistry  │
                       └──┬──────────┬──────────┬────────┘
                          ▲          ▲          ▲
              UDS / shared-mem / localhost gRPC
                          │          │          │
                       ┌──┴──┐    ┌──┴──┐    ┌──┴──┐
                       │ W1  │    │ W2  │    │ W24 │     ◄── workers stateless
                       └─────┘    └─────┘    └─────┘
                          ▲
   nginx ──► gunicorn socket (any worker takes the request)
```

**Pros**
- Removes the affinity problem at the source. Workers don't own sessions, so there's nothing to scatter.
- No `WORKER_ID`, no pub/sub, no Redis ownership keys, no `post_fork` hook.
- Coordinator can serve any worker via UDS (~10 μs) — way faster than Redis pub/sub (~1–2 ms).
- Architecturally clean: stateful and stateless sides are explicitly separated.
- Opens the door to a Rust/PyO3 coordinator later for further perf.

**Cons**
- **New process type to deploy and operate.** Today it's "just gunicorn workers." The coordinator is another thing to monitor, restart, version-skew-test.
- **Single point of failure per replica.** Coordinator crash kills every session in that replica. Today's per-worker design only loses ~1/24 of sessions on a worker crash.
- **Coordinator becomes the throughput ceiling.** Every MCP request crosses the IPC boundary. Even at 10 μs that's measurable at high RPS, and a single-process coordinator is capped by one GIL's worth of work.
- **Significant refactor.** `UpstreamSessionRegistry`, `_handle_rpc_authenticated`, the streamable-HTTP transport, the session-lifecycle code — all need to move or learn to call the coordinator.
- **Multi-replica sessions don't survive replica failure.** Coordinator-per-replica doesn't get you cluster-wide session migration. That would need a cluster-wide coordinator, which is a much bigger project.

**When to pick**
If the project grows to need cluster-wide session migration (blue/green deploys, auto-scaling that doesn't drop sessions, multi-region failover), this becomes the natural architecture. Today's pub/sub model is a stepping stone toward this; the coordinator is the structural endpoint.

---

## Approach 3 — Redis-Based Cross-Worker Forwarding

Redis stores `sid → owner_worker_id`; when a request lands on the wrong worker, the receiving worker forwards the payload to the owner over an IPC transport, and the response comes back the same way. The question this approach has to answer is **what transport carries the forwarded payload?**

This approach has the smallest delta from the gateway's current architecture. The directory-lookup path (`mcpgw:pool_owner:{sid} → worker_id`) is already in place; only the dispatch path needs fixing. Implementation is therefore bounded to a small surface — no new process types, no LB-layer changes, no deployment-shape constraints. This makes it the **fastest path to a working solution**, with room to evolve the transport later (3a → 3c) as performance demands grow.

```
   Worker X
     │ Redis GET mcpgw:pool_owner:{sid} → "worker-7"
     ▼
   <transport>  ──── forward payload ────►  Worker 7  (owns the session)
                ◄─── response ────────────
     │
     ▼
   Worker X returns response to client
```

The transport options below all share the same ownership lookup in Redis. They differ only in how the request/response payload travels between workers.

### Sub-option 3a — Redis pub/sub over TCP

```
   Worker X  ──PUBLISH──►  Redis (TCP)  ──fanout──►  Worker 7 (SUBSCRIBE)
   Worker X  ◄────── response via another pub/sub channel ──────────
```

- **Latency**: ~1–2 ms per round-trip (transport ~50–200 μs each way + Redis-side fanout ~100–500 μs + serialization + ASGI dispatch ~500 μs–2 ms).
- **Mechanics**: each worker subscribes to its own channel `mcpgw:pool_http:{worker_id}`. Pub/sub semantics are "broadcast to all subscribers of a channel" — constrained to point-to-point by giving each channel exactly one subscriber.
- **Operationally simplest**: Redis is already in the stack; nothing else to deploy.
- **Fire-and-forget**: pub/sub has no persistence. If the owner worker is restarting when the publish lands, the message is lost.
- **Smallest mental model**: everything goes through Redis, which is also the observability and rate-limit substrate.

This is the baseline transport for Approach 3. The other sub-options swap it for something faster or more direct, but the surrounding architecture (Redis directory, worker subscriptions, dead-worker reclaim) is unchanged.

### Sub-option 3b — Redis pub/sub over Unix Domain Sockets

Keep Redis as the broker, but connect the gateway to Redis via UDS instead of TCP loopback.

```
   redis.conf:
     unixsocket /var/run/redis/redis.sock
     unixsocketperm 770

   gateway:
     redis.Redis(unix_socket_path="/var/run/redis/redis.sock")
```

- **Latency win**: TCP loopback round-trip ~50–200 μs → UDS round-trip ~10–50 μs. **2–5× faster on the transport layer.**
- **Overall win is smaller**: transport is only one slice of the per-call cost. Net latency improvement is roughly **15–25%**, not 2–5×.
- **Requires co-located Redis**: gateway and Redis must share a filesystem path. Easy in docker-compose with a shared named volume; hard in Kubernetes/OCP where Redis is typically a separate Pod in a different namespace.
- **Smallest change of all the options**: a few lines of config, no code change.
- **Doesn't change the architecture**: pub/sub is still pub/sub; this is a transport tweak, not a redesign.

**When to pick**: dev environments, single-node deployments, or edge appliances where Redis is co-located. Don't pick for multi-Pod Kubernetes — UDS doesn't cross Pod boundaries.

### Sub-option 3c — Worker-to-Worker UDS (Redis as directory only)

Remove Redis from the data path entirely. Each worker opens a UDS listener at a known path; Redis only stores the directory `worker_id → UDS path`. Forwarding is a direct HTTP POST over UDS, no broker.

```
   Redis (directory only)
     mcpgw:pool_owner:{sid} → worker-7
     mcpgw:worker_uds:worker-7 → /var/run/mcpgw/worker-7.sock

   Worker X
     │ httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds="/var/run/mcpgw/worker-7.sock"))
     │     .post("/rpc", content=body, headers=headers)
     ▼
   Worker 7  ◄── kernel-mediated direct copy, no network, no broker
```

- **Latency**: ~5–50 μs per round-trip. **10–100× faster than Redis pub/sub.**
- **httpx supports UDS natively**: `AsyncHTTPTransport(uds=...)`. No new dependency.
- **Synchronous request/response**: the call is one round-trip; no correlation-id-keyed response channel, no subscription teardown. `forward_to_owner` becomes ~15 lines.
- **Backpressure for free**: UDS has TCP-style flow control. Pub/sub has none.
- **Doesn't cross containers**: UDS is host-local. Cross-container forwards need a fallback (TCP loopback, or sticky LB at nginx so cross-container forwards don't happen).
- **Lifecycle overhead**: workers must clean up their `.sock` file on shutdown. Stale entries accumulate otherwise.
- **Shared mount required**: the UDS directory needs to be writable by all worker UIDs.

**When to pick**: most affinity forwards are intra-container (which they will be in our 24 × 3 setup), so the UDS fast path covers the common case. Falls back to current pub/sub (or sticky LB) for the rare cross-container case.

### Sub-option 3d — Direct TCP per worker

Each worker binds an additional internal TCP port (e.g., `5000 + worker_idx`). Forwarding is a direct HTTP POST to that port.

```
   Redis (directory):
     mcpgw:worker_addr:worker-7 → 10.0.0.5:5007

   Worker X ────── direct TCP ──────► Worker 7  (10.0.0.5:5007)
```

- **Works across containers** (UDS doesn't).
- **Latency**: ~50 μs intra-host, ~500 μs cross-container on the same node, ~1–5 ms across nodes. Still 2–10× faster than Redis pub/sub for the common case.
- **More attack surface**: every worker exposes an internal port. Needs network policy + per-port auth (mTLS or HMAC, like the trusted-internal endpoint already uses).
- **Port allocation contract**: 24 workers per container = 24 ports per container. Manageable but adds a deployment contract.
- **More complex than UDS** for the intra-container case (which is most of our traffic). You're paying for cross-container support that you may not use.

**When to pick**: if cross-container forwarding is a significant fraction of total forwards (low workers-per-container, many containers, no sticky LB).

### Sub-option 3e — ZeroMQ point-to-point messaging

Use ZMQ's `REQ/REP` pattern over `ipc://` (UDS) or `tcp://`. Discovery still in Redis.

```
   Worker X                                 Worker 7
     ┌──────────┐                          ┌──────────┐
     │ ZMQ REQ  │ ──── tcp://10.0.0.5:5007 ──► REP    │
     └──────────┘                          └──────────┘
              ◄── reply ────────────────────────
```

- **Purpose-built**: ZMQ exists to be "point-to-point messaging that's faster than a broker." Exactly this use case.
- **Single API across UDS and TCP**: switch transports with a URL change. Get UDS perf intra-host and TCP reach cross-host without two code paths.
- **Latency**: ~20–50 μs over `ipc://`, comparable to UDS.
- **Built-in retry**: `REQ/REP` retries failed requests. Pub/sub gives you nothing.
- **New dependency**: `pyzmq` + `libzmq` C library. Containerfile change.
- **Bypasses ASGI**: ZMQ doesn't go through the FastAPI middleware stack, so observability, CSRF, RBAC, etc. don't apply automatically. You'd reimplement that or accept it.
- **Heavier mental model**: socket types, framing, pattern semantics. Onboarding cost.

**When to pick**: if you're willing to make MCP forwarding its own bounded subsystem with custom observability, and per-call latency matters enough to justify the dependency. Probably not us, today.

---

## Comparison Matrix

| Approach | Latency / forward | Cross-container | Operational delta | Code change | Pub/sub still needed |
|---|---|---|---|---|---|
| **1. Sticky LB** | 0 (no forward) | n/a | nginx config + 1-worker-per-container | small | no |
| **2. Coordinator-worker** | ~10 μs UDS to coordinator | yes | new process type, lifecycle, monitoring | very large | no |
| **3a. Redis pub/sub TCP** | ~1–2 ms | yes | none | none | yes |
| **3b. Redis pub/sub UDS** | ~0.8–1.7 ms (15–25% faster) | only if co-located | shared volume, config | tiny | yes |
| **3c. Worker-to-worker UDS** | ~5–50 μs (10–100× faster) | no (needs fallback) | shared mount, UDS lifecycle | medium | no, intra-container |
| **3d. Direct TCP per worker** | ~50 μs–5 ms | yes | per-worker port allocation, auth | medium | no |
| **3e. ZeroMQ** | ~20–50 μs over ipc | yes | new dependency, custom observability | medium-large | no |

---

## Recommendation

**Starting point: Approach 3 with sub-option 3a (Redis pub/sub over TCP).**

Rationale:

- **Smallest delta from existing architecture.** The Redis directory, worker subscriptions, dead-worker reclaim, and observability surface are already in place. Implementation is bounded to fixing defects in the dispatch path rather than restructuring components.
- **No new operational burden.** Redis is already in the deployment; no new process types, no new dependencies, no LB-layer changes, no deployment-shape constraints.
- **Fastest path to a working solution.** Approaches 1 and 2 deliver more in the long run but require structural change (LB stickiness or a coordinator process) that takes more time to design, validate, and operationalise.
- **Doesn't foreclose the long-term options.** Picking 3a now leaves room to evolve toward 3c (worker-to-worker UDS) when perf demands grow, or pivot to Approach 1 / Approach 2 if the deployment shape or requirements change.

### Further improvements within Approach 3

These are transport-only upgrades — the surrounding architecture stays the same, so they can be adopted incrementally as the system matures.

| Upgrade | When to consider it |
|---|---|
| **3b (Redis pub/sub over UDS)** | Single-node deployments where Redis is co-located with the gateway. Drop-in transport upgrade, no architectural change. Not useful for multi-Pod Kubernetes/OCP topologies where Redis is a separate Pod. |
| **3c (worker-to-worker UDS)** | When affinity forwarding becomes a measured bottleneck. Removes Redis from the data path entirely (keeps it as the directory), 10–100× faster per forward, intra-container fast path covers the common case in the 24 × 3 deployment shape. The natural next step if 3a's ~1–2 ms per forward is shown to matter. |
| **3d (per-worker TCP)** | When cross-container forwarding is a significant fraction of total forwards (low workers-per-container, many containers, no sticky LB). Niche; most deployments don't hit this. |
| **3e (ZeroMQ)** | When MCP forwarding warrants its own bounded subsystem with custom observability. Adds a dependency and bypasses ASGI; rarely worth the trade for this use case. |

### When to revisit and switch approach

- **Pivot to Approach 1 (sticky LB)** if the deployment moves to one-worker-per-container. With no intra-container scatter, sticky LB at nginx is strictly simpler than any forwarding mechanism.
- **Pivot to Approach 2 (coordinator-worker)** if cluster-wide session migration becomes a real requirement (auto-scale without dropping sessions, blue/green deploys preserving session state, multi-region failover). At that point the structural refactor is worth the cost.

The question that drives any future revisit isn't *"should we replace pub/sub with X?"* — it's *"do the deployment shape or the requirements still match the assumptions behind Approach 3?"* As long as both hold, 3a (with 3b/3c as ready-to-pick upgrades) covers the problem cleanly.
