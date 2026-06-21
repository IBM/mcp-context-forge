# Proposed A2A Hook Types for `cpex.framework`

**Status**: Proposal / pending cpex review
**Owners**: ContextForge A2A native passthrough plan, Amendment F (Phase C)
**Related**: [`mcpgateway/services/a2a_hooks.py`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_hooks.py), `.omo/plans/a2a-native-passthrough.md` Amendment F

## Summary

The A2A native passthrough work landed three new code paths that DO NOT call `A2AAgentService.invoke_agent`:

1. **T11 card route** — `GET /a2a/{agent_name}/.well-known/agent-card.json` (per-agent + v-server-scoped form) at `mcpgateway/main.py::get_a2a_agent_card`. Resolves the agent via `synthesize_agent_card`.
2. **T12 GetExtendedAgentCard branch** — `POST /a2a/{agent_name}` with method `GetExtendedAgentCard` / `agent/getAuthenticatedExtendedCard` at `mcpgateway/main.py::dispatch_a2a_agent`. Synthesizes from the DB row (D18 — NEVER forwards upstream).
3. **T5 streaming dispatch** — `POST /a2a/{agent_name}` with streaming methods (`SendStreamingMessage`, `SubscribeToTask`, plus v0.3 aliases) at `mcpgateway/services/a2a_service.py::dispatch_a2a_jsonrpc_streaming`. Returns an async generator.

The existing cpex `AgentHookType.AGENT_PRE_INVOKE` / `AGENT_POST_INVOKE` fire on the unary `invoke_agent` path but NOT on these three. A2A-specific plugins (per-method rate-limiters, audit on card discoveries, streaming-aware backpressure) are blind on the new paths.

The global HTTP-level `HttpAuthMiddleware → run_pre_request_hooks` already fires for `/a2a/*` URLs, so plugins that gate at the HTTP layer continue to work today. This proposal is about METHOD-AWARE A2A hooks beyond what the HTTP layer provides.

## Decision fork

Two acceptable implementation paths exist. Pick ONE before any cpex change lands.

### Path A — Add dedicated cpex hook types

Extend `cpex.framework.AgentHookType` with six new enum values and add matching payload classes. The placeholder helpers in `mcpgateway/services/a2a_hooks.py` get a one-line body each.

**Pros**: clean semantic separation; plugins subscribe to exactly what they care about; matches the existing per-event pattern in cpex.

**Cons**: schema churn on cpex; new payload classes need to live in cpex even though they're A2A-specific; downstream cpex consumers (other gateways) inherit the new types.

### Path B — Reuse `AGENT_PRE_INVOKE` / `AGENT_POST_INVOKE` with a method discriminator

Add a `method` field to the existing payloads (or its companion metadata dict) and route all six events through the existing pair. Plugins filter on `payload.method in {"GetAgentCard", "GetExtendedAgentCard", "SendStreamingMessage", ...}`.

**Pros**: zero cpex enum churn; existing plugins that ignore the field keep working; one less integration point to maintain.

**Cons**: conflates metadata reads (card discovery) with actual invocations from a plugin's perspective; rate-limiters that gate on `AGENT_PRE_INVOKE` would suddenly start rate-limiting public card fetches unless they're updated to filter on `method`; semantically misleading.

### Recommendation

**Path A** for production deployments that care about plugin semantics. The clean enum separation is worth the cpex churn — a future-Cedar / OPA-style migration will thank you for not conflating two operations under one event name. Path B is acceptable as a transitional shape if cpex changes are blocked.

## Proposed hook types

All six events are A2A-specific and apply only to agents (not tools / resources / prompts). They reuse the existing cpex `GlobalContext`, `HttpHeaderPayload`, and `PluginViolationError` types; only the per-event payload classes are new.

### `AGENT_CARD_PRE` (Amendment F, T-Phase-C-1)

Fires immediately before `synthesize_agent_card` runs at the public T11 well-known card route. Anonymous / unauthenticated callers are valid here — the card route is the only A2A path that legitimately serves `user_email=None, token_teams=[]`.

```python
# Proposed cpex addition
class AgentHookType(Enum):
    ...
    AGENT_CARD_PRE = "agent.card.pre"
    AGENT_CARD_POST = "agent.card.post"

@dataclass(frozen=True)
class AgentCardPrePayload:
    """Pre-discovery payload for AGENT_CARD_PRE."""
    agent_name: str               # Path param — the only identifier available pre-resolution.
    server_id: Optional[str]      # Set when fired from the v-server-scoped /servers/{id}/a2a/{name} URL.
    public_base_url: str          # Gateway-public base URL the card will advertise (F15 + Oracle re-review #4).
    caller_email: Optional[str]   # None on the anonymous public path; populated when the route runs under auth.
```

