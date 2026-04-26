# ContextForge MCP Runtime (Rust)

This crate is the optional Rust MCP sidecar/runtime for `ContextForge`.

It can act as:

- an internal-only Rust sidecar for parity and rollback testing
- the public MCP HTTP edge for `GET /mcp`, `POST /mcp`, and `DELETE /mcp`
- the owner of selected session, replay, live-stream, affinity, and direct
  execution paths in `full` mode

Python still remains the authority for authentication, token scoping, and
RBAC.

Further reading:

- [Rust MCP runtime architecture](../../docs/docs/architecture/rust-mcp-runtime.md)
- [ADR-043: Rust MCP runtime sidecar + mode model](../../docs/docs/architecture/adr/043-rust-mcp-runtime-sidecar-mode-model.md)
- [Current status snapshot](STATUS.md)
- [Session/auth isolation testing design](TESTING-DESIGN.md)

## Mode model

The top-level UX is controlled by `RUST_MCP_MODE`.

| Mode | Public `/mcp` served by | Main Rust-owned behavior | Intended use |
| --- | --- | --- | --- |
| `off` | Python | none | baseline / no Rust MCP |
| `shadow` | Python | Rust sidecar is built/running internally | safest fallback and comparison mode |
| `edge` | Rust | Rust public MCP edge and direct fast paths | fast public edge without full session/event cores |
| `full` | Rust | `edge` plus Rust session/event-store/resume/live-stream/affinity cores | fullest Rust runtime path |

Important nuance:

- `edge` and `full` default to the Rust session-auth reuse fast path through
  the mode presets in [docker-entrypoint.sh](../../docker-entrypoint.sh).
- `MCP_RUST_SESSION_AUTH_REUSE_ENABLED=true|false` is the direct runtime
  override read by the Rust sidecar. `RUST_MCP_SESSION_AUTH_REUSE` remains a
  compatibility input translated by [docker-entrypoint.sh](../../docker-entrypoint.sh).
  Prefer `RUST_MCP_MODE` unless you are intentionally testing a specific
  override path.
