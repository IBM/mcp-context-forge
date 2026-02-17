# ADR-0041: Secure MCP Runtime Deployment and Catalog Integration

- *Status:* Accepted
- *Date:* 2026-02-17
- *Deciders:* Mihai Criveti

## Context

Gateway operators needed a first-class way to deploy MCP servers from catalog metadata without requiring separate manual container orchestration.

Primary drivers:

- One-click deployment of catalog entries.
- Backend abstraction for multiple runtimes (Docker and IBM Code Engine).
- Security controls through guardrail profiles and approval workflow.
- Automatic gateway registration for deployed runtimes.
- Catalog metadata for backend compatibility and runtime source definitions.

Without a runtime subsystem, deployment required external tooling and duplicated operational/security policy.

## Decision

Introduce a Secure MCP Runtime subsystem with:

1. Runtime API surface under `/runtimes`.
2. Runtime service orchestration layer with backend capability checks.
3. Backend implementations:
   - Docker backend
   - IBM Code Engine backend
4. Guardrail profile model:
   - Built-in profiles (`unrestricted`, `standard`, `restricted`, `airgapped`)
   - Custom profile CRUD
   - Backend compatibility warnings
5. Approval workflow:
   - Pending approval records
   - Approve/reject endpoints
   - Rule-driven triggers based on source type, registry allowlist, guardrail profile, and catalog metadata
6. Catalog integration extensions:
   - `source_type`, `source`
   - `supported_backends`
   - `requires_approval`
   - `featured`, `deprecated`
   - Optional remote catalog federation for runtime-enabled catalogs
7. Persistence model:
   - Runtime guardrail profiles
   - Runtime deployments
   - Runtime deployment approvals

Feature is gated by `MCPGATEWAY_RUNTIME_ENABLED`.

## Consequences

### Positive

- Unified deployment workflow directly in gateway APIs.
- Backend-specific enforcement with explicit compatibility warnings instead of silent failures.
- Approval and guardrail policies are centrally managed.
- Catalog becomes deployable metadata, not only discovery metadata.
- Enables incremental extension for future runtime backends.

### Negative

- Adds operational complexity (new runtime tables, APIs, and backend dependencies).
- Runtime orchestration currently relies on backend CLIs (`docker`, `ibmcloud`) being available.
- Backend capability differences require user education and API-level warnings.

### Risks / Mitigations

- **Risk:** Misconfigured backend or missing CLI binaries.
  - **Mitigation:** Capability listing endpoint (`GET /runtimes/backends`) and explicit backend errors.
- **Risk:** Deploying untrusted workloads.
  - **Mitigation:** Guardrail profiles, approval workflow, and registry/source gating.
- **Risk:** Catalog entries targeting unsupported backends.
  - **Mitigation:** `supported_backends` enforcement at deploy time.

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Keep runtime orchestration outside gateway | Prevents policy centralization and breaks one-click catalog deployment goal. |
| Single backend-only implementation (Docker only) | Does not meet multi-environment deployment requirements. |
| No approval workflow | Insufficient for enterprise governance and controlled rollout. |
| Hard-fail unsupported guardrail fields | Too rigid across heterogeneous backends; warnings preserve portability while signaling gaps. |

## Related

- Runtime operations guide: [Secure Runtime](../../manage/runtime.md)
- Configuration reference: [Configuration](../../manage/configuration.md#secure-mcp-runtime)
- Catalog metadata guide: [MCP Server Catalog](../../manage/catalog.md#runtime-aware-catalog-metadata)
