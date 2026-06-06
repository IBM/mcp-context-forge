# Design: Approach 2 — Coordinator-Worker prototype

**Status: design only.** No code in this branch. The purpose is to surface
gotchas, IPC details, and failure modes *before* anyone commits a focused
day or two to a smoke prototype. If after reading this the call is "this
is worth prototyping", the doc becomes the README scaffold for the
experiment branch that follows.

This document describes the **Shape A** variant of the coordinator-worker
model as defined in
[session-affinity-alternatives.md](../session-affinity-alternatives.md):
workers are stateless HTTP handlers, a single coordinator process per
replica owns the upstream MCP sessions, and workers dispatch MCP calls to
the coordinator over in-replica IPC. The architecture doc's
[Approach 2 diagram](../session-affinity-alternatives.md) is the
authoritative picture; this doc fills in everything that diagram doesn't
say.

The alternative shape from
[#4557](https://github.com/IBM/mcp-context-forge/issues/4557) — coordinator
at the front, workers running plugin pre/post hooks over an MQ — is
discussed under "Alternatives considered" near the end. It is not what
this design covers.

## Goal

Produce enough detail to (a) estimate prototype effort within ±50%, and
(b) decide whether the trade-offs Approach 2 introduces are acceptable
for the deployment shapes ContextForge targets. **Not** a production
spec; not a finished implementation plan.

## Why this design over the simpler alternatives

The [`sticky-lb-auth-hash`](./sticky-lb-auth-hash.md) experiment showed
that Approach 1 (sticky LB + one async worker per pod) clears the
correctness bar and produces 117 RPS per worker — vs. ~5.5 RPS per worker
on the current affinity-layer baseline. For most workloads
ContextForge sees today, Approach 1 is already the cleaner answer.

Approach 2 becomes interesting only when one of three things is true:

1. **Cluster-wide session migration** is a requirement (blue/green deploys,
   auto-scale without dropping sessions, multi-region failover). Sticky LB
   doesn't migrate sessions; a coordinator-as-state-owner can be evolved
   toward a cluster-wide owner later.
2. **Plugin processing becomes CPU-heavy** in a way that benefits from
   independent scaling. (This is more #4557's framing than Approach 2's,
   and would be addressed differently — see Alternatives.)
3. **Multi-tenant fairness** at the in-replica level becomes a hard
   requirement. Approach 1 collapses one user's sessions onto one pod,
   which is a load-distribution skew Approach 2 doesn't have because
   workers stay HTTP-stateless.

None of those are pressing today. Prototyping Approach 2 anyway is worth
doing as **structural insurance**: when the day comes that one of those
becomes pressing, we want to have already measured the IPC overhead, the
coordinator failure semantics, and the migration path — not be starting
from a blank page under deadline pressure.

## Architecture

### Components

- **Worker** (gunicorn / async): handles incoming HTTP, runs middleware
  (auth, RBAC, observability), parses the JSON-RPC body. For
  non-MCP-stateful paths (catalog, admin, health) it executes locally as
  today. For MCP `/servers/{id}/mcp` traffic, it dispatches the parsed
  request to the coordinator over UDS.
- **Coordinator** (one per replica, standalone Python process): owns
  the `UpstreamSessionRegistry`. Maintains the upstream MCP `ClientSession`
  per `Mcp-Session-Id`. Receives JSON-RPC requests via UDS, dispatches
  them to the right upstream, returns the response.
- **Upstream MCP server**: unchanged. The coordinator is just a faithful
  long-lived MCP client.
- **nginx**: unchanged from the existing config. No sticky LB required —
  any worker can dispatch any session to the coordinator, because the
  coordinator owns all the state. (This is the structural property that
  makes Approach 2 interesting.)

### Request flow

```
Client ──HTTP──▶ nginx ──HTTP──▶ Worker N (any)
                                    │
                                    │  parse JSON-RPC
                                    │  auth + middleware
                                    │
                                    └─UDS──▶ Coordinator (1 per replica)
                                                │
                                                │  look up Mcp-Session-Id
                                                │  fetch or open ClientSession
                                                │
                                                └─HTTP/SSE──▶ Upstream MCP server
```

Response travels back the same path: upstream → coordinator → worker → client.

### What stays in the worker

- HTTP termination and TLS
- Auth (JWT validation, RBAC, team scoping)
- Observability (OTel spans, request id, audit log emission)
- Middleware: rate limiting, CORS, security headers
- Non-MCP routes (catalog, /servers, /tools, /health, /version, admin UI)
- JSON-RPC parsing and validation
- Response framing (SSE event encoding for streamable responses)

### What moves to the coordinator

- `UpstreamSessionRegistry` (the entire registry — one process owns it). The
  existing module-level `init_upstream_session_registry()` is suitable for
  direct use in the coordinator process; the registry does not depend on
  the FastAPI request scope, the user identity context, or any per-worker
  singleton, so no extraction work is required to host it standalone.
- Upstream `ClientSession` lifecycle: open, keepalive, close.
- Per-session locks and ordering guarantees.
- The dispatch step that actually calls `tools/call`, `tools/list`, etc.
  on the upstream.

### What's deleted

- The affinity layer (`session_affinity.py` in its current form is no
  longer on the hot path).
- The `mcpgw:pool_owner:*` and `mcpgw:pool_http:*` / `mcpgw:pool_rpc:*`
  Redis keys.
- The `WORKER_ID` post-fork hook (still potentially useful for
  observability tagging, but no longer load-bearing for routing).
- The in-process ASGI dispatch helper from #4987 (replaced by IPC).

## IPC protocol sketch

### Transport

**Unix domain socket** (`/sockets/coordinator.sock` or similar, mounted
into both worker and coordinator containers via a shared volume).
Reasons over the alternatives:

- **UDS vs. TCP loopback**: UDS skips the TCP stack, no port allocation
  per replica, no exposure to other containers. Cheaper end-to-end.
- **UDS vs. gRPC**: gRPC adds a code-gen + protobuf dependency. For
  per-replica IPC where both sides are Python and we control the
  protocol, raw UDS framing is fine. gRPC stays as a future option if
  we ever cross a process-language boundary.
- **UDS vs. shared memory**: shared mem with `multiprocessing` would be
  faster per call (~1μs) but the async story is messy — `asyncio`
  doesn't have first-class shared-memory primitives, and we'd be hand-
  rolling sync. Not worth it for this prototype.

### Framing

Length-prefixed JSON on the socket. Each frame is:

```
+--------+-----------------+
| u32 BE | JSON payload    |
| length | (UTF-8, exactly |
|        |  `length` bytes)|
+--------+-----------------+
```

Simple, debuggable with `socat`, no schema-evolution headaches. msgpack
or CBOR is a drop-in upgrade later if profiling shows JSON encoding is
hot.

### Message types

```jsonc
// Worker → Coordinator (dispatch request)
{
  "type": "dispatch",
  "req_id": "<uuid4>",                 // for response correlation
  "mcp_session_id": "<sid or null>",   // null on initialize
  "gateway_id": "<gateway uuid>",
  "method": "tools/call",
  "params": { ... },                   // raw JSON-RPC params
  "auth": {                            // pre-validated auth context
    "user_email": "...",
    "teams": [...],
    "is_admin": false
  },
  "deadline_ms": 30000                 // worker's timeout budget
}

// Coordinator → Worker (response)
{
  "type": "response",
  "req_id": "<uuid4>",                 // matches the dispatch
  "result": { ... },                   // JSON-RPC result on success
  "error": { "code": -32000, "message": "..." },  // on failure
  "mcp_session_id": "<sid>"            // returned to client on initialize
}

// Bidirectional (control plane, optional in MVP)
{ "type": "ping" }
{ "type": "pong" }
{ "type": "shutdown" }                 // coordinator drain signal
```

### Concurrency model

- **One persistent UDS connection per worker.** Workers connect at
  startup; reconnect with exponential backoff if the socket disappears.
- **Per-connection request multiplexing.** Each `dispatch` carries a
  unique `req_id`; the coordinator can interleave responses out of order.
  Worker maintains a `dict[req_id, asyncio.Future]` and resolves the
  future when the matching response arrives.
- **Bounded inflight queue.** If the worker has too many requests waiting
  on the coordinator (say 1000), the next request returns 503 instead of
  waiting — backpressure that propagates to nginx and the client.

### Error model

- **Coordinator-side error during dispatch**: returned as a JSON-RPC
  error inside the `response` frame. Worker passes it back to the client.
- **Coordinator unreachable** (socket gone / read fails): worker fails
  the inflight requests with a synthetic JSON-RPC error
  (`{"code": -32603, "message": "internal error: coordinator unavailable"}`)
  and starts the reconnect loop. Client sees a 503 with that error.
- **Timeout**: worker enforces `deadline_ms`. If exceeded, fail the
  request locally, cancel the inflight future, and tell the coordinator
  to drop the call via a `{"type": "cancel", "req_id": ...}` frame (best
  effort).

### Auth pass-through

The coordinator does not re-validate auth. The worker has already
authenticated; the `auth` field in the dispatch is the pre-validated
context. The coordinator trusts it because the UDS socket is intra-
replica and not addressable from outside.

**Caveat**: this trust model means the coordinator MUST NOT be reachable
from outside the replica. UDS in a private volume is the enforcement.

## Coordinator state machine (per session)

```
                  (no entry)
                       │
                       ▼
                ┌─────────────┐
   dispatch ───▶│  Opening    │   open ClientSession to upstream,
   (sid=null)   │             │   bind sid, return it
   ─ or ─       └──────┬──────┘
   first call w/       │
   unknown sid         ▼
                ┌─────────────┐
                │   Active    │◀─── dispatch hits this state on every
                │             │     subsequent call for this sid
                │  upstream   │
                │ ClientSess  │
                └──────┬──────┘
                       │  idle timeout / client disconnects
                       │  or evict signal
                       ▼
                ┌─────────────┐
                │   Closing   │   await in-flight calls, close upstream,
                │             │   release session-id slot
                └──────┬──────┘
                       │
                       ▼
                  (no entry)
```

The transitions correspond directly to operations the current
`UpstreamSessionRegistry` already performs. The work isn't to invent a
new state machine — it's to lift the existing one into a separate process
and put an IPC boundary in front of it.

### Per-session locking

The coordinator runs one asyncio task per upstream `ClientSession`. Calls
arriving on the IPC are pushed into a per-session queue and processed in
order — this preserves the JSON-RPC ordering guarantee that today's
in-process registry provides via `asyncio.Lock`.

## Code changes (estimated)

| File | Action | LOC |
|---|---|---|
| `mcpgateway/coordinator.py` | NEW: standalone process. asyncio UDS server, hosts `UpstreamSessionRegistry`, frame parser, dispatch loop. | ~300 |
| `mcpgateway/transports/coordinator_client.py` | NEW: connection manager (reconnect, multiplex), `dispatch()` coroutine returning `asyncio.Future`. | ~150 |
| `mcpgateway/services/tool_service.py` | MODIFY: at the two pooled-dispatch sites (the SSE and the StreamableHTTP branches of `call_tool`, both ~10 lines around the `registry.acquire(...)` block), env-gate on `COORDINATOR_UDS_PATH`. When set, call `coordinator_client.call_tool(...)` and reconstruct a `types.CallToolResult` from the response; otherwise fall through to the existing local-registry path. Default behaviour is unchanged. | ~80 |
| `mcpgateway/main.py` | MODIFY: at startup, if running in worker mode and `COORDINATOR_UDS_PATH` is set, instantiate `coordinator_client` as a singleton bound to the FastAPI app's lifespan. | ~20 |
| `mcpgateway/config.py` | MODIFY: new env vars (`COORDINATOR_UDS_PATH`, `COORDINATOR_DISPATCH_TIMEOUT_MS`, `COORDINATOR_MAX_INFLIGHT`). | ~10 |

**Total**: ~560 LOC for the smoke prototype. Real prototype with chaos
tests and proper observability is double that.

> **Note on the dispatch site.** The pooled upstream call lives in
> `tool_service.py`, *not* in `streamablehttp_transport.py`. The streamable-HTTP
> transport handles the worker's *downstream* MCP session (with the client);
> `tool_service.call_tool` is where the worker reaches into the
> `UpstreamSessionRegistry` to dispatch the upstream tool call. The split is
> easy to miss when scanning the codebase for the right hook point.

## Compose overlay

```yaml
# docker-compose.coordinator.yml
services:
  coordinator:
    extends:
      file: docker-compose.yml
      service: gateway
    command: ["python", "-m", "mcpgateway.coordinator"]
    environment:
      - COORDINATOR_UDS_PATH=/sockets/coordinator.sock
      - GUNICORN_WORKERS=0           # not a gunicorn service
    volumes:
      - coordinator-socket:/sockets
    depends_on:
      pgbouncer:
        condition: service_healthy
      redis:
        condition: service_started

  gateway:
    environment:
      - COORDINATOR_UDS_PATH=/sockets/coordinator.sock
      - MCPGATEWAY_SESSION_AFFINITY_ENABLED=false
    volumes:
      - coordinator-socket:/sockets:ro
    depends_on:
      coordinator:
        condition: service_started

volumes:
  coordinator-socket:
```

For a multi-replica deployment we'd need one coordinator per gateway
replica, each with its own socket volume — the K8s equivalent is a
sidecar pattern with an `emptyDir` volume shared between sidecar and
main container in the same pod.

## Failure modes (the important part)

| Failure | Today (affinity layer) | Approach 2 (coordinator) |
|---|---|---|
| Worker crash | ~1/24 of sessions in that replica lost (the ones the dead worker owned) | **0 sessions affected** (workers are stateless) |
| Coordinator crash | n/a | **All sessions in the replica lost** |
| Worker OOM | same as worker crash, plus container restart | same as worker crash |
| Coordinator OOM | n/a | same as coordinator crash |
| Coordinator slow / hung | n/a | every request in that replica blocks until timeout, then fails |
| UDS socket gone | n/a | worker reconnects with backoff; in-flight requests fail with 503 |
| Upstream MCP server slow | inflight calls in the owner worker block | inflight calls in the coordinator block, **shared across all workers in the replica** |
| Coordinator graceful restart | n/a | drain inflight (send `shutdown`, refuse new dispatches), wait for in-flight to complete or hit deadline, then exit. Same blast radius as crash for whatever's mid-flight. |

**The big one: coordinator crash blast radius.** Today, killing one
worker drops ~4% of the replica's sessions. Killing one coordinator under
Approach 2 drops **100%** of the replica's sessions. The replicas are
independent (one per replica), so a multi-replica deployment still has
~1/N of the cluster's sessions survive. But within a replica, the
coordinator is a single point of failure by design.

Mitigations:
- **Liveness probe and fast restart.** Aim for sub-second restart so the
  client retry budget covers it.
- **Graceful drain on rolling deploy.** Coordinator gets shutdown signal,
  refuses new dispatches, completes in-flight, then exits. Workers see
  the socket close, fail fast on new requests, clients re-initialize.
- **Replicate at deployment level.** Run more replicas with fewer
  workers each, so the blast radius per coordinator failure is smaller.

### What clients see during coordinator restart

- In-flight dispatch: gets `503 coordinator unavailable` after timeout.
- Subsequent calls on the same `Mcp-Session-Id`: the new coordinator
  has no record → `404 session not found`. Client re-initializes.

This is the **same recovery contract as the sticky-LB pod-kill test**: a
session error means "re-initialize." We tested this works cleanly under
Approach 1; it'd work the same way here.

## Observability

The IPC boundary needs to be visible:

- **Cross-process tracing.** Inject the OTel span context into the
  dispatch frame; coordinator resumes the span on the other side. Without
  this, every trace shows a black box at the worker→coordinator boundary.
- **Coordinator-side metrics.** Active sessions count, inflight queue
  depth, per-method dispatch latency (p50/p99), upstream call latency,
  reconnect counts.
- **Worker-side metrics.** IPC dispatch latency (worker view), reconnect
  events, queued requests, request 503s due to coordinator unavailability.
- **Health checks.** Coordinator exposes `/health` over UDS (or a TCP
  side-channel). nginx never sees the coordinator; the orchestrator
  (compose / k8s) probes it directly.

## Migration / coexistence

Env-gated path: `COORDINATOR_UDS_PATH` set → use coordinator dispatch.
Unset → use the existing in-process registry + affinity layer. Same
binary, both paths shipped. Per-replica rollout possible.

This is critical for the prototype: we never want a flag day. We want to
say "deploy this replica with COORDINATOR_UDS_PATH=…, leave the others
on the legacy path, compare metrics."

## Open questions before any code is written

These are the things most likely to surprise the prototype:

1. **What's the per-request IPC overhead under load?**
   UDS round-trip is ~10–30 μs on Linux. JSON encode + decode on a typical
   200-byte payload is another ~50–150 μs. Total ~100–200 μs per dispatch.
   Acceptable for tool calls that take 1–100 ms upstream, but worth
   measuring under concurrency before making scaling claims — the
   single-coordinator event loop is the ceiling per replica.
2. **Does asyncio + per-session locking inside one process scale to the
   target session count?**
   The current registry is already this architecture; the only new thing
   is that all sessions in the replica now share *one* process's event
   loop, not 24. GIL contention is not the issue (single process), but
   event-loop latency under 1000+ active sessions might be.
3. **How do plugin pre/post hooks interact with the IPC boundary?**
   Today they run inline in the worker's request path. Under Approach 2,
   the question is: do plugins run in the worker (before/after dispatch)
   or in the coordinator (before/after the upstream call)? Different
   plugins want different answers. Likely answer: keep plugins in the
   worker by default; let opt-in plugins run in the coordinator if they
   need the upstream connection (e.g., observability of upstream
   responses).
4. **Auth context propagation across the IPC.**
   The dispatch frame must carry the worker-validated identity (user
   email, teams, admin flag) so the coordinator has the user context it
   needs without re-validating. The coordinator trusts the IPC payload
   because the UDS socket is intra-replica and not network-addressable;
   this trust boundary should be stated explicitly in code and audited.
5. **Observability span context propagation.**
   The dispatch frame should carry the OTel span context so the
   coordinator-side dispatch resumes the worker's trace. Without it,
   every span has a black box at the worker → coordinator boundary,
   which is exactly where the interesting latency lives.
6. **SSE / GET-stream behaviour (ADR-052).**
   The coordinator owns the upstream `ClientSession`, which is the source
   of server-initiated notifications. Workers can't easily relay SSE
   events from coordinator → client without an extra long-lived IPC
   channel per active stream. This is the most under-designed part right
   now; the smoke prototype should defer SSE and only handle POST /mcp.
7. **Cluster-wide migration is still out of reach.**
   Approach 2 is *per-replica* coordinator, not cluster-wide. Sessions
   still die on replica failure. True session migration requires a
   cluster-wide owner with externalised state, which is Approach 4
   (Redis-resident) shape — and we already concluded that's not viable
   for federating gateways. Approach 2 is a stepping stone, not the
   endpoint.

## Estimated prototype effort

| Milestone | Work | Wall-clock estimate |
|---|---|---|
| **A — Coordinator process boots, handles ping/pong** | new `coordinator.py`, framing, basic UDS server | ~3 hours |
| **B — Counter probe passes through coordinator** | wire IPC client, env-gated dispatch path, lift `UpstreamSessionRegistry` | ~6 hours |
| **C — Cross-user / same-user-multi-session probes pass** | per-session locking, concurrency tests | ~4 hours |
| **D — Coordinator-kill / worker-kill chaos** | health probes, failure semantics, recovery | ~4 hours |
| **E — Benchmark (per-user tokens)** | run, profile IPC overhead | ~3 hours |
| **F — Experiment README + architecture doc note** | write up findings, link from main doc | ~2 hours |
| **Total** | | **~22 hours / ~2-3 focused days** |

If E shows the IPC overhead eats the per-worker efficiency win, the
experiment ends honestly there and the architecture doc gets an
empirical note saying "Approach 2 measured X RPS — not better than
Approach 1, so the structural-insurance argument is the only reason to
pursue it." If E shows a clear win, the design becomes the basis for a
real PR.

## Alternatives considered

### Shape B — #4557's coordinator-front model

Coordinator handles HTTP directly; workers run plugin pre/post hooks
via an MQ. We covered the comparison in detail in the architecture doc's
"Empirical note" sections. Short version: Shape B reduces to "Approach 1
with optional plugin offload" — which is mostly redundant for our
workload, where plugins are lightweight. Not pursued in this design.

If plugins ever become CPU-heavy enough to justify offload, the cleaner
path is to add an *optional* MQ tier on top of Approach 1, not to
re-architect the front of the gateway.

### Threading or `multiprocessing` instead of UDS

Both move the coordinator inside the worker container as a thread or
forked process. Loses the property that workers are stateless (the
thread holds session state in the same address space) and brings GIL
contention back. Not better than today's affinity layer.

### gRPC instead of raw UDS framing

Adds protobuf, code generation, an extra dependency to operate. The
trade is "type safety + cross-language" for "simplicity." Since both
sides are Python and we control the protocol, the win isn't worth the
weight at prototype stage. gRPC is a drop-in upgrade later if cross-
language coordinators (e.g., Rust) become interesting.

## Decision points

Before committing to the prototype, the team should agree on:

1. **Is the coordinator-as-SPOF blast radius acceptable** at the
   deployments ContextForge targets? (Mostly multi-replica deployments,
   so yes — but worth saying out loud.)
2. **Is the IPC overhead small enough** that we expect a clear win over
   the affinity layer? (The numbers above suggest yes, but they need
   measuring.)
3. **Is this worth the 2-3 days now**, or does it stay theoretical until
   one of the three triggers in the "Why this design" section becomes
   pressing?

If 1 and 2 are "yes" and 3 is "yes, now is fine," the next step is to
create `experiment/coordinator-worker` (without `-design`), use this doc
as the README scaffold, and start with Milestone A.

If 3 is "wait," this design doc sits on its branch as documented intent.
The architecture doc gets a one-line link, and we move on.
