# ADR-043: Rust MCP Runtime Sidecar with Mode-Based Rollout

- *Status:* Accepted
- *Date:* 2026-03-14
- *Deciders:* Platform Team
- *Supersedes:* ADR-038 (experimental Rust transport backend)

## Context

ContextForge's original Rust transport spike began as a narrow experiment around
the streamable HTTP MCP path. The implementation has since evolved beyond that
proposal:

- the runtime is deployed as a separate Rust sidecar/runtime, not as PyO3/FFI
- nginx can route public `/mcp` traffic directly to Rust
- Rust can own session, event-store, resume, live-stream, and affinity MCP
  cores in the `full` mode
- Python still remains authoritative for authentication, token scoping, and RBAC
- rollout and rollback are now controlled through a top-level mode model instead
  of only through low-level experimental flags

The older ADR no longer describes the implemented architecture or the operator
experience.

## Decision

We standardize on a **Rust MCP runtime sidecar** with a **mode-based rollout
model**.

### User-facing modes

`RUST_MCP_MODE` is the primary operational control:

- `off`: keep the public MCP path on Python
- `shadow`: run the Rust sidecar, but keep public `/mcp` on Python
- `edge`: route public `/mcp` directly from nginx to Rust
- `full`: `edge` plus Rust-owned MCP session/event-store/resume/live-stream and
  affinity cores

### Public ingress model

In `edge|full`, nginx routes public `GET/POST/DELETE /mcp` traffic directly to
the Rust runtime through a dedicated public listener.

Rust authenticates public requests through a trusted internal Python endpoint:

- `POST /_internal/mcp/authenticate`

Python remains the system of record for:

- JWT validation
- token scoping / team visibility
- RBAC

Rust consumes the authenticated context and owns progressively more of the
public MCP runtime path.

### Session/auth reuse

Rust may reuse authenticated context per MCP session, but only with explicit
ownership/binding checks. Session reuse is:

- bound to the original authenticated context
- validated against an auth-binding fingerprint
- denied if the auth binding changes for the same `mcp-session-id`
- backed by dedicated session-isolation tests

### Fallback and safety

`shadow` is the safety-first rollback/comparison mode. It keeps the public MCP
transport/session path on Python while still running the Rust sidecar
internally.

Low-level `EXPERIMENTAL_RUST_MCP_*` flags still exist as advanced overrides, but
the documented operator model is the high-level mode switch above.

## Consequences

### Positive

- Clear operational model for rollout, benchmarking, and rollback
- Public MCP ingress can move off Python incrementally without rewriting the
  full security/control plane
- `shadow` provides a clean safety mode instead of an ambiguous hybrid path
- Session/auth reuse has a documented security model and dedicated isolation
  coverage
- The runtime can own more of the hot MCP path while preserving Python
  compatibility fallbacks

### Negative

- The architecture is now explicitly multi-process and multi-language
- Rust and Python responsibilities must remain carefully documented and tested
- Health, profiling, and debugging require mode-aware operational knowledge
- Some behavior still depends on narrow internal Python routes and compatibility
  seams

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Keep ADR-038 as the canonical description | No longer matches the implementation or rollout model |
| Full Rust rewrite of the entire gateway/security stack | Higher risk and out of scope for the current incremental migration |
| Expose only low-level `EXPERIMENTAL_RUST_MCP_*` flags | Too hard for operators to reason about safely |
| Keep public `/mcp` permanently on Python and use Rust only behind Python | Leaves the Python ingress hop in the hot path and limits the performance gain |

## References

- [Rust MCP Runtime Architecture](../rust-mcp-runtime.md)
- [Performance Architecture](../performance-architecture.md)
- `tools_rust/mcp_runtime/TESTING-DESIGN.md` in the repository
- `tools_rust/mcp_runtime/README.md` in the repository