Modification points (if cpex policy allows): plugins MAY override `public_base_url` to force a different advertised URL (e.g. for proxy / reverse-tunnel scenarios). Plugins MUST NOT override `agent_name` or `server_id` — those are routing inputs, not policy outputs.

### `AGENT_CARD_POST` (Amendment F, T-Phase-C-1)

Fires after `synthesize_agent_card` returns, regardless of outcome. `card_resolved=False` distinguishes a legitimate 404 (visibility miss / agent not found / v-server membership miss) from a real card discovery.

```python
@dataclass(frozen=True)
class AgentCardPostPayload:
    agent_name: str
    server_id: Optional[str]
    card_resolved: bool           # False for 404 outcomes — Amendment B three-level conjunctive deny.
    card_summary: Optional[Mapping[str, Any]]   # Optional projection of the AgentCard (name, version, capabilities). None on 404.
```

Non-blocking semantics — exceptions from the plugin chain are logged but never propagated, matching `AGENT_POST_INVOKE`.

### `AGENT_EXTENDED_CARD_PRE` (Amendment F, T-Phase-C-2)

Fires in the T12 `GetExtendedAgentCard` / `agent/getAuthenticatedExtendedCard` branch of `dispatch_a2a_agent` BEFORE the local synthesis. D18 is non-negotiable: the gateway NEVER forwards an extended card request upstream, so this hook only observes the synthesis decision; it does NOT gate forwarding.

The agent ORM row is already resolved at this point. The proposed payload reuses the existing `agent_id` shape from `AgentPreInvokePayload` for symmetry.

```python
class AgentHookType(Enum):
    ...
    AGENT_EXTENDED_CARD_PRE = "agent.extended_card.pre"
    AGENT_EXTENDED_CARD_POST = "agent.extended_card.post"

@dataclass(frozen=True)
class AgentExtendedCardPrePayload:
    agent_id: str                 # UUID of the resolved agent.
    server_id: Optional[str]      # Set on the v-server-scoped URL form.
    method: str                   # "GetExtendedAgentCard" or "agent/getAuthenticatedExtendedCard".
    caller_email: str             # MUST be authenticated for this branch — anonymous callers hit the 401 path before this.
    capabilities_advertised: bool # Whether agent.capabilities["extendedAgentCard"] is True. False short-circuits to -32007.
```

### `AGENT_EXTENDED_CARD_POST` (Amendment F, T-Phase-C-2)

Fires after the extended card synthesis returns OR after `-32007 AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED` short-circuits.

```python
@dataclass(frozen=True)
class AgentExtendedCardPostPayload:
    agent_id: str
    server_id: Optional[str]
    method: str
    success: bool                 # False on -32007 or visibility race condition (None card).
    card_summary: Optional[Mapping[str, Any]]
```

### `AGENT_STREAMING_DISPATCH_PRE` (Amendment F, T-Phase-C-3)

Fires once at the head of `dispatch_a2a_jsonrpc_streaming` BEFORE the upstream SSE connection opens. MUST fire exactly once per request regardless of stream length.

```python
class AgentHookType(Enum):
    ...
    AGENT_STREAMING_DISPATCH_PRE = "agent.streaming_dispatch.pre"
    AGENT_STREAMING_DISPATCH_POST = "agent.streaming_dispatch.post"

@dataclass(frozen=True)
class AgentStreamingDispatchPrePayload:
    agent_id: str
    server_id: Optional[str]      # Set on /servers/{id}/a2a/{name} URL form.
    method: str                   # "SendStreamingMessage" | "SubscribeToTask" | "message/stream" | "tasks/resubscribe"
    hop_count: int                # UAID federation hop counter, pre-stamp.
    bearer_token_present: bool    # NOT the token value — just whether one was forwarded.
    headers: HttpHeaderPayload
```

Plugins MAY deny the streaming dispatch by raising `PluginViolationError` (analogous to `AGENT_PRE_INVOKE`). A rate-limiter that has saturated for the caller would deny here BEFORE the upstream connection opens; a content filter that needs to inspect the request body before the first chunk would inspect via `headers` / `parameters` mirrors.

### `AGENT_STREAMING_DISPATCH_POST` (Amendment F, T-Phase-C-3)

