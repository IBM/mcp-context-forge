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
| `mcp/test_private_key_jwt_e2e.py` | stub AS and upstream reachable via `host.docker.internal` (the compose default) | `make testing-up` |
| `sso/` | Keycloak (jwks tests) and/or Entra ID (entra tests) | `docker compose --profile sso up -d` for Keycloak; `AZURE_*` env vars for Entra |
| `e2e_rust/` | gateway built with the Rust transport (edge or full mode) | `make testing-up` with the Rust profile, or rebuild compose images with Rust enabled |
| `a2a/` | self-contained: each test boots its own gateway subprocess; needs the `observability` extra | `uv run --extra plugins --extra observability pytest tests/live_gateway/a2a/` |

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
make test-private-key-jwt-live     # tests/live_gateway/mcp/test_private_key_jwt_e2e.py

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
# Omit this variable for a host gateway. The fixture then binds to 127.0.0.1.
# Use host.docker.internal for Docker Desktop or host.lima.internal for Colima.
# Container access binds the unauthenticated fixture to 0.0.0.0 and prints a warning.
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

## Pre-provisioned users with external IdP authentication

`sso/test_preprovisioned_idp_auth.py` validates issue #6583 against real HTTPS Keycloak and gateway
processes. It creates unique, email-verified Keycloak users and provisions matching gateway accounts
through `POST /v1/admin/users/sso`. It obtains access tokens through Keycloak's password grant;
it does not use browser Admin UI login. A missing-account control verifies that bearer authentication
does not create users when `auto_create_users=false`.

