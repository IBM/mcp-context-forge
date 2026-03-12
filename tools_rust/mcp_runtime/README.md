# ContextForge MCP Runtime (Rust Prototype)

This crate is an experimental Rust MCP runtime edge for ContextForge.

## What it is

This prototype owns:

- MCP transport-level `MCP-Protocol-Version` validation
- default compatibility with current MCP SDK protocol versions (`2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`)
- JSON-RPC request validation
- JSON-RPC batch rejection
- `202 Accepted` handling for notification-only calls
- initialize parameter validation
- local MCP-safe method handling for `ping`
- HTTP routing for `/rpc` and `/mcp`
- forwarding of the remaining MCP methods to the existing ContextForge backend `/rpc`
- reusable pooled backend HTTP client
- TCP or Unix domain socket listening
- an optional Rust-owned MCP session metadata core behind a separate runtime
  flag

This prototype deliberately does **not** yet own:

- auth and RBAC decisions
- persistence
- the underlying resumable session-manager/event-store implementation
- SSE / resumable stream orchestration
- upstream MCP client federation

Those still live in Python until the gateway extracts a cleaner internal protocol core.

## Why this boundary

The current Python gateway mixes MCP behavior across:

- route handlers
- streamable transport
- auth/RBAC
- session state
- service-layer upstream MCP clients

Trying to move all of that into Rust in one shot would mostly duplicate coupling.

This crate chooses a narrower, more credible first seam:

- Python keeps **auth, path rewriting, session ownership, and business logic**
- Rust owns the **mounted `/mcp` runtime shell**
- Python `/rpc` remains the current backend contract for business execution

That keeps the prototype useful now while preserving a clean migration path later.

## Design decisions

### 1. `/rpc` is the current backend contract

Today, the Rust runtime forwards most methods to the existing ContextForge `/rpc` endpoint.

Reason:

- it keeps the prototype working against the current gateway immediately
- it avoids inventing a second Python dispatch layer before the existing one is extracted

Future direction:

- replace backend `/rpc` forwarding with a narrower internal MCP core contract

### 2. `ping` is handled locally

`ping` is safe to terminate in Rust because it has no business-logic dependency.

Reason:

- proves the runtime can own MCP protocol behavior locally
- creates a pattern for gradually moving more protocol methods into Rust later

### 3. Notifications are accepted at the transport edge

JSON-RPC notifications are forwarded to the backend, but the Rust runtime returns HTTP `202 Accepted`.

Reason:

- matches the repo's MCP-2025 compliance expectations for Streamable HTTP notifications
- keeps side effects in Python while moving transport semantics into Rust

### 4. `/mcp` is currently POST-first JSON mode

This prototype supports `POST /mcp` as a Rust-owned MCP edge alias.

Reason:

- current gateway defaults to JSON response mode for streamable HTTP
- it gives a working MCP-shaped entrypoint without pretending resumable SSE/session behavior is already complete

Current limitation:

- Rust now fronts `GET/POST/DELETE /mcp`, but the underlying resumable
  Streamable HTTP session manager, session registry, and most live-stream
  execution are still Python-owned behind a trusted internal transport bridge
- when `MCP_RUST_SESSION_CORE_ENABLED=true`, Rust owns the session metadata
  layer, routes `initialize` through that bridge, and tracks session
  lifecycle hints without taking over the underlying Python stream engine yet
- when `MCP_RUST_EVENT_STORE_ENABLED=true` and `MCP_RUST_RESUME_CORE_ENABLED=true`,
  Rust also owns Redis-backed resumable replay for public `GET /mcp` requests
  that carry `Last-Event-ID`

### 5. UDS is preferred over loopback TCP

The prototype supports both TCP and Unix sockets, but UDS is the intended local deployment path.

Reason:

- lower overhead than loopback HTTP/TCP
- cleaner local sidecar deployment story
- aligns with the repo's existing external Unix-socket plugin transport pattern

## Running it

### Build

```bash
cd tools_rust/mcp_runtime
cargo build --release
```

### Run over TCP

```bash
cd tools_rust/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/rpc \
  --listen-http 127.0.0.1:8787 \
  --session-core-enabled \
  --supported-protocol-version 2025-11-25,2025-03-26
```

### Run over Unix socket

```bash
cd tools_rust/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/rpc \
  --listen-uds /tmp/contextforge-mcp-rust.sock \
  --session-core-enabled
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

### Initialize via backend forwarding

```bash
curl -s http://127.0.0.1:8787/mcp/ \
  -H 'content-type: application/json' \
  -H 'mcp-protocol-version: 2025-11-25' \
  -H 'authorization: Bearer YOUR_TOKEN' \
  -d '{"jsonrpc":"2.0","id":"init-1","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
