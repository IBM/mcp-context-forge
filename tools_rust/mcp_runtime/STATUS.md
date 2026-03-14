# Rust MCP Runtime Status

Last updated: March 14, 2026

## Current snapshot

The Rust MCP runtime is now a real optional runtime slice in `ContextForge`,
not just a transport experiment.

Current top-level mode model:

- `RUST_MCP_MODE=off`
- `RUST_MCP_MODE=shadow`
- `RUST_MCP_MODE=edge`
- `RUST_MCP_MODE=full`

Current meaning:

- `off`: public MCP stays on Python
- `shadow`: Rust sidecar is present, but public `/mcp` stays on Python
- `edge`: public `/mcp` is routed directly to Rust
- `full`: `edge` plus Rust session/event-store/resume/live-stream/affinity
  cores

Python still remains the authority for:

- authentication
- token scoping
- RBAC
- trusted internal auth/context derivation
- fallback compatibility/business logic

## What is implemented

### Rust-owned today

- public `GET /mcp`, `POST /mcp`, and `DELETE /mcp` edge in `edge|full`
- MCP protocol/version validation
- JSON-RPC validation and batch rejection
- local `ping`
- notification transport semantics
- direct `tools/call` fast path with reusable upstream sessions
- optional `rmcp` upstream client path
- server-scoped direct fast paths for:
  - `tools/list`
  - `resources/list`
  - `resources/read`
  - `resources/templates/list`
  - `prompts/list`
  - `prompts/get`
- in `full` mode:
  - runtime session metadata
  - Redis-backed event store and replay
  - public resumable `GET /mcp`
  - public live-stream `GET /mcp`
  - affinity forwarding edge

### Python-owned today

- trusted internal MCP authenticate endpoint
- auth cache and revocation/user/team lookups
- token scoping and RBAC decisions
- fallback dispatcher/business logic where Rust deliberately bails out for
  parity
- parts of the underlying stream/session behavior behind the trusted internal
  bridge

## Session/auth reuse status

Session-auth reuse is implemented.

Current behavior:

- public Rust ingress still treats Python as the auth authority
- after `initialize`, Rust can bind the encoded auth context to the runtime
  session
- reuse is only allowed when:
  - the session exists
  - the server scope still matches
  - the auth-binding fingerprint still matches
  - the reuse TTL has not expired

This logic is enforced in:

- [authenticate_public_request_if_needed](src/lib.rs)
- [validate_runtime_session_request](src/lib.rs)
- [runtime_session_allows_access](src/lib.rs)
- [maybe_bind_session_auth_context](src/lib.rs)

The safe fallback still exists:

- `RUST_MCP_MODE=shadow` keeps public MCP on Python
- `RUST_MCP_SESSION_AUTH_REUSE=false` remains an advanced override for
  explicitly testing away from the default fast path

## Validation status

### Rust-local validation on the current tree

Verified locally and currently green:

- `make -C tools_rust/mcp_runtime fmt-check`
- `make -C tools_rust/mcp_runtime check`
- `make -C tools_rust/mcp_runtime clippy`
- `make -C tools_rust/mcp_runtime clippy-all`
- `make -C tools_rust/mcp_runtime test`
- `make -C tools_rust/mcp_runtime test-rmcp`

### Latest compose-backed MCP/runtime validation on this branch

Most recent rebuilt full-Rust compose validation on this branch:

- `make test-mcp-cli`
  - `23 passed`
- `make test-mcp-rbac`
  - `40 passed`
- `make test-mcp-session-isolation`
  - `7 passed`
- `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
  - `48 passed`
- `make test`
  - `14626 passed`
  - `485 skipped`
  - `19 warnings`

## Performance snapshot

These are branch-local measurements from rebuilt full-Rust compose runs and
should be treated as current engineering signals, not release targets.

### Recent tools-only measurements

- `60s / 1000 users`
  - `10454.16 RPS` overall
  - `9937.7 RPS` on `MCP tools/call [rapid]`
  - `0` failures
- `300s / 1000 users`
  - `6350.12 RPS` overall
  - `6045.2 RPS` on `MCP tools/call [rapid]`
  - `5` failures total

### Current throughput read

- short-run peak is much higher than sustained `5m` throughput
- the practical sustained sweet spot on the tools-only workload is about
  `1000` concurrent users
- `2000+` users are beyond the efficient knee for sustained tools-only load

### Current profiling read

The obvious Rust-specific setup bottleneck was already removed by reusing a
shared RMCP `reqwest 0.13` client. Current profiling points more at:

- syscall/network cost (`writev`, `futex`, `recvfrom`)
- broader system/upstream behavior
- remaining Rust <-> Python control/auth seam work

Notably, the earlier Rust-side TLS/client setup cost is no longer the main
runtime-specific hotspot.

## Known caveats

### 1. Python is still on the control/auth seam

Even in `edge|full`, Python still owns auth, RBAC, and the trusted internal
auth-context derivation step.

That means:

- the shared Python auth cache still matters
- reducing internal Rust -> Python control/auth hops remains a useful next
  optimization target

### 2. Mixed benchmarks are noisier than tools-only benchmarks

The tools-only benchmark targets are the cleanest transport/runtime signal.

The mixed benchmark targets exercise broader seeded fixture and data behavior.
If they fail, validate whether the issue is:

- a transport/runtime regression, or
- a seeded server/data issue on the benchmark fixture

before attributing the result to Rust MCP itself.

### 3. Session-auth reuse still needs more hardening coverage

The compose-backed isolation suite now proves the main hijack-deny paths, but
the following still need stronger automated coverage:

- revocation after initialize
- team membership / role changes after initialize
- explicit multi-worker affinity ownership under forced cross-worker routing
- multi-user load tests that validate correctness, not only throughput

See [TESTING-DESIGN.md](TESTING-DESIGN.md).

### 4. Broader UI flakiness is not a Rust-runtime signal

The wider Playwright suite still has broader repo instability/flakiness. That
should not be used as the primary signal for the MCP runtime slice unless the
failure path actually exercises `/mcp`.

## Recommended next steps

### 1. Add observability for the session-auth fast path

Add counters for:

- session-auth reuse hits
- session-auth reuse misses
- fallback reasons
- internal Python auth round-trips

### 2. Extend the isolation suite

Add explicit coverage for:

- revocation after initialize
- membership/role changes after initialize
- forced cross-worker affinity ownership
- multi-user load/correctness validation

### 3. Investigate residual long-run tools-only failures

The remaining low-rate failures in sustained tools-only runs are the clearest
quality issue left on the hot path.

### 4. Keep reducing avoidable seam work

The next meaningful gains are more likely to come from:

- removing remaining Rust -> Python control/auth round-trips
- trimming fallback frequency
- improving upstream server behavior

than from small Rust micro-optimizations inside the current crate.

## Related documents

- [Runtime overview and operator guide](README.md)
- [Session/auth isolation testing design](TESTING-DESIGN.md)
- [Rust MCP runtime architecture](../../docs/docs/architecture/rust-mcp-runtime.md)
- [ADR-043: Rust MCP runtime sidecar + mode model](../../docs/docs/architecture/adr/043-rust-mcp-runtime-sidecar-mode-model.md)
