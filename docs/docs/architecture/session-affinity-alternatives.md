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

> **Status: paper design only.** Significant architectural change (new process type, IPC layer, ~22h prototype estimated). Not implemented. See [paper design](#paper-design-2) below.

Move session ownership out of workers. A single coordinator process per replica owns all upstream MCP sessions; workers become stateless and proxy through the coordinator via cheap local IPC.

nginx → any worker → coordinator (per replica, owns sessions) → upstream MCP server.

<details><summary>Architecture diagram</summary>

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

</details>

**Pros**
- Removes the affinity problem at the source. Workers don't own sessions.
- No `WORKER_ID`, no pub/sub, no Redis ownership keys, no `post_fork` hook.
- UDS IPC (~10 μs) is much faster than Redis pub/sub (~1–2 ms).
- Clean separation: stateful and stateless sides are explicit.
- Opens the door to a Rust/PyO3 coordinator later.

**Cons**
- New process type to deploy, monitor, version-skew-test.
- Single point of failure per replica: coordinator crash = 100% of in-replica sessions lost (vs ~4% on a worker crash today).
- Throughput ceiling: one GIL per replica; every request crosses the IPC boundary.
- Significant refactor: `UpstreamSessionRegistry`, RPC dispatch, transport, lifecycle.
- No cluster-wide session migration; coordinator-per-replica is local only.

<a id="paper-design-2"></a>**Paper design.** Full design — IPC framing (length-prefixed JSON over UDS), per-session locking, request-flow walk-through, failure-mode comparison, SSE / ADR-052 open question, env-gated coexistence, ~22h prototype estimate — in the [coordinator-worker design doc](https://github.com/IBM/mcp-context-forge/blob/experiment/coordinator-worker-design/docs/docs/architecture/experiments/coordinator-worker-design.md).

**When to pick:** when cluster-wide session migration becomes a hard requirement (blue/green deploys, auto-scale without session loss, multi-region failover). Not justified today.

---

## Approach 3 — Redis-Based Cross-Worker Forwarding

> **Status: in-flight hardening.** Three PRs (#4981, #4987, #4997) implement the four invariants below. Production-ready when those land.

Redis stores `sid → owner_worker_id`; the receiving worker forwards the payload to the owner over an IPC transport, and the response comes back the same way. The architecture has no delta from the gateway's current design — the Redis directory, per-worker channels, and dead-worker reclaim are all already in place. The #4557 regression came from invariants not being honoured, not from the architecture being wrong. The four invariants below are what the in-flight PRs are fixing.

### Invariants any Approach-3 implementation must satisfy

These are non-negotiable properties of the design. The existing code violated several of them, which is what produced the regression in #4557.

- **Unique per-worker `WORKER_ID` after fork.** `--preload` captures the master's id at import; workers must recompute in `post_fork`. A shared `WORKER_ID` collapses every worker onto one Redis channel — the source of the 24× amplification in #4557.
- **Exactly one subscriber per per-worker channel.** Follows from invariant 1, but worth stating independently because operators can verify it directly: `PUBSUB NUMSUB mcpgw:pool_http:{worker_id}` and `PUBSUB NUMSUB mcpgw:pool_rpc:{worker_id}` must each return 1, not N. Anything > 1 means a `WORKER_ID` collision is amplifying forwards on that transport.
- **Forwarded requests execute in the owner process.** Network loopback to `127.0.0.1` hits the shared gunicorn socket, where `SO_REUSEPORT` scatters the call to a random worker that doesn't hold the bound upstream session. In-process dispatch (`httpx.ASGITransport(app=app)`) keeps execution on the correct worker.
- **Forwarded requests preserve the original `streamable_http_auth()` context.** The originating worker already validated the inbound credentials (ContextForge JWT, virtual-server OAuth, or public-only mode). The owner must trust that decision rather than re-authenticate — OAuth bearers fail internal JWT verification, and public-only requests have no token to verify at all. Either failure manifests as 401 on the inner dispatch even though the edge auth was correct.

Transport choice is independent of these invariants; none of the sub-options below compensate for an invariant being violated.

Worker X reads `mcpgw:pool_owner:{sid}` from Redis to find the owner, then forwards the payload to that worker over the configured transport.

<details><summary>Forwarding flow diagram</summary>

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

</details>

The transport options below all share this ownership lookup. They differ only in how the request/response payload travels between workers.

### Sub-option 3a — Redis pub/sub over TCP (the baseline)

Baseline transport. Operationally simplest; ~1–2 ms per round-trip. Being hardened by #4981 / #4987 / #4997.

<details><summary>Diagram, pros, cons</summary>

```
   Worker X  ──PUBLISH──►  Redis (TCP)  ──fanout──►  Worker 7 (SUBSCRIBE)
   Worker X  ◄────── response via another pub/sub channel ──────────
```

**Pros**
- Operationally simplest: Redis already in the stack.
- Smallest mental model: everything goes through one substrate (also the observability and rate-limit layer).
- Point-to-point constrained from broadcast by per-worker channels (invariant 2).

**Cons**
- Latency ~1–2 ms per round-trip (transport + Redis fanout + ASGI dispatch).
- Fire-and-forget: no persistence; message lost if the owner is restarting at publish time.

The other sub-options swap the transport without changing the surrounding architecture (Redis directory, worker subscriptions, dead-worker reclaim).

</details>

### Sub-option 3b — Redis pub/sub over Unix Domain Sockets

Transport tweak only: swap TCP loopback to Redis for UDS. ~15–25% net latency win. Dev / single-node / edge.

<details><summary>Config, pros, cons</summary>

Keep Redis as the broker; connect the gateway to it over UDS instead of TCP loopback.

```
   redis.conf:
     unixsocket /var/run/redis/redis.sock
     unixsocketperm 770

   gateway:
     redis.Redis(unix_socket_path="/var/run/redis/redis.sock")
```

**Pros**
- Smallest change of all the options: a few lines of config, no code change.
- ~15–25% net latency improvement (transport layer is 2–5× faster; transport is one slice of the per-call cost).

**Cons**
- Requires co-located Redis (shared filesystem path). Easy in docker-compose; hard in Kubernetes where Redis is a separate Pod.
- Transport tweak only; no architectural improvement over 3a.

**When to pick:** dev / single-node / edge. Don't pick for multi-Pod Kubernetes.

</details>

### Sub-option 3c — Worker-to-Worker UDS (Redis as directory only)

Remove Redis from the data path; forward worker-to-worker over UDS directly. 10–100× faster than 3a. Intra-container only.

<details><summary>Diagram, pros, cons</summary>

Each worker opens a UDS listener; Redis only stores `worker_id → UDS path`. Forwarding is a direct HTTP POST over UDS, no broker.

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

**Pros**
- ~10–100× faster than Redis pub/sub (~5–50 μs per round-trip).
- Backpressure for free (UDS has TCP-style flow control; pub/sub has none).
- Synchronous request/response; `forward_to_owner` shrinks to ~15 lines (no correlation-id channel, no subscription teardown).
- `httpx` supports UDS natively (`AsyncHTTPTransport(uds=...)`). No new dependency.

**Cons**
- Doesn't cross pod/node boundaries. Needs fallback (TCP loopback, or sticky LB at nginx) for cross-container forwards.
- Lifecycle overhead: workers must clean up their `.sock` on shutdown; stale entries accumulate otherwise.
- Shared mount required: the UDS directory must be writable by all worker UIDs.

**When to pick:** when intra-container forwards dominate (e.g., 24 × 3 setup) and the cross-container case is rare enough to fall back.

</details>

### Sub-option 3d — Direct TCP per worker

Each worker binds an internal TCP port; forward directly to it. Works cross-container. 2–10× faster than 3a.

<details><summary>Diagram, pros, cons</summary>

Each worker binds an additional internal TCP port (e.g., `5000 + worker_idx`). Forwarding is a direct HTTP POST to that port.

```
   Redis (directory):
     mcpgw:worker_addr:worker-7 → 10.0.0.5:5007

   Worker X ────── direct TCP ──────► Worker 7  (10.0.0.5:5007)
```

**Pros**
- Works across containers (UDS doesn't).
- Still 2–10× faster than Redis pub/sub for the common case (~50 μs intra-host, ~500 μs cross-container same-node, ~1–5 ms cross-node).

**Cons**
- More attack surface: every worker exposes an internal port. Needs network policy + per-port auth (mTLS or HMAC, like the trusted-internal endpoint).
- Port allocation contract: 24 workers per container = 24 ports per container.
- More complex than UDS for the intra-container case (which is most traffic). Pays for cross-container support that may not be used.

**When to pick:** when cross-container forwarding is a significant fraction of total forwards (low workers-per-container, many containers, no sticky LB).

</details>

### Sub-option 3e — ZeroMQ point-to-point messaging

ZMQ `REQ/REP` over `ipc://` (UDS) or `tcp://`. Purpose-built point-to-point messaging. New dependency; bypasses ASGI.

<details><summary>Diagram, pros, cons</summary>

Use ZMQ's `REQ/REP` pattern over `ipc://` (UDS) or `tcp://`. Discovery still in Redis.

```
   Worker X                                 Worker 7
     ┌──────────┐                          ┌──────────┐
     │ ZMQ REQ  │ ──── tcp://10.0.0.5:5007 ──► REP    │
     └──────────┘                          └──────────┘
              ◄── reply ────────────────────────
```

**Pros**
- Purpose-built for point-to-point messaging faster than a broker.
- Single API across UDS and TCP: switch transports with a URL change.
- Transport-level resilience: sockets reconnect automatically on transient drops.
- Latency ~20–50 μs over `ipc://`, comparable to UDS.

**Cons**
- New dependency: `pyzmq` + `libzmq` C library. Containerfile change.
- Bypasses ASGI middleware (observability, CSRF, RBAC don't apply automatically; need re-implementation).
- Heavier mental model (socket types, framing, pattern semantics). Onboarding cost.
- `REQ/REP` doesn't give you application-level retry semantics (request IDs, timeouts, idempotency); caller still implements those.

**When to pick:** when MCP forwarding is worth making its own bounded subsystem with custom observability, and per-call latency justifies the dependency. Probably not today.

</details>

---

## Approach 4 — Redis-Resident Sessions

> **Status: ruled out for ContextForge.** Requires every upstream MCP server to support cross-connection session resumption, which most don't (rmcp / Python SDK tie state to the TCP connection). Not viable for a federating gateway over arbitrary third-party upstreams.

Externalise session state to Redis so any worker can serve any session. Workers re-open upstream connections on each request and resume via the stored session id.

<details><summary>Diagram, pros, cons</summary>

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
- No affinity layer needed. LB round-robins freely; no `pool_owner` keys, no per-worker channels.
- No cross-worker forwarding. Removes the entire IPC sub-problem that Approach 3 has to solve.
- Worker failure doesn't strand sessions; next request opens a fresh upstream on a different worker.
- Sessions could survive worker restarts and rolling deploys.
- Truly stateless workers; horizontal scale is trivial.

**Cons**
- Requires every upstream MCP server to support cross-connection session resumption. The MCP spec doesn't standardise an upstream `resume(session_id)` primitive; most rmcp / Python SDK servers tie state to the TCP connection.
- Per-request connection establishment adds 50–500 ms (TCP + TLS handshake + MCP `initialize` + `notifications/initialized` round-trip, every request).
- Stateful upstreams break by default: two workers reconnecting with the same sid get two separate counters, or the server rejects the duplicate.
- Concurrency races: two workers handling the same downstream session in parallel send overlapping requests on different connections, fighting for state ordering upstream.
- Redis becomes the data path, not just the directory. Hot-path Redis (~5–10 ms) is more expensive than ownership lookup (~0.5 ms); a Redis outage degrades from "no forwarding" to "no requests at all."
- Server-initiated SSE / notifications break — only the worker holding the live connection receives upstream-pushed events. Fan-out reintroduces the cross-worker problem this approach was meant to remove.

**When to pick:** only if every upstream is stateless and supports cross-connection resumption, AND the per-call reconnect cost is acceptable. For a federating gateway over arbitrary third-party MCP servers, this bet doesn't hold.

</details>

---

## Comparison Matrix

Side-by-side comparison of all 8 variants — latency, cross-container support, operational delta, code-change size, and pub/sub dependency.

<details><summary>Comparison table</summary>

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

</details>

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
