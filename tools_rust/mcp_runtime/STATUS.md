# Rust MCP Runtime Status

Last updated: March 9, 2026

Status focus in this update:

- Unix domain socket handoff between Python and the managed Rust sidecar
- a narrower trusted internal dispatcher route at `/_internal/mcp/rpc`
- forwarded MCP auth context instead of recomputing auth on the internal hop
- the final no-DB optimization pass before moving read-only DB paths into Rust

## Executive Summary

The Rust MCP runtime is now a real, integrated stage-1 implementation, not just a throwaway prototype.

Today it successfully owns the MCP HTTP transport edge for `POST /mcp` when
`EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`, while Python still owns:

- auth and RBAC
- business execution behind the internal MCP dispatcher
- MCP session management for non-`POST` transport flows

In practice, this means:

- Rust is already on the hot path for `ping`, `initialize`, `tools/list`, `tools/call`, `resources/list`, `prompts/list`, and similar JSON-RPC `POST /mcp` traffic
- Python no longer reparses and rewrites server-scoped MCP JSON bodies just to inject `server_id`
- the managed Python -> Rust hop can now run over a Unix domain socket instead of loopback TCP
- Python forwards a trusted auth context to the internal dispatcher, so auth and RBAC stay Python-owned without being recomputed on the internal hop
- the trusted internal MCP dispatcher now owns its SQLAlchemy session directly instead of paying FastAPI `Depends(get_db)` overhead on every Rust-backed call
- trusted Rust -> Python MCP dispatch no longer re-runs Pydantic `RPCRequest` validation that Rust already performed
- Rust is not yet the full MCP implementation for resumable Streamable HTTP or SSE/session orchestration
- the current cut is viable, testable, containerized, and live behind an experimental flag

## What Is Implemented

### Runtime crate

Implemented in this crate:

- `GET /health`
- `GET /healthz`
- `POST /rpc`
- `POST /rpc/`
- `POST /mcp`
- `POST /mcp/`
- MCP protocol-version validation
- support for current compatibility versions:
  - `2025-11-25`
  - `2025-06-18`
  - `2025-03-26`
  - `2024-11-05`
- JSON-RPC parsing and validation
- JSON-RPC batch rejection
- `initialize` parameter validation
- local handling for `ping`
- notification handling with HTTP `202 Accepted`
- forwarding of non-local methods to Python over the configured backend RPC URL
- response stamping with `x-contextforge-mcp-runtime: rust`
- stripping of internal-only forwarded headers
- info-level request logging when `MCP_RUST_LOG=info`

### Gateway integration

Integrated in the main application:

- Python mounts a hybrid MCP transport app
- `POST /mcp` is proxied to the Rust runtime when enabled
- non-`POST` MCP traffic still falls back to the Python transport
- `/servers/<id>/mcp` requests preserve semantics by carrying `server_id` across the Python -> Rust -> Python seam via `x-contextforge-server-id`
- Python can connect to the managed Rust runtime over `EXPERIMENTAL_RUST_MCP_RUNTIME_UDS`
- the managed Rust runtime can listen on `MCP_RUST_LISTEN_UDS`
- Rust now forwards backend calls to `/_internal/mcp/rpc` instead of the public `/rpc` route
- Python forwards a trusted internal MCP auth blob via `x-contextforge-auth-context`
- the proxy strips forwarded-chain headers like `x-forwarded-for` before the internal Rust -> Python hop so loopback trust stays real
- the internal Rust-backed MCP route now creates its own `SessionLocal()` session instead of using FastAPI `Depends(get_db)`
- trusted internal dispatch now lazily materializes lowered request headers only for branches that actually need them
- the managed sidecar can be launched from `docker-entrypoint.sh`
- `Containerfile.lite` includes the Rust runtime binary when built with `ENABLE_RUST=true`
- `docker-compose.yml` exposes the Rust runtime env vars, including `MCP_RUST_LOG`

### Observability

Current observability features:

- every Rust-owned MCP response includes:
  - `x-contextforge-mcp-runtime: rust`
