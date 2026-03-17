# Rust MCP Runtime

The Rust MCP runtime is an optional sidecar/runtime path for ContextForge's
streamable HTTP MCP traffic. It is designed to move the public MCP hot path out
of Python incrementally while keeping Python authoritative for authentication,
token scoping, and RBAC.

It is also the first concrete precedent for the broader
[Modular Runtime Architecture](modular-design.md): a protocol-specific runtime
that can move out of the Python process while the core platform remains the
shared policy and control plane. The generalized implementor-facing contract
for future modules is documented in the
[Modular Runtime Specification](modular-runtime/index.md).

This page describes the current architecture and the supported rollout modes.

## Mode Model

The user-facing control is `RUST_MCP_MODE`:

| Mode | Public `/mcp` ingress | Rust session/event/resume/live-stream cores | Intended use |
|------|------------------------|--------------------------------------------|--------------|
| `off` | Python | No | Baseline Python MCP path |
| `shadow` | Python | No public Rust ownership | Safety-first rollback/comparison mode with Rust sidecar present |
| `edge` | Rust | No | Direct public Rust ingress with Python still backing more MCP internals |
| `full` | Rust | Yes | Fastest public Rust path with Rust-owned MCP session/runtime cores |

Use the testing stack wrappers to bring these up locally:

```bash
make testing-rebuild-rust-shadow
make testing-rebuild-rust
make testing-rebuild-rust-full
```

## Request Flows

### `off` and `shadow`

In `off` and `shadow`, the public MCP path remains Python-owned:

```text
client
  -> nginx
  -> Python gateway transport/auth/token scoping/RBAC
  -> Python MCP handlers
  -> upstream MCP server
```

`shadow` differs from `off` only in that the Rust sidecar is present and can be
used for internal validation and comparison; it does not own the public MCP
transport.

### `edge` and `full`

In `edge` and `full`, nginx routes public `GET/POST/DELETE /mcp` directly to
the Rust runtime:

```text
client
  -> nginx
  -> Rust public listener
  -> trusted Python auth endpoint (internal)
  -> Rust MCP routing/execution/session logic
  -> upstream MCP server or narrow Python internal endpoint
```

Important details:

- Direct public Rust ingress is enabled by the dedicated public listener set up
  from `RUST_MCP_MODE=edge|full`.
- Rust authenticates public traffic through the trusted Python internal endpoint
  `POST /_internal/mcp/authenticate`.
- Rust strips forwarded/proxy-chain headers on the trusted Rust -> Python hop so
  Python evaluates the request as an internal runtime dispatch rather than as an
  external client IP.

## Responsibility Split

The current split is intentionally conservative:

| Concern | Python | Rust |
|---------|--------|------|
| JWT authentication | Yes | Via trusted internal Python auth |
| Token scoping / team visibility | Yes | Consumes authenticated context |
| RBAC | Yes | Enforces Python-authenticated result |
| Public MCP HTTP edge | `off`, `shadow` | `edge`, `full` |
| Session registry | Python in `off`, `shadow` | Rust in `full` |
| Event store / replay / resume | Python in `off`, `shadow`, `edge` | Rust in `full` |
| Live `GET /mcp` SSE edge | Python in `off`, `shadow`, `edge` | Rust in `full` |
| Affinity / owner-worker forwarding | Python in `off`, `shadow`, `edge` | Rust in `full` |
| Direct `tools/call` execution | Python fallback still exists | Rust hot path when eligible |

The important architectural point is that Rust does not currently replace the
full security model. Python remains the authority for auth and RBAC while Rust
owns progressively more of the public MCP transport and session/runtime work.

## Session/Auth Reuse Model

To reduce repeated auth overhead on session-bound MCP traffic, Rust can reuse
authenticated context for an established MCP session. This is not a global
per-user cache. It is bound to the MCP session and validated against the
original authenticated context.

Key invariants:

- a session belongs to exactly one authenticated caller context
- a different caller cannot reuse the same `mcp-session-id`
- a changed auth binding on the same session is denied rather than reused
- replay/resume and delete operations preserve the same ownership checks

This model is validated by the dedicated isolation suite:

```bash
make test-mcp-session-isolation
```

See the detailed threat model and test matrix in
`tools_rust/mcp_runtime/TESTING-DESIGN.md` in the repository.

## Verification

After bringing up the stack, verify the active mode through `/health`:

```bash
curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'
```

Representative full-Rust headers:

```text
x-contextforge-mcp-runtime-mode: rust-managed
x-contextforge-mcp-transport-mounted: rust
x-contextforge-mcp-session-core-mode: rust
x-contextforge-mcp-event-store-mode: rust
x-contextforge-mcp-resume-core-mode: rust
x-contextforge-mcp-live-stream-core-mode: rust
x-contextforge-mcp-affinity-core-mode: rust
x-contextforge-mcp-session-auth-reuse-mode: rust
```

Representative shadow-mode headers:

```text
x-contextforge-mcp-runtime-mode: rust-managed
x-contextforge-mcp-transport-mounted: python
x-contextforge-mcp-session-core-mode: python
x-contextforge-mcp-event-store-mode: python
x-contextforge-mcp-resume-core-mode: python
x-contextforge-mcp-live-stream-core-mode: python
x-contextforge-mcp-affinity-core-mode: python
x-contextforge-mcp-session-auth-reuse-mode: python
```

## Validation and Benchmark Workflow

Recommended stack-backed validation:

```bash
make testing-rebuild-rust-full
make test-mcp-cli
make test-mcp-rbac
make test-mcp-session-isolation
cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml
```

Recommended benchmark wrappers:

```bash
make benchmark-mcp-mixed
make benchmark-mcp-tools
make benchmark-mcp-mixed-300
make benchmark-mcp-tools-300
```

For Rust-local profiling and crate-level lint/test helpers, see
`tools_rust/mcp_runtime/README.md` in the repository.