Use the HTTPS setup in `sso/test_external_idp_rest_auth_e2e.py`. Export matching issuer/client values
for the gateway and tests: `KEYCLOAK_URL`, `KEYCLOAK_INTERNAL_URL`, `KEYCLOAK_REALM`,
`KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, and `SSL_CERT_FILE`. The issuer and JWKS URLs
must use HTTPS. Provide Keycloak administrator access through `KEYCLOAK_ADMIN` and
`KEYCLOAK_ADMIN_PASSWORD`, plus the gateway's `JWT_SECRET_KEY` and `PLATFORM_ADMIN_EMAIL`.
Set `SSO_TEST_DATABASE_URL` to the isolated gateway database. Functional checks use HTTP/MCP.
Teardown uses this database only to remove the fixture users' membership-history references before
deleting accounts through the API. It verifies each account exists in that database first.

Export these settings before starting the isolated gateways and pytest:

```bash
export MCPGATEWAY_ADMIN_API_ENABLED=true EMAIL_AUTH_ENABLED=true
export SSO_ENABLED=true SSO_KEYCLOAK_ENABLED=true SSO_API_TOKEN_AUTH_ENABLED=true
export SSO_ALLOW_PROVIDER_LINKING=false EXTERNAL_IDENTITY_CACHE_TTL=2
export SSO_AUTO_ADMIN_DOMAINS='[]'
export AUTH_CACHE_ENABLED=false AUTH_CACHE_TEAMS_ENABLED=false REGISTRY_CACHE_ENABLED=false
```

Set the same cache/auth settings in the pytest environment. Configure the gateway's
`SSO_KEYCLOAK_BASE_URL`, realm, and client values to match Keycloak. `SSO_TEST_PROVIDER_ID` defaults
to the bootstrapped `keycloak` provider. A local HTTPS IdP can require a test-only localhost egress
allowance; retain normal HTTPS certificate verification.

For flag-disabled coverage, start a second gateway with the same database, JWT secret, encryption
secret, SSO settings, and trusted certificate. Set only its `SSO_USER_PROVISIONING_API_ENABLED=false`
and give it a separate port. Tests create users through the primary gateway, then verify `404` for
provisioning POSTs and successful REST/MCP authentication through the second gateway.
Neither gateway starts or restarts from inside pytest. Start each in a separate terminal with the
exported settings and the same isolated `DATABASE_URL`:

```bash
SSO_USER_PROVISIONING_API_ENABLED=true uv run uvicorn mcpgateway.main:app --host 127.0.0.1 --port 8080
SSO_USER_PROVISIONING_API_ENABLED=false uv run uvicorn mcpgateway.main:app --host 127.0.0.1 --port 8081
```

Use Compose overrides to pass these settings when using containers. Host exports alone do not
override settings omitted from the Compose service's environment.

```bash
MCP_CLI_BASE_URL=http://127.0.0.1:8080 \
SSO_PROVISIONING_DISABLED_BASE_URL=http://127.0.0.1:8081 \
SSO_API_TOKEN_AUTH_ENABLED=true EXTERNAL_IDENTITY_CACHE_TTL=2 AUTH_CACHE_ENABLED=false \
uv run pytest tests/live_gateway/sso/test_preprovisioned_idp_auth.py -v -rs
```

The suite temporarily changes the bootstrapped provider's auto-creation, trust, audience,
domain, and mapping settings. It restores these fields and removes its unique audience mapper
on teardown. It also removes its users, roles, team, tool, virtual server, and mismatch provider.
Run serially, without xdist, and do not run another suite against the shared provider/client
until teardown completes. The fixture rejects parallel execution.

REST checks use `GET /v1/tools` and assert the protected tool's UUID. MCP checks initialize a real
SDK session at `/servers/{id}/mcp/`, call `tools/list`, and assert the corresponding tool name.
The fixture virtual server is public and OAuth-enabled, with the Keycloak issuer and test audience.
Its associated tool belongs to a dedicated non-personal team. Tests remove automatic
onboarding/membership roles before assigning explicit DB permissions. REST requires `tools.read`;
MCP initialization requires `servers.use`. A separate `tools/call` denial checks `tools.execute`
without contacting the tool URL. Revocation tests remove the DB read and transport grants.

The external identity cache stores synthesized identities per token. Its configured TTL can delay
refresh of cached identity/team information; this suite does not change that behavior. Role/team
mutation cases reuse the same unexpired token after the fixed TTL. Active-user and RBAC checks
also run independently of that cache. Tests never update a provider merely to invalidate identity
caches. Separate auth/registry caches are disabled to keep the observation window controlled.

HTTPS/IdP prerequisites follow the live suite's opt-in skip conventions. Missing
`SSO_PROVISIONING_DISABLED_BASE_URL` skips only the second-gateway case. Export it and run both
gateways to exercise every acceptance criterion.

## Adding new tests

### SSO user provisioning API

`sso/test_sso_user_provisioning_api.py` runs against an externally started gateway; it never
restarts the stack. It needs no browser or running IdP. Enabled tests create a temporary
provider through the SSO provider API and clean up their provider and users.

Start the default stack with `SSO_USER_PROVISIONING_API_ENABLED=false`, then run:

```bash
SSO_PROVISIONING_TEST_MODE=disabled uv run pytest \
  tests/live_gateway/sso/test_sso_user_provisioning_api.py -v -rs
```

For enabled coverage, start or recreate the gateway with:

```bash
MCPGATEWAY_ADMIN_API_ENABLED=true
EMAIL_AUTH_ENABLED=true
SSO_ENABLED=true
SSO_USER_PROVISIONING_API_ENABLED=true
```

The main Compose gateway passes the provisioning flag through its environment. Recreate the
gateway after changing flags; exporting them only in the test process does not enable routes.
Use the running stack's `JWT_SECRET_KEY`, `PLATFORM_ADMIN_EMAIL`, and `MCP_CLI_BASE_URL` for tests:

```bash
SSO_PROVISIONING_TEST_MODE=enabled uv run pytest \
  tests/live_gateway/sso/test_sso_user_provisioning_api.py -v -rs
```

The default `auto` mode probes OpenAPI registration and skips incompatible cases. Explicit
`enabled`/`disabled` modes fail on an unexpected route-registration state. All modes retain
the suite's unreachable-gateway skip behavior. The full startup-flag matrix and runtime
flag-mutation checks run in isolated application tests.

If you write a test that genuinely needs a live gateway or external service,
add it under the appropriate subdirectory here. Tests that only need
in-process FastAPI fixtures belong under `tests/e2e/` (top level) or
`tests/integration/` instead.
