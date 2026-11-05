# Rust MCP Runtime (Removed)

The Rust MCP runtime sidecar is removed under
[EPIC #5817](https://github.com/IBM/mcp-context-forge/issues/5817).
The gateway in this repository serves MCP requests through the Python transport.
The separate external Rust dataplane is outside this removal.

## Removed Runtime Interfaces

Remove the old sidecar and Rust runtime configuration from deployments.
The runtime mode override APIs and their health status fields are removed.
The Python transport retains the `x-contextforge-mcp-runtime: python` response header.
Use the standard Python gateway image and
[deployment configuration](../deployment/index.md).

## Runtime Mode Override

The MCP and A2A runtime mode override APIs are removed. The gateway no longer
selects between Python and Rust runtimes.

The `/_internal/mcp/*` endpoints remain for Python session affinity.
The trust boundary is the derived shared-secret header
(`x-contextforge-mcp-runtime-auth`) plus the forwarded auth context when required.
The header is a static SHA-256 value derived from `AUTH_ENCRYPTION_SECRET`.
It is not a per-request HMAC. Requests also check the runtime marker.
The loopback address check is defense in depth:
`ProxyHeaders(trusted_hosts="*")` lets external callers influence `request.client.host`.
Do not route `/_internal/*` from external listeners; deny it at the reverse proxy.
Treat `AUTH_ENCRYPTION_SECRET` as the credential for internal dispatch.
Rotate it if exposed.

Rust marker branches and deployment remnants remain tracked in
[#7445](https://github.com/IBM/mcp-context-forge/issues/7445).

[ADR-043](adr/043-rust-mcp-runtime-sidecar-mode-model.md) preserves the historical
design. [ADR-058](adr/058-remove-rust-runtime-and-workspace.md) records its removal.
See [Deprecations](../deprecations.md#removed) for the removal registry.
