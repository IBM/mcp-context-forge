# ADR-050: Defer Generic Cluster-Wide Settings Propagation Framework

- *Status:* Accepted
- *Date:* 2026-04-18
- *Deciders:* Platform Team
- *Related:* [ADR-043: Rust MCP Runtime Sidecar with Mode-Based Rollout](043-rust-mcp-runtime-sidecar-mode-model.md), [Issue #4273: Runtime-mutable RUST_MCP_MODE](https://github.com/IBM/mcp-context-forge/issues/4273)

## Context

Issue #4273 introduced the first runtime-mutable cluster-wide setting in
ContextForge: an authenticated admin can now flip the public `/mcp` ingress
(and the registered-A2A invocation path) between `shadow` and `edge` at
runtime, with the change propagating across all pods via Redis. The
implementation lives in `mcpgateway/runtime_state.py` and exposes:

- `RuntimeStateCoordinator` — Redis pub/sub on
  `contextforge:runtime:mode`, with a `LISTEN_LOOP_DEGRADE_THRESHOLD` for
  fault tolerance and a `cluster_propagation` status surfaced via `/health`
- A monotonic per-runtime version counter via `INCR contextforge:runtime:mode_version:{runtime}`
  that prevents two pods from silently overwriting each other's flips
- A short-lived per-runtime hint key
  (`contextforge:runtime:mode_state:{runtime}`, TTL 24h) so a freshly
  started pod reconciles to the cluster's current desired override on boot
- A compatibility gate (`version.deployment_allows_override_mode` →
  `MoveCompatibility` enum) that prevents stranded overrides on deployments
  whose boot-time flags can't safely honor the requested mode
- `BootReconcileStatus` (`OK` / `REDIS_UNAVAILABLE` / `MALFORMED_HINT` /
  `INCOMPATIBLE_NO_DISPATCHER` / `INCOMPATIBLE_BOOT_FULL` /
  `INCOMPATIBLE_SAFETY_FLAG` / `PUBSUB_UNAVAILABLE` / `COORDINATOR_OFFLINE`)
  for granular operator visibility
- Audit trail integration via `SecurityLogger.log_data_access`
- A reverse-proxy detection WARN that surfaces the proxy-doesn't-follow-the-flip
  gap (tracked in [#4278](https://github.com/IBM/mcp-context-forge/issues/4278))

The natural follow-up question: **other runtime-mutable settings will
appear** (feature flags, log levels, plugin enable/disable, traffic-shaping
knobs, etc.). Should we extract this propagation machinery into a generic
framework now, before the second consumer arrives?

## Decision

**We do NOT extract a generic framework today.** The current implementation
stays purpose-built for MCP / A2A runtime mode overrides. When a second
genuine cluster-wide-mutable-setting use case lands, we revisit with
concrete requirements from both consumers in hand.

This ADR records the decision, the alternative we analyzed, and the
trigger conditions for revisiting — so the next contributor doesn't have
to re-derive the same trade-off from scratch.

## Rationale

1. **N=1 is the wrong moment to abstract.** Repo convention is explicit:
   three similar lines beats a premature abstraction.

   We have exactly one concrete consumer (with two sub-kinds, MCP and A2A,
   that already share most of the implementation). The shape of the right
   abstraction is hard to see from a single instance — what looks generic
   in one consumer often turns out to be policy-specific in the second.

2. **The current code is the most-reviewed code on the branch.** Six
   stop-time review iterations caught real bugs during development
   (safety-invariant bypass, stranded overrides, listen-loop
   false-recovery, self-contradicting 409 messages, etc.). Pulling the
   propagation primitives into a separate framework now would either lose
   that hardening or require porting all the regression tests across an
   additional API boundary. Either path is net-negative for reliability.

3. **The current factoring already supports a second consumer cheaply.**
   `MoveCompatibility`, `BootReconcileStatus`, and the per-runtime keying
   scheme were intentionally kept generic-shaped. A second consumer can
   copy-modify `runtime_state.py` and `runtime_admin_router.py` (≈900 LOC
   together) and the diff against this ADR's design will be the basis for
   the eventual abstraction. That diff is more reliable design input than
   any framework we'd guess at now.

## The alternative we considered

A `ClusterStatePrimitive` (or `RuntimeSettingsCoordinator`) that owns the
operational shell, with each consumer plugging in its policy. Sketch:

```python
class ClusterStatePrimitive:
    """Generic Redis-backed cluster-wide propagation for in-memory settings."""

    def __init__(
        self,
        *,
        channel: str,                       # e.g. "contextforge:runtime:mode"
        hint_key_prefix: str,               # e.g. "contextforge:runtime:mode_state"
        version_key_prefix: str,            # e.g. "contextforge:runtime:mode_version"
        hint_ttl_seconds: int = 24 * 60 * 60,
        listen_loop_degrade_threshold: int = 5,
    ) -> None: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def next_version(self, key: str, current_version: int) -> int: ...
    async def publish(self, payload: dict) -> bool: ...
    def register_consumer(
        self,
        kind: str,
        *,
        compat_check: Callable[[Any, Any], CompatibilityResult],
        apply_callback: Callable[[ChangeEvent], Awaitable[None]],
        status_setter: Callable[[BootStatus], None],
    ) -> None: ...
```

Each consumer (MCP modes, log levels, feature flags, …) would register
itself and supply:

- a **serializer** for its value type
- a **`compat_check`** that returns a structured rejection reason or `OK`
  (today's `MoveCompatibility` becomes one realization)
- an **`apply_callback`** invoked when a remote change lands in local state
- a **`status_setter`** so per-consumer boot reconcile status surfaces on
  `/health` independently

What stays per-consumer (intentionally):

- The compatibility-rejection enum (today's `MoveCompatibility`) is
  policy-specific and shouldn't be generalized; it just has to satisfy a
  protocol shape (`OK` vs. structured-reason).
- The admin router endpoints (URL shape, RBAC permission, audit
  resource\_type) stay one-per-feature.
- The transport-layer wiring that observes the override (today's
  `MCPStreamableHTTPModeDispatcher`) is consumer-specific by definition.

What the framework would own:

- Pub/sub channel lifecycle, subscriber backoff, `degraded` status
- Monotonic version allocation (`INCR` discipline)
- Boot hint reconciliation (read + compatibility-gated apply)
- Listen-loop with the same compatibility gate on remote messages
- Per-consumer `cluster_propagation` and `boot_reconcile_status` surfaces
- A single set of operational dashboards / alert rules

## When to revisit

Build the framework when **any one** of the following becomes true:

1. A second concrete cluster-wide-mutable-setting use case is in flight,
   not hypothetical. At that point, build both consumers side-by-side and
   let the framework fall out of the diff.
2. A third, independently-tracked use case is on the horizon. Two
   consumers may still be close enough that a framework is premature; three
   makes the case unambiguous.
3. We need cross-consumer coordination (e.g. atomic multi-setting flips,
   global per-cluster freeze, or a "config version" that pins multiple
   settings together). That's a feature the framework enables; the
   purpose-built coordinator can't deliver it without significant rework.

Until one of those conditions hits, the right move is to copy-modify
`runtime_state.py` for the second consumer and treat the resulting two-file
diff as the design input for ADR-051 (or whichever number lands).

## Consequences

### Positive

- The current implementation stays exactly as the six review rounds shaped
  it — no risk of regression from porting the hardened logic across a new
  API boundary.
- The next contributor adding a runtime-mutable setting has a working,
  well-tested template to copy and a clear ADR explaining why the framework
  doesn't exist yet.
- Operational tooling (alerts, dashboards, runbooks) for MCP/A2A overrides
  can be built and refined without worrying about a framework refactor
  invalidating them.

### Negative

- Two near-identical consumers will exist in the codebase between when the
  second use case lands and when the framework is built. That's the
  expected cost of waiting for the right shape.
- A second contributor might miss a subtle defense (e.g. the listen-loop
  compatibility gate, the discarded-hint-stays-in-Redis trade-off, the
  reverse-proxy WARN) when copy-modifying. **Mitigation:** before the
  second consumer ships, capture the non-obvious defenses as a checklist in
  this ADR's "When to revisit" section so the copy-modify diff is reviewed
  against them.

### Neutral

- ADR-043 (Rust MCP Runtime Sidecar with Mode-Based Rollout) and the
  Modular Runtime Architecture work continue independently. Nothing in
  this ADR forecloses or accelerates either.

## References

- Implementation: `mcpgateway/runtime_state.py`,
  `mcpgateway/routers/runtime_admin_router.py`,
  `mcpgateway/version.py` (the `_should_mount_public_rust_transport` /
  `_should_delegate_a2a_to_rust` / `_deployment_allows_override_mode`
  helpers)
- Architecture overview: [Rust MCP Runtime — Runtime Mode Override](../rust-mcp-runtime.md#runtime-mode-override)
- Reverse-proxy follow-up: [#4278](https://github.com/IBM/mcp-context-forge/issues/4278)