Fires once after the stream closes — normal completion OR client disconnect OR upstream error. MUST NOT fire from inside the async-generator yield loop. The implementation wraps the SSE generator in a `try/finally` that fires the post-hook in the `finally` block.

```python
@dataclass(frozen=True)
class AgentStreamingDispatchPostPayload:
    agent_id: str
    server_id: Optional[str]
    method: str
    chunks_sent: int              # Counter incremented per yield. Plugins can record stream length without subscribing to per-chunk data.
    completed_normally: bool      # False on client disconnect, upstream protocol error, or task cancellation.
    duration_ms: float
```

Non-blocking semantics. A misbehaving streaming-post plugin must never delay the SSE response close or leak the connection.

## Wire-level contract

For Path A:

- All six events fire from `mcpgateway/services/a2a_hooks.py` helpers. Today those helpers are no-op placeholders that log at DEBUG. The future Phase C commit swaps the bodies for real `await plugin_manager.invoke_hook(AgentHookType.AGENT_CARD_PRE, payload=..., global_context=..., local_contexts=..., violations_as_exceptions=...)` calls.
- `GlobalContext` is constructed via the SAME `build_a2a_hook_context` helper used by the existing `AGENT_PRE_INVOKE` / `AGENT_POST_INVOKE` path. Plugins receive a unified context shape across all six events.
- For Path B: `AGENT_PRE_INVOKE` and `AGENT_POST_INVOKE` grow an optional `method` field on the payload; the helpers populate it; legacy plugins that don't filter on `method` keep firing on every event and may need their thresholds re-tuned.

## Threading model

All six events fire INSIDE the request handler's event loop (no thread offload). Plugins MUST NOT do blocking I/O — async-only. The two POST events run in `try/except` blocks that swallow plugin exceptions; the four PRE events propagate `PluginViolationError` for deny semantics.

## Test strategy

The future Phase C commit will add:

- Per-event "fired" tests asserting the plugin chain receives the expected payload.
- A "fires exactly once" test for `AGENT_STREAMING_DISPATCH_POST` — guards against the chunk-level firing regression.
- A "non-blocking" test for the POST events — a plugin that raises must not fail the request.
- A "deny" test for each PRE event — `PluginViolationError` propagation surfaces as the appropriate JSON-RPC error code or HTTP status.

## Migration plan

Per Amendment F's deferral note, the future Phase C focused commit does THREE things:

1. **Pick Path A or B** based on cpex maintainer guidance.
2. **Land the cpex changes** (Path A) OR **update the payload schema** (Path B) in the cpex repository.
3. **Swap the placeholder bodies** in `mcpgateway/services/a2a_hooks.py` for real firing. Wire to `main.py::get_a2a_agent_card`, `main.py::dispatch_a2a_agent` (extended-card branch), and the SSE generator wrapping in the streaming branch.

The helper signatures in `a2a_hooks.py` are stable across both paths — only the BODIES change. Callers at T11 / T12 / T5 do not change.

## Open questions

- **Should `AGENT_CARD_PRE` allow plugin denial?** Today the card route is public; a rate-limiter that denies card fetches would degrade discovery. Recommendation: NO denial — make `violations_as_exceptions=False` for both card events, blocking deny only on the actual invocation paths (`AGENT_PRE_INVOKE`, `AGENT_EXTENDED_CARD_PRE`, `AGENT_STREAMING_DISPATCH_PRE`).
- **Per-chunk hook?** Plugins that want token-level audit / per-chunk PII redaction would need an `AGENT_STREAMING_DISPATCH_CHUNK` event firing inside the yield loop. Out of scope for this proposal — defer until a concrete use case lands.
- **Reuse across MCP streaming?** ContextForge has MCP streaming too. If the cpex team wants generic `STREAMING_DISPATCH_PRE` / `POST` types that span A2A + MCP, the A2A-specific payload fields move into per-protocol subclasses. Out of scope for this proposal — A2A is shipping first.

## References

- A2A native passthrough plan: `.omo/plans/a2a-native-passthrough.md` Amendment F + deferral note
- Helper module + placeholder helpers: `mcpgateway/services/a2a_hooks.py`
- Existing `AGENT_PRE_INVOKE` / `AGENT_POST_INVOKE` firing convention: `mcpgateway/services/a2a_service.py` (post-helper-refactor)
- HTTP-level pre-request hook that fires globally for `/a2a/*` today: `mcpgateway/middleware/http_auth_middleware.py:156-227`
