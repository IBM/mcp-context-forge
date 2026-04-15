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
`crates/mcp_runtime/TESTING-DESIGN.md` in the repository.

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

## Plugin Execution and tools/call Flow

The Rust runtime does not execute plugin code directly. All plugin
execution happens in Python, with results communicated to Rust over internal
HTTP RPC endpoints.

### Internal RPC Endpoints

Rust derives internal endpoint URLs from its `--backend-rpc-url`
configuration. The following endpoints exist on the Python side:

| Endpoint | Purpose |
|----------|---------|
| `POST /_internal/mcp/authenticate` | JWT validation, token scoping, RBAC context |
| `POST /_internal/mcp/tools/call/resolve` | Build execution plan; runs pre-invoke plugin hooks |
| `POST /_internal/mcp/tools/call` | Full Python fallback execution with all plugins |
| `POST /_internal/mcp/tools/call/metric` | Record tool execution timing and success/failure |

These are trusted internal endpoints, not exposed to external clients.

### tools/call Request Flow (edge and full modes)

When a `tools/call` request arrives at the Rust runtime in `edge` or `full`
mode, it follows a two-phase resolve-then-execute model:

```text
client
  -> nginx
  -> Rust public listener
  -> Rust: POST /_internal/mcp/tools/call/resolve (Python)
     -> Python: auth + RBAC + tool lookup
     -> Python: pre-invoke plugin hooks (if registered)
     -> Python: returns execution plan to Rust
  -> Rust: eligible?
     YES -> Rust applies modified args + headers from plan
            -> Rust calls upstream MCP server directly
            -> Rust: POST /_internal/mcp/tools/call/metric (Python)
     NO  -> Rust: POST /_internal/mcp/tools/call (Python)
            -> Python: full invoke_tool() with pre + post-invoke plugins
            -> Python calls upstream MCP server
```

### Plugin Handling by Mode

| Mode | Pre-invoke hooks | Post-invoke hooks | Tool execution |
|------|-----------------|-------------------|----------------|
| `off` | Python (normal path) | Python (normal path) | Python |
| `shadow` | Python (normal path) | Python (normal path) | Python |
| `edge` | Python (via `/resolve` RPC) | Python (fallback only) | Rust direct when eligible, Python fallback otherwise |
| `full` | Python (via `/resolve` RPC) | Python (fallback only) | Rust direct when eligible, Python fallback otherwise |

Key behaviors:

- **Pre-invoke hooks** always run in Python. In `edge`/`full`, they execute
  during the `/resolve` call. Their output — modified arguments and injected
  headers — is returned in the execution plan for Rust to apply.
- **Post-invoke hooks** cannot run after Rust direct execution, so their
  presence forces an immediate fallback to the full Python path
  (`eligible: false`, `fallbackReason: post-invoke-hooks-configured`).
- **Plan caching** is disabled when pre-invoke hooks executed, because hook
  results may depend on per-call context (e.g. connection IDs, rotated
  credentials).

### Direct Execution Eligibility

A tool is eligible for Rust direct execution only when **all** of the
following are true:

- No post-invoke plugin hooks are registered
- No active observability trace
- Tool integration type is `MCP`
- Transport is `streamablehttp`
- No JSONPath filter configured on the tool
- No custom CA certificate on the gateway
- Gateway URL is present
- Gateway is not in `direct_proxy` mode
- OAuth grant type is not `authorization_code` (or token retrieval succeeds)
- Tool resolves unambiguously to a single enabled, reachable tool

When any condition fails, `prepare_rust_mcp_tool_execution()` returns
`eligible: false` with a `fallbackReason` string, and Rust forwards the
full request to the Python `/_internal/mcp/tools/call` endpoint.

## Validation and Benchmark Workflow

Recommended stack-backed validation:

```bash
make testing-rebuild-rust-full
make test-mcp-cli
make test-mcp-rbac
make test-mcp-session-isolation
cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml
```

Recommended benchmark wrappers:

```bash
make benchmark-mcp-mixed
make benchmark-mcp-tools
make benchmark-mcp-mixed-300
make benchmark-mcp-tools-300
```

For Rust-local profiling and crate-level lint/test helpers, see
`crates/mcp_runtime/README.md` in the repository.
