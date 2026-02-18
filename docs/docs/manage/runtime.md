# Secure MCP Runtime

The Secure MCP Runtime lets operators deploy catalog-backed MCP servers directly from the gateway using runtime backends.

Current backends:

- `docker`
- `ibm_code_engine`

The runtime API is mounted at `/runtimes` when enabled.

---

## Enable the Feature

Set these variables (for example in `.env`):

```bash
MCPGATEWAY_RUNTIME_ENABLED=true
RUNTIME_PLATFORM_ADMIN_ONLY=true
RUNTIME_DEFAULT_BACKEND=docker
RUNTIME_DOCKER_ENABLED=true
RUNTIME_IBM_CODE_ENGINE_ENABLED=false
```

If you build the gateway container via Docker Compose, you can control backend CLI tooling in the image build:

```bash
GATEWAY_ENABLE_DOCKER_CLI=true
GATEWAY_ENABLE_IBMCLOUD_CLI=true
```

Set either value to `false` to omit that CLI from the image.

When disabled, runtime endpoints are not exposed.
By default, runtime endpoints are platform-admin-only. Set `RUNTIME_PLATFORM_ADMIN_ONLY=false` to use route-level RBAC checks instead.

---

## Local Docker Quickstart (Fast Time Server)

This is a known-working end-to-end example for local testing.

### 1. Configure runtime flags

Set these values in your environment (for example `.env`, Docker Compose `environment:`, or Helm values):

```bash
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
MCPGATEWAY_RUNTIME_ENABLED=true
RUNTIME_PLATFORM_ADMIN_ONLY=true
RUNTIME_DEFAULT_BACKEND=docker
RUNTIME_DOCKER_ENABLED=true
RUNTIME_IBM_CODE_ENGINE_ENABLED=false
```

### 2. Open the Runtime admin panel

Navigate to:

- `/admin#runtime` (tab label: **Runtime**)

### 3. Deploy a runtime with the known test image

In the Deploy form, use:

- source type: `docker`
- image: `ghcr.io/ibm/fast-time-server:0.8.0`
- endpoint port: `8080` (optional, recommended when server does not expose a default port map)
- endpoint path: `/http` (optional, recommended for fast-time streamable HTTP endpoint)

Expected result:

- the runtime appears in the Runtime table
- status transitions toward `running`/`connected`
- `logs` action returns container output

### 4. Validate over API (optional)

```bash
# list runtime records
curl -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  http://localhost:4444/runtimes

# fetch runtime logs
curl -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  "http://localhost:4444/runtimes/<runtime_id>/logs?tail=200"

# delete runtime
curl -X DELETE -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  http://localhost:4444/runtimes/<runtime_id>
```

---

## Runtime APIs

Main endpoints:

- `GET /runtimes/backends`
- `POST /runtimes/deploy`
- `GET /runtimes`
- `GET /runtimes/{runtime_id}`
- `POST /runtimes/{runtime_id}/start`
- `POST /runtimes/{runtime_id}/stop`
- `DELETE /runtimes/{runtime_id}`
- `GET /runtimes/{runtime_id}/logs`

---

## Admin UI

When `MCPGATEWAY_RUNTIME_ENABLED=true`, the Admin UI includes a **Runtime** tab at `#runtime` (`/admin#runtime`).

Visibility rules:

- Runtime disabled: tab is hidden and `/admin/runtime/partial` returns `404`.
- `RUNTIME_PLATFORM_ADMIN_ONLY=true`: tab and runtime panel are available only to platform administrators.
- `RUNTIME_PLATFORM_ADMIN_ONLY=false`: tab is shown to users allowed into the admin UI, with runtime API access still enforced by RBAC route permissions.
- You can explicitly hide it with `MCPGATEWAY_UI_HIDE_SECTIONS=runtime`.

Quick UI test (known working image):

1. Enable runtime settings:
   `MCPGATEWAY_RUNTIME_ENABLED=true`
   `RUNTIME_DOCKER_ENABLED=true`
