# ADR-047: Incremental Migration Over Rewrite

- *Status:* Proposed
- *Date:* 2026-03-15
- *Deciders:* Platform Team
- *Related:* [Modular Runtime Architecture](../modular-design.md), [ADR-019](019-modular-architecture-split.md)

## Context

The modular gateway architecture requires significant restructuring of the existing monolithic FastAPI application. Two approaches are possible:

1. **Incremental migration:** Refactor the existing codebase phase-by-phase, keeping the system functional at each step.
2. **Ground-up rewrite:** Build the modular architecture from scratch and migrate services over.

The existing codebase already has:

- production behavior that cannot be broken casually
- a broad unit, integration, E2E, security, and performance test surface
- cross-cutting concerns such as auth, RBAC, plugins, and admin UI that must
  remain coherent while protocol runtimes are extracted
- an implemented Rust MCP sidecar precedent showing that sidecar rollout is
  feasible

## Decision

We **modularize through phased refactoring**, not a ground-up rewrite. The migration follows five phases:

1. **Phase 0 — prerequisite refactors:** create cleaner seams inside the
   monolith without changing the deployment model
2. **Phase 1 — core SPI definition:** express core/module boundaries as
   internal interfaces first
3. **Phase 2 — module lifecycle:** wrap existing runtimes behind a common
   lifecycle and capability model
4. **Phase 3 — sidecar transport:** add sidecar-capable communication where it
   is justified
5. **Phase 4 — additional modules:** extract or introduce new protocol
   runtimes on top of the same contract

Feature flags and rollout controls may be used during the transition, but this
ADR does not freeze their final names.

## Consequences

### Positive

- The existing test suite provides regression safety at every phase.
- Each phase leaves the system fully functional — no "big bang" cutover.
- Risk is distributed across multiple small PRs instead of one massive change.
- Legacy mode preserves an escape hatch if module mode has issues.
- The implemented Rust MCP runtime sidecar proves the sidecar pattern works before generalizing it.

### Negative

- The codebase will temporarily have both legacy and modular code paths.
- Feature flag complexity increases until legacy mode is retired.
- Each phase requires careful testing in both modes.

### Neutral

- The migration timeline is longer than a rewrite but carries less risk.
- Legacy mode can be retired once all modules are stable and production-validated.

## References

- [Modular Runtime Architecture](../modular-design.md)
- [ADR-043](043-rust-mcp-runtime-sidecar-mode-model.md)
