# ADR-0041: Top-Level Rust Workspace (Cargo.toml at Repository Root)

- *Status:* Accepted
- *Date:* 2026-02-26
- *Deciders:* Core Engineering Team

## Context

The repository is primarily Python-based with some Rust usage (e.g. plugins, tools). There was no structured Rust workspace, no single command to build/test all Rust code, and no clear pattern for adding performance-critical components. Issue [#3027](https://github.com/IBM/mcp-context-forge/issues/3027) evaluated several layout options.

## Decision

Adopt **Option 1: workspace at repository root**.

- Add a root `Cargo.toml` defining a Rust workspace.
- Include **all** Rust crates as workspace members: `mcpgateway_rust/`, `tools_rust/`, and `plugins_rust/`. Plugin crates remain independent per ADR-0039, but are now workspace members so they are built and tested with one root-level workflow instead of per-crate Make setup.
- Keep the existing directory layout: Python in `mcpgateway/`, `plugins/`, etc.; Rust crates remain where they are and are referenced from the root workspace.
- PyO3/maturin bindings and CI for Rust builds and tests follow this workspace (see [#3027](https://github.com/IBM/mcp-context-forge/issues/3027) for make targets and acceptance criteria).

## Consequences

### Positive

- Single `cargo build` / `cargo test` / `maturin build` at repo root for all Rust code.
- Centralized dependency management and simpler CI.
- Easier cross-crate refactors; natural place to add future Rust components.
- **Maturin** (by default with a top-level workspace) uses the root `.venv` instead of creating venvs at lower levels—one shared Python environment and simpler dev setup.

### Negative

- Rust and Python directories live side-by-side at root; language boundary is less visually isolated than a dedicated `rust/` folder.

## Alternatives Considered

- **Option 2 (dedicated `mcpgateway_rust/` as workspace root)**: Clearer language boundary but extra `cd`/Make indirection and no single root-level workspace for plugins.
- **Option 3 (hybrid `rust/` folder with gateway_core boundary)**: Deferred; can be revisited if we want a stricter FFI boundary.
- **Option 4+ (Rust as services / split repos / full rewrite)**: Out of scope for this decision.

## Related

- Issue: [https://github.com/IBM/mcp-context-forge/issues/3027](https://github.com/IBM/mcp-context-forge/issues/3027)
- **Supersedes** (build layout): [ADR-0039](039-adopt-fully-independent-plugin-crates-architecture.md)—plugin crates remain independent per ADR-0039, but are now workspace members so they are built and tested with one root-level workflow instead of per-crate Make setup.
