# Rust MCP Runtime (Removed)

The Rust MCP runtime sidecar is removed under
[EPIC #5817](https://github.com/IBM/mcp-context-forge/issues/5817).
ContextForge serves MCP requests through the Python transport.

## Removed Runtime Interfaces

Remove the old sidecar and Rust runtime configuration from deployments.
The runtime status fields and Rust-specific response headers are also removed.
Use the standard Python gateway image and
[deployment configuration](../deployment/index.md).

## Runtime Mode Override

The MCP and A2A runtime mode override APIs are removed. The gateway no longer
selects between Python and Rust runtimes.

[ADR-043](adr/043-rust-mcp-runtime-sidecar-mode-model.md) preserves the historical
design. [ADR-058](adr/058-remove-rust-runtime-and-workspace.md) records its removal.
See [Deprecations](../deprecations.md#removed) for the removal registry.
