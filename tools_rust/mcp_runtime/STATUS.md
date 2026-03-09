# Rust MCP Runtime Status

Last updated: March 9, 2026
Current reference commit: `2f31415e1`

## Executive Summary

The Rust MCP runtime is now a real, integrated stage-1 implementation, not just a throwaway prototype.

Today it successfully owns the MCP HTTP transport edge for `POST /mcp` when
`EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`, while Python still owns:

- auth and RBAC
- path rewriting and some request shaping
- business execution behind `/rpc`
- MCP session management for non-`POST` transport flows

In practice, this means:

- Rust is already on the hot path for `ping`, `initialize`, `tools/list`, `tools/call`, `resources/list`, `prompts/list`, and similar JSON-RPC `POST /mcp` traffic
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
- forwarding of non-local methods to Python `/rpc`
- response stamping with `x-contextforge-mcp-runtime: rust`
- stripping of internal-only forwarded headers
- info-level request logging when `MCP_RUST_LOG=info`

### Gateway integration

Integrated in the main application:

- Python mounts a hybrid MCP transport app
- `POST /mcp` is proxied to the Rust runtime when enabled
- non-`POST` MCP traffic still falls back to the Python transport
- `/servers/<id>/mcp` requests preserve semantics by injecting `server_id` before `/rpc`
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
- protocol-version compatibility checks
- JSON-RPC envelope validation
- notification response semantics
- local `ping`
- backend proxying to Python `/rpc`
- runtime-level response header stamping

### Python-owned today

- authentication
- token scoping
- RBAC
- server/path semantics before Rust proxy handoff
- `/rpc` business logic and MCP operation execution
- session registry
- SSE/resumable stream management
- non-`POST` Streamable HTTP transport behavior
- upstream MCP federation/client logic

### Important consequence

This is not yet a full Rust rewrite of MCP in ContextForge.

It is a transport-edge replacement for the `POST /mcp` JSON-RPC path, with Python still acting as the execution core behind `/rpc`.

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

Rust currently forwards most work to Python `/rpc`.

That means:

- Rust does not yet reduce Python business-logic coupling much
- the current performance gains are mostly transport-edge gains
- the real modularity win still requires extracting a cleaner dispatcher/core contract

### 3. Wider regression coverage is still in progress

As of March 9, 2026:

- `mcp-cli` E2E is green
- direct live Rust-path checks are green
- `make test-ui-headless` is still being exercised externally
- `make test-mcp-rbac` was started against the Rust-enabled stack and early discovery/listing coverage passed, but failures appeared later in the call-path portion and that investigation was interrupted before completion

So the Rust transport edge is proven on the main MCP CLI path, but wider regression parity is not yet fully signed off.

### 4. Startup noise in compose

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

### Phase 2: remove Python `/rpc` coupling

Next architectural step:

- extract a shared internal MCP dispatcher contract from Python `/rpc`
- point both Python transport and Rust runtime at the same execution contract
- stop treating `/rpc` as the long-term internal interface

This is the step that turns the current transport-edge replacement into real modularization.

### Phase 3: move session orchestration

Then:

- move Streamable HTTP session handling into Rust
- implement resumable session behavior in Rust
- replace more of the Python session registry transport path

### Phase 4: move execution primitives

After the dispatcher seam is real:

- move `tools/list`
- move `tools/call`
- move `resources/list`
- move `prompts/list`
- move more direct MCP response shaping into Rust

## How To Run

### Local crate only

```bash
cd tools_rust/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/rpc \
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
docker compose --profile testing up -d --force-recreate gateway nginx
```

Optional runtime tuning:

```bash
MCP_RUST_LOG=info
MCP_RUST_LISTEN_HTTP=127.0.0.1:8787
MCP_RUST_BACKEND_RPC_URL=http://127.0.0.1:4444/rpc
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

### 2. Check the logs

```bash
docker compose logs -f gateway | rg "rust_mcp_runtime method="
```

Expected examples:

```text
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

### End-to-end MCP CLI

```bash
MCP_CLI_BASE_URL=http://localhost:8080 \
JWT_SECRET_KEY=my-test-key \
PLATFORM_ADMIN_EMAIL=admin@example.com \
MCP_CLI_TIMEOUT=60 \
uv run pytest tests/e2e/test_mcp_cli_protocol.py -v -s --tb=short
```

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