- the runtime logs handled methods at `info`, for example:
  - `rust_mcp_runtime method=ping mode=local`
  - `rust_mcp_runtime method=tools/list mode=backend-forward`
  - `rust_mcp_runtime method=tools/call mode=backend-forward`

This is the cleanest proof that live requests are actually traversing Rust.

## Current Architecture Boundary

### Rust-owned today

- outer HTTP MCP runtime shell for `POST /mcp`
- optional UDS listener for the managed sidecar
- protocol-version compatibility checks
- JSON-RPC envelope validation
- notification response semantics
- local `ping`
- backend proxying to Python `/_internal/mcp/rpc`
- runtime-level response header stamping

### Python-owned today

- authentication and token verification on the public MCP transport
- token scoping normalization
- RBAC decision-making
- creation of the forwarded internal auth context
- business execution behind the internal MCP dispatcher
- session registry
- session pool ownership
- Redis-backed caches and eventing
- SSE/resumable stream management
- non-`POST` Streamable HTTP transport behavior
- upstream MCP federation/client logic

### Redis / cache boundary

Redis is still entirely Python-owned today. That is intentional for this phase.

Relevant MCP-path components that still live in Python:

- auth cache in [`mcpgateway/cache/auth_cache.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/auth_cache.py)
- registry cache for tools/resources/prompts in [`mcpgateway/cache/registry_cache.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/registry_cache.py)
- session registry in [`mcpgateway/cache/session_registry.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/cache/session_registry.py)
- MCP session pool setup in [`mcpgateway/main.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/main.py)
- Redis event store for resumable Streamable HTTP in [`mcpgateway/transports/redis_event_store.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/transports/redis_event_store.py)
- cancellation pub/sub in [`mcpgateway/services/cancellation_service.py`](/home/cmihai/agents2/pr/mcp-context-forge/mcpgateway/services/cancellation_service.py)

Implication:

- the UDS and internal-dispatch optimization preserves existing Redis-assisted behavior
- moving read-only MCP list methods into Rust later will require a deliberate cache strategy instead of accidentally bypassing Python’s Redis caches

### Important consequence

This is not yet a full Rust rewrite of MCP in ContextForge.

It is a transport-edge replacement for the `POST /mcp` JSON-RPC path, with Python still acting as the execution core behind a trusted internal MCP dispatcher.

That is intentional. It gives a low-risk seam that already works while keeping the next migration steps clear.

## Proven Working

The following have been validated successfully against the Rust-enabled path.

### Unit and crate tests

Validated:

- `cargo test --release` in `tools_rust/mcp_runtime`
- unit tests for the Python Rust proxy transport

These currently cover:

- `ping` handled locally
- header propagation
- runtime response header presence
- unsupported protocol version rejection
- notification `202 Accepted`
- `initialize` validation
- batch rejection
- `/mcp` aliasing
- stripping spoofed internal headers

### mcp-cli end-to-end

Validated on March 9, 2026:

- `tests/e2e/test_mcp_cli_protocol.py`
- result: `22 passed`

This exercised the live path:

- `mcp-cli`
- `mcpgateway.wrapper`
- gateway `/mcp`
- Rust runtime
- Python `/rpc`

### Live compose validation

Validated on March 9, 2026:

- rebuilt `Containerfile.lite` image with `ENABLE_RUST=true`
- started compose stack with:
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`
- confirmed live response header:
  - `x-contextforge-mcp-runtime: rust`
- confirmed live runtime logs for:
  - `ping`
  - `initialize`
  - `tools/list`
  - `tools/call`
  - `resources/list`
  - `prompts/list`

## Still Missing

The major missing items are structural, not cosmetic.

### Transport parity gaps

Not yet in Rust:

- `GET /mcp` session-management behavior
- `DELETE /mcp` session teardown behavior
- resumable Streamable HTTP semantics
- SSE event streaming orchestration
- Python `StreamableHTTPSessionManager` replacement

### Core execution gaps

Not yet moved into Rust:

- direct Rust ownership of `tools/list`
- direct Rust ownership of `tools/call`
- direct Rust ownership of `resources/*`
- direct Rust ownership of `prompts/*`
- a narrower internal dispatcher contract than Python `/rpc`

### Security/control-path gaps

Still Python-owned:

- auth enforcement
- token team normalization
- RBAC permission checks
- server-scoped execution policies
- OAuth-related MCP/session policies

These are not accidental omissions. They are part of the current staged migration boundary.

## Known Risks / Open Issues

### 1. Rust is only on `POST /mcp`

This is the most important current limitation.

If a flow depends on MCP `GET`/`DELETE` session-management behavior, it is still using Python transport code.

### 2. `/rpc` is still the real backend contract

Rust no longer needs the public `/rpc` route, but it still forwards most work to Python in a JSON-RPC-shaped backend contract.

That means:

- Rust does not yet reduce Python business-logic coupling much
- the current performance gains are mostly transport-edge gains
- the real modularity win still requires extracting a cleaner dispatcher/core contract than a generic JSON-RPC passthrough

### 3. Performance is still dominated by the seam

The highest-leverage performance work so far has not been inside Rust business logic.

It has been reducing avoidable Python work around the Rust edge:

- Rust backend responses now stream back to the client instead of buffering in Python first
- Python no longer reparses and rewrites JSON request bodies just to attach `server_id` for `/servers/<id>/mcp`
- server scope now crosses the seam in an internal header instead of a body mutation
- the managed sidecar can now use UDS instead of loopback HTTP
- public transport auth is now forwarded as a trusted internal context instead of being recomputed on the internal backend hop
- the trusted internal dispatcher no longer pays `Depends(get_db)` setup/teardown overhead on every Rust-backed call
- trusted internal dispatch no longer revalidates JSON-RPC envelopes that Rust already validated

This matters because the load-test target in `tests/loadtest/locustfile_mcp_protocol.py` is the server-scoped MCP path, so every unnecessary parse/serialize on that path shows up directly in throughput and latency.

### 4. Benchmark noise still exists in seeded data

The current compose seed data on the fast-time server includes duplicate resource URIs.

That means `resources/read` is currently a noisy benchmark signal, independent of the Rust seam:

- `resources/list` succeeds through Rust
- manual `resources/read` on the same server returns:
  - `Multiple rows were found when one or none was required`
- Locust records that as JSON-RPC `-32000 Internal error`

This is a correctness issue in the seeded benchmark fixture, not evidence that the UDS/internal-dispatch seam broke `resources/read`.

### 5. Wider regression coverage is still in progress

As of March 9, 2026:

- `mcp-cli` E2E is green
- direct live Rust-path checks are green for:
  - `/mcp`
  - `/servers/<id>/mcp initialize`
  - `/servers/<id>/mcp tools/list`
  - `/servers/<id>/mcp tools/call`
- `make test-ui-headless` is still being exercised externally
- `make test-mcp-rbac` was started against the Rust-enabled stack and early discovery/listing coverage passed, but failures appeared later in the call-path portion and that investigation was interrupted before completion

So the Rust transport edge is proven on the main MCP CLI path, but wider regression parity is not yet fully signed off.

### 5. Startup noise in compose

The current compose stack still emits pre-existing bootstrap duplicate-key warnings during startup in some seeded environments.

Those warnings did not prevent:

- healthy containers
- Rust-side request handling
- `mcp-cli` success

But they do make debugging noisier than it should be.

## Recommended Next Steps

### Phase 1: finish parity hardening

Immediate priorities:

- finish `make test-mcp-rbac` investigation and fix any Rust-path regressions
- finish `make test-ui-headless` validation against the Rust-enabled stack
- add more explicit integration tests proving Rust is used for:
  - `initialize`
  - `tools/call`
  - server-scoped `/servers/<id>/mcp`
- add regression coverage for non-`POST` fallback behavior so the hybrid boundary stays intentional
- keep validating load runs with an explicit server-scope sanity check before each run, so benchmark results are not polluted by accidental global discovery

## Performance Investigation Update

### What was tested on the rebased branch

Using the load-test tooling now on `origin/main`:

- `tests/loadtest/locustfile_mcp_protocol.py`
- direct `locust` runs following `todo/performance/reproduce-testing.md`
- live compose stack built from the rebased image with:
  - `ENABLE_RUST_BUILD=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
  - `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`

### What profiling showed

A short live `py-spy` sample on a loaded gunicorn worker was noisy, but directionally useful:

- the worker spent most sampled time inside AnyIO / threadpool worker activity rather than in the Rust sidecar
- that pointed at Python request/dependency machinery as the next no-DB optimization target
- the biggest actionable item from that result was removing FastAPI `Depends(get_db)` from the trusted internal MCP route

### Important test hygiene note

The first post-rebase comparison attempt produced invalid results because server-scoped MCP discovery briefly fell back to global discovery after an overly strict backend trust check for the internal `server_id` header.

Symptoms were:

- `tools/list` on `/servers/<id>/mcp` returning global tools/resources/prompts instead of the selected server scope
- `resources/read` failures in Locust because discovery and execution no longer matched

That bug was fixed by making `/rpc` honor `x-contextforge-server-id` whenever the request is marked as coming from the Rust runtime via `x-contextforge-mcp-runtime: rust`.

### Current measured impact of the latest no-DB seam optimization batch

The latest optimization stack is now:

- narrower internal Python dispatcher at `/_internal/mcp/rpc`
- trusted forwarded MCP auth context
- no Python JSON body rewriting for `/servers/<id>/mcp`
- UDS between Python and the managed Rust sidecar
- admin-permission short-circuit after token-scope enforcement
- direct `SessionLocal()` management on the trusted internal Rust -> Python MCP route
- no Pydantic `RPCRequest` validation on trusted internal dispatch
- lazy lower-casing of request headers only when needed
- conversion of several hot-path f-string logs to lazy logging calls
- dedicated internal `/_internal/mcp/tools/list` path for server-scoped discovery
- lean `tool_service.list_server_mcp_tool_definitions(...)` output that skips `ToolRead` conversion
- Rust-side specialized mode logging: `rust_mcp_runtime method=tools/list mode=backend-tools-list-direct`
- container launch hardening so an empty `MCP_RUST_LISTEN_UDS` env no longer breaks the managed sidecar startup

These numbers are from live server-scoped `100 users / 30s` Locust runs following `todo/performance/reproduce-testing.md`.

Repeated pre-batch runs on the same rebuilt Rust-enabled stack settled around:

```text
Run | RPS    | Avg(ms) | p95 | p99 | Failures
1   | 671.73 | 51.48   | 84  | 210 | 1.88%
2   | 671.64 | 52.51   | 91  | 200 | 1.95%
```

Post-batch runs on the same stack:

```text
Run | RPS    | Avg(ms) | p95 | p99 | Failures
1   | 692.41 | 41.07   | 69  | 190 | 1.88%
2   | 722.22 | 41.05   | 69  | 160 | 1.92%
```

Failure caveat for all of these runs:

- the failures are all `resources/read`
- they trace to duplicate seeded resource URIs on the benchmark server
- they are not specific to the new Rust seam

Interpretation:

- the repeated pre-batch baseline is about `672 RPS`
- the first post-batch run is about `+3.1%` RPS with about `-20%` average latency
- the warmed post-batch rerun is about `+7.5%` RPS with about `-22%` average latency and materially lower `p95` / `p99`
- the warmed best run is still slightly below the earlier one-off `738 RPS` UDS/header-forward peak, so that earlier number should be treated as a high-water mark, not the stable baseline

Conclusion:

- this non-DB optimization batch is worth keeping
- the current stable improvement comes from removing Python internal-dispatch overhead, not from changing Rust transport parsing
- the current bottleneck is still Python-owned execution and data access behind the Rust edge
- there is still headroom, but the remaining big wins are now unlikely to come from more Python-side no-DB micro-optimizations

### Follow-up result: dedicated server-scoped `tools/list` seam

After the generic `/_internal/mcp/rpc` trimming work, one more Python-owned seam optimization was added:

- server-scoped `tools/list` now goes to `/_internal/mcp/tools/list`
- Python still owns auth/RBAC and DB access for that path
- Rust no longer forwards that method through the generic JSON-RPC switch
- Python no longer builds full `ToolRead` models for this path

Live validation on the rebuilt Rust-enabled compose stack:

- public MCP responses still include `x-contextforge-mcp-runtime: rust`
- gateway logs now show:

```text
rust_mcp_runtime method=tools/list mode=backend-tools-list-direct
```

- full `tests/e2e/test_mcp_cli_protocol.py` still passes against the rebuilt image (`22 passed`)

Measured `100 users / 30s` runs after this dedicated `tools/list` cut:

```text
Run | RPS    | Avg(ms) | p95 | p99 | Failures
1   | 672.23 | 45.01   | 83  | 180 | 1.94%
2   | 700.04 | 45.94   | 87  | 170 | 1.86%
```

Endpoint-level effect from the warmed second run:

- `MCP tools/list`: `51.87 RPS`, `28.8ms avg`, `130ms p99`
- `MCP tools/list [churn]`: `31.48 RPS`, `28.9ms avg`, `110ms p99`
- `MCP tools/list [rapid]`: `11.34 RPS`, `27.8ms avg`, `80ms p99`

Interpretation:

- this seam is correct, live, and leaner than the generic `/rpc` path
- it improves the `tools/list` slice, but it does **not** materially move the full protocol mix by itself
- that is expected because `tools/call` remains the dominant request class in the load test
- this is the clearest point where further Python-owned no-DB seam work has diminishing returns

### Next performance steps in priority order

1. Keep this no-DB seam as the new baseline.
2. Fix or replace the seeded benchmark server so `resources/read` stops polluting load-test comparisons.
3. Start the first Rust-owned read-only DB path with server-scoped `tools/list`.
   - preserve Python auth/RBAC ownership first
   - keep Redis/session/cancellation out of scope for this cut
4. Then move the remaining read-heavy server-scoped MCP discovery methods into Rust with direct read-only Postgres access:
   - `resources/list`
   - `prompts/list`
   - `resources/templates/list`
5. Keep Redis/session/cancellation ownership in Python during that phase.
   - those are not the first methods to move
6. After the list/read path is Rust-owned, decide whether `initialize` stays Python-owned for session ownership semantics or gets a narrower Rust-aware session contract.
7. Only after that start carving `tools/call` out of Python.

The practical lesson from the latest run is simple:

- removing generic dispatcher overhead from Python helped
- removing a single read method from the generic dispatcher helped less than the earlier seam cuts
- the next meaningful gains now require Rust to own the actual read queries, not just the transport and routing shell

### Phase 2: remove Python `/rpc` coupling

Next architectural step:

- extract a shared internal MCP dispatcher contract from the current Python RPC handler
- point both Python transport and Rust runtime at the same execution contract
- stop treating a generic JSON-RPC passthrough as the long-term internal interface

This is the step that turns the current transport-edge replacement into real modularization.

### Phase 3: move session orchestration

Then:

- move Streamable HTTP session handling into Rust
- implement resumable session behavior in Rust
- replace more of the Python session registry transport path

### Phase 4: move execution primitives

After the dispatcher seam is real and the benchmark fixture is clean:

- move `tools/list`
- move `resources/list`
- move `prompts/list`
- move `resources/templates/list`
- then evaluate `tools/call`
- move more direct MCP response shaping into Rust

## How To Run

### Local crate only

```bash
cd tools_rust/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/_internal/mcp/rpc \
  --listen-http 127.0.0.1:8787
```

### Docker image

```bash
docker build --build-arg ENABLE_RUST=true -f Containerfile.lite .
```

### Compose stack

```bash
ENABLE_RUST_BUILD=true \
EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true \
EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true \
EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock \
MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock \
docker compose --profile testing up -d --force-recreate gateway nginx
```

Optional runtime tuning:

```bash
MCP_RUST_LOG=info
MCP_RUST_LISTEN_HTTP=127.0.0.1:8787
MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock
EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock
MCP_RUST_BACKEND_RPC_URL=http://127.0.0.1:4444/_internal/mcp/rpc
```

## How To Verify It Is Going Through Rust

### 1. Check the response header

Any Rust-owned MCP response should include:

```text
x-contextforge-mcp-runtime: rust
```

Example:

```bash
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 60 --secret my-test-key | tail -n1)

