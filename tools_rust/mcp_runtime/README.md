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

This prototype deliberately does **not** yet own:

- auth and RBAC decisions
- persistence
- session registry semantics
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

- GET/DELETE stream management is not yet implemented here, so the integrated
  gateway currently keeps those methods on the Python transport

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
  --supported-protocol-version 2025-11-25,2025-03-26
```

### Run over Unix socket

```bash
cd tools_rust/mcp_runtime
cargo run --release -- \
  --backend-rpc-url http://127.0.0.1:4444/rpc \
  --listen-uds /tmp/contextforge-mcp-rust.sock
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
- backend forwarding for all other JSON-RPC methods
- propagation of `Authorization`, cookies, `mcp-session-id`, and other non-hop-by-hop headers
- stripping of internal-only forwarded headers such as `x-forwarded-internally`
- Python-side embedding for the mounted `/mcp` route:
  - Python auth and path rewriting stay in front
  - server-scoped `/servers/<id>/mcp` requests have `server_id` injected before reaching `/rpc`
  - non-POST MCP session-management requests still fall back to the Python transport

Not yet implemented:

- resumable Streamable HTTP session orchestration
- SSE event streaming
- direct Rust ownership of `tools/list`, `tools/call`, `resources/*`, `prompts/*`
- backend contract narrower than `/rpc`

## Gateway integration

The gateway now supports an integrated experimental mode:

- `EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_URL=http://127.0.0.1:8787`
- `EXPERIMENTAL_RUST_MCP_RUNTIME_TIMEOUT_SECONDS=30`

Behavior in this mode:

- Python still performs MCP auth, token scoping, and path rewriting
- POST `/mcp` traffic is proxied to the Rust runtime
- GET/DELETE `/mcp` traffic still uses the Python `StreamableHTTPSessionManager`
- server-scoped `/servers/<id>/mcp` requests preserve semantics by injecting `server_id`
  into the forwarded JSON-RPC params

## Container integration

`Containerfile.lite` now includes the runtime behind the existing build flag:

```bash
docker build --build-arg ENABLE_RUST=true -f Containerfile.lite .
```

When the image contains Rust artifacts, the bundled entrypoint can supervise the
sidecar automatically:

```bash
docker run \
  -e EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED=true \
  -e EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true \
  -e HTTP_SERVER=gunicorn \
  mcpgateway
```

Optional launcher/runtime envs:

- `EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED=true|false`
- `MCP_RUST_LISTEN_HTTP=127.0.0.1:8787`
- `MCP_RUST_LOG=info`
- `MCP_RUST_BACKEND_RPC_URL=http://127.0.0.1:4444/rpc`

With `MCP_RUST_LOG=info`, the runtime emits one line per handled MCP method, for example:

```text
rust_mcp_runtime method=tools/list mode=backend-forward
```

Every MCP response generated by the Rust edge also includes:

- `x-contextforge-mcp-runtime: rust`

That header is the easiest live proof that a request was handled by the Rust runtime instead
of the legacy Python-only transport path.

## Testing

```bash
cd tools_rust/mcp_runtime
cargo test --release
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
