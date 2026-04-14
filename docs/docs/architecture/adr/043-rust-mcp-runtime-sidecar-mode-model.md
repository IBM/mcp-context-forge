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

Rust communicates with Python through trusted internal HTTP endpoints derived
from `--backend-rpc-url` (default `http://127.0.0.1:4444/rpc`):

| Endpoint | Purpose |
|----------|---------|
| `POST /_internal/mcp/authenticate` | Validate JWT, return authenticated context |
| `POST /_internal/mcp/tools/call/resolve` | Build execution plan; runs pre-invoke plugin hooks |
| `POST /_internal/mcp/tools/call` | Full Python fallback execution (all plugins) |
| `POST /_internal/mcp/tools/call/metric` | Record tool execution timing and success/failure |

These endpoints are internal-only and are not exposed through nginx to
external clients.

Python remains the system of record for:

- JWT validation
- token scoping / team visibility
- RBAC
- plugin hook execution (pre-invoke and post-invoke)

Rust consumes the authenticated context and plugin-modified state, then owns
progressively more of the public MCP runtime path.

### Session/auth reuse

Rust may reuse authenticated context per MCP session, but only with explicit
ownership/binding checks. Session reuse is:

- bound to the original authenticated context
- validated against an auth-binding fingerprint
- denied if the auth binding changes for the same `mcp-session-id`
- backed by dedicated session-isolation tests

### Two-phase tools/call model

In `edge` and `full` modes, `tools/call` follows a resolve-then-execute
pattern:

**Phase 1 — Resolve (Rust calls Python)**

Rust sends the original JSON-RPC payload to
`POST /_internal/mcp/tools/call/resolve`. Python runs
`tool_service.prepare_rust_mcp_tool_execution()`, which:

1. Validates auth, RBAC, tool visibility, and server scope
2. Checks eligibility for direct Rust execution (see criteria below)
3. If eligible and pre-invoke plugin hooks are registered, executes them
4. Returns an execution plan containing:
   - `eligible` — whether Rust can execute directly
   - `transport` — must be `streamablehttp` for direct execution
   - `serverUrl` — upstream MCP server URL with auth applied
   - `remoteToolName` — tool name at the upstream server
   - `headers` — auth headers including any injected by pre-invoke plugins
   - `modifiedArgs` — arguments potentially transformed by pre-invoke plugins
   - `hasPreInvokeHooks` — flag indicating hooks ran (disables plan caching)
   - `fallbackReason` — why the tool is ineligible, when applicable

**Phase 2 — Execute or Fallback**

- **If `eligible == true`**: Rust applies `modifiedArgs` and `headers` from
  the plan and calls the upstream MCP server directly. Python is not
  involved in the hot path.
- **If `eligible == false`**: Rust forwards the full request to
  `POST /_internal/mcp/tools/call`, where Python executes the complete
  `invoke_tool()` path with all pre-invoke and post-invoke plugin hooks.

After direct execution, Rust calls
`POST /_internal/mcp/tools/call/metric` to record timing and
success/failure for observability.

### Plugin execution by mode

| Mode | Pre-invoke plugins | Post-invoke plugins | Tool execution |
|------|-------------------|---------------------|----------------|
| `off` | Python (normal path) | Python (normal path) | Python |
| `shadow` | Python (normal path) | Python (normal path) | Python |
| `edge` | Python (via `/resolve`) | Python (fallback only) | Rust direct or Python fallback |
| `full` | Python (via `/resolve`) | Python (fallback only) | Rust direct or Python fallback |

- **Pre-invoke hooks** always execute in Python, even on the Rust direct
  path. Their output (modified args, injected headers) is passed to Rust
  through the execution plan.
- **Post-invoke hooks** force a full Python fallback. If any post-invoke
  hook is registered, `prepare_rust_mcp_tool_execution()` returns
  `eligible: false` immediately, so the entire call goes through Python.
- **Plan caching** is disabled when pre-invoke hooks ran, because hook
  results may depend on per-call context (e.g. connection IDs, credentials).

### Direct execution eligibility

`prepare_rust_mcp_tool_execution()` returns `eligible: false` when any of
the following conditions apply:

| Condition | `fallbackReason` |
|-----------|-----------------|
| Post-invoke plugin hooks are configured | `post-invoke-hooks-configured` |
| Active observability trace | `observability-trace-active` |
| Gateway is in `direct_proxy` mode | `direct-proxy` |
| Tool integration type is not `MCP` | `unsupported-integration:{type}` |
| Transport is not `streamablehttp` | `unsupported-transport:{transport}` |
| JSONPath filter configured on tool | `jsonpath-filter-configured` |
| Custom CA certificate on gateway | `custom-ca-certificate` |
| Missing gateway URL | `missing-gateway-url` |
| OAuth with `authorization_code` grant | (handled inline, raises on token failure) |

When none of these conditions apply and the tool resolves to a single
unambiguous, enabled, reachable MCP tool behind a streamable HTTP gateway,
the plan is marked `eligible: true` and Rust executes directly.

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
- `crates/mcp_runtime/TESTING-DESIGN.md` in the repository
- `crates/mcp_runtime/README.md` in the repository