curl -i http://localhost:8080/mcp/ \
  -H 'content-type: application/json' \
  -H 'mcp-protocol-version: 2025-11-25' \
  -H "authorization: Bearer $TOKEN" \
  --data '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'
```

For the server-scoped path used by the MCP load test, a stronger verification is:

```bash
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 60 --secret my-test-key | tail -n1)
SERVER_ID=<server-id>

curl -s -X POST http://localhost:8080/servers/$SERVER_ID/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-protocol-version: 2024-11-05" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}' \
  | python3 -c 'import json,sys; data=json.load(sys.stdin); print(len(data.get("result",{}).get("tools",[])))'
```

If server scoping is correct, this should return the tool count for that specific virtual server, not the global registry.

### 2. Check the logs

```bash
docker compose logs -f gateway | rg "rust_mcp_runtime method="
```

Expected examples:

```text
Starting experimental Rust MCP runtime on unix:///tmp/contextforge-mcp-rust.sock
rust_mcp_runtime method=ping mode=local
rust_mcp_runtime method=initialize mode=backend-forward
rust_mcp_runtime method=tools/list mode=backend-forward
rust_mcp_runtime method=tools/call mode=backend-forward
```

### 3. Remember the current boundary

Only MCP `POST` traffic is on Rust today.

These still remain on Python:

- MCP `GET`
- MCP `DELETE`
- session-management flows

## Test Commands

### Fast checks

```bash
cd tools_rust/mcp_runtime
cargo test --release
```

```bash
uv run pytest -q tests/unit/mcpgateway/transports/test_rust_mcp_runtime_proxy.py
```

```bash
uv run pytest -q \
  tests/unit/mcpgateway/test_main_extended.py -k 'internal_mcp_rpc or rust_server_header or tools_list_server'
