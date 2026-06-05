# Experiment: sticky LB with `hash $http_authorization`

Follow-up to [`sticky-lb-single-worker`](./sticky-lb-single-worker.md), which
surfaced a structural bug: hashing on the server-generated `Mcp-Session-Id`
breaks the initialize → follow-up handoff because the LB has no way to route
the bind request to the same pod the follow-up will hash to.

This branch swaps the LB hash key from `Mcp-Session-Id` to `Authorization`.
The client already holds the bearer token before sending `initialize`, so
**routing is deterministic from the very first request** — no bind-pod
mismatch, no gateway code change, no SDK monkey-patch.

The result: Approach 1 from
[session-affinity-alternatives.md](../session-affinity-alternatives.md)
ships as a config-only change after all, with a small benchmark patch to
make the measurement fair.

## Goal

Validate that `hash $http_authorization` in nginx (combined with
`GUNICORN_WORKERS=1` and the affinity layer disabled) supports the full
MCP session lifecycle end-to-end, and measure throughput vs the #4987
baseline (affinity layer + 3×24 workers).

## What's in this branch

Built on top of the previous experiment branch — same overlay topology
(`docker-compose.sticky-lb.yml`, discrete `gateway-1..gateway-3` services,
`MCPGATEWAY_SESSION_AFFINITY_ENABLED=false`), with two small additions:

| File | Change |
|---|---|
| `infra/nginx/nginx-sticky-lb.conf` | Both `upstream` blocks (`gateway_pool` and `mcp_transport_pool`) swap `hash $http_mcp_session_id consistent;` → `hash $http_authorization consistent;`. Two lines. |
| `tests/loadtest/locustfile_mcp_protocol.py` | Env-gated branch in `_get_token()`: when `BENCHMARK_UNIQUE_TOKENS=1`, mint a fresh JWT per `_get_token()` call so each Locust user instance gets its own `Authorization` header. Default behaviour (shared singleton token) is preserved when the env var is unset. |

The locustfile change is necessary because the existing benchmark caches one
shared JWT across all 125 simulated users; with sticky LB on Authorization,
that would collapse the entire benchmark onto one backend and tell us
nothing about distribution.

## How to reproduce

```bash
git checkout experiment/sticky-lb-auth-hash

# Bring up the stack
COMPOSE_FILE=docker-compose.yml:docker-compose.sticky-lb.yml make testing-up
sleep 30 && curl -fsS http://localhost:8080/health

# Run the benchmark with per-user tokens
BENCHMARK_UNIQUE_TOKENS=1 make benchmark-mcp-tools

# Tear down
COMPOSE_FILE=docker-compose.yml:docker-compose.sticky-lb.yml make testing-down
```

## What worked — five tests, all passed

### 1. Counter probe (the canonical #4205 reproducer)

Single token, 25 increments through the registered counter virtual server.
Strict monotonic 1..25, `get_value` returned 25, single upstream session
held by one pod throughout.

```
token → pod=555afb3636eb
initialize → sid=3f6aeef8...
notifications/initialized: 202
25 increments: 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25
get-value: 25
```

### 2. Cross-user isolation

Two distinct tokens, parallel counters.

```
[A] pod=555afb3636eb  increments: 1 2 3 4 5 6 7 8 9 10  final: 10
[B] pod=0a265444cab5  increments: 1 2 3 4 5 6 7 8 9 10  final: 10
```

Different tokens hashed to different pods; sessions independent; no
cross-contamination.

### 3. Same-user multi-session

One token, three parallel sessions.

```
token → pod=555afb3636eb (gateway-3)
[S1] sid=d36172cd... increments: 1..10  final: 10
[S2] sid=4a16c0c7... increments: 1..10  final: 10
[S3] sid=b24a2a68... increments: 1..10  final: 10
```

All three sessions pinned to gateway-3 as expected (user-pinning by
Authorization hash). Each session independent, three separate upstream
MCP sessions held in one async pod, no cross-talk.

### 4. Pod-kill / failover

Stopped `gateway-3` (the pod the test token hashed to), observed
behaviour on the same token.

```
before: pod=555afb3636eb (gateway-3),  sid bound, increments OK
docker compose stop gateway-3
old sid request: connection error
token → pod=22d94c05449e (gateway-2)   ← consistent hash skipped dead pod
fresh initialize on gateway-2: new sid, increments 1..5 on fresh counter
docker compose start gateway-3
```

Sessions on the killed pod are lost (no in-flight migration). Consistent
hash routes the same token to a remaining pod, and `initialize` rebinds
cleanly there. The recovery contract is "client re-initializes after
detecting a connection error" — same as any sticky-LB-with-pod-failure
deployment.

### 5. Per-user benchmark (`BENCHMARK_UNIQUE_TOKENS=1 make benchmark-mcp-tools`)

125 Locust users, each minting its own JWT (unique `jti`), 60s run.

```
Total Requests:    21,090
Total Failures:         0   (0.00%)
RPS:               352.21
p50 / p99:         280ms / 530ms

  endpoint                  reqs    RPS    p99(ms)
  ────────────────────────────────────────────────
  tools/call [rapid]      20,002   334.0    530
  tools/list [rapid]         963    16.1    430
  initialize                 125     2.1    920
```

