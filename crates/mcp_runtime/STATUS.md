# Rust MCP Runtime Status

Last updated: March 15, 2026

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

Boot mode `edge` additionally supports an in-memory runtime override
(`shadow ↔ edge`) via `PATCH /admin/runtime/mcp-mode` and
`PATCH /admin/runtime/a2a-mode`. `off`, `shadow`, and `full` are not
flippable at runtime — `off` has no Rust sidecar to swap to, `shadow` did
not opt into the session-auth-reuse / delegate-enabled safety invariant
that routing public traffic to Rust requires, and `full` would require
live migration of Rust-owned MCP session/event-store cores. When Redis is
available the override propagates to the whole cluster; otherwise it stays
local to the pod that received the PATCH.

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

- `make -C crates/mcp_runtime fmt-check`
- `make -C crates/mcp_runtime check`
- `make -C crates/mcp_runtime clippy`
- `make -C crates/mcp_runtime clippy-all`
- `make -C crates/mcp_runtime test`
- `make -C crates/mcp_runtime test-rmcp`

### Latest compose-backed MCP/runtime validation on this branch

Most recent rebuilt full-Rust compose validation on this branch:

- `make test-mcp-cli`
  - `23 passed`
- `make test-mcp-rbac`
  - `40 passed`
- `make test-mcp-plugin-parity`
  - plugin-parity gate is green in both Python mode and Rust full mode
  - live coverage now includes:
    - `resources/read` with `LicenseHeaderInjector`
    - `tools/call` with `TestToolOutputSentinelPlugin`
    - `prompts/get` with `PromptOutputSentinelPlugin`
- `make test-mcp-session-isolation`
  - `10 passed`
- `make test-mcp-session-isolation-load`
  - dedicated Rust-only Locust correctness harness
  - validate with a short session-auth reuse TTL during release-style checks
- `cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml`
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

### 3. Session-auth reuse is still TTL-based

The isolation and correctness coverage is much stronger now:

- revocation-after-initialize is covered with a bounded TTL contract
- team membership removal and role revocation are covered with the same bounded
  TTL contract
- forced cross-worker affinity ownership is covered in Rust integration tests
- there is now a dedicated multi-user correctness load harness

The remaining caveat is architectural, not missing test coverage:

- session-auth reuse still depends on a bounded reuse TTL and therefore does
  not react instantly to revocation without another Python auth check

See [TESTING-DESIGN.md](TESTING-DESIGN.md).

### 4. Broader UI flakiness is not a Rust-runtime signal

The wider Playwright suite still has broader repo instability/flakiness. That
should not be used as the primary signal for the MCP runtime slice unless the
failure path actually exercises `/mcp`.

### 5. Prompt deny-path parity is still follow-up work

Prompt happy-path correctness is now covered and release-gated:

- `prompts/get` succeeds on both Python mode and Rust full mode under the
  plugin-parity stack
- the prompt post-fetch sentinel plugin is exercised live in both modes
- malformed prompt argument shapes now return a structured MCP `-32602` error
  on the Rust public path instead of an opaque backend decode failure

The remaining prompt caveat is narrower:

- blocked `prompts/get` parity is still noisy on the Python side and remains
  tracked as follow-up work rather than a Rust MCP correctness gap

## Code review follow-up

The March 15, 2026 review in [todo/code-review.md](../../todo/code-review.md)
identified a mix of real vulnerabilities, performance issues, and longer-term
design tradeoffs.

### Addressed in the current branch

- public ingress now strips client-supplied internal auth headers before the
  Rust -> Python auth hop
- public ingress no longer trusts client-supplied `x-contextforge-server-id`
  and only uses trusted routing state for server-scoped dispatch
- internal auth handoff now uses the actual peer address and does not default a
  missing client IP to loopback
- the direct public Rust listener now exposes a dedicated public router and no
  longer exposes internal event-store routes
- upstream tool-session initialization no longer holds the shared mutex across
  HTTP I/O
- local in-memory runtime caches now have periodic sweeping and expiry cleanup
- Redis affinity keys/channels now honor the configured cache prefix
- runtime session counting in Redis now uses `SCAN` instead of `KEYS`
- the direct public Rust listener now returns a minimal public health payload
  instead of the detailed internal runtime view
- runtime/proxy transport failures now log full exception details server-side
  while returning redacted client-visible error data
- Rust direct DB mode now supports optional PostgreSQL TLS via
  `MCP_RUST_DATABASE_URL` / `sslmode=disable|prefer|require`, while preserving
  the existing non-TLS local/test path
