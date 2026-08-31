# ADR-051: Swappable MCP Ingress Mount

- *Status:* Accepted
- *Date:* 2026-04-18
- *Deciders:* Platform Team
- *Related:* [ADR-043: Rust MCP Runtime Sidecar with Mode-Based Rollout](043-rust-mcp-runtime-sidecar-mode-model.md), [ADR-050: Defer Generic Cluster-Wide Settings Propagation Framework](050-defer-generic-cluster-settings-propagation-framework.md), [Issue #4273: Runtime-mutable RUST_MCP_MODE](https://github.com/IBM/mcp-context-forge/issues/4273), [Issue #4278: Propagate runtime MCP mode override into the public reverse proxy](https://github.com/IBM/mcp-context-forge/issues/4278)

## Context

Issue #4273 introduced the runtime-mutable MCP mode override. The original
implementation mounted an `MCPStreamableHTTPModeDispatcher` at `/mcp` that
held two hard-coded transports — `MCPRuntimeHeaderTransportWrapper`
(Python) and `RustMCPRuntimeProxy` (the trusted Python→Rust forwarder over
`MCP_RUST_LISTEN_HTTP` / UDS) — and chose between them per request based
on `_should_mount_public_rust_transport()`. That worked for the two
transports we had at the time but pinned the dispatcher to a closed set
and embedded the selection policy inside the dispatch method.

Two near-term needs surfaced that the dispatcher couldn't accommodate
cleanly:

1. **An nginx-style reverse proxy to the Rust public listener.** In a
   single-process / no-nginx deployment, edge mode still routes through
   Python's `RustMCPRuntimeProxy` over the trusted-internal listener
   (`MCP_RUST_LISTEN_HTTP`). For deployments without nginx in front, the
   gateway can also play the nginx role itself by reverse-proxying to
   the Rust public listener at `MCP_RUST_PUBLIC_LISTEN_HTTP`. This is a
   third ingress kind, not a different way of using the existing two.

2. **Future ingresses we don't yet have specs for.** Shadow-comparison
   (run both transports, compare results), percentage traffic split,
   per-method routing (POST → Rust direct, GET SSE → Python), header-based
   A/B canaries — each is a distinct ingress shape, not a tweak to the
   selection policy. Adding them under the closed dispatcher requires
   either growing its constructor signature with each new transport or
   subclassing repeatedly.

ADR-050 deferred the broader cluster-wide settings framework on the
grounds that N=1 is too few examples to abstract. The MCP ingress case is
different: we're already moving from N=2 to N=3 ingresses inside the same
mount, and the future N is plausibly larger. The abstraction sweet spot
is here.

## Decision

We replace `MCPStreamableHTTPModeDispatcher` with `MCPIngressMount`: a
thin ASGI indirection that holds a registry of named ASGI ingresses and a
swappable selector function. The mount itself owns no policy.

Implementation:

- **`mcpgateway/transports/mcp_ingress_mount.py`** — `MCPIngressMount`
  class. `register(name, app)` adds an ingress; `set_selector(fn)` swaps
  the policy; `dispatch(scope, receive, send)` is the ASGI entry point.
  Selector receives the ASGI scope so policies can inspect
  method/path/headers without changing the mount API.

- **`mcpgateway/transports/rust_mcp_public_proxy.py`** —
  `RustMCPPublicProxyApp`, an ASGI app that does nginx-style reverse-proxy
  to `MCP_RUST_PUBLIC_LISTEN_HTTP`. Adds `X-Forwarded-{For,Proto,Host}`,
  RFC 7239 `Forwarded`, and `X-Real-IP` so the Rust public listener's
  `/_internal/mcp/authenticate` callback sees the original client info.
  Streams both directions; preserves `Authorization` / `Cookie` (this is
  a public hop, not trusted-internal); does NOT inject any trust-marker
  headers. Built via `build_rust_public_proxy_app()` factory.

- **`mcpgateway/main.py`** — `_select_mcp_ingress(scope)` is the single
  selection policy. `_build_mcp_transport_app()` constructs the mount,
  registers `python` + `rust-internal` (always for boot=shadow/edge) and
  `rust-public` (only for boot=edge — shadow doesn't bind the Rust public
  listener). The mount is exposed under the legacy `mcp_transport_app`
  module attribute and aliases `dispatch` as `handle_streamable_http` so
  the `app.mount("/mcp", app=mcp_transport_app.handle_streamable_http)`
  line stays unchanged.

- **`mcpgateway/config.py`** — two new settings:
  - `mcp_rust_ingress: str = "internal"` — selector input, picks between
    the two Rust ingress shapes (`"internal"` or `"public"`).
  - `mcp_rust_public_proxy_upstream: str = "http://127.0.0.1:8787"` —
    default upstream for `RustMCPPublicProxyApp`, matching
    `docker-entrypoint.sh`'s `MCP_RUST_PUBLIC_LISTEN_HTTP=0.0.0.0:8787`
    accessed via loopback inside the same pod.

The selection policy in `_select_mcp_ingress` preserves all the existing
safety invariants:

- `_should_mount_public_rust_transport()` is consulted first — same
  function the runtime-mode override coordinator already gates on, so
  shadow override / edge boot / safety-flag check / boot=full all behave
  identically to the prior dispatcher.
- Within the Rust branch, the `mcp_rust_ingress` setting selects between
  the two shapes. Default is `"internal"` to preserve the prior behavior
  bit-for-bit; operators opt into the public-proxy shape with a single
  setting change.
- For boot=full, the mount isn't used at all — the plain
  `RustMCPRuntimeProxy` is mounted directly per the prior code, since
  full-boot has no dispatcher (flipping `full` would orphan Rust-held
  session/event-store state per ADR-043).

## Why this isn't the framework ADR-050 deferred

ADR-050 deferred a generic cluster-wide settings propagation framework.
This ADR is scoped to the single mount point that serves `/mcp` and the
ingress shapes that mount can hold. It doesn't introduce a registry of
runtime settings, a propagation channel, or a coordinator — those remain
purpose-built in `runtime_state.py`. The MoveCompatibility/safety
invariant gate, the boot reconcile status surfacing, the audit pipeline
all stay exactly where they are; the new mount just consumes
`should_mount_public_rust_transport()` and `settings.mcp_rust_ingress`
the same way the prior dispatcher consumed the same predicates.

## Consequences

### Positive

- **Adding a new ingress is one `register()` call.** No conditional in
  the dispatch hot path, no class hierarchy churn. Future shapes
  (shadow-comparison, percentage traffic split, per-method routing) plug
  in without touching the mount class or the existing ingresses.
- **Each ingress is a plain ASGI 3.0 callable.** Testable in isolation
  by calling `await ingress(scope, receive, send)` with a mock — see
  `tests/unit/mcpgateway/transports/test_mcp_ingress_mount.py`.
- **Selector swap is atomic.** `set_selector(fn)` replaces the policy
  without rebuilding the mount or touching ingress registrations. In
  practice the selector is set once at boot and the runtime-mode
  override coordinator drives behavior changes through the predicates
  the selector reads — but the mechanism for hot-swapping the policy
  itself is now there.
- **Operator-facing 503 names the missing ingress.** When a deployment
  is misconfigured (selector returns an ingress name not registered for
  this build) the response body reads, e.g., `MCP ingress 'rust-public'
  is not registered for this build; available: ['python', 'rust-internal']`.
- **The nginx-style public proxy is now a usable production option.**
  Single-process / no-proxy edge deployments can set
  `mcp_rust_ingress=public` and route directly to Rust's public listener
  without nginx in the picture — partially closing the gap tracked in
  #4278 for non-nginx topologies.
- **Drain semantics preserved.** Per-request selection means in-flight
  requests on a deselected ingress complete on their original handler;
  only newly-accepted requests follow the new selection. Same property
  the prior dispatcher had — see the in-flight drain test in
  `tests/unit/mcpgateway/test_main_extended.py`.

### Negative

- **One more abstraction to learn.** Contributors wanting to understand
  the `/mcp` mount now read three modules
  (`mcp_ingress_mount.py`, the ingress implementations, the selector in
  `main.py`) instead of one dispatcher class. The mount is intentionally
  ~140 LOC including docstrings, and `_select_mcp_ingress` is one screen
  of code, so the additional cognitive load is small.
- **The legacy `handle_streamable_http` alias is a wart.** The mount
  exposes `dispatch` as the natural ASGI entry point but the
  `app.mount("/mcp", app=mcp_transport_app.handle_streamable_http)` line
  in `main.py` predates the rename. Aliasing one to the other keeps the
  mount line unchanged; a follow-up could change the mount line and drop
  the alias.
- **Public-listener proxy shares a port with the internal listener.**
  `MCP_RUST_LISTEN_HTTP=127.0.0.1:8787` and
  `MCP_RUST_PUBLIC_LISTEN_HTTP=0.0.0.0:8787` are the same port on
  different bind addresses. Operators who want to run both listeners
  from outside the default `docker-entrypoint.sh` flow need to be aware
  that the Rust binary picks one or the other based on env at startup —
  this isn't something the new ingress shape can change.

### Neutral

- The runtime-mode override admin API (`PATCH /admin/runtime/mcp-mode`)
  is unchanged. It still reads/writes `RuntimeState`; the selector picks
  it up via `_should_mount_public_rust_transport()` on the next request.
- Docs at `docs/docs/architecture/rust-mcp-runtime.md` and the operator
  guidance in `.env.example` / `docker-compose.yml` continue to describe
  shadow ↔ edge as the user-visible toggle. The internal/public ingress
  choice is a deployment-shape setting separate from the runtime override.

## Migration from MCPStreamableHTTPModeDispatcher

Code consumers:

- `mcp_transport_app: MCPStreamableHTTPModeDispatcher` →
  `mcp_transport_app: MCPIngressMount` for boot=shadow/edge. Same
  attribute on the module, different class.
- `dispatcher._python_transport` / `_rust_transport` →
  `mount._ingresses["python"]` / `mount._ingresses["rust-internal"]`
  (or `mount.names()` for the registered set).
- `dispatcher.handle_streamable_http(scope, receive, send)` →
  `mount.dispatch(scope, receive, send)`. The `handle_streamable_http`
  alias is preserved on the mount so the existing `app.mount(...)` line
  works unchanged.

Tests:

- The dispatcher-behavior tests in `tests/unit/mcpgateway/test_main_extended.py`
  (the `TestConditionalPaths::test_import_*` group plus the two
  `test_mcp_ingress_mount_*` async tests) now assert against
  `MCPIngressMount` / `_select_mcp_ingress` instead of the prior
  dispatcher class. Behavior assertions (per-request routing, in-flight
  drain) are preserved.
- New focused tests for the mount itself live at
  `tests/unit/mcpgateway/transports/test_mcp_ingress_mount.py`.
- New focused tests for the public-listener proxy (header forwarding,
  XFF spoof rejection, hop-by-hop stripping, error mapping, streaming
  close-on-exit) live at
  `tests/unit/mcpgateway/transports/test_rust_mcp_public_proxy.py`.

## When to revisit

Build the next layer of abstraction (e.g., a registry-based ingress
plugin system that auto-registers from setup.cfg entry points) when:

1. A second non-Rust ingress shape appears that benefits from registration
   outside `main.py` — e.g., a third-party plugin shipping its own MCP
   ingress.
2. The selector grows past ~50 LOC of policy. At that point the right
   move is to extract policy into composable predicates rather than to
   change the mount.

Until then, registration in `main.py` is the simplest thing that works
and keeps the available ingress set auditable from one location.

## References

- Implementation:
  - `mcpgateway/transports/mcp_ingress_mount.py`
  - `mcpgateway/transports/rust_mcp_public_proxy.py`
  - `mcpgateway/main.py` (`_build_mcp_transport_app`, `_select_mcp_ingress`)
  - `mcpgateway/config.py` (`mcp_rust_ingress`, `mcp_rust_public_proxy_upstream`)
- Tests:
  - `tests/unit/mcpgateway/transports/test_mcp_ingress_mount.py`
  - `tests/unit/mcpgateway/test_main_extended.py` (the two
    `test_mcp_ingress_mount_*` tests + the three `test_import_*` tests)
- Architecture overview: [Rust MCP Runtime](../rust-mcp-runtime.md)
- Reverse-proxy follow-up: [#4278](https://github.com/IBM/mcp-context-forge/issues/4278)