## Comparison table

| | Sticky LB, shared token | Sticky LB, per-user tokens (this run) | #4987 baseline |
|---|---|---|---|
| Stack | 3 pods × 1 worker = 3 workers | 3 pods × 1 worker = 3 workers | 3 pods × 24 workers = 72 workers |
| RPS | 17 | **352** | 397 |
| Failures | 20.42% | **0%** | 0% |
| p99 | 30 s (timeout ceiling) | **530 ms** | 1.6 s |
| RPS per worker | 5.7 | **117** | 5.5 |

The shared-token run is included because it's what `make benchmark-mcp-tools`
produces by default. It is **not** representative of sticky LB performance
in a multi-tenant deployment — it shows what happens when one token's load
crushes the single pod it pins to. The per-user-token run is the realistic
shape: 125 distinct tokens spread across 3 pods, ~40 users per pod.

The standout number is **RPS per worker**: ~21× the affinity baseline's
per-worker efficiency. The costs that disappear under Approach 1:

- No Redis pub/sub forwarding hop on cross-worker requests.
- No ASGI in-process dispatch (no middleware re-run from #4987's helper).
- No `pool_owner` lookup, no cross-worker coordination.
- Pure asyncio inside one process — no GIL contention from 24 threads.
- Each pod owns its sessions in-process; lookup is a dict access, not a
  Redis call.

## Production acceptability

The wire-level / operational requirements for sticky LB on `Authorization`
are the same as any header-based stickiness, and are already met by
ContextForge defaults:

- **TLS in transit.** Mandatory — both `Authorization` and `Mcp-Session-Id`
  would be plaintext on the wire otherwise. ContextForge's production
  configuration uses TLS.
- **Don't log `$http_authorization` at the LB.** nginx's default access
  log format does not include it. A one-time grep on the deployed nginx
  config before shipping confirms no custom `log_format` includes
  `$http_authorization`.
- **No token in URLs or error pages.** Already true today.

Trade-offs specific to user-pinning (Authorization-hashed):

- **Heavy-user concentration.** All of one user's parallel sessions land
  on one pod. Mitigation: per-`$http_authorization` nginx rate limit
  (`limit_req_zone $http_authorization zone=per_user:10m rate=200r/s;`)
  caps the load any one token can drive at the LB tier before it touches
  the pod.
- **Session loss on token refresh.** A fresh JWT is a different string,
  so it hashes to a (possibly different) pod, leaving the old sessions
  unreachable. Mitigated in practice by long-lived JWTs (hours to days)
  and by clients that re-initialize on auth refresh.
- **Failover during pod outages strands sessions created mid-outage.**
  When a downed pod recovers, the hash routes back to it, but sessions
  created on the temporary substitute pod become unreachable. The
  recovery contract is "client re-initializes after a session error."

## What's still unmeasured

This experiment ran on a laptop, on three pods, on a workload of
lightweight tools (`fast_test_server`). To take this from "promising
prototype" to "production candidate," the next things worth measuring:

- **Production hardware run.** Replay the benchmark on the Fyre VM with
  the same per-user-token shape and at least 6–12 pods. Confirm whether
  RPS scales roughly linearly with pod count (it should, given per-pod
  CPU was nowhere near the headroom limit at 117 RPS).
- **Longer soak.** 60 s is a sanity check, not a steady-state measurement.
  10–30 minute runs would surface memory growth, connection-pool
  exhaustion, JWT-refresh-induced session-loss patterns.
- **Heavy upstream workload.** `fast_test_server` returns quickly. A
  real upstream MCP server (LLM, database tool, slow API) would expose
  whether per-pod asyncio concurrency holds up under realistic call
  durations.
- **Heavy-user concentration probe.** Deliberately drive one token at
  20× the average rate; observe whether the per-`$http_authorization`
  rate limit and per-pod backpressure behave correctly.
- **Apples-to-apples vs #4987.** Run the same per-user-token benchmark
  against the #4987 stack (3×24=72 workers, affinity on) for a true
  side-by-side at matching worker count.

## If picked back up

1. Add per-`$http_authorization` rate limit to `nginx-sticky-lb.conf`:
   ```nginx
   limit_req_zone $http_authorization zone=per_user:10m rate=200r/s;
   # in the MCP location blocks:
   limit_req zone=per_user burst=400 nodelay;
   ```
2. Scale the overlay to 6 or 9 single-worker pods, re-run the
   per-user-token benchmark, confirm linear RPS gain.
3. If the gain holds: promote to a real PR with the production-defaults
   discussion (when to choose sticky LB vs the #4987 affinity layer,
   based on deployment shape).
4. If a structural surprise appears at scale: document it here and
   reconsider Approach 1 vs the coordinator-worker direction
   (Approach 2) for high-scale deployments.

## Relationship to the parent experiment

The branch `experiment/sticky-lb-single-worker` documents the *failure*
mode of naive `hash $http_mcp_session_id` — useful as a record of why
the obvious approach doesn't work and what to try next. This branch
documents the working solution. Both are referenced from Approach 1 in
the [main architecture alternatives doc](../session-affinity-alternatives.md).