```

### Tools list via backend forwarding

```bash
curl -s http://127.0.0.1:8787/mcp/ \
  -H 'content-type: application/json' \
  -H 'mcp-protocol-version: 2025-11-25' \
  -H 'authorization: Bearer YOUR_TOKEN' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Notification accepted by the Rust edge

```bash
curl -i http://127.0.0.1:8787/mcp/ \
  -H 'content-type: application/json' \
  -H 'mcp-protocol-version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
```

## Current scope

Implemented:

- `GET /healthz`
- `GET /health`
- `GET /mcp`
- `GET /mcp/`
- `DELETE /mcp`
- `DELETE /mcp/`
- `POST /rpc`
- `POST /rpc/`
- `POST /mcp`
- `POST /mcp/`
- `MCP-Protocol-Version` validation with defaulting when the header is missing
- default support for current MCP SDK protocol versions
- JSON-RPC batch rejection
- initialize parameter validation
- local `ping`
- `202 Accepted` notification handling
- Rust-fronted MCP transport for `GET/POST/DELETE /mcp`
- optional Rust-owned session metadata for:
  - `initialize`
  - `GET /mcp`
  - `DELETE /mcp`
- dedicated Rust-specialized routing for:
  - `initialize`
  - `notifications/initialized`
  - `notifications/message`
  - `notifications/cancelled`
  - `tools/list`
  - `tools/call`
  - `resources/list`
  - `resources/read`
  - `resources/subscribe`
  - `resources/unsubscribe`
  - `resources/templates/list`
  - `prompts/list`
  - `prompts/get`
  - `roots/list`
  - `completion/complete`
  - `sampling/createMessage`
  - `logging/setLevel`
- Rust-local catch-all handling for unsupported:
  - `notifications/*`
  - `sampling/*`
  - `completion/*`
  - `logging/*`
  - `elicitation/*` except `elicitation/create`
- backend forwarding for the remaining compatibility and fallback paths
- propagation of `Authorization`, cookies, `mcp-session-id`, and other non-hop-by-hop headers
- stripping of internal-only forwarded headers such as `x-forwarded-internally`
- Python-side embedding for the mounted `/mcp` route:
  - Python auth and path rewriting stay in front
  - server-scoped `/servers/<id>/mcp` requests preserve scope across the
    Python -> Rust -> Python seam
  - GET/DELETE transport requests cross a trusted internal transport bridge
  - when enabled, session metadata and teardown hints live in Rust while the
    current Python stream engine remains the backend
  - `tools/list` has a Rust-owned DB-backed fast path
  - `tools/call` has a Rust-owned hot path with reusable upstream sessions
    and optional `rmcp` upstream client support

Not yet implemented:

- resumable Streamable HTTP session orchestration
- SSE event streaming
- full Rust ownership of session registry, session affinity, and resumable
  event storage
- `elicitation/create`
- a completely eliminated Python fallback dispatcher / backend contract

## Gateway integration

The gateway now supports a simpler integrated experimental mode:

- `RUST_MCP_BUILD=true` builds the Rust MCP runtime into the image
- `RUST_MCP_MODE=off|edge|full`
  - `off`: Python MCP transport
  - `edge`: Rust MCP runtime edge with managed UDS sidecar defaults
  - `full`: `edge` plus Rust session/event-store/resume/live-stream cores
- `RUST_MCP_LOG=warn` controls the bundled sidecar log level for the simple path

Advanced low-level env vars still exist and override the simple mode when set:

