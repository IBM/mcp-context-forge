# A2A Native Passthrough

**Status**: Shipped (Waves 1-7 + Phase 3 amendments)
**Owners**: ContextForge A2A native passthrough plan (`.omo/plans/a2a-native-passthrough.md`)
**Related**: [`a2a-cpex-hook-proposal.md`](a2a-cpex-hook-proposal.md), [`multitenancy.md`](multitenancy.md), [`security-features.md`](security-features.md)

## Overview

ContextForge speaks A2A 1.0.0 (and the v0.3 legacy method aliases) end-to-end through a native passthrough — no per-tenant Rust sidecar, no separate proxy process. The same FastAPI app that hosts MCP and the admin UI also exposes:

- **Per-agent dispatch**: `POST /a2a/{agent_name}`
- **Per-agent card discovery**: `GET /a2a/{agent_name}/.well-known/agent-card.json`
- **V-server-scoped dispatch**: `POST /servers/{server_id}/a2a/{agent_name}` (path-rewritten to the per-agent form before handler invocation)
- **V-server-scoped card discovery**: `GET /servers/{server_id}/a2a/{agent_name}/.well-known/agent-card.json`
- **Streaming dispatch**: same URL, surfaces as SSE for `SendStreamingMessage` / `SubscribeToTask` (plus the v0.3 `message/stream` / `tasks/resubscribe` aliases)

