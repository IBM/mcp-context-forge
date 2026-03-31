# ADR-045: Authentication and Authorization Remain in Core

- *Status:* Proposed
- *Date:* 2026-03-15
- *Deciders:* Platform Team
- *Related:* [Modular Runtime Architecture](../modular-design.md), [ADR-004](004-combine-jwt-and-basic-auth.md)

## Context

The modular gateway architecture introduces protocol modules that can be implemented in different languages and run as separate processes. A key question is whether authentication and authorization logic should be duplicated in each module or centralized in the core platform.

ContextForge implements a two-layer security model:

1. **Token Scoping (Layer 1):** `normalize_token_teams()` in `mcpgateway/auth.py` controls what resources a caller can see.
2. **RBAC (Layer 2):** `PermissionService` controls what actions a caller can perform.

Both layers are security-critical and have non-trivial edge cases (admin bypass, public-only tokens, team hierarchy resolution).

## Decision

Authentication and authorization **never move into modules**. The core
platform remains the single source of truth for:

- JWT verification and token scoping (`normalize_token_teams()`).
- RBAC permission checks (`PermissionService`).
- SSO provider integration (GitHub, Google, Okta, Keycloak, Entra ID, generic OIDC).
- Token revocation checks.
- Rate limiting.

Modules consume auth through a core-owned auth and policy SPI. The exact RPC or
method names are intentionally left open, but the contract must support:

- resolving a caller into a typed authenticated context
- checking permissions against that context
- preserving token-scoped visibility and deny-path behavior

Modules receive authenticated context or permission outcomes from the core and
pass that context through subsequent core SPI calls as needed.

## Consequences

### Positive

- Security-critical code has a single implementation — no drift between module auth implementations.
- Simplifies security auditing — one codebase to review, not N per module.
- Modules in any language get the full auth stack without reimplementing it.
- Consistent behavior across all protocols (MCP, A2A, LLM, REST).

### Negative

- Every module request that needs auth must make at least one call or cacheable
  check against the core-owned auth boundary.
- Auth logic cannot be freely reimplemented per protocol without risking
  policy drift.

### Neutral

- Auth caching at the core level (ADR-028) can amortize the cost of repeated
  checks.
- The current Rust MCP runtime already demonstrates this pattern in practice.

## References

- [Modular Runtime Architecture](../modular-design.md)
- `mcpgateway/auth.py` — `normalize_token_teams()`, single source of truth
- [ADR-043](043-rust-mcp-runtime-sidecar-mode-model.md)
