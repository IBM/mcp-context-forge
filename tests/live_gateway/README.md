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
| `e2e/` | gateway with MCP transports and Playwright | `make testing-up` (default profile) |
| `mcp/` | gateway with MCP transports registered | `make testing-up` (default profile) |
| `mcp/test_oauth_status_live.py` | Postgres reachable at `localhost:5433` (the compose default) | `make testing-up` |
| `sso/` | Keycloak (jwks tests) and/or Entra ID (entra tests) | `docker compose --profile sso up -d` for Keycloak; `AZURE_*` env vars for Entra |
| `e2e_rust/` | gateway built with the Rust transport (edge or full mode) | `make testing-up` with the Rust profile, or rebuild compose images with Rust enabled |

`tests/live_gateway/helpers/` holds shared fixtures used across these
subsuites (e.g., `BASE_URL`, `JWT_SECRET`, `skip_no_gateway`).

## Running the tests

```bash
# Run everything in this directory at once
make test-live-gateway

# Or run a focused subsuite
make test-e2e                      # tests/live_gateway/e2e/test_e2e.py
make test-mcp-plugin-parity        # tests/live_gateway/mcp/test_mcp_plugin_parity.py
make test-mcp-access-matrix        # tests/live_gateway/e2e_rust/test_mcp_access_matrix.py
make test-mcp-session-isolation    # tests/live_gateway/e2e_rust/test_mcp_session_isolation.py
make test-e2e-sso                  # tests/live_gateway/sso/
make test-oauth-status-live        # tests/live_gateway/mcp/test_oauth_status_live.py

# Or run a specific file directly via uv
uv run --extra plugins pytest tests/live_gateway/mcp/test_langfuse_traces.py -v
```

## Resource template federation (#6625)

Run the Python gateway with authentication enabled and a test workload allowance
for rate limiting. The fixture registers two real Streamable HTTP upstreams.
It creates and deletes its own gateways, resources, virtual servers, users, and teams.

```bash
# Match these values to the running gateway.
export MCP_CLI_BASE_URL=http://127.0.0.1:8080
export GATEWAY_TOOL_NAME_SEPARATOR=-
export MCP_TEMPLATE_GATEWAY_COMMIT="commit-used-to-build-the-gateway"
# Use 127.0.0.1 for a host gateway, host.docker.internal for Docker Desktop,
# or host.lima.internal for Colima. The gateway must reach the fixture ports.
export MCP_TEMPLATE_UPSTREAM_HOST=host.docker.internal
make test-e2e K=resource_template
```

Supply `JWT_SECRET_KEY` for the test gateway through the environment.
Enable `MCP_REQUIRE_AUTH` on the gateway for the unauthenticated denial case.
Use `RATE_LIMITING_ENABLED=false` only on an isolated test gateway, or configure
limits that accommodate the suite. Allow the fixture host through the test gateway's SSRF policy.

The acceptance tests verify both templates, concrete-resource separation, expanded
URI reads, upstream request correlation, and gateway-prefixed names. They exercise
global and server-scoped endpoints. Security cases cover narrowed team tokens,
public-only tokens, private resources, another administrator, disabled resources,
wrong-server reads, missing permissions, and unauthenticated initialization.

The five `edge_probe` cases record observations; a passing probe does not certify
support for nonstandard advertisements or non-text templates. Their JSON output
and optional JUnit `resource_template_probe` properties retain the observations.
For JUnit evidence, add `--junitxml=<output.xml> -o junit_family=legacy` through `PYTEST_ADDOPTS`.

Namespacing assertions certify the post-#6621 baseline. Every result identifies
the supplied gateway commit; it does not certify an untested `main` checkout.
Authenticated requests bypass the unscoped template cache. Identical URI patterns
across upstreams and the Rust runtime are outside this suite's scope.

For independent client verification, keep the fixture running in another terminal:

```bash
uv run python -m tests.live_gateway.fixtures.resource_templates
```

Register both printed `gateway_url` values through the gateway API or Admin UI.
Associate their discovered concrete resources and templates with a virtual server.
In MCP Inspector, connect using a token with `resources.read` and `servers.use`.
Run `resources/templates/list`, `resources/list`, and `resources/read` with a printed
`read_uri`. Compare returned text with `expected_text` and inspect `received_uri`
in the fixture terminal. Repeat against the global MCP endpoint. This checks an
independent client's parsing as well as upstream routing. Delete the registered
objects and stop the fixture with Ctrl+C.

## Tuning sync deadlines

`tests/live_gateway/e2e/test_e2e.py` polls the gateway for state that
propagates asynchronously (tool catalog publish, cross-replica sync). Two
env vars override the poll deadlines when a stack needs more time:

| Variable | Default | Purpose |
|---|---|---|
| `MCP_E2E_PUBLISHER_SYNC_DEADLINE` | `75.0` (seconds) | Deadline for a registered gateway's tools to appear in `GET /tools`. Covers one 60-second publish interval plus 15 seconds of slack. |
| `MCP_E2E_REPLICA_SYNC_DEADLINE` | `30.0` (seconds) | Deadline for the Streamable HTTP gateway's tool catalog to stabilize across Nginx-routed replica reads. Shorter than the publisher deadline because replica propagation is expected to be faster than the tool-catalog publish interval. |

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
