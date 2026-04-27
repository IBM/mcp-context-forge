# ADR-0041: Top-Level Rust Workspace (Cargo.toml at Repository Root)

- *Status:* Accepted
- *Date:* 2026-02-26
- *Deciders:* Core Engineering Team

## Context

The repository is primarily Python-based with some Rust usage (e.g. plugins, tools). There was no structured Rust workspace, no single command to build/test all Rust code, and no clear pattern for adding performance-critical components. Issue [#3027](https://github.com/IBM/mcp-context-forge/issues/3027) evaluated several layout options.

## Decision

Adopt **Option 1: workspace at repository root**.

- Add a root `Cargo.toml` defining a Rust workspace.
- Keep the root workspace member policy simple: workspace-owned crates live under `crates/`, and the root manifest includes them via `crates/*`.
- Keep the existing directory layout: Python stays in `mcpgateway/`, `plugins/`, and related top-level folders; the Rust workspace-owned crates live in `crates/`.
- Keep `mcp-servers/rust/` out of the shared workspace. Those sample/test servers remain separately managed and can move out of the repository later if we give them a plugin-like distribution path.
- PyO3/maturin bindings and CI for Rust builds and tests follow this workspace (see [#3027](https://github.com/IBM/mcp-context-forge/issues/3027) for make targets and acceptance criteria).

## Consequences

### Positive

- Single `cargo build` / `cargo test` / `maturin build` at repo root for all Rust code.
- Clear placement rule for future workspace crates: if it belongs to the shared root workspace, it goes under `crates/`.
- Centralized dependency management and simpler CI.
- Easier cross-crate refactors; natural place to add future Rust components.
- **Maturin** (by default with a top-level workspace) uses the root `.venv` instead of creating venvs at lower levels—one shared Python environment and simpler dev setup.

### Negative

- Rust and Python directories live side-by-side at root; language boundary is less visually isolated than a dedicated `rust/` folder.
- Rust sample/test servers outside `crates/` need their own packaging and release handling until they move to a separate distribution model.

## Alternatives Considered

- **Option 2 (dedicated `mcpgateway_rust/` as workspace root)**: Clearer language boundary but extra `cd`/Make indirection and no single root-level workspace.
- **Option 3 (hybrid `rust/` folder with gateway_core boundary)**: Deferred; can be revisited if we want a stricter FFI boundary.
- **Option 4+ (Rust as services / split repos / full rewrite)**: Out of scope for this decision.

## Related

- Issue: [https://github.com/IBM/mcp-context-forge/issues/3027](https://github.com/IBM/mcp-context-forge/issues/3027)
- Follow-up: [#4174](https://github.com/IBM/mcp-context-forge/issues/4174) tracks factoring the large Rust CI workflow into reusable building blocks.
- **Supersedes** (build layout): [ADR-0039](039-adopt-fully-independent-plugin-crates-architecture.md) for the internal workspace-owned Rust layout. Independent Rust packages can still live outside the workspace when they need separate release metadata or lifecycles.