- When the boot mode is `edge` an authorized admin can flip the public
  `/mcp` ingress between `shadow` and `edge` at runtime via
  `PATCH /admin/runtime/mcp-mode` (and `/admin/runtime/a2a-mode` for A2A).
  `off`, `shadow`, and `full` are not flippable — `shadow` did not opt
  into the session-auth-reuse safety invariant; see the architecture doc.
  see [docs/docs/architecture/rust-mcp-runtime.md](../../docs/docs/architecture/rust-mcp-runtime.md#runtime-mode-override)
  for the full operator contract and cluster propagation behavior.

## Quick reference

### Build and start

```bash
make testing-rebuild-rust-shadow
make testing-rebuild-rust
make testing-rebuild-rust-full
```

Start without rebuilding:

```bash
make testing-up-rust-shadow
make testing-up-rust
make testing-up-rust-full
```

### Core validation

```bash
make test
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-session-isolation
make test-mcp-session-isolation-load
cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml
```

### Benchmarks

```bash
make benchmark-mcp-mixed
make benchmark-mcp-tools
make benchmark-mcp-mixed-300
make benchmark-mcp-tools-300
```

### Rust-local crate checks

```bash
make -C crates/mcp_runtime fmt-check
make -C crates/mcp_runtime check
make -C crates/mcp_runtime clippy
make -C crates/mcp_runtime clippy-all
make -C crates/mcp_runtime test
make -C crates/mcp_runtime test-rmcp
make -C crates/mcp_runtime coverage
```

### Rust-local profiling

```bash
make -C crates/mcp_runtime setup-profiling
make -C crates/mcp_runtime flamegraph-test
make -C crates/mcp_runtime flamegraph-test-rmcp
```

Generated profiling artifacts are written under:

```text
crates/mcp_runtime/profiles/
```

## Configuration

### Backend URL Validation

Validates outgoing HTTP requests from Rust → Python backend services to protect against SSRF via misconfigured environment variables.

**Scope**: Validates `MCP_RUST_BACKEND_RPC_URL` and derived backend service URLs (NOT incoming client requests).

**Threat Model**: Defends against misconfigured environment variables pointing to cloud metadata endpoints or blocked internal networks.

**Out of scope (deliberate, NOT a security guarantee)**:
- DNS rebinding / DNS poisoning / `/etc/hosts` manipulation — the allowlist is a string match on the URL host; the resolved IP is never checked.
- HTTP redirects to blocked hosts — mitigated at the shared `reqwest::Client` builder via `redirect::Policy::none()`, not by this module.

Operators who need defense-in-depth against DNS-layer attacks must pin DNS resolution at the connector level.

**Environment Variables:**

```bash
MCP_RUST_BACKEND_VALIDATION_ENABLED=true                        # Enable validation (default: true)
MCP_RUST_BACKEND_ALLOWED_HOSTS="localhost,127.0.0.1,[::1]"      # Approved backend hosts (default)
MCP_RUST_BACKEND_BLOCKED_NETWORKS="169.254.169.254/32,fd00::1/128" # CIDR ranges to block (default; IPv4 + IPv6 metadata)
MCP_RUST_BACKEND_MAX_URL_LENGTH=2048                            # Per-URL byte cap for DoS / log-bloat mitigation (default: 2048)
```

The validator runs once at startup (fast-fail on misconfig) and again on every outbound backend request (defense-in-depth). `MCP_RUST_BACKEND_RPC_URL` is rejected at startup if it does not satisfy the policy.

IPv6 literals are matched post-bracket-strip (e.g. allowlisting `[::1]` matches `http://[::1]/`), and `::ffff:…` IPv4-mapped addresses are compared against IPv4 CIDR rules — so `http://[::ffff:169.254.169.254]/` is caught by the default `169.254.169.254/32` block.

**Examples:**

```bash
# Production: strict allowlist with IPv4 + IPv6 metadata endpoints blocked
MCP_RUST_BACKEND_ALLOWED_HOSTS="backend.internal,10.0.1.50" \
MCP_RUST_BACKEND_BLOCKED_NETWORKS="169.254.169.254/32,fd00::1/128,10.0.0.0/8" \
cargo run

# Development: local only (dual-stack loopback)
MCP_RUST_BACKEND_ALLOWED_HOSTS="localhost,127.0.0.1,[::1]" cargo run

# Disable validation (NOT recommended)
MCP_RUST_BACKEND_VALIDATION_ENABLED=false cargo run
```

URLs not in the allowlist or IPs in blocked networks are rejected with a Bad Gateway (502) response.

### Request Body Size Limits

Control maximum request payload size to prevent resource exhaustion.

**Environment Variables:**

```bash
MCP_RUST_MAX_REQUEST_BODY_SIZE_BYTES=10485760  # Max body size (default: 10MB)
```

**Examples:**

```bash
# Increase limit for large tool payloads
MCP_RUST_MAX_REQUEST_BODY_SIZE_BYTES=52428800 cargo run  # 50MB

# Strict limit for constrained environments
MCP_RUST_MAX_REQUEST_BODY_SIZE_BYTES=1048576 cargo run   # 1MB
```

Requests exceeding the limit receive a `413 Payload Too Large` response.

## Verify what is running

### Compose/gateway view

```bash
curl -sD - http://localhost:8080/health -o /dev/null | rg 'x-contextforge-mcp-'
```

Typical full-Rust health headers:

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

Typical shadow/fallback health headers:

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

### Per-request proof

Responses generated by the Rust edge include:

- `x-contextforge-mcp-runtime: rust`
- `x-contextforge-mcp-session-core: rust|python`
- `x-contextforge-mcp-event-store: rust|python`
- `x-contextforge-mcp-resume-core: rust|python`
- `x-contextforge-mcp-live-stream-core: rust|python`
- `x-contextforge-mcp-affinity-core: rust|python`

Direct `tools/call` responses can also expose:

- `x-contextforge-mcp-upstream-client: native`
- `x-contextforge-mcp-upstream-client: rmcp`

### Raw runtime view

When running the crate directly, the runtime exposes:

- `GET /health`
- `GET /healthz`

Example:

```bash
curl http://127.0.0.1:8787/healthz
```

## Architecture boundary

### Rust owns today

- public MCP transport edge in `edge|full`
- protocol/version validation and JSON-RPC request shaping
- local `ping`
- notification transport semantics
- direct `tools/call` fast path with reusable upstream sessions
- optional `rmcp` upstream client path
- server-scoped DB-backed direct reads where Rust can preserve parity:
  - `tools/list`
  - `resources/list`
  - `resources/read`
  - `resources/templates/list`
  - `prompts/list`
  - `prompts/get`
- in `full` mode:
  - runtime session metadata
  - Redis-backed event store and replay
  - live-stream response edge
  - affinity forwarding edge

### Python still owns today

- authentication
- token scoping
- RBAC
- the trusted internal authenticate endpoint
- plugin hook execution (pre-invoke and post-invoke)
- fallback compatibility handlers
- parts of the underlying stream/session behavior behind the trusted bridge
- existing business logic and data/model semantics where Rust intentionally
  falls back for parity

### tools/call two-phase model

In `edge|full` mode, `tools/call` follows a resolve-then-execute pattern:

1. **Resolve**: Rust calls `POST /_internal/mcp/tools/call/resolve` on
   Python. Python validates auth/RBAC, runs pre-invoke plugin hooks, and
   returns an execution plan with `eligible`, `modifiedArgs`, `headers`,
   and `fallbackReason`.
2. **Execute or fallback**:
   - If `eligible == true`: Rust applies the plugin-modified args and
     headers, then calls the upstream MCP server directly.
   - If `eligible == false`: Rust forwards the full request to
     `POST /_internal/mcp/tools/call` for standard Python execution.
3. **Metrics**: After direct execution, Rust calls
   `POST /_internal/mcp/tools/call/metric` to record timing.

Post-invoke plugin hooks force `eligible: false`, ensuring the full plugin
chain runs in Python. Pre-invoke hook results are passed to Rust through
the execution plan. See the
[plugin execution documentation](../../docs/docs/architecture/rust-mcp-runtime.md#plugin-execution-and-toolscall-flow)
for the complete eligibility criteria and flow diagrams.

## Auth and session model

Python still authenticates public MCP traffic first.

In `edge|full`, Rust can then:

- call the trusted internal authenticate endpoint
- bind the encoded auth context to a runtime session after `initialize`
- reuse that auth context for the same session while:
  - the auth-binding fingerprint still matches
  - the server scope still matches
  - the reuse TTL has not expired

That means:

- the shared Python auth cache still matters in all modes
- session-auth reuse is session-bound, not a global user cache
- same-email / different-token and cross-user session reuse attempts are denied
  by the runtime session ownership checks
- bounded-TTL revocation and membership/role drift cases are now covered in the
  compose-backed Rust isolation suite
- runtime `/health` now exposes `runtime_stats` so reuse hits, misses,
  denial reasons, and affinity forwarding can be inspected during validation

See [TESTING-DESIGN.md](TESTING-DESIGN.md) for the threat model and
compose-backed isolation coverage.

## Running the crate directly

Compose users should prefer the `make testing-*` targets above. The examples
below are for crate-only development.

### Run over TCP

```bash
cd crates/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/_internal/mcp/rpc \
  --listen-http 127.0.0.1:8787
```

### Run over Unix socket

```bash
cd crates/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/_internal/mcp/rpc \
  --listen-uds /tmp/contextforge-mcp-rust.sock
```

### Optional direct public listener

```bash
cd crates/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/_internal/mcp/rpc \
  --listen-uds /tmp/contextforge-mcp-rust.sock \
  --public-listen-http 127.0.0.1:8787
```

## Example requests

### Health

```bash
curl http://127.0.0.1:8787/healthz
```

### Ping

```bash
curl -s http://127.0.0.1:8787/mcp/ \
  -H 'content-type: application/json' \
  -H 'mcp-protocol-version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'
```

### Initialize

```bash
curl -s http://127.0.0.1:8787/mcp/ \
  -H 'content-type: application/json' \
  -H 'mcp-protocol-version: 2025-11-25' \
  -H 'authorization: Bearer YOUR_TOKEN' \
  -d '{"jsonrpc":"2.0","id":"init-1","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

### Tools list

```bash
curl -s http://127.0.0.1:8787/mcp/ \
  -H 'content-type: application/json' \
  -H 'mcp-protocol-version: 2025-11-25' \
  -H 'authorization: Bearer YOUR_TOKEN' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## Benchmark guidance

Use the make targets from the repository root:

```bash
make benchmark-mcp-mixed
make benchmark-mcp-tools
make benchmark-mcp-mixed-300
make benchmark-mcp-tools-300
```

Guidance:

- `benchmark-mcp-tools*` is the cleanest signal for the Rust hot path
- `benchmark-mcp-mixed*` exercises broader fixture/data behavior and can expose
  seeded test-server issues that are not transport regressions
- for branch-local numbers, use [STATUS.md](STATUS.md) instead of hardcoding
  benchmark snapshots here

## Current recommended validation flow

For the full-Rust public path:

```bash
make testing-rebuild-rust-full
make test-mcp-protocol-e2e
make test-mcp-rbac
make test-mcp-session-isolation
cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml
make benchmark-mcp-tools
```

For the bounded-TTL drift checks, rerun the Rust full stack with a short reuse
TTL:

```bash
MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS=2 MCP_RUST_SESSION_AUTH_REUSE_GRACE_SECONDS=1 make testing-rebuild-rust-full
make test-mcp-session-isolation
make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s
```

For the safe fallback path:

```bash
make testing-rebuild-rust-shadow
make test-mcp-protocol-e2e
make test-mcp-rbac
```

## Further reading

- [Architecture: Rust MCP runtime](../../docs/docs/architecture/rust-mcp-runtime.md)
- [ADR-043: Rust MCP runtime sidecar + mode model](../../docs/docs/architecture/adr/043-rust-mcp-runtime-sidecar-mode-model.md)
- [Current status snapshot](STATUS.md)
- [Session/auth isolation testing design](TESTING-DESIGN.md)
- [Follow-ups for separate cleanup work](FOLLOWUPS.md)
