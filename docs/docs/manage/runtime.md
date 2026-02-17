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
RUNTIME_DEFAULT_BACKEND=docker
RUNTIME_DOCKER_ENABLED=true
RUNTIME_IBM_CODE_ENGINE_ENABLED=false
```

When disabled, runtime endpoints are not exposed.

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

