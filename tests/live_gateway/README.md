# tests/live_gateway/ — Live-Infrastructure Test Suites

Tests in this directory **require a running ContextForge gateway and/or
external services**. They are excluded from the default `make test` run.

## Why this directory exists

The default `make test` target keeps CI green without external infrastructure
— in-process FastAPI via `TestClient` / `ASGITransport` is enough for the
overwhelming majority of the suite. The tests collected here cannot satisfy
that constraint:

* They open real HTTP/WebSocket connections to a gateway (`http://localhost:8080`).
* They exercise transport behavior (SSE, streamable HTTP, MCP `/mcp`).
* They depend on side-services (Keycloak, Entra ID, Langfuse, Redis).
* They spawn helper subprocesses (`mcpgateway.translate`).

Putting them under `tests/live_gateway/` makes the dependency obvious from
the path alone and lets us ignore the entire tree with a single `--ignore`.

## Bringing the stack up

The standard local entry point is:

```bash
make testing-up          # docker-compose stack with gateway + supporting services
```

Specific subsuites need additional services on top:

| Subdir | Extra requirement | How to start |
|---|---|---|
| `mcp/` | gateway with MCP transports registered | `make testing-up` (default profile) |
| `sso/` | Keycloak (jwks tests) and/or Entra ID (entra tests) | `docker compose --profile sso up -d` for Keycloak; `AZURE_*` env vars for Entra |
| `protocol_compliance/` | gateway in proxy + virtual-server modes | `make testing-up` |
| `e2e_rust/` | gateway built with the Rust transport (edge or full mode) | `make testing-up` with the Rust profile, or rebuild compose images with Rust enabled |

`tests/live_gateway/helpers/` holds shared fixtures used across these
subsuites (e.g., `BASE_URL`, `JWT_SECRET`, `skip_no_gateway`).

## Running the tests

```bash
# Run everything in this directory at once
make test-live-gateway

# Or run a focused subsuite
make test-mcp-protocol-e2e         # tests/live_gateway/mcp/test_mcp_protocol_e2e.py
make test-mcp-rbac                 # tests/live_gateway/mcp/test_mcp_rbac_transport.py
make test-mcp-plugin-parity        # tests/live_gateway/mcp/test_mcp_plugin_parity.py
make test-mcp-access-matrix        # tests/live_gateway/e2e_rust/test_mcp_access_matrix.py
make test-mcp-session-isolation    # tests/live_gateway/e2e_rust/test_mcp_session_isolation.py
make test-e2e-sso                  # tests/live_gateway/sso/
make test-protocol-compliance      # tests/live_gateway/protocol_compliance/ (full matrix)
make test-protocol-compliance-reference  # reference-target only (fast)
make test-protocol-compliance-gateway    # gateway-target only

# Or run a specific file directly via uv
uv run --extra plugins pytest tests/live_gateway/mcp/test_langfuse_traces.py -v
```

## Skip behavior

Most tests here use `skip_no_gateway` or similar markers (defined in
`helpers/mcp_test_helpers.py`) that probe the configured `BASE_URL` and
self-skip when the service isn't reachable. That means `make test-live-gateway`
won't fail catastrophically on a clean checkout — it just collects and skips.
The opt-in subsuites are still the right entry point when you actually want
to run them against a stack you've started.

## Adding new tests

If you write a test that genuinely needs a live gateway or external service,
add it under the appropriate subdirectory here. Tests that only need
in-process FastAPI fixtures belong under `tests/e2e/` (top level) or
`tests/integration/` instead.
