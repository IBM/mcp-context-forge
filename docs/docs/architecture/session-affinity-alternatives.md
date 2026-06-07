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

> **Status: empirically validated.** `hash $http_authorization` config-only variant measured at **352 RPS, 0% failures, p99 530 ms** on a 3-pod prototype. ~21× per-worker efficiency vs the current affinity-layer baseline. See [empirical summary](#empirical-summary) below.

Stop forwarding at the application layer. Route correctly at the LB layer.

Client → nginx hashes on `$http_authorization` → pod → `/rpc` executes locally. No forwarding.

<details><summary>Original architecture diagram (Mcp-Session-Id variant)</summary>

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

</details>

**Pros**
- No forward path. No pub/sub. No `WORKER_ID`. No `post_fork` hook.
- Lower latency: no Redis on the hot path.
- Simplest architecture once wired.
- Easy to reason about: session X on worker Y, always.

**Cons**
- Two layers of stickiness required. nginx handles Layer-1; Layer-2 (intra-container) needs more work (see options below).
- Worker failures reshuffle sessions; sticky LB has no per-session migration. Today's pub/sub model handles this transparently via heartbeat-based dead-worker reclaim.
- SSE / GET streams don't benefit (#4334).
- Capacity coupled to stickiness ratio — heavy users concentrate on one worker.

<details><summary>Layer-2 stickiness options</summary>

- **Disable `SO_REUSEPORT`** and use one worker per container; scale by running more containers. Costs per-container parallelism.
- **Port-per-worker:** each gunicorn worker binds a distinct port; nginx upstream lists `container:portN` for every worker. Operationally unusual (N entries per container, per-port health checks, separate gunicorn instances). Few teams run this.
- **Intra-container router** (sidecar or coordinator). Adds complexity and a new failure mode.

</details>

**Bootstrap routing.** The `initialize` request doesn't yet carry `Mcp-Session-Id`, so hashing on that header can't pin the bootstrap itself. Solved empirically by hashing on `Authorization` instead (see [empirical summary](#empirical-summary)).

<details><summary>Bootstrap design alternatives considered (before the auth-hash variant was tested)</summary>

Two known mitigations for the `Mcp-Session-Id` variant of the problem:

- **(a) Server-side session-id minting that encodes routing.** The worker generating the session id constructs it so the LB's hash function returns this worker — e.g., the id contains a prefix or slot identifier the LB hash respects. Requires a tight contract between the LB hash and the gateway's session-id format; brittle to LB config changes.
- **(b) Bootstrap-then-pin.** `initialize` lands on any worker via non-hashed routing (least-conn or round-robin), the response returns the session id, and from then on the LB hashes on the session id. Requires the LB hash to be deterministic across requests AND deterministic from the worker's point of view at session-creation time — typically achieved by hashing into a slot ring known to both sides. Failure mode: if a worker dies before the bootstrap completes, the session id may map elsewhere.

Neither mitigation is structurally complex, but both require the gateway to know — and round-trip through — the LB's hash function. The MCP Python SDK doesn't expose the session-id generator as a hook (today it's a hardcoded `uuid4().hex` inside `StreamableHTTPSessionManager`), so mitigation (a) needs either a small SDK patch upstreamed or a startup-time monkey-patch in the gateway. Both were superseded by the simpler answer: hash on `Authorization`, which is present on every request from the start.

</details>

<a id="empirical-summary"></a>**Empirical summary**

| Variant | Status | Notes |
|---|---|---|
| `hash $http_mcp_session_id` (naive) | failed | Initialize→follow-up bootstrap mismatch. [Single-worker experiment README](https://github.com/IBM/mcp-context-forge/blob/experiment/sticky-lb-single-worker/docs/docs/architecture/experiments/sticky-lb-single-worker.md). |
| `hash $http_authorization` (variant that works) | **passed** | 352 RPS / 0% fail / p99 530 ms on 3 single-worker pods. 5/5 correctness tests pass. ~21× per-worker efficiency vs Approach 3. Mitigations for user-pinning trade-offs (rate-limit, JWT lifetime) covered in the README. [Auth-hash experiment README](https://github.com/IBM/mcp-context-forge/blob/experiment/sticky-lb-auth-hash/docs/docs/architecture/experiments/sticky-lb-auth-hash.md). |

Net: Approach 1 ships as a config-only change when the LB hash key is `Authorization` rather than `Mcp-Session-Id`.

**When to pick:** moving to one-worker-per-pod (or already there). Auth-hash variant is the recommended config.

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

**Paper design.**
The [coordinator-worker design doc](https://github.com/IBM/mcp-context-forge/blob/experiment/coordinator-worker-design/docs/docs/architecture/experiments/coordinator-worker-design.md) fills in what this section deliberately leaves abstract: the IPC framing (length-prefixed JSON over UDS), the per-session locking and concurrency model, the request-flow walk-through, the failure-mode comparison vs the current affinity layer (coordinator crash = 100% of in-replica sessions vs ~4% today on a 24-worker setup), the SSE / ADR-052 open question, the env-gated coexistence path, and a wall-clock prototype estimate (~22 hours / 2-3 focused days). Implementing Approach 2 is a significant architectural and code change; the design doc is the implementation starting point if this approach is picked up.

**When to pick**
If the project grows to need cluster-wide session migration (blue/green deploys, auto-scaling that doesn't drop sessions, multi-region failover), this becomes the natural architecture. Today's pub/sub model is a stepping stone toward this; the coordinator is the structural endpoint.

---

## Approach 3 — Redis-Based Cross-Worker Forwarding

Redis stores `sid → owner_worker_id`; when a request lands on the wrong worker, the receiving worker forwards the payload to the owner over an IPC transport, and the response comes back the same way. Two questions this approach has to answer:

1. **What transport carries the forwarded payload?** (the sub-options 3a–3e below)
2. **What invariants must the implementation satisfy** for the architecture to actually behave as point-to-point forwarding?

The second question matters because the architecture is correct only when those invariants hold — and the existing implementation violates several of them, which is what produced the #4557 regression. The transport choice is independent of whether the invariants hold. Both have to be addressed.

This approach has no architectural delta from the gateway's current design: the Redis directory (`mcpgw:pool_owner:{sid} → worker_id`), the per-worker channels, and the dead-worker reclaim path are all already in place. The work is bounded to honouring the invariants below and (optionally) upgrading the transport. No new process types, no LB-layer changes, no deployment-shape constraints. This makes it the **fastest path to a working solution**, with room to evolve the transport later (3a → 3c) as performance demands grow.

### Invariants any Approach-3 implementation must satisfy

These are non-negotiable properties of the design. The existing code violated several of them, which is what produced the regression in #4557.

- **Unique per-worker `WORKER_ID`** after process fork. Under gunicorn `--preload` the `WORKER_ID` constant is captured in the master process before workers fork, so all workers inherit the same id unless the value is recomputed in the `post_fork` hook. A shared `WORKER_ID` collapses every worker onto the same Redis channel, and pub/sub then delivers each forwarded request to every worker in the container — the source of the 24× amplification observed in #4557.
- **Exactly one subscriber per per-worker channel.** `SessionAffinity.start_rpc_listener()` subscribes each worker to both its Streamable HTTP forwarding channel (`mcpgw:pool_http:{worker_id}`) and its SSE/RPC forwarding channel (`mcpgw:pool_rpc:{worker_id}`). Redis pub/sub semantics are broadcast; this approach constrains them to point-to-point by giving each channel a unique name keyed on the unique `WORKER_ID`. The invariant follows directly from per-worker `WORKER_ID` but is worth stating independently because operators can verify it directly: `PUBSUB NUMSUB mcpgw:pool_http:{worker_id}` and `PUBSUB NUMSUB mcpgw:pool_rpc:{worker_id}` should each return 1, not N. If either returns more than 1, the `WORKER_ID` collision is present on the corresponding transport and that transport will amplify forwards.
- **Forwarded requests execute in the owner process**, not via a network loopback through the shared gunicorn socket. Network loopback hits the shared socket, where `SO_REUSEPORT` scatters the call to whichever worker the kernel picks — almost never the owner that holds the bound upstream session. In-process dispatch (e.g., `httpx.ASGITransport(app=app)`) keeps execution on the correct worker.
- **Forwarded requests preserve the original `streamable_http_auth()` context.** The originating worker has already validated the inbound credentials (ContextForge JWT, virtual-server OAuth verifier, public-only mode). The forwarded payload must carry that validated identity to the owner; otherwise the owner's inner dispatch will re-authenticate against a context it cannot validate (IdP OAuth bearers fail at internal JWT verification, public-only requests have no token to verify). Both fail with 401 on the inner call even though the original request was correctly authenticated at the edge.

These invariants are what make point-to-point semantics, owner-process execution, and end-to-end auth correctness all hold simultaneously. The transport sub-options below assume them; none of the sub-options compensate for an invariant being violated.

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
- **Doesn't cross pod/node boundaries**: UDS is host-local and requires a shared filesystem path. Cross-container use only works when containers are co-located on the same node *and* share a mount for the socket directory with compatible permissions. Cross-pod or cross-node forwards need a fallback (TCP loopback, or sticky LB at nginx so cross-container forwards don't happen in the first place).
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
- **Transport-level resilience**: ZMQ sockets reconnect automatically on transient drops, which pub/sub gives you nothing equivalent to. Application-level retry semantics (request IDs, timeouts, idempotency, exactly-once) are NOT handled by `REQ/REP` itself — those still need to be implemented in the caller, same as for any other transport.
- **New dependency**: `pyzmq` + `libzmq` C library. Containerfile change.
- **Bypasses ASGI**: ZMQ doesn't go through the FastAPI middleware stack, so observability, CSRF, RBAC, etc. don't apply automatically. You'd reimplement that or accept it.
- **Heavier mental model**: socket types, framing, pattern semantics. Onboarding cost.

**When to pick**: if you're willing to make MCP forwarding its own bounded subsystem with custom observability, and per-call latency matters enough to justify the dependency. Probably not us, today.

---

## Approach 4 — Redis-Resident Sessions

Externalise the session state into Redis so any worker can serve any downstream session. Workers don't keep upstream connections alive; they re-open one and resume on each request using the upstream session id stored in Redis.

```
                       ┌───────────────────────────────────────┐
                       │  Redis (data path, not just directory)│
                       │                                       │
                       │  mcpgw:session:{sid} →                │
                       │    { upstream_url, upstream_sid,      │
                       │      last_seq, capabilities, ... }    │
                       └───────────────────────────────────────┘
                                ▲          ▲          ▲
                                │          │          │
                            (read/write per request)
                                │          │          │
                       ┌────────┴───┐ ┌────┴───┐ ┌────┴───┐
                       │  Worker 1  │ │  W 2   │ │  W N   │
                       │ stateless  │ │        │ │        │
                       └─────┬──────┘ └────┬───┘ └────┬───┘
                             │              │           │
                       (each opens its own upstream connection
                        on each request and resumes via upstream_sid)
                             │              │           │
                             ▼              ▼           ▼
                       ┌─────────────────────────────────────┐
                       │   Upstream MCP server (rmcp etc.)   │
                       │   must support: resume by sid       │
                       └─────────────────────────────────────┘
```

**Pros**

- No affinity layer needed. LB can round-robin freely; no `mcpgw:pool_owner` keys, no per-worker pub/sub channels.
- No cross-worker forwarding. Removes the entire IPC sub-problem that Approach 3 has to solve.
- Worker failure doesn't strand sessions; the next request opens a fresh upstream connection on a different worker.
- Sessions could survive worker restarts and rolling deploys.
- Truly stateless workers, horizontal scale is trivial.

**Cons**

- **Requires every upstream MCP server to support cross-connection session resumption.** The MCP spec has `Mcp-Session-Id` for client-side continuity but does not standardise an upstream `resume(session_id)` primitive. Most rmcp and Python SDK servers tie state to the TCP connection.
- **Per-request connection establishment adds 50–500 ms.** TCP plus TLS handshake plus MCP `initialize` plus `notifications/initialized` round-trip, on the request critical path, every time.
- **Stateful upstreams break by default.** Servers like the rmcp counter keep state keyed by connection. Two workers reconnecting with the same upstream session id will get two separate counters, or the server may reject the duplicate.
- **Concurrency races on the upstream.** Two workers handling the same downstream session in parallel can send overlapping requests on different connections, fighting for state ordering on the upstream. The current single-writer model avoids this entirely.
- **Redis becomes the data path, not just the directory.** Every request reads and writes session state. Hot-path Redis is more expensive than ownership lookup (~5-10 ms vs ~0.5 ms) and a Redis outage degrades to "no requests at all" rather than "no forwarding."
- **Server-initiated SSE / notifications break.** Only the worker holding the live connection receives upstream-pushed events. You'd need a fan-out mechanism, which is exactly the cross-worker forwarding this approach was trying to avoid.

**When to pick**: only if you can guarantee all upstreams are stateless request-response tools (no counters, no resources, no subscriptions) AND every upstream supports cross-connection resumption AND you're willing to pay the per-call reconnect cost. For a federating gateway that has to handle arbitrary third-party MCP servers, this bet doesn't hold.

---

## Comparison Matrix

> **Latency figures are order-of-magnitude estimates** drawn from typical commodity hardware, included to support relative comparison between the approaches. They are sensitive to deployment specifics (kernel, container runtime, Redis version, network path, payload size) and must be measured against the gateway benchmark stack before being used for capacity planning or SLA commitments.

| Approach | Latency / forward (est.) | Cross-container | Operational delta | Code change | Pub/sub still needed |
|---|---|---|---|---|---|
| **1. Sticky LB** | 0 (no forward); 352 RPS / p99 530 ms measured on a 3-pod sticky-on-`Authorization` prototype | n/a | nginx config + 1-worker-per-container | small | no |
| **2. Coordinator-worker** | ~10 μs UDS to coordinator | yes | new process type, lifecycle, monitoring | very large | no |
| **3a. Redis pub/sub TCP** | ~1–2 ms | yes | none | bounded (honour the Approach-3 invariants) | yes |
| **3b. Redis pub/sub UDS** | ~0.8–1.7 ms (15–25% faster) | only if co-located | shared volume, config | tiny | yes |
| **3c. Worker-to-worker UDS** | ~5–50 μs (10–100× faster) | no (needs fallback) | shared mount, UDS lifecycle | medium | no, intra-container |
| **3d. Direct TCP per worker** | ~50 μs–5 ms | yes | per-worker port allocation, auth | medium | no |
| **3e. ZeroMQ** | ~20–50 μs over ipc | yes | new dependency, custom observability | medium-large | no |
| **4. Redis-resident sessions** | n/a (no forward; +50–500 ms per call to re-establish upstream) | yes | Redis becomes data path | very large | no |

---

## Recommendation

**Adopt Approach 3 with Redis pub/sub over TCP (sub-option 3a) as the transport, and repair the existing implementation against the four Approach-3 invariants.**

The recommendation is not "stay with the existing code" — the existing implementation produced the regression in #4557. The recommendation is "keep the existing architecture (Redis-based cross-worker forwarding with pub/sub transport) and enforce the invariants the architecture depends on." Concretely, an Approach-3 implementation must:

1. Recompute `WORKER_ID` per worker after fork (so each worker has a unique Redis channel).
2. Maintain exactly one subscriber per worker's pub/sub channels — both `mcpgw:pool_http:{worker_id}` (Streamable HTTP) and `mcpgw:pool_rpc:{worker_id}` (SSE/RPC). A verifiable property: `PUBSUB NUMSUB` returns 1 for each, not N.
3. Dispatch the forwarded request in the owner process, not via a network loopback that the shared gunicorn socket would scatter.
4. Preserve the `streamable_http_auth()` context across the forward so OAuth and `MCP_REQUIRE_AUTH=false` requests survive without 401-ing on the inner dispatch.

The four invariants are listed in detail under [Approach 3 — Invariants](#invariants-any-approach-3-implementation-must-satisfy). This contract was implemented incrementally across three stacked PRs — [#4981](https://github.com/IBM/mcp-context-forge/pull/4981) (per-worker `WORKER_ID` + foundation), [#4987](https://github.com/IBM/mcp-context-forge/pull/4987) (in-process forward dispatch), and [#4997](https://github.com/IBM/mcp-context-forge/pull/4997) (auth-context propagation). The three were brought together on an integration branch, [`fix/session-affinity-multiworker-forwarding`](https://github.com/IBM/mcp-context-forge/compare/main...fix/session-affinity-multiworker-forwarding), to test the full approach end-to-end on the 3 × 24 reference stack (~390 RPS, 0% failures, `PUBSUB NUMSUB` = 1).

### Why this approach over the alternatives

- **No architectural delta.** The Redis directory, per-worker channels, and dead-worker reclaim are already in place. Approach 1 (sticky LB) requires LB-layer and deployment-shape changes plus the user-pinning trade-offs of routing on `Authorization` (heavy-user concentration, session loss on token refresh); the bootstrap-routing question now has an empirically validated answer (see the [follow-up experiment](#approach-1--sticky-load-balancing-on-mcp-session-id)). Approach 2 (coordinator-worker) is a significant refactor that introduces a new process type.
- **No new operational burden.** Redis is already in the deployment; no new dependencies, no new process types to monitor and version.
- **Fastest path to a working solution.** Bounded to honouring the four invariants — the surface is small and the validation criteria are explicit and verifiable.
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

- **Pivot to Approach 1 (sticky LB)** if the deployment moves to one-worker-per-container. With no intra-container scatter, sticky LB at nginx is strictly simpler than any forwarding mechanism. This pivot is empirically de-risked: [`experiment/sticky-lb-auth-hash`](https://github.com/IBM/mcp-context-forge/tree/experiment/sticky-lb-auth-hash) demonstrated end-to-end correctness and **117 RPS per worker vs. 5.5 RPS per worker** for the current affinity baseline (#4987) — production rollout still needs a longer soak, real-hardware run, and the per-`$http_authorization` rate-limit recommended in the experiment write-up.
- **Pivot to Approach 2 (coordinator-worker)** if cluster-wide session migration becomes a real requirement (auto-scale without dropping sessions, blue/green deploys preserving session state, multi-region failover). At that point the structural refactor is worth the cost.
- **Approach 4 (Redis-resident sessions) stays out of scope** as long as ContextForge is a federating gateway over arbitrary third-party upstreams. It would only make sense if the gateway's role narrowed to stateless tool execution AND every supported upstream guaranteed cross-connection session resumption. Neither holds today.

The question that drives any future revisit isn't *"should we replace pub/sub with X?"* — it's *"do the deployment shape or the requirements still match the assumptions behind Approach 3?"* As long as both hold, 3a (with 3b/3c as ready-to-pick upgrades) covers the problem cleanly.
