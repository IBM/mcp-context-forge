# ADR-0039: Adopt Fully Independent Plugin Crates Architecture

## Context

The current `pii_filter` plugin is not a separate crate and embeds PyO3 dependencies and macros directly. This couples plugin logic to Python bindings, making it difficult to add new plugins and increasing long-term maintenance costs as we expand support for both Rust and Python implementations.

## Decision

Adopt ** Fully Independent Plugin Crates** as the plugin architecture.

- Each plugin lives in its own crate with its own versioning and types.
- Plugins expose their own `#[pyfunction]` / `#[pymodule]`/ `#[pyclass]` for in-process usage (via maturin/pip packaging).
- Plugin authors may choose in-process (PyO3) or out-of-process (gRPC/HTTP) execution.
- Shared utilities, error conversions, or common adapters live in a separate shared crate if needed.
- Strong isolation and self-containment for plugins.

## Consequences

### Positive
- Clear ownership and strong isolation per plugin
- Straightforward pip distribution for Python integration
- Flexibility: in-process or remote execution per plugin
- Reduced coupling between core and plugin code
- Easier to add/maintain plugins independently

### Negative
- Minor boilerplate per plugin for bindings/API surface

### Risks / Mitigations
- Repetition in bindings → mitigate with shared helper crate when patterns emerge
- Workspace uniformity → optional shared crate

## Alternatives Considered

- **Option 1: Rust API on top of Python API** — Rejected (creates duplicative public Rust contract, tight coupling)
- **Option 3: Hybrid workspace with dedicated adapter crate** — Deferred (viable future evolution if many plugins justify shared adapters; little practical difference from Option 2 initially)
- **Option 4: Only gRPC/HTTP** — Rejected (adds latency/complexity for local dev; not required for all use cases)

## Related
- Testing: Use shared Python-based integration tests across Rust and Python implementations
- Issue: https://github.com/IBM/mcp-context-forge/issues/2730
