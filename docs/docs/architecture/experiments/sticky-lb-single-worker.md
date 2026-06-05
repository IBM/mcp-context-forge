# Experiment: sticky LB at one-worker-per-container

This document records an experiment to evaluate **Approach 1** from
[session-affinity-alternatives.md](../session-affinity-alternatives.md):
sticky load balancing on `Mcp-Session-Id` with one gunicorn worker per
container. Lives on the branch `experiment/sticky-lb-single-worker`.

The experiment did **not** succeed end-to-end. The canonical counter
reproducer failed because of a structural mismatch between server-generated
session ids and LB-level hash routing. The finding is useful: it shows that
the "config-only" framing of Approach 1 is too generous. Several follow-up
options exist and are ranked below.

## Goal

Test whether Approach 1 is shippable as a **config-only change** — no
gateway code, no new components, just nginx + docker-compose. The
hypothesis was that sticky LB on `Mcp-Session-Id` would route session
follow-ups back to the worker that holds the upstream MCP session, letting
us turn the in-process affinity layer off without losing the
[#4205 isolation invariant](../session-affinity-alternatives.md#the-core-problem).

## What's in this branch

Two new files, zero edits to existing files. Layer them on top of the
base `docker-compose.yml`:

| File | Purpose |
|---|---|
| `docker-compose.sticky-lb.yml` | Overlay that disables the replicated `gateway` service (`replicas: 0`), defines discrete `gateway-1/2/3` services using `extends`, each with `GUNICORN_WORKERS=1` and `MCPGATEWAY_SESSION_AFFINITY_ENABLED=false`, and overrides nginx to mount the sticky config. |
| `infra/nginx/nginx-sticky-lb.conf` | Copy of `nginx.conf` with explicit `upstream gateway_pool` and `upstream mcp_transport_pool` blocks using `hash $http_mcp_session_id consistent;`, plus the corresponding `map` reroutes. `a2a_backend` is updated to list `gateway-1/2/3` explicitly. |

## How to reproduce

```bash
git checkout experiment/sticky-lb-single-worker

# Bring up the stack with the overlay
COMPOSE_FILE=docker-compose.yml:docker-compose.sticky-lb.yml make testing-up
sleep 30 && curl -fsS http://localhost:8080/health

# Tear down
COMPOSE_FILE=docker-compose.yml:docker-compose.sticky-lb.yml make testing-down
```

`make testing-up` exits non-zero because the `register_fast_time` init
container fails (a one-shot script unrelated to the experiment). The
gateway/nginx/redis services come up healthy.

## What worked

**Sticky routing is deterministic for arbitrary header values.** A probe of
30 unique session ids against `/health` (which echoes `pod_id` in the
response) produced this distribution across 3 backends:

```
 7  0a265444cab5
10  22d94c05449e
13  555afb3636eb
```

Spread is uneven (23% / 33% / 43%) at N=30, well within consistent-hash
variance for small N. With 300+ probes the distribution would flatten
toward 33% each. The same session id always lands on the same pod, which
is the property sticky LB needs to provide. **Stickiness itself is fine.**

The stack also came up cleanly:
- `gateway-1`, `gateway-2`, `gateway-3` all healthy with `GUNICORN_WORKERS=1`
  (one worker per pod, confirmed in logs).
- `MCPGATEWAY_SESSION_AFFINITY_ENABLED=false` in effect.
- nginx healthy, accepting traffic on `localhost:8080`.

## What didn't — the counter test gap

The canonical [#4205 counter reproducer](../session-affinity-alternatives.md)
fails on this branch. Steps:

1. Register a counter MCP server as a gateway.
2. Create a virtual server scoping its three tools (echo, increment, get_value).
3. `POST /servers/{id}/mcp` with `{"method":"initialize"}` — gateway responds
   with a fresh `Mcp-Session-Id` header (e.g. `b616268e74704c37a6cb2af3f7d51114`).
4. `POST /servers/{id}/mcp` with `{"method":"tools/call","name":"increment"}`
   and the new `Mcp-Session-Id` header.

Expected: 25 monotonic increments 1..25.

Observed: the increment call returns
```json
{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Session not found"}}
```

The session id was minted by some pod, but no pod's logs reference the id
on the follow-up. The follow-up landed on a pod that never bound the session.

## Root cause

Naive hash-on-`Mcp-Session-Id` has a structural bug: **the server picks the
sid after the routing decision has already been made.**

```
Initialize:
  Client → nginx (no Mcp-Session-Id header)
         → hash("") = deterministic but arbitrary → pod A
         → pod A generates sid "abc123", binds session, returns sid
         → client now holds "abc123"

Follow-up:
  Client → nginx (Mcp-Session-Id: abc123)
         → hash("abc123") → pod B  (not pod A)
         → pod B has no record of "abc123" → "Session not found"
```

The LB has no way to know that "abc123" was minted on pod A. The mapping
between sid and bind-pod exists only in pod A's in-memory registry.

Confirmed in the probe: when we asked nginx which pod the returned sid
hashed to (`curl -H "Mcp-Session-Id: $SID" /health`), it routed to a pod
different from the one the gateway logs showed had bound the session.

We also confirmed the gateway **does not honour a client-provided sid on
initialize**: sending `Mcp-Session-Id: client-chosen-xyz` with the
initialize body produced no `Mcp-Session-Id` response header. The cheap
"let the client pick the routing key" fix doesn't work without a gateway
code change.

## Why #4987 doesn't have this problem

In [#4987](https://github.com/IBM/mcp-context-forge/pull/4987) the affinity
layer is **on**. When a follow-up lands on the wrong pod, the gateway
consults Redis (`mcpgw:pool_owner:{sid}`) to find the owner, then forwards
the request to it over pub/sub. The affinity layer is the safety net that
catches the bind-pod mismatch.

Turning the affinity layer off (this experiment) removes the safety net
without providing an alternative routing mechanism. Sticky LB on
`Mcp-Session-Id` is **not** an alternative because of the mismatch above.

## Options to address, ranked by simplicity

To make Approach 1 work end-to-end, one of these needs to be true: the
routing key must be **stable from the first request** and known to both
the client and the LB before any pod has bound the session.

### 1. Hash on `Authorization` header (simplest)

```nginx
upstream gateway_pool {
    hash $http_authorization consistent;
    server gateway-1:4444 max_fails=3 fail_timeout=30s;
    server gateway-2:4444 max_fails=3 fail_timeout=30s;
    server gateway-3:4444 max_fails=3 fail_timeout=30s;
    keepalive 512;
}
```

- One-line nginx change. No gateway code, no SDK monkey-patch, no env wiring.
- `Authorization` is present on every request including initialize (auth is
  required in ContextForge).
- Per-user stickiness instead of per-session. All of one user's sessions
  land on one pod.

**Trade-offs:** heavy-user load concentration on a single pod; session loss
on token refresh. Mitigated by per-user nginx rate-limit and by typical
ContextForge JWT lifetimes (hours, not minutes).

### 2. `ip_hash` (absolute simplest)

```nginx
upstream gateway_pool {
    ip_hash;
    server gateway-1:4444;
    server gateway-2:4444;
    server gateway-3:4444;
}
```

- Built-in nginx directive. One line.
- **NAT collapse:** many clients behind one corporate or carrier NAT all
  land on the same backend. Fine for benchmarks, bad for production with
  real users.

### 3. Pod-encoded opaque session ids

Patch the MCP SDK so generated sids carry an opaque pod fingerprint:
`f"{POD_FINGERPRINT}-{uuid4().hex}"`. nginx routes by mapping the prefix
to a backend.

```nginx
map $http_mcp_session_id $sid_prefix {
    ~^([a-f0-9]{8})-  $1;
    default "";
}
map $sid_prefix $target {
    a1b2c3d4   "http://gateway-1:4444";
    e5f6a7b8   "http://gateway-2:4444";
    c9d0e1f2   "http://gateway-3:4444";
    default    "http://gateway_pool";  # bind-step fallback
}
```

- ~15 LOC monkey-patch of `mcp.server.streamable_http_manager.uuid4` (SDK
  doesn't accept a custom sid factory).
- Per-session stickiness (each sid carries its own routing identity).
- **Security caveat:** a leaked sid lets an attacker target one pod for
  concentrated-DoS. Must be paired with per-pod-prefix nginx rate-limit
  (`limit_req_zone $sid_prefix`) to be production-acceptable.

### 4. Cookie-based stickiness

LB sets a routing cookie on the first response; client returns it on
follow-ups. The textbook industry pattern.

- nginx OSS doesn't support `sticky cookie` — requires **nginx Plus**
  (commercial), HAProxy, or a third-party nginx module.
- Depends on every MCP client SDK honouring HTTP cookies. The MCP spec
  doesn't mandate cookie handling, so this needs per-SDK validation.

### 5. Coordinator-worker (Approach 2)

Sidestep the LB problem entirely: a coordinator per container owns
upstream sessions, workers are stateless and dispatch through it. See
[#4557](https://github.com/IBM/mcp-context-forge/issues/4557).

- Full architectural refactor.
- No bind-pod mismatch because the LB target is also the session owner
  by construction.

## Production acceptability summary

| Option | Code change | LB change | Production acceptable? | Notes |
|---|---|---|---|---|
| 1. Hash on Authorization | none | 1 line | yes | Heavy-user concentration, mitigated by rate-limit. Session loss on token refresh. |
| 2. `ip_hash` | none | 1 line | only without NAT | NAT collapse breaks fairness under real load. |
| 3. Pod-encoded opaque sids | ~15 LOC SDK patch | ~10 lines | yes with caveats | Needs per-pod rate-limit to defend against targeted DoS. |
| 4. Cookie stickiness | none | LB tech change | yes | Requires nginx Plus / HAProxy. Client SDK cookie support required. |
| 5. Coordinator-worker | major | n/a | yes | Largest change. Sidesteps the routing problem. |

## Alternatives considered but not pursued

A couple of intra-container topologies were discussed during the experiment
and rejected before any code was written. Captured here so a future reader
knows the design space was explored.

### Port-per-worker (multi-workers, each on a distinct port)

Keep `GUNICORN_WORKERS=N` per container, but bind each worker to a distinct
port instead of sharing one via `SO_REUSEPORT`. nginx upstream would list
every `container:port` pair as a separate backend.

- Theoretically valid. Each worker becomes its own routable endpoint, so
  `hash $http_authorization` (or any deterministic hash) routes to a
  specific worker, not just a container.
- **Operationally unusual.** Requires either separate gunicorn instances
  per port or a custom worker bootstrap. nginx upstream grows to N entries
  per container (3 containers × 24 workers = 72 entries). Per-port health
  checks. Port management per pod. Container restart re-binds all ports.
- Not adopted by mainstream Python web deployments — the modern pattern
  is one worker per pod and scale with replicas. We didn't see a strong
  reason to swim against the current here.

### Intra-container sidecar / coordinator

A small process inside each container that reads `Mcp-Session-Id`, looks up
the owning worker in a per-container map, and forwards via UDS or a local
port.

- This is the affinity layer relocated from the worker process to a
  sidecar. Doesn't simplify the architecture; just moves the problem.
- Adds a new failure mode (sidecar liveness), a new IPC contract, and
  per-container state.
- Effectively reinvents Approach 2 (coordinator-worker) at container scope.
  If we want a coordinator, we'd do the full Approach 2 instead of a
  partial sidecar version.

Both options are documented in the parent architecture alternatives doc
under Approach 1's intra-container stickiness bullet.

## What still needs to be measured

The experiment stopped at the counter test failure. The original verification
plan was not exercised:

- `make benchmark-mcp-tools` RPS / p99 vs the #4987 baseline (397 RPS, 1.6 s).
- Per-pod resource footprint at N=3 single-worker pods vs the current
  3×24 worker stack.
- Pod-kill / session-loss behaviour under sticky LB.

These will become meaningful once one of the routing options above is
applied and the counter test passes.

## If picked back up

Cheapest next move: change one line in `nginx-sticky-lb.conf` from
`hash $http_mcp_session_id consistent;` to `hash $http_authorization consistent;`,
restart nginx, re-run the counter probe. If that produces strict monotonic
1..25 across all probes, proceed to the benchmark and pod-kill measurements
the original plan called for. If it surfaces a new issue (header parsing,
auth refresh, etc.), fall back to Option 3 (pod-encoded sids) as the next
candidate.

The per-pod / per-user rate-limit recommendation pairs with whichever
routing option is picked — for option 1 it becomes
`limit_req_zone $http_authorization zone=per_user:10m rate=200r/s;`;
for option 3 it becomes `limit_req_zone $sid_prefix zone=per_pod:10m rate=200r/s;`.