- `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_URL=http://127.0.0.1:8787`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_TIMEOUT_SECONDS=30`
- `EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED=true|false`
- `EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED=true|false`
- `EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED=true|false`

Behavior in this mode:

- Python still performs MCP auth, token scoping, and path rewriting
- all public `GET/POST/DELETE /mcp` traffic hits Rust first
- server-scoped `/servers/<id>/mcp` requests preserve semantics across the
  internal seam
- when `EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED=true`, Rust owns the
  session metadata layer and routes `initialize` through the internal
  transport bridge
- when `EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED=true` and
  `EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED=true`, Rust replays resumable
  `GET /mcp` traffic directly from the Redis-backed event store
- when `EXPERIMENTAL_RUST_MCP_LIVE_STREAM_CORE_ENABLED=true`, Rust terminates
  the public non-resume `GET /mcp` SSE response itself and opens the trusted
  Python backend stream lazily so public headers are sent immediately
- the current Python boundary is now mostly:
  - auth and RBAC
  - the underlying live stream/session-manager implementation behind the
    trusted transport bridge
  - owner/affinity checks that still live on the trusted transport bridge
  - fallback compatibility methods
  - remaining business execution behind narrow internal routes

## Shared auth cache behavior

Rust MCP does **not** currently own authentication or RBAC. Public MCP requests
still authenticate in Python first, before they reach the Rust sidecar.

That means the Python auth path is still part of the hot path for:

- `RUST_MCP_MODE=off`
- `RUST_MCP_MODE=edge`
- `RUST_MCP_MODE=full`

The Streamable HTTP MCP auth path now reuses the existing shared auth cache and
batched auth lookup logic instead of bypassing it. No new MCP-specific auth
cache settings were introduced.

What this means operationally:

- `AUTH_CACHE_*` tuning affects Python-only MCP and Rust MCP
- disabling auth cache affects the Rust MCP path too, because Python still
  authenticates first
- short warm-up effects are expected because the auth cache starts cold after a
  restart and then fills quickly under load

The relevant existing settings are:

- `AUTH_CACHE_ENABLED=true|false`
- `AUTH_CACHE_BATCH_QUERIES=true|false`
- `AUTH_CACHE_TEAMS_ENABLED=true|false`
- `AUTH_CACHE_USER_TTL`
- `AUTH_CACHE_REVOCATION_TTL`
- `AUTH_CACHE_TEAM_TTL`
- `AUTH_CACHE_ROLE_TTL`
- `AUTH_CACHE_TEAMS_TTL`

Recommended default stance:

- leave `AUTH_CACHE_ENABLED=true`
- leave `AUTH_CACHE_BATCH_QUERIES=true`
- keep `AUTH_CACHE_REVOCATION_TTL` short

Reason:

- the cache removes repeated Python DB work for token revocation checks and
  user lookup
- the batched lookup keeps cache misses to one DB round-trip instead of several
- revocation TTL is the security-sensitive knob, so that one should stay
  conservative

If you want to disable the shared auth cache entirely:

```env
AUTH_CACHE_ENABLED=false
```

If you want behavior closest to the older per-request MCP auth path:

```env
AUTH_CACHE_ENABLED=false
AUTH_CACHE_BATCH_QUERIES=false
AUTH_CACHE_TEAMS_ENABLED=false
```

If you want to keep caching but reduce staleness windows:

```env
AUTH_CACHE_USER_TTL=30
AUTH_CACHE_REVOCATION_TTL=10
AUTH_CACHE_TEAM_TTL=30
AUTH_CACHE_TEAMS_TTL=30
```

Security notes:

- revocation checks are still performed; cache only short-circuits repeated
  lookups for a short TTL
- account disable and user lookup results are also cached for a short TTL
- there is no MCP-specific long-lived trust shortcut here; this is reuse of the
  existing platform auth cache

Performance notes:

- this shared auth cache helps Python and Rust modes both
- in local load testing on the same codebase, enabling the MCP path to reuse
  the existing auth cache materially improved `off`, `edge`, and `full`
  throughput
- longer steady-state runs tend to look better than cold `30s` runs because the
  cache fills during the first part of the benchmark

## Container integration

`Containerfile.lite` now includes the runtime behind the simple build flag:

```bash
RUST_MCP_BUILD=true make docker-prod-rust
```

To force a clean rebuild:

```bash
make docker-prod-rust-no-cache
```

The simple compose workflows are:

```bash
make testing-up-rust
make testing-up-rust-full
make testing-rebuild-rust
make testing-rebuild-rust-full
```

If you want the raw docker/compose equivalents, the low-level env vars below are
still available.

Optional launcher/runtime envs:

- `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true|false`
- `EXPERIMENTAL_RUST_MCP_SESSION_CORE_ENABLED=true|false`
- `EXPERIMENTAL_RUST_MCP_EVENT_STORE_ENABLED=true|false`
- `EXPERIMENTAL_RUST_MCP_RESUME_CORE_ENABLED=true|false`
- `MCP_RUST_LISTEN_HTTP=127.0.0.1:8787`
- `MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock`
- `MCP_RUST_LOG=info`
- `MCP_RUST_BACKEND_RPC_URL=http://127.0.0.1:4444/rpc`
- `MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=true|false`
- `MCP_RUST_SESSION_CORE_ENABLED=true|false`
- `MCP_RUST_EVENT_STORE_ENABLED=true|false`
- `MCP_RUST_RESUME_CORE_ENABLED=true|false`
- `MCP_RUST_REDIS_URL=redis://redis:6379/0`
- `MCP_RUST_EVENT_STORE_POLL_INTERVAL_MS=100`
- `MCP_RUST_SESSION_TTL_SECONDS=3600`

With `MCP_RUST_LOG=info`, the runtime emits one line per handled MCP method, for example:

```text
rust_mcp_runtime method=tools/list mode=db-tools-list-direct
```