- Rust `/health` now exposes runtime fast-path observability counters for:
  - session-auth reuse hits and misses
  - miss reasons
  - internal Python auth round-trips
  - session access denial reasons
  - affinity forward attempts and forwarded requests
- the compose-backed Rust isolation suite now includes bounded-TTL coverage for:
  - token revocation after initialize
  - team membership removal after initialize
  - team role revocation after initialize
- the Rust integration suite now includes forced cross-worker affinity
  ownership validation
- a dedicated Rust-only correctness load harness now exists at
  `tests/loadtest/locustfile_mcp_isolation.py`

### Still open / follow-up

- `session_id` query-parameter compatibility still exists in both Rust and
  Python; this branch documents it as compatibility debt rather than making a
  breaking behavior change
- the new Rust access-matrix coverage shows that non-admin scoped tokens can
  initialize and read on `/servers/{id}/mcp`, but are still denied at
  `tools/call` even when the token includes `tools.execute`; this needs a
  product/RBAC follow-up to decide whether that restriction is intentional
- Rust direct DB mode still does not support client certificate authentication
  via `sslcert` / `sslkey`; the current TLS support covers the common
  `sslmode=require`/system-roots path and optional `sslrootcert`
- catch-all `sampling/`, `completion/`, `logging/`, and `elicitation/` methods
  still return an empty success object; that appears to be existing project
  behavior, but it should be documented or revisited
- session-auth reuse is still TTL-based and therefore does not immediately
  react to revocation events without a fresh Python auth check
- broader Python MCP handlers outside the Rust runtime proxy still need their
  own repository-wide error-redaction pass

## Recommended next steps

### 1. Investigate residual long-run tools-only failures

The remaining low-rate failures in sustained tools-only runs are the clearest
quality issue left on the hot path.

### 2. Use the new runtime stats to keep reducing avoidable seam work

The next meaningful gains are more likely to come from:

- removing remaining Rust -> Python control/auth round-trips
- trimming fallback frequency
- improving upstream server behavior

than from small Rust micro-optimizations inside the current crate.

### 3. Decide the `session_id` compatibility strategy

This branch intentionally does not make breaking Python behavior changes. The
remaining decision is whether to:

- keep the query-parameter fallback as an explicit compatibility exception, or
- deprecate it and later retire it across both Rust and Python

### 4. Decide whether Rust needs DB client-certificate TLS

The common PostgreSQL TLS path is now supported. Only the `sslcert` / `sslkey`
client-certificate mode remains unimplemented.

## Related documents

- [Runtime overview and operator guide](README.md)
- [Session/auth isolation testing design](TESTING-DESIGN.md)
- [Rust MCP runtime architecture](../../docs/docs/architecture/rust-mcp-runtime.md)
- [ADR-043: Rust MCP runtime sidecar + mode model](../../docs/docs/architecture/adr/043-rust-mcp-runtime-sidecar-mode-model.md)

## Next steps checklist

This PR should stay open until the Rust MCP path is revalidated against the
items below and any remaining issues are either fixed or explicitly understood.

- [ ] Re-run the full Rust validation battery on the exact PR head after each
  substantive change:
  - `make testing-rebuild-rust-full`
  - `make test`
  - `make test-mcp-cli`
  - `make test-mcp-rbac`
  - `make test-mcp-session-isolation`
  - `cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml`
- [x] Add observability for the session-auth fast path:
  - reuse hits
  - reuse misses
  - fallback-to-Python reasons
  - owner mismatch denials
  - server-id mismatch denials
  - internal Python auth round-trips
- [x] Extend the isolation suite with explicit revocation-after-initialize
  coverage.
- [x] Extend the isolation suite with explicit membership/role-change coverage
  after initialize.
- [x] Add forced cross-worker affinity ownership coverage so forwarded and
  local handling prove the same ownership rules.
- [x] Add a dedicated multi-user load/correctness harness separate from the
  throughput benchmarks.
- [ ] Investigate and explain the remaining low-rate failures in sustained
  tools-only runs.
- [ ] Use the new observability to identify and reduce avoidable Rust -> Python
  control/auth seam work before attempting more micro-optimizations inside the
  crate.
- [ ] Re-run the sustained tools-only benchmark after each meaningful
  control/auth seam change:
  - `make benchmark-mcp-tools-300 MCP_BENCHMARK_HIGH_USERS=1000 MCP_BENCHMARK_HIGH_RUN_TIME=300s`
- [ ] Keep broader Playwright/admin UI flakiness tracked separately unless the
  failing path clearly exercises `/mcp`.
- [ ] Do not merge until the MCP/Rust-specific validation, isolation tests, and
  benchmark results are green and understood.
