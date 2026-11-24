# ADR-058: Remove Rust Runtime Sidecars and Workspace

- *Status:* Accepted
- *Date:* 2026-11-04
- *Deciders:* Core Engineering Team, through [EPIC #5817](https://github.com/IBM/mcp-context-forge/issues/5817)
- *Supersedes:* ADR-041, ADR-042, ADR-043

## Context

EPIC #5817 removes the Rust runtime sidecars and repository-owned Rust workspace.
Maintaining parallel Python and Rust runtime paths adds build, testing, deployment,
and security maintenance costs. Python remains the gateway runtime.

The merged changes remove the runtime proxies, mode-selection settings, Rust
build infrastructure, and `crates/mcp_runtime`. Some internal Python handlers
and deployment remnants remain. This record documents the verified removals
for [#5823](https://github.com/IBM/mcp-context-forge/issues/5823).

## Decision

Use the Python MCP transport and Python A2A invocation path in this repository.
Remove the Rust runtime sidecars and the root Cargo workspace.

The external Rust dataplane is outside this decision. Its configuration publisher
(`DATAPLANE_PUBLISHER`) and `/contextforge-rs` ingress remain separate from the
removed repository-owned sidecars. See [Configuration](../../manage/configuration.md).

The verified removals include:

- The Rust MCP and A2A runtime proxies and runtime selection settings.
- The runtime mode override APIs and their health status fields.
- Rust build targets, container stages, CI jobs, and workspace tooling.
- `crates/mcp_runtime`, the root Cargo manifests, toolchain configuration, and supply-chain files.

The `/_internal/mcp/*` dispatch endpoints remain for Python session affinity.
The trust boundary is the derived shared-secret header
(`x-contextforge-mcp-runtime-auth`) plus the forwarded auth context when required.
The header is a static SHA-256 value derived from `AUTH_ENCRYPTION_SECRET`.
It is not a per-request HMAC. Requests also check the runtime marker.
The loopback address check is defense in depth:
`ProxyHeaders(trusted_hosts="*")` lets external callers influence `request.client.host`.
Do not route `/_internal/*` from external listeners; deny it at the reverse proxy.
Treat `AUTH_ENCRYPTION_SECRET` as the credential for internal dispatch.
Rotate it if exposed.

Rust marker branches, internal handlers, and deployment remnants remain tracked
in [#7445](https://github.com/IBM/mcp-context-forge/issues/7445).
The Python MCP transport also retains the
`x-contextforge-mcp-runtime: python` response header.

Retain ADR-041, ADR-042, and ADR-043 as superseded historical records.
The proposed modular runtime contracts remain design guidance, without an active Rust MCP reference implementation.

## Consequences

- Operators remove old Rust runtime settings and sidecars from deployments.
- Contributors use the Python build, validation, and profiling commands.
- External plugins and native dependencies retain their own implementation languages and packaging.
- A future protocol module requires its own implementation and conformance evidence.

## References

- [EPIC #5817](https://github.com/IBM/mcp-context-forge/issues/5817)
- [Python runtime integration removal, #6177](https://github.com/IBM/mcp-context-forge/pull/6177)
- [Build and CI removal, #7354](https://github.com/IBM/mcp-context-forge/pull/7354)
- [MCP crate and workspace removal, #7359](https://github.com/IBM/mcp-context-forge/pull/7359)