```

### End-to-end MCP CLI

```bash
MCP_CLI_BASE_URL=http://localhost:8080 \
JWT_SECRET_KEY=my-test-key \
PLATFORM_ADMIN_EMAIL=admin@example.com \
MCP_CLI_TIMEOUT=60 \
uv run pytest tests/e2e/test_mcp_cli_protocol.py -v -s --tb=short
```

### Reproduce the protocol load test directly

```bash
source .venv/bin/activate
MCP_SERVER_ID=<server-id> \
locust -f tests/loadtest/locustfile_mcp_protocol.py \
  --host=http://localhost:8080 \
  --users=100 \
  --spawn-rate=100 \
  --run-time=30s \
  --headless
```

If the current seeded fast-time server is used, expect `resources/read` failures until the duplicate-resource fixture issue is cleaned up.

### Broader regression suites

These are the next parity checks to keep running against the Rust-enabled stack:

```bash
make test-mcp-rbac
```

```bash
make test-ui-headless
```

If the local environment uses the repo-local virtualenv rather than `$(HOME)/.venv/mcpgateway`, make sure the Makefile environment is aligned before drawing conclusions from failures.

## Files That Matter Most

Primary implementation:

- `tools_rust/mcp_runtime/src/lib.rs`
- `tools_rust/mcp_runtime/src/config.rs`
- `tools_rust/mcp_runtime/tests/runtime.rs`

Python integration:

- `mcpgateway/transports/rust_mcp_runtime_proxy.py`
- `mcpgateway/main.py`
- `mcpgateway/config.py`
- `docker-entrypoint.sh`
- `Containerfile.lite`
- `docker-compose.yml`

## Bottom Line

The Rust MCP runtime is already real enough to use as the live `POST /mcp` transport edge.

It now also owns a specialized server-scoped `tools/list` routing path that bypasses the generic Python JSON-RPC dispatcher.

It is not yet the complete MCP implementation for ContextForge.

The remaining work is mostly:

- parity hardening across broader test suites
- moving the read-only discovery queries (`tools/list`, `resources/list`, `prompts/list`, `resources/templates/list`) into Rust with direct Postgres reads
- keeping Redis/session/cancellation Python-owned until the read path is solid
- only then moving session orchestration and heavier execution logic like `tools/call`

That is a credible migration path. The current implementation is strong stage-1 infrastructure, not yet the final Rust end state.