The Python dispatcher in [`mcpgateway.services.a2a_service`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_service.py) is the only A2A execution path. The Rust A2A runtime that existed in earlier waves was unwired in Wave 6 and is scheduled for physical removal one release later (see [Rust Deprecation Cycle](#rust-deprecation-cycle-wave-6) below).

This document captures the architecture as it actually exists in code today. For the plan-level rationale and decision log see `.omo/plans/a2a-native-passthrough.md`.

## URL Families

Two URL shapes resolve to the same agent — they differ only in WHO can see the agent at that URL.

### Per-agent URL (`/a2a/{agent_name}`)

The canonical dispatch path. Visibility is single-level: the caller must be able to see the agent according to its `visibility` (`public` / `team` / `private`) per Layer-1 token scoping.

### V-server-scoped URL (`/servers/{server_id}/a2a/{agent_name}`)

The same agent surfaced under a virtual server. Visibility is **three-level conjunctive** evaluated cheapest-first to minimize timing side-channels (per Plan Amendment B):

1. Server visibility — caller can see the server itself
2. Server membership — the agent is bound to the server via `server_a2a_association`
3. Agent visibility — caller can see the agent directly

All three denials collapse to **HTTP 404** at the wire layer (Plan D14) so the client cannot distinguish "agent doesn't exist" from "agent exists but you can't see it" from "agent exists but not in this server".

The well-known card and dispatch URLs follow the same suffix convention; everything below `/{agent_name}` is preserved by the path-rewrite middleware.

## Path Rewrite Middleware

[`mcpgateway/middleware/a2a_path_rewrite.py`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/middleware/a2a_path_rewrite.py) is a pure ASGI middleware that rewrites the v-server URL form into the canonical per-agent form before the handler runs:

```text
Inbound:    /servers/{server_id}/a2a/{agent_name}[/suffix]
Rewritten:  /a2a/{agent_name}[/suffix]
Side effect: scope["a2a_server_id"] = server_id
```

The T11 card handler and T12 dispatch handler read `request.scope.get("a2a_server_id")` and thread it into [`A2AAgentService.synthesize_agent_card`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_service.py) / [`A2AAgentService.resolve_agent_for_dispatch`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_service.py). That's where the three-level visibility check runs — the middleware itself does NOT enforce membership (Plan D14).

Design invariants:

- Pure ASGI (not `BaseHTTPMiddleware`) for low overhead and full scope mutability
- Only HTTP scope is matched; WebSocket / lifespan pass through untouched
- Reverse-proxy `root_path` is stripped before regex matching so the same logic works behind a path-rewriting proxy
- Regex makes the trailing suffix group optional so BOTH the base dispatch URL `/servers/X/a2a/Y` (no trailing slash) AND every suffix-bearing URL like `/.well-known/agent-card.json` match
- Non-A2A paths (including `/servers/{id}/mcp` MCP transport URLs) pass through unchanged

## Agent Card Synthesizer

[`A2AAgentService.synthesize_agent_card`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_service.py) projects a session-attached `DbA2AAgent` row into an A2A 1.0.0 `AgentCard`, advertising the gateway as the dispatch URL — never the upstream agent's own URL. This is what makes the passthrough work end-to-end without round-tripping to the underlying agent for discovery.

URL rewriting in the synthesized card:

```python
# Per-agent form
url = f"{public_base_url}/a2a/{agent_name}"

# V-server-scoped form
url = f"{public_base_url}/servers/{server_id}/a2a/{agent_name}"
```

`public_base_url` resolution honors a soft override (Plan F15):

```python
public_base = getattr(settings, "a2a_public_base_url", None) or str(settings.app_domain).rstrip("/")
```

This lets operators set the advertised URL independently of the gateway's bind address (useful behind reverse proxies, when running on a non-standard port internally, etc.) without breaking deployments that don't set the optional field.

A synthesizer miss collapses to `None`, which the [`get_a2a_agent_card`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/main.py) handler renders as **HTTP 404** — agent unknown, visibility denied, and v-server membership miss produce the same wire outcome per D14.

The synthesizer is invoked from THREE places:

1. The public T11 card route (`GET /a2a/{name}/.well-known/agent-card.json`) — anonymous access valid; runs with `user_email=None, token_teams=[]`
2. The T12 dispatch `GetExtendedAgentCard` / `agent/getAuthenticatedExtendedCard` branch — synthesized from the DB row, **never forwarded upstream** (D18)
3. Internal flows that need the canonical card representation

## Dispatch Pipeline

[`dispatch_a2a_agent`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/main.py) at `POST /a2a/{agent_name}` runs a strict 9-step pipeline per Plan T12:

1. **Filter context** — `get_rpc_filter_context(request, user)` plus the admin / public-only token reshape that mirrors `/invoke` (D11)
2. **Agent resolution** — `resolve_agent_for_dispatch` checks visibility + v-server membership; raises `A2AAgentNotFoundError` / `AgentNotInServerError` on any denial; both collapse to HTTP 404 (D14)
3. **Per-invoke plumbing** — `hop_count` via `uaid_utils.read_hop_count`, bearer token, content-type, request headers (sensitive headers filtered)
4. **Body parse** — `JSONDecodeError` → `-32700 ParseError`; non-object body → `-32600 InvalidRequest` (Oracle v2 #7). The `Body(...)` dependency is **omitted** on purpose (D17) so the raw body is available for `-32700` framing
5. **A2A-Version validation** — method-aware (see [A2A-Version Negotiation](#a2a-version-negotiation))
6. **Method-dependent RBAC** — see [Method-Aware RBAC](#method-aware-rbac)
7. **`GetExtendedAgentCard` branch** — synthesize locally from the DB row; never forward; `-32007 AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED` when the agent's `capabilities["extendedAgentCard"]` is falsy
8. **Streaming branch** — `SendStreamingMessage` / `SubscribeToTask` and v0.3 aliases; see [Streaming Dispatch](#streaming-dispatch)
9. **Unary dispatch** — `dispatch_a2a_jsonrpc_unary`; success → JSON-RPC result envelope; error tuple → `make_jsonrpc_error`

The route deliberately has **no `@require_permission` decorator** (Oracle v2 #1) — body-dependent permission requires inspecting the JSON-RPC method first, which only makes sense after step 4.

## Method-Aware RBAC

Different A2A methods require different permissions. The gateway resolves the permission AFTER body parse:

| Method | Required permission |
|--------|---------------------|
| `GetExtendedAgentCard`, `agent/getAuthenticatedExtendedCard` | `a2a.read` |
| `SendMessage`, `SendStreamingMessage`, `SubscribeToTask`, all other invocations | `a2a.invoke` |

The check uses `PermissionService.check_permission(user_email=..., permission=..., resource_type="a2a_agent", resource_id=str(agent.id), team_id=agent.team_id, token_teams=token_teams)`. Passing `token_teams` is **security-significant**: it suppresses admin bypass when the token is public-only (`teams=[]`). See [`mcpgateway.services.permission_service`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/permission_service.py).

Permission denial returns **HTTP 403**, separate from the 404 visibility outcome. The two layers serve different purposes:

- **Layer 1 (visibility)** — controls what the caller can SEE; denial collapses to 404 to prevent enumeration
- **Layer 2 (RBAC)** — controls what the caller can DO with what they can see; denial returns 403

Both must pass.

## A2A-Version Negotiation

[`validate_a2a_version`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_service.py) is method-aware: it accepts a missing `A2A-Version` header for the legacy v0.3 slash-aliased methods (`message/send`, `message/stream`, `tasks/get`, `tasks/cancel`, `tasks/resubscribe`) and REQUIRES the header for the v1 PascalCase methods (`SendMessage`, `SendStreamingMessage`, `SubscribeToTask`, `GetExtendedAgentCard`, ...).

Mismatches surface as JSON-RPC `-32009 VersionNotSupported` over HTTP 200 — the wire shape preferred by the A2A SDK's `ClientFactory`.

The streaming branch list explicitly carries BOTH the v1 PascalCase names AND the v0.3 slash-aliases so the streaming check fires BEFORE the dispatcher rewrites the alias. This matches what the SDK's `ClientFactory` expects on the wire.

## Streaming Dispatch

Streaming methods return `StreamingResponse(_stream_with_post_hook(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})`.

The pipeline:

1. [`dispatch_a2a_jsonrpc_streaming`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_service.py) is called — note this is **not** awaited at the call site; it returns an async generator directly (Oracle v5 fix). The upstream HTTP/SSE connection is opened lazily on first iteration.
2. The generator parses the upstream SSE framing and yields plain JSON-RPC dicts.
3. `_sse_format` re-wraps each dict as exactly one `data: {json}\n\n` SSE event (D10 + D15: T5 has already stripped the `data:` prefix, so wrapping once here is correct framing, not double-encoding).
4. `_stream_with_post_hook` wraps the generator in `try/finally` so the streaming-dispatch post-hook fires once on stream close — normal completion, client disconnect, or upstream protocol error all produce exactly one post-hook event (Amendment F invariant).

This wrapping pattern matters: the post-hook MUST fire OUTSIDE the yield loop. Firing per chunk would break rate-limiting / audit semantics and overrun the plugin context budget.

## Plugin Hooks

A2A code paths fire six conceptual events via the helpers in [`mcpgateway.services.a2a_hooks`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_hooks.py):

| Helper | Live? | When |
|--------|-------|------|
| `fire_a2a_pre_invoke_hook` / `fire_a2a_post_invoke_hook` | ✅ Live (via cpex `AGENT_PRE_INVOKE` / `AGENT_POST_INVOKE`) | Unary dispatch |
| `fire_a2a_card_pre_hook` / `fire_a2a_card_post_hook` | ⏳ Placeholder | Well-known card route (T11) |
| `fire_a2a_extended_card_pre_hook` / `fire_a2a_extended_card_post_hook` | ⏳ Placeholder | `GetExtendedAgentCard` branch (T12) |
| `fire_a2a_streaming_dispatch_pre_hook` / `fire_a2a_streaming_dispatch_post_hook` | ⏳ Placeholder | Streaming dispatch (T5 + T14) |

The placeholders are intentional no-ops that log at DEBUG so the audit trail still reflects WHERE the firing would happen. Switching them to real firing is the focused commit gated on the cpex hook proposal at [`a2a-cpex-hook-proposal.md`](a2a-cpex-hook-proposal.md). See Plan Amendment F for the deferral note.

### Snapshot dataclass

Plan Amendment G introduced [`A2AAgentSnapshot`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_hooks.py), a frozen projection of a `DbA2AAgent` ORM row used by every downstream consumer (hooks, visibility policy, telemetry):

- Built once per request via `A2AAgentSnapshot.from_orm(agent)` BEFORE `db.commit + db.close` so the snapshot captures real column values, not getattr defaults.
- Lets the DB connection close before any HTTP / RPC latency.
- Pairs with `CallerContext` as the AGENT side of every `(caller, target)` policy input.
- Field set is bounded: identity, visibility / RBAC inputs, plugin-relevant config flags, and the auth-type label. Wire-level secrets (`endpoint_url`, `auth_value`, `auth_query_params`) stay on the ORM row and flow through `prepare_a2a_invocation` separately — those are dispatch concerns, not authorization concerns.

The three centralized policy functions in [`mcpgateway.services.a2a_access_policy`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/services/a2a_access_policy.py) consume snapshots exclusively:

- `can_view_a2a_agent_directly` — single-level direct visibility
- `can_view_a2a_agent_in_server_context` — three-level conjunctive (server + membership + agent) with cheap-first short-circuit
- `can_associate_a2a_agent_with_server` — CRUD authorization (server + agent, NO membership — the call IS what creates the membership)

`_check_agent_access` accepts either an ORM row or a snapshot during the transition (both expose the same `visibility / owner_email / team_id` field names).

## Visibility & Security Invariants

The two-layer model (see [Multitenancy](multitenancy.md) and [Security Features](security-features.md) for the broader context) applies to every A2A path:

- **Layer 1 (token scoping)** controls what the caller can SEE. Token-team interpretation is centralized in `mcpgateway.auth.normalize_token_teams()` (API/legacy tokens) and `resolve_session_teams()` (session tokens). A2A code MUST NOT re-implement team interpretation.
- **Layer 2 (RBAC)** controls what the caller can DO. The dispatch handler evaluates this after body parse so the permission can depend on the JSON-RPC method.

Wire-level rules:

- All visibility denials at the dispatch and well-known card endpoints collapse to **HTTP 404** (D14)
- All RBAC denials at the dispatch endpoint return **HTTP 403**
- Unauthenticated requests are rejected by middleware with **HTTP 401** before they reach the handler — except in operator-explicit anonymous mode, which requires both gateway-wide auth and per-server OAuth to be disabled; see [AGENTS.md](https://github.com/IBM/mcp-context-forge/blob/main/AGENTS.md) for the full configuration matrix
- `GetExtendedAgentCard` is **never forwarded upstream** (D18) — the gateway always synthesizes locally
- The dispatch route deliberately has NO `@require_permission` decorator because permission is method-dependent

Cross-gateway UAID routing (when A2A federation is enabled) requires an explicit domain allowlist (`UAID_ALLOWED_DOMAINS`) and forwards bearer tokens for RBAC enforcement on remote gateways. See the [UAID Cross-Gateway Routing](https://github.com/IBM/mcp-context-forge/blob/main/AGENTS.md#uaid-cross-gateway-security) section for the production checklist.

## Rust Deprecation Cycle

The Rust A2A runtime that existed in earlier waves was deprecated in Wave 6:

- **T25** removed all call sites from the gateway's execution path. The Python dispatcher in `mcpgateway.services.a2a_service` is the only A2A execution path.
- **T26** marked the backing module and config fields as deprecated. The `_rust_a2a_runtime_managed()` helper in [`mcpgateway/version.py`](https://github.com/IBM/mcp-context-forge/blob/main/mcpgateway/version.py) always returns `False` so external `/version` consumers don't break.
- **PATCH `/admin/runtime/a2a`** now returns **HTTP 410 Gone** with a migration message — there is no longer a runtime to switch modes against.
- **Physical removal** is scheduled one release later per the split deprecation cycle (Plan T26).

The Rust MCP runtime (separate from A2A) follows its own deprecation track tracked in [`rust-mcp-runtime.md`](rust-mcp-runtime.md).

## Compliance Harness

[`tests/live_gateway/a2a_compliance/`](https://github.com/IBM/mcp-context-forge/blob/main/tests/live_gateway/a2a_compliance/) is a black-box A2A protocol compliance harness driven by the official `a2a-sdk` client (with raw `httpx` where wire-level precision matters). The same test bodies run across THREE targets in parallel so behavioral drift surfaces as a concrete test failure rather than a manual log diff:

| Target | Description |
|--------|-------------|
| `reference` | Direct to the bundled `a2a_echo_agent` — the protocol baseline |
| `gateway_proxy` | Via ContextForge's per-agent native passthrough |
| `gateway_virtual` | Via ContextForge's v-server-scoped native passthrough |

Run targets:

```bash
make test-protocol-compliance-a2a            # full matrix
make test-protocol-compliance-a2a-v1-0-0     # A2A 1.0.0 only
make test-protocol-compliance-a2a-reference  # reference only (no gateway needed)
```

Gaps are tracked in [`COMPLIANCE_GAPS.md`](https://github.com/IBM/mcp-context-forge/blob/main/tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md) and wired into affected tests via `xfail_on(request, ...)` so pytest reports `XFAIL` rather than `FAIL`. A fix surfaces as `XPASS` and signals the gap is closing on that cell.

Phase 1 covers A2A 1.0.0; the v0.3.0 overlay arrives in Phase 2. Adding a new target is mechanical:

1. Subclass `A2AComplianceTarget` in `targets/<name>.py`. Set `name` and `supported_transports`.
2. Implement `_open_client(transport, **kwargs)` as an `asynccontextmanager` yielding a connected `a2a.client.Client`.
3. Register in `conftest.py`'s `_CASES` list. The parametrize matrix picks it up automatically.

The compliance harness deliberately requires a live gateway — it self-skips when unreachable. See [`tests/live_gateway/README.md`](https://github.com/IBM/mcp-context-forge/blob/main/tests/live_gateway/README.md) for the bring-up flow (`make testing-up`).

## References

- Plan: `.omo/plans/a2a-native-passthrough.md` — wave structure, amendments A-I, decision log
- Plugin hook proposal: [`a2a-cpex-hook-proposal.md`](a2a-cpex-hook-proposal.md) — the deferred Phase C work
- Multi-tenancy two-layer model: [`multitenancy.md`](multitenancy.md)
- Security features (auth, RBAC, headers): [`security-features.md`](security-features.md)
- Rust runtime status: [`rust-mcp-runtime.md`](rust-mcp-runtime.md)
- Top-level repo guide: [`AGENTS.md`](https://github.com/IBM/mcp-context-forge/blob/main/AGENTS.md)
- Compliance harness: [`tests/live_gateway/a2a_compliance/README.md`](https://github.com/IBM/mcp-context-forge/blob/main/tests/live_gateway/a2a_compliance/README.md)