2. Open `/admin#runtime`.
3. Deploy with:
   source type `docker`
   image `ghcr.io/ibm/fast-time-server:0.8.0`
   endpoint port `8080` (optional)
   endpoint path `/http` (optional)
4. Verify the deployment appears in the table, then click `logs` to confirm runtime output.

Endpoint override behavior:

- `Endpoint Port` overrides the preferred container port used to resolve runtime endpoint URL.
- `Endpoint Path` is used first during auto-registration to MCP Server gateway URL discovery.
- If unset, runtime keeps backend-driven defaults and transport-specific path heuristics (`/http`, `/mcp`, `/sse`).

Guardrails management:

- `GET /runtimes/guardrails`
- `GET /runtimes/guardrails/{name}`
- `GET /runtimes/guardrails/{name}/compatibility?backend=...`
- `POST /runtimes/guardrails`
- `PUT /runtimes/guardrails/{name}`
- `DELETE /runtimes/guardrails/{name}`

Approval workflow:

- `GET /runtimes/approvals`
- `GET /runtimes/approvals/{approval_id}`
- `POST /runtimes/approvals/{approval_id}/approve`
- `POST /runtimes/approvals/{approval_id}/reject`

---

## Deployment Sources

Supported source types:

- `docker` image source
- `github` repository build source
- `compose` source (Docker backend only)

Backend compatibility is enforced before deployment. For example, compose sources are rejected on Code Engine.

---

## Catalog Integration

Catalog entries can include runtime metadata:

- `source` and `source_type`
- `supported_backends`
- `guardrails_profile`
- `requires_approval`

At deploy time:

- The runtime service resolves source config from catalog entries.
- `supported_backends` is enforced.
- `guardrails_profile` is used as default if the caller keeps default profile and does not send overrides.
- `requires_approval: true` triggers approval when runtime approval is enabled.

Remote catalog federation for runtime use can be enabled with:

```bash
RUNTIME_CATALOG_REMOTE_URLS='["https://example.com/catalog.yml"]'
RUNTIME_CATALOG_REMOTE_TIMEOUT_SECONDS=15
```

Catalog example (Docker source using fast-time server):

```yaml
servers:
  - id: "fast-time-runtime"
    name: "Fast Time Runtime"
    description: "Known working runtime sample for Docker backend"
    source_type: "docker"
    source: "ghcr.io/ibm/fast-time-server:0.8.0"
    transport: "streamable-http"
    endpoint: "http://localhost:8099/mcp"
    runtime:
      supported_backends: ["docker"]
      guardrails_profile: "standard"
      requires_approval: false
```

---

## Guardrails

Built-in guardrail profiles:

- `unrestricted`
- `standard`
- `restricted`
- `airgapped`

Compatibility warnings are returned for backend-specific gaps (for example, host-level egress allowlists on Code Engine).

Deployment responses include `guardrails_warnings` so operators can see which controls were partially enforced.

---

## Approval Workflow

Enable approval flow:

```bash
RUNTIME_APPROVAL_ENABLED=true
RUNTIME_APPROVAL_REQUIRED_SOURCE_TYPES='["github"]'
RUNTIME_APPROVAL_REGISTRY_ALLOWLIST='["docker.io/library","docker.io/mcp"]'
RUNTIME_APPROVAL_REQUIRED_GUARDRAILS_PROFILES='["unrestricted"]'
RUNTIME_APPROVERS='["security-team"]'
RUNTIME_APPROVAL_TIMEOUT_HOURS=48
```

When triggered:

1. Deployment is created with `status=pending_approval`.
2. Approval request record is created.
3. Approver can approve or reject via API.
4. Approved requests continue deployment automatically.

---

## Operational Notes

- Runtime status reflects backend state (`pending`, `deploying`, `running`, `connected`, `stopped`, `error`, `deleted`).
- Successful deployments can auto-register a gateway entry.
- Runtime logs are available through backend-native retrieval (`docker logs` or `ibmcloud ce application logs`).