Every MCP response generated by the Rust edge also includes:

- `x-contextforge-mcp-runtime: rust`
- `x-contextforge-mcp-session-core: rust|python`
- `x-contextforge-mcp-event-store: rust|python`
- `x-contextforge-mcp-resume-core: rust|python`
- direct upstream `tools/call` responses also expose:
  - `x-contextforge-mcp-upstream-client: native`
  - `x-contextforge-mcp-upstream-client: rmcp`

That header is the easiest live proof that a request was handled by the Rust runtime instead
of the legacy Python-only transport path.

## Testing

```bash
cd tools_rust/mcp_runtime
cargo test --release
```

Feature-enabled validation for the optional official Rust SDK upstream client:

```bash
cd tools_rust/mcp_runtime
cargo test --release --features rmcp-upstream-client
```

The test suite verifies:

- gateway-style `/health` probes work
- local `ping` does not hit the backend
- unsupported `MCP-Protocol-Version` headers are rejected with `400`
- notifications return `202 Accepted` while still forwarding to the backend
- initialize requests missing `protocolVersion` return JSON-RPC `-32602`
- JSON-RPC batch payloads are rejected
- forwarded requests preserve JSON bodies
- forwarded requests propagate auth and session headers
- `/mcp` aliases correctly to the same runtime handler
- direct `tools/call` execution can reuse upstream sessions
- SSE-framed upstream responses are decoded correctly
- feature-enabled `rmcp` upstream client execution works for `tools/call`

## Compose-backed validation

Validated on the live compose stack with:

- `ENABLE_RUST_BUILD=true`
- `ENABLE_RUST_MCP_RMCP_BUILD=true`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_UDS=/tmp/contextforge-mcp-rust.sock`
- `MCP_RUST_LISTEN_UDS=/tmp/contextforge-mcp-rust.sock`
- `MCP_RUST_USE_RMCP_UPSTREAM_CLIENT=true`
- `HTTP_SERVER=gunicorn`
- `GUNICORN_WORKERS=32`

Validated results on that compose-built stack:

- `make test-mcp-cli` -> `23 passed`
- `make test-mcp-rbac` -> `40 passed`
- full `make test-ui-headless` completed with:
  - `761 passed`
  - `83 skipped`
  - `3 failed`
  - `5 errors`
  - the exact `8` failing/error cases all passed when rerun individually on
    the same stack, which currently points to suite-order or shared-state UI
    flake rather than a deterministic MCP runtime regression

Live proof on the compose-built stack:

- `/health` reports:
  - `x-contextforge-mcp-runtime-mode: rust-managed`
  - `x-contextforge-mcp-transport-mounted: rust`
  - `x-contextforge-rust-build-included: true`
- `tools/call` responses can report:
  - `x-contextforge-mcp-runtime: rust`
  - `x-contextforge-mcp-upstream-client: rmcp`

## Compliance smoke

I also validated the runtime against the repo's MCP 2025-11-25 compliance tests using:

- the Rust runtime as the HTTP edge
- a small mock backend behind `/rpc`

The following compliance files passed in that setup:

- `tests/compliance/mcp_2025_11_25/base/test_no_batch_payloads.py`
- `tests/compliance/mcp_2025_11_25/lifecycle/test_initialize.py`
- `tests/compliance/mcp_2025_11_25/transport_core/test_streamable_http_protocol_header.py`
- `tests/compliance/mcp_2025_11_25/server_features/test_discovery_methods.py`
- `tests/compliance/mcp_2025_11_25/utilities/test_ping_and_notifications.py`
- `tests/compliance/mcp_2025_11_25/tasks/test_tasks_optional_capability.py`
- `tests/compliance/mcp_2025_11_25/authorization/test_protected_resource_metadata.py`
- `tests/compliance/mcp_2025_11_25/base/test_schema_surface_runtime.py`

That smoke run demonstrates the current runtime is already a credible MCP-2025 transport shell, even though the real gateway business logic still lives behind Python `/rpc`.

## mcp-cli validation

I also ran the repo's full `tests/e2e/test_mcp_cli_protocol.py` file against:

- the Rust runtime as the HTTP MCP edge
- `mcpgateway.wrapper` as the stdio bridge used by `mcp-cli`
- a controlled backend behind Python-compatible `/rpc`

Result:

- `22 passed`

What mattered in practice:

- the runtime needed a `/health` endpoint because the repo's `mcp-cli` E2E suite probes `GET {base_url}/health`
- default compatibility with `2025-03-26` and `2025-06-18` mattered because the current `mcp-cli` path does not yet operate purely on `2025-11-25`

That result is stronger than the protocol-only compliance smoke because it validates the real `mcp-cli -> wrapper -> Rust runtime` path used by this repo.
