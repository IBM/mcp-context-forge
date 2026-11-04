# ADR-058: Remove Rust Runtime Sidecars and Workspace

- *Status:* Accepted
- *Date:* 2026-11-04
- *Deciders:* Core Engineering Team, through [EPIC #5817](https://github.com/IBM/mcp-context-forge/issues/5817)
- *Supersedes:* ADR-041, ADR-042, ADR-043

## Context

EPIC #5817 removes the Rust runtime sidecars and repository-owned Rust workspace.
Maintaining parallel Python and Rust runtime paths adds build, testing, deployment,
and security maintenance costs. Python remains the gateway runtime.

The implementation removes the Python runtime proxies, settings, deployment
wiring, build infrastructure, and `crates/mcp_runtime`. This record completes the
historical documentation required by [#5823](https://github.com/IBM/mcp-context-forge/issues/5823).

## Decision

Use the Python MCP transport and Python A2A invocation path.
Remove the Rust runtime sidecars and the root Cargo workspace.

The removal includes:

- The Rust MCP and A2A integration paths and runtime selection settings.
- The runtime mode override APIs and Rust-specific health and response metadata.
- The Rust session-validation bypass and session-auth-reuse path.
- Rust build targets, container stages, CI jobs, and workspace tooling.
- `crates/mcp_runtime`, the root Cargo manifests, toolchain configuration, and supply-chain files.

Retain ADR-041, ADR-042, and ADR-043 as superseded historical records.
The proposed modular runtime contracts remain design guidance, without an active Rust MCP reference implementation.

## Consequences

- Operators remove old Rust runtime settings and sidecars from deployments.
- Existing Rust sessions require a drained cutover to new Python sessions.
- Contributors use the Python build, validation, and profiling commands.
- External plugins and native dependencies retain their own implementation languages and packaging.
- A future protocol module requires its own implementation and conformance evidence.

## References

- [EPIC #5817](https://github.com/IBM/mcp-context-forge/issues/5817)
- [Python runtime integration removal, #6177](https://github.com/IBM/mcp-context-forge/pull/6177)
- [Build and CI removal, #7354](https://github.com/IBM/mcp-context-forge/pull/7354)
- [MCP crate and workspace removal, #7359](https://github.com/IBM/mcp-context-forge/pull/7359)
