# Rust MCP Runtime Status

Last updated: March 9, 2026

Status focus in this update:

- Unix domain socket handoff between Python and the managed Rust sidecar
- a narrower trusted internal dispatcher route at `/_internal/mcp/rpc`
- forwarded MCP auth context instead of recomputing auth on the internal hop
- updated live load-test baseline before moving any DB reads into Rust

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

### Important test hygiene note

The first post-rebase comparison attempt produced invalid results because server-scoped MCP discovery briefly fell back to global discovery after an overly strict backend trust check for the internal `server_id` header.

Symptoms were:

- `tools/list` on `/servers/<id>/mcp` returning global tools/resources/prompts instead of the selected server scope
- `resources/read` failures in Locust because discovery and execution no longer matched

That bug was fixed by making `/rpc` honor `x-contextforge-server-id` whenever the request is marked as coming from the Rust runtime via `x-contextforge-mcp-runtime: rust`.

### Current measured impact of the latest seam optimization

The latest optimization stack was:

- narrower internal Python dispatcher at `/_internal/mcp/rpc`
- trusted forwarded MCP auth context
- no Python JSON body rewriting for `/servers/<id>/mcp`
- UDS between Python and the managed Rust sidecar

These numbers are the current live baseline on the server-scoped fast-time target, using 30-second Locust runs following `todo/performance/reproduce-testing.md`.

Current measured baseline:

```text
Users | RPS    | Avg(ms) | p95 | p99 | Failures
50    | 424.82 | 20.81   | 29  |  88 | 1.67%
100   | 738.44 | 38.40   | 65  | 150 | 1.91%
```

Failure caveat:

- the failures are all `resources/read`
- they trace to duplicate seeded resource URIs on the benchmark server
- they are not specific to the new Rust seam

For context, the previous pre-UDS/header-forward baseline on the same broad server-scoped path was:

```text
Users | RPS    | Avg(ms) | p95 | p99 | Failures
50    | 363.81 | 29.93   | 64  | 110 | 0%
100   | 672.11 | 48.59   | 86  | 200 | 0%
```

Interpretation:

- at 50 users, the current stack is about `+16.8%` RPS with materially lower average latency
- at 100 users, the current stack is about `+9.9%` RPS with materially lower average latency
- the comparison is directionally useful, but not perfectly apples-to-apples because the seeded `resources/read` issue polluted the latest run

Conclusion:

- the seam optimization is worth keeping
- the current bottleneck is still the Python/Rust handoff and Python backend dispatcher, not the Rust transport shell itself
- there is still substantial headroom before Rust can show its full value because most MCP execution work remains in Python

### Next performance steps in priority order

1. Keep the new UDS and internal-dispatch seam as the baseline; do not add Rust DB access until this path is fully characterized.
2. Make the internal dispatcher narrower than generic JSON-RPC.
   - pass method-specific internal payloads instead of a full `/rpc` envelope where practical
   - avoid more Python envelope shaping than strictly necessary
3. Let Rust own the mounted server-scoped MCP path directly.
   - today Python still mounts `/servers/<id>/mcp` and translates path context into internal headers
4. Fix or replace the seeded benchmark server so `resources/read` stops polluting load-test comparisons.
5. Move read-heavy MCP methods first:
   - `tools/list`
   - `resources/list`
   - `prompts/list`
   - optionally `resources/templates/list`
6. After that, revisit deeper Rust-side JSON parsing micro-optimizations only if profiling still points there.

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

It is not yet the complete MCP implementation for ContextForge.

The remaining work is mostly:

- parity hardening across broader test suites
- replacing the Python `/rpc` coupling with a cleaner internal dispatcher seam
- moving session orchestration and more MCP execution logic into Rust

That is a credible migration path. The current implementation is strong stage-1 infrastructure, not yet the final Rust end state.
