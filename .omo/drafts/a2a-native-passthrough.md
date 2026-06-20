---
slug: a2a-native-passthrough
status: approved (revised x2)
intent: clear
pending-action: execute .omo/plans/a2a-native-passthrough.md
approach: Native A2A 1.0.0 passthrough as a pure-Python layered architecture. **8 components C1-C8** (revised from 6 after first adversarial review). C1 control-plane API + helpers; C2 per-agent data plane (well-known card + JSON-RPC dispatch + SSE streaming) with method-aware RBAC and manual JSON parsing; C3 virtual-server-scoped data plane with `A2APathRewriteMiddleware`; C4 compliance audit + gap-closure tests written BEFORE implementation (P5); C5 server CRUD service verify + Admin UI server-form A2A selector + formSubmitHandlers.js wiring + card-URL display; C6 Rust A2A runtime DEPRECATION (this release: warning + Cargo default-members exclusion + call-site removal; physical deletion deferred to release N+1); C7 compliance harness completion with real ClientFactory(config=...) `@asynccontextmanager` shape; C8 documentation. AuthN/AuthZ reuse existing `@require_permission` + `get_current_user_with_permissions` modules unchanged; method-aware RBAC inside T12 handler (NOT route decorator) so `GetExtendedAgentCard` can require `a2a.read`. `server_a2a_association` join table already exists; no schema migration. `associated_a2a_agents` already in `ServerCreate`/`ServerUpdate` schemas (F10). Card synthesis is FRESH from `A2AAgent` row, NOT via legacy `get_agent_card()` (D12).
---

## SUPERSESSION NOTICE (revisions 2 and 3)

This draft accumulated content across three planning rounds and TWO adversarial reviews. The most current authoritative sources are:

- **Components, Scope IN/OUT, Decisions, Wave structure, Todos** → `.omo/plans/a2a-native-passthrough.md` (sections labeled "REVISED post-adversarial-review" or "REVISED — third pass")
- **Principles P1-P5, Findings F1-F15, Decisions D1-D19, Open assumptions A1-A13, Open questions Q1-Q13** → authoritative IN THIS DRAFT (sections below are current).
- **Stale in this draft**: the original "Scope IN" / "Scope OUT" enumerations below (written before reviews) — superseded by the plan's "Must have (8 items)" + "Must NOT have (20 items)". If you find a contradiction between this draft's Scope IN/OUT and the plan's, the PLAN wins.

Implementers reading this draft should anchor primarily on the plan; this draft documents the REASONING (why the principles, why the findings) but the executable contract is in the plan.

# Draft: a2a-native-passthrough

## Components (topology ledger — revised post-review)

| id | outcome (one line) | status | evidence path |
|----|--------------------|--------|---------------|
| C1-CP | Control-plane API contract: agent resolution with visibility enforcement (`_check_agent_access`), server membership, **fresh v1 card synthesis from A2AAgent row (NOT via legacy `get_agent_card`)**, `A2A-Version` header handling (method-aware per v4 MEDIUM #9), GetExtendedAgentCard-specific synthesis with concrete `-32007` trigger. All in `mcpgateway/services/a2a_service.py` + `services/server_service.py`. **NOTE (v4 polish)**: earlier draft listed `get_upstream_client_config` here — removed per Momus v4 #3; T4/T5 reuse existing `invoke_agent()` (verified `main.py:5125-5137`) which already handles per-agent upstream config. | active | F1, F5, F6, F9, F12 |
| C2-DP-AGENT | Per-agent data-plane endpoints: `GET /a2a/{agent_name}/.well-known/agent-card.json` (public per D11, calls synthesizer with `token_teams=[]`); `POST /a2a/{agent_name}` (manual JSON parse per D17; A2A 1.0.0 spec-compliant errors including A2A-specific `-32001..-32009`; explicit `GetExtendedAgentCard` branch per D18; HTTP 404 for unknown agent path vs `-32601` for unknown method per D14; separate SSE streaming path per D15; `A2A-Version` validation per D13). | active | F3, F6, F8, F9, F12, F15 |
| C3-DP-VSCOPE | Virtual-server-scoped data plane: `A2APathRewriteMiddleware` matching `/servers/{server_id}/a2a/{agent_name}` AND `/servers/{server_id}/a2a/{agent_name}/.well-known/agent-card.json` (base + suffix forms, Oracle #14 fix). Membership via `server_a2a_association` enforced in handlers (C2 reuses with `server_id` from scope). | active | F1, F2 |
| C4-COMPLIANCE | **NEW per P5.** Compliance coverage audit + gap-closure tests. Audit `tests/live_gateway/a2a_compliance/` against A2A 1.0.0 full method catalog, error codes (incl. `-32001..-32009`), SSE shape, version negotiation, RBAC denial paths, v-server scoping. Write missing compliance tests BEFORE Wave 2/3 implementation lands. A9 (minimal-harness) supersedes itself wherever a real coverage gap exists. | active | P5, F8 spec catalog |
| C5-CRUD-UI | **NEW addressing user question.** Verify `ServerService.create_server` / `update_server` actually populates `server_a2a_association` from `schemas.ServerCreate.associated_a2a_agents` (F10 confirmed schema layer is wired; service layer TBD). Verify admin server-create / server-edit forms use `agents_selector_items.html` to bind A2A agents (F11 says selector template exists; form integration TBD). Add card-endpoint-URL display in agent detail view (ops affordance). | active | F10, F11 |
| C6-MIG-RUST | Rust A2A runtime deprecation per D16: (a) add startup warning when `EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED=true`, (b) remove `crates/a2a_runtime/` from `Cargo.toml` `default-members`, (c) remove call-site branches in `tool_service.py` + `a2a_service.py`, (d) delete `rust_a2a_runtime.py` + config fields + `version.py` reporting + admin router toggle. Staged. | active | F7, F13 |
| C7-HARNESS | Compliance harness completion: wire fixture plumbing (gateway base URL, auth token, agent name, server_id) in `tests/live_gateway/a2a_compliance/conftest.py` (Oracle #11 — NOT just `_open_client`). Update both target classes. Delete GAP-001 xfail hook. Close GAP-001 in `COMPLIANCE_GAPS.md`. | active | C4 must land first |
| C8-DOCS | A2A 1.0.0 wire-conformance + migration documentation at `docs/docs/architecture/a2a-native.md`. | active | C7 must verify wire first |

**Boundary discipline (per P1+P3+P5)**: every component above respects the control/data split:
- C1 is pure control plane (no HTTP handling); functions take explicit `(db, ..., user_email, token_teams)` so visibility derivation is callable, not implicit.
- C2/C3 are pure data plane: route decorators derive `(user_email, token_teams, is_admin) = get_rpc_filter_context(request, user)` then pass into C1. No JWT claim reading inside handler bodies. No `request.state.user` mutation.
- C4 is test-only and runs BEFORE C2/C3 implementation per P5.
- C5 is service-layer verify/patch + UI verify/patch.
- C6 is migration-only.
- C7 is test-wiring only.
- C8 is docs-only.

**No AuthN/AuthZ component**: existing modules satisfy P3 (per F5). C2/C3 use `@require_permission` and `get_current_user_with_permissions` exclusively for auth; no auth logic appears in handler bodies. Visibility (Layer 1) is derived in the route via existing `get_rpc_filter_context` and passed to control plane.

## Open assumptions (announced defaults — revised post-review)

| # | assumption | adopted default | rationale | reversible? |
|---|------------|-----------------|-----------|-------------|
| A1 | Rust deprecation scope | NARROW: `rust_a2a_runtime.py` + remove `crates/a2a_runtime/` from `default-members` (keep in `members` during transition) | F13 corrected the earlier "harmless" claim; broader Rust deprecation (`crates/mcp_runtime`, `plugins_rust/`, `tools_rust/`) needs its own plan | Yes, expandable at gate |
| A2 | Existing `/a2a/{name}/invoke` envelope route | KEEP indefinitely for backward compat; document as "legacy non-A2A-1.0.0" alongside new native route | Production callers exist; no harness covers it so silent removal is risky | Yes, can add deprecation timeline at gate |
| A3 | PR #5313's `/jsonrpc` URL | **REVISED per F14:** build native dispatch from scratch (PR #5313 is NOT in current checkout — `main.py:5237-5454` is Tool APIs, not A2A dispatch). PR #5313 disposition becomes a separate post-landing decision; if/when merged, its `/jsonrpc` URL can be registered as a same-handler alias to the native dispatch route. | Adversarial review #12 + Momus #3 both flagged the missing PR | Yes, can re-evaluate if PR #5313 merges into the branch before execution starts |
| A4 | Card route auth posture | BASIC card UNAUTHENTICATED (per D11: synthesizer called with `token_teams=[]` — public-only visibility); EXTENDED card AUTHENTICATED via the `GetExtendedAgentCard` JSON-RPC method (per D18: explicit method branch requires `a2a.read`) | A2A discovery convention; F9 corrected the visibility model gotcha | Yes, can require auth on basic card at gate |
| A5 | PR #5226 streaming | ORTHOGONAL: this plan implements native A2A 1.0.0 `message/stream` SSE per D15; PR #5226's envelope-`/stream` is separate work | F4-style envelope ≠ A2A 1.0.0 wire; they target different consumers | Yes, can fold #5226 in at gate |
| A6 | Method coverage | PASS-THROUGH all methods upstream supports; **GetExtendedAgentCard is the ONE exception** (D18 — gateway-handled, never forwarded); `tasks/list` is NOT a legacy v0.3 alias and must NOT be mapped (Oracle #22 correction) | Upstream agent's card declares what it supports; spec-aware exceptions only | Yes, can whitelist at gate |
| A7 | Card `url` rewriting source | **REVISED per F15:** use existing `settings.app_domain` (`config.py:1172`) as the primary public-URL source. Add new `settings.a2a_public_base_url` (optional override) for environments where the gateway is proxied at a different external base. NO `PUBLIC_BASE_URL` setting exists. | F15 verified: only `sso_keycloak_public_base_url` (Keycloak-specific) and `app_domain` (generic) exist | Yes, can per-agent at gate |
| A8 | Bearer forwarding to upstream | Use existing per-agent auth config; UAID federation routing happens BEFORE local resolution (Oracle #13 fix — `dispatch_a2a_jsonrpc` checks for UAID and calls `invoke_agent`'s UAID path first, then falls back to local `resolve_agent_for_dispatch`) | F3 + Oracle #13 confirm this is the existing semantic; preserve it | Yes |
| A9 | Test harness scope | **REVISED per P5:** minimal for matrix/fixtures/target-class CONSTRUCTORS unchanged, BUT compliance assertions are EXTENDED wherever C4's audit finds gaps. Net change: more compliance tests than the original "minimal" framing allowed. | P5 supersedes A9 wherever a real coverage gap exists | No, P5 is binding |
| A10 | Phase ordering | **REVISED with C4 inserted and C5 parallelizable:** C1 → C4 (compliance audit + missing tests) → C2 → C3 in parallel with C5 (CRUD-UI verify) → C6 (Rust dep) → C7 (harness completion) → C8 (docs). Rust deprecation (C6) still happens AFTER native Python data plane lands. | Migration safety + P5 (compliance-test-first) | No, this is a hard ordering constraint |
| A11 | **NEW:** Compliance audit scope | Audit covers: A2A 1.0.0 method catalog from F8, JSON-RPC error codes including A2A-specific `-32001..-32009`, SSE shape, `A2A-Version` negotiation, RBAC denial paths, v-server scoping. Does NOT cover non-protocol gateway behavior (rate limiting, observability, federation header conventions). | P5 framing; non-protocol behavior is covered by other test surfaces | Yes, expandable at gate |
| A12 | **NEW:** Server↔A2A binding service-layer wiring | UNVERIFIED at draft time. Assumption: `ServerService.create_server` and `update_server` already populate `server_a2a_association` from `schemas.ServerCreate.associated_a2a_agents`. If verification confirms: C5 collapses to UI work only. If verification disproves: C5 adds a small service-layer fix. | F10 confirmed schema is wired; service layer needs spot-check | Yes — outcome determines plan size |
| A13 | **NEW:** Admin UI server-form A2A selector | UNVERIFIED at draft time. Assumption: existing `agents_selector_items.html` template is referenced from the server-create/edit form. If verification confirms: UI is already done. If verification disproves: small UI patch to add the selector. Either way, a new "card endpoint URL display" affordance is added to agent detail view. | F11 confirmed selector template exists; form integration TBD | Yes |

## Architectural principles (user-locked, do not retrofit)

The user stated three load-bearing principles before exploration returned. These are NOT preferences — they are constraints every downstream decision must respect. Record them here so each fork resolution can be cross-checked against them.

### P1 — Control plane and data plane are separate, with a defined interaction API

- **Control plane** = configuration and state management: A2AAgent CRUD, virtual-server composition (agent-server associations), card synthesis from stored config, auth/authz policy storage.
- **Data plane** = request processing: well-known card serving, JSON-RPC dispatch to upstream agents, response passthrough, streaming.
- **Interaction API**: data plane queries control plane for "which agents belong to this virtual server", "what card should I serve for this agent", "is this principal allowed to invoke this action on this resource". The interface MUST be expressible as function signatures with no implicit shared state. For phase 1 in-process is fine, but the surface must be definable so a later phase could split control plane out without rewriting handlers.

### P2 — Data plane is stateless to the extent the protocol allows

- The protocol REQUIRES the gateway to hold per-task state (echo agent's TaskStore is the existing example). This stays on the upstream — the gateway forwards `GetTask` / `ListTasks` / `CancelTask` to the upstream's store and is itself stateless about that.
- All configuration the data-plane handlers consume comes from the control plane on each request (or via a per-request snapshot the control plane builds). No global mutable maps in the dispatcher; no init-time-frozen caches in the route module.
- Implication: rebuilding the gateway should not change protocol behavior beyond what configuration changes the user made through the control-plane API.

### P3 — AuthN and RBAC/ABAC are independent modules with established APIs

- **AuthN** module — takes an incoming request, returns a `Principal` (or rejects with 401). Responsible for bearer-token validation, JWT parsing, OAuth introspection. Has a single entry function with a clear signature.
- **AuthZ** module — takes `(Principal, Resource, Action)`, returns Allow/Deny (plus possibly a reason). Implements role checks AND attribute checks (ABAC for things like `team_id` matching). Has a single entry function with a clear signature.
- Data-plane handlers MUST NOT inline auth or authz logic. They MUST call these modules via the established API.
- AuthN and AuthZ MUST be replaceable as units. Swapping the JWT validator implementation, or extending the authz policy with new ABAC attributes, MUST NOT require touching A2A route handlers.

### P4 — Pure Python implementation; Rust A2A runtime deprecated by this plan

- The data plane and control plane for native A2A passthrough are implemented in **pure Python**. No new Rust code is introduced.
- `mcpgateway/services/rust_a2a_runtime.py` (and any A2A-specific crates it bridges to under `crates/`) are marked deprecated by this work. The new Python A2A dispatcher replaces them functionally; the Rust runtime is retired on a defined deprecation timeline.
- Existing call sites that route through the Rust runtime MUST be migrated to the Python dispatcher as part of this plan; the deprecated module stays importable for one release with a `DeprecationWarning` (or hard-fails behind a feature flag — to be decided at the gate), then is removed.
- Performance posture: the Python dispatcher MUST be designed with async I/O and connection reuse from the start so the deprecation does not become a perf regression. SDK-native `ClientFactory` + `httpx.AsyncClient` per upstream agent with connection pooling is the baseline. If a benchmark gap emerges later, that becomes a separate, scoped optimization plan — NOT a reason to keep Rust in the data plane.
- **Open scope question for the gate:** does P4 apply ONLY to `rust_a2a_runtime.py` and A2A-related crates (narrow), or to the broader `crates/mcp_runtime` + `plugins_rust/` + `tools_rust/` surfaces (broad)? Default I will assume unless overridden: narrow — this plan deprecates only the A2A Rust runtime; broader Rust deprecation is acknowledged as a future direction but tracked in a separate plan.

### P5 — Compliance test coverage MUST match protocol implementation (compliance-test-first)

- **Definition.** For every protocol behavior the implementation provides, the compliance harness at `tests/live_gateway/a2a_compliance/` MUST contain at least one assertion that exercises it. Where the harness already covers a behavior, that behavior is verified by harness pass. Where it doesn't, **compliance tests are WRITTEN BEFORE the corresponding implementation code lands.**
- **Scope of coverage matching.** Includes (non-exhaustive): card discovery URL + content shape + field names (`protocolBinding`, `protocolVersion` placement); JSON-RPC envelope validation; A2A 1.0.0 method coverage (every method in F8's catalog); spec-compliant error codes including A2A-specific `-32001..-32009`; SSE streaming shape per F8; v0.3 method-alias mapping; `A2A-Version` header validation and outbound forwarding; visibility / RBAC denial paths; virtual-server scoping behavior.
- **Workflow ordering (binding).** Before any todo in Wave 2/3 (data-plane implementation) starts, an explicit compliance-coverage audit todo runs first. The audit:
  1. Enumerates every existing assertion in `tests/live_gateway/a2a_compliance/` and maps it to A2A 1.0.0 protocol requirements.
  2. Identifies gaps (protocol requirements with NO assertion covering them).
  3. Produces a gap closure list: each gap becomes a "write compliance test for X" todo, scheduled BEFORE the implementation todo that will satisfy it.
- **Reconciling with A9 (minimal harness change).** A9 was about the *URL update + xfail removal* being the only harness change. P5 supersedes A9 wherever a coverage gap exists: gap-closure compliance tests are MANDATED, not optional. A9 still binds the parts of the harness that don't relate to coverage gaps (matrix layout, fixture shapes, target-class constructors stay untouched beyond what URL wiring requires).
- **Practical consequence.** The plan structure changes: insert a new Wave 1.5 ("Compliance coverage gap audit + new compliance tests") between Foundation and Per-agent data plane. Implementation todos in Waves 2/3 explicitly cite the compliance test that will verify them once green.
- **Why this matters.** Protocol work has a unique failure mode: implementation that "passes our own tests" but fails real interop because our own tests didn't actually exercise the spec corner the wire requires. The compliance harness is the spec-anchored truth; making it the verification floor for implementation prevents that failure mode by construction.

### Implications for the 12 forks in the user request

- Fork 5 (JSON-RPC dispatch): the new handler delegates to a data-plane dispatcher that reads `(agent_id, server_id_or_null)` configuration via the control-plane API. PR #5313's handler may be reusable as the route layer, but its inline service-call should route through the dispatcher contract.
- Fork 7 (Auth/RBAC posture): the route decorators MUST be thin — they call `authn.identify(request)` and `authz.authorize(principal, resource, action)` and nothing else. No `Depends(...)` that bypasses this contract.
- Fork 2 (Card serving strategy): card synthesis lives in the control plane (sole source of truth for `url` rewriting, etc.). Data plane only RENDERS the pre-built card. Pure passthrough of the upstream card is OUT — it would smuggle the upstream's `url` field into the response without going through control-plane rewriting.
- Fork 8 (Cross-gateway federation/UAID): the federation routing decision is a CONTROL-plane concern (lookup table). The data plane just forwards per the decision.
- Fork 11 (Compliance harness updates): aligned — the harness can only verify a stable wire contract, and the wire contract IS the data-plane / control-plane interaction expressed at HTTP.

These principles narrow several forks to a single answer; the remaining open questions are surfaced at the approval gate.

## Findings (cited - path:lines)

### F1 — Virtual-server ↔ A2A composition already exists in DB

- `server_a2a_association` join table is already defined: `mcpgateway/db.py:2490-2495`. Composite PK on `(server_id, a2a_agent_id)`. **NO `ON DELETE CASCADE`** (earlier claim was wrong — adversarial review #17 corrected this). Migration would be required to add cascade; not in scope for this plan.
- `Server.a2a_agents` relationship exists alongside `Server.tools`, `Server.resources`, `Server.prompts`: `mcpgateway/db.py:4320-4378`.
- `A2AAgent` also carries `tool_id` FK to `tools.id`: `mcpgateway/db.py:4825-4917`. Each A2A agent is dual-registered as a tool, which is how A2A agents already show up under `tools/list` for MCP virtual servers.
- A2AAgent has `team_id`, `owner_email`, `visibility` columns (RBAC/ABAC-ready).

**Implication for topology**: a new "Server↔A2AAgent association" table is NOT in scope. The composition surface is already correct. What's missing is the data-plane mount that exposes the composition over A2A's native wire (currently it's only exposed via the tool-shim in MCP `tools/list`).

### F2 — Existing virtual-server MCP composition uses path rewrite middleware

- `MCPPathRewriteMiddleware` at `mcpgateway/main.py:3000-3041` rewrites `/servers/{id}/mcp` → mounted `/mcp/` while preserving `modified_path` and extracting `server_id` into scope.
- Transport layer reads server context via `streamablehttp_transport._get_request_context_or_default()` at `mcpgateway/transports/streamablehttp_transport.py:1972-2064`.
- Server-scoped tool listing flows: HTTP `/servers/{id}/mcp` → middleware → transport → `@mcp_app.list_tools()` at `streamablehttp_transport.py:2165-2267` → `ToolService.list_server_tools(db, server_id, ...)` at `mcpgateway/services/tool_service.py:2834-2969`.
- Federated tool naming convention: `<gateway-slug>-<tool-name>`, separator from `config.py:2794-2807` (default `-`), strip logic in `tool_service.py:3665-3680`.

**Implication for topology**: a virtual-server-scoped A2A surface should mirror this pattern — `/servers/{server_id}/a2a/{agent_name}*` rewrites to `/a2a/{agent_name}*` with server context attached, then a control-plane membership check on `server_a2a_association` enforces composition.

### F3 — Existing `/a2a/{name}/invoke` is REST-envelope, RBAC-protected, federation-aware

- Route definition: `mcpgateway/main.py:5041-5137`. Decorators: `@a2a_router.post("/{agent_name}/invoke", response_model=Dict[str, Any])`, `@require_permission("a2a.invoke")`, `db: Session = Depends(get_db)`, `user=Depends(get_current_user_with_permissions)`.
- Body shape: `{ "parameters": Dict[str, Any], "interaction_type": "query" }` — this is NOT A2A 1.0.0 wire.
- Bearer token extracted from `request.state.bearer_token` (set by auth middleware) and passed to service for cross-gateway forwarding.
- Cross-gateway federation routing: `mcpgateway/services/a2a_service.py:2613-2618` + `2672-2714`. UAID allowlist validator (fail-closed) at `services/a2a_service.py:106-134, 239-244`. Config in `mcpgateway/config.py:767-801`.

**Implication for topology**: `/invoke` is the legacy envelope, kept for backward compat under P4 narrow-scope assumption. The new native A2A surface lives at a distinct route family.

### F4 — PR #5313's `/a2a/{name}/jsonrpc` dispatch core is reusable; its error model is not

- Route definition: `mcpgateway/main.py:5237-5454` (in PR #5313 branch). Decorators identical to `/invoke`: `@require_permission("a2a.invoke")`, `get_current_user_with_permissions`.
- Body validation: loose — checks `jsonrpc == "2.0"`, non-empty `method`, `params` is dict/null, `id` optional. **Extra fields tolerated**. No Pydantic body model.
- Dispatch path: calls existing `a2a_service.invoke_agent(...)` with `parameters=body, interaction_type="query"`. Response: passes through if `result["jsonrpc"]` present, else wraps in JSON-RPC envelope.
- **Errors are HTTP-centric, not JSON-RPC**: `HTTPException(400)` for invalid envelope, `404` for missing agent, `500` for unexpected — with a JSON-RPC `-32603` blob nested inside `detail`. This is NOT A2A 1.0.0 spec-compliant on the wire.
- No URL rewriting / card-proxy logic added.
- Auth posture: same admin/public-only token-scoping split as `/invoke` at `main.py:5380-5387`. Admin bypass only when `is_admin AND token_teams is None`.

**Implication for plan**: REUSE the dispatch CORE (extract `a2a_service.invoke_agent` call + body parse) into a shared helper that the new native route calls. REPLACE the error layer with a proper JSON-RPC error mapper (codes `-32700/-32600/-32601/-32602/-32603` returned as HTTP 200 with JSON-RPC error body, per A2A 1.0.0 wire). The new native route on the spec-correct URL supersedes `/jsonrpc` as the public-facing dispatch endpoint; whether `/jsonrpc` stays as an internal alias is a fork.

### F5 — AuthN and AuthZ surfaces already exist as discrete modules (P3-compatible)

- **AuthN entry**: `request.state.user` is populated EARLY by `mcpgateway/middleware/auth_middleware.py:118-190` (extracts JWT/cookie). Route-level dependency `get_current_user_with_permissions` (from `mcpgateway/middleware/rbac.py`) also injects user/state via `mcpgateway/auth.py:1524-1525, 1632-1644, 1790-1797, 2048-2105`. **There is a clear AuthN entry contract** (request → Principal stored on `request.state.user`).
- **AuthZ entry**: `@require_permission("...")` decorator + permission resolution against `Permissions` constants in `mcpgateway/db.py:1356-1361` (`A2A_CREATE/READ/UPDATE/DELETE/INVOKE`). Visibility/ABAC filter in `mcpgateway/services/a2a_service.py:483-545` (team match against `token_teams`). **There is a clear AuthZ entry contract** (Principal × Resource × Action → Allow/Deny + visibility filter).
- Middleware order: `mcpgateway/main.py:3197-3220`. `PasswordChangeEnforcement` only intercepts `/admin/*` (`mcpgateway/middleware/password_change_enforcement.py:88-90`); `/a2a/*` is unaffected.

**Implication for P3**: the principle is ALREADY satisfied by the existing scaffolding. The new A2A native routes MUST use `@require_permission(...)` + `get_current_user_with_permissions` exclusively for authn/authz, with NO inline auth logic. The data-plane dispatcher receives Principal and team-scoped visibility from these modules; it does not re-derive them.

### F6 — No public unauthenticated A2A card route exists today

- Current card endpoint is internal-only: `mcpgateway/main.py:9372-9405`. Gated by `_is_trusted_internal_mcp_runtime_request(request)`, then calls `get_agent_card(..., user_email=..., token_teams=...)`.
- Card helper is visibility-aware and returns `supportsAuthenticatedExtendedCard: True`: `mcpgateway/services/a2a_service.py:1332-1395`.
- For contrast, MCP well-known discovery endpoints are intentionally PUBLIC/unauthenticated: `mcpgateway/routers/well_known.py:118-133, 308-336`.

**Implication for plan**: a new public card route is required. The auth posture for it is a fork (basic card public per A2A convention? or authn-required matching the gateway's own RBAC?). The synthesizer (`get_agent_card`) is reusable; the route only needs to (a) authenticate per the posture decision and (b) ensure the `url` field is rewritten to the gateway's public URL for that agent (not the upstream's URL). URL rewriting is currently NOT done — this is a gap to close.

### F7 — Rust A2A runtime is already in deprecation phase; finishing it is a closed-scope migration

- The Rust A2A runtime is **already an experimental, deprecation-warned sidecar**. `RUST_A2A_RUNTIME_DEPRECATION_MESSAGE` is logged on first use: `mcpgateway/services/rust_a2a_runtime.py:24, 62-65`.
- Public surface of the Python client (the only thing callers touch): `RustA2ARuntimeClient.invoke(prepared, timeout_seconds=...)` returning `Dict[str, Any]` (`rust_a2a_runtime.py:41-142`), `get_rust_a2a_runtime_client()` singleton (`168-180`), `RustA2ARuntimeError` exception (`32-38`). One method, one error class, one singleton — small migration surface.
- All call sites are gated behind `settings.experimental_rust_a2a_runtime_enabled` (and a second `delegate_enabled` flag). Default is disabled.
- **Caller inventory** (all call sites — three total, narrow scope):
  - `mcpgateway/services/tool_service.py:89` (import), `:5873` (call inside tool execution), `:5910` (`RustA2ARuntimeError` handler), `:7130` (second call site).
  - `mcpgateway/services/a2a_service.py:45` (import), `:2306` (call), `:2395-2436` (delegate-mode branch + error handler).
  - `mcpgateway/version.py:140-567` (status reporting in `/version`).
  - `mcpgateway/routers/runtime_admin_router.py:92` (admin runtime toggle).
- Config knobs to remove: `experimental_rust_a2a_runtime_enabled`, `experimental_rust_a2a_runtime_delegate_enabled`, `experimental_rust_a2a_runtime_managed`, `experimental_rust_a2a_runtime_url`, `experimental_rust_a2a_runtime_uds`, `experimental_rust_a2a_runtime_timeout_seconds` (`mcpgateway/config.py:331-351, 2883`).
- Rust source crate: `crates/a2a_runtime/`. Marked for retirement after the Python data plane absorbs its responsibilities. The retirement is sequenced AFTER the new Python data plane lands so callers have a target to migrate to.

**Implication for P4**: the deprecation is already underway and the user is asking us to FINISH IT. The plan's Rust-deprecation component is therefore three concrete edits:
1. Remove `experimental_rust_a2a_runtime_*` branches from `tool_service.py` (2 call sites) and `a2a_service.py` (1 call site + delegate-mode branch) — the Python dispatcher becomes the only path.
2. Delete `mcpgateway/services/rust_a2a_runtime.py`, the `experimental_rust_a2a_runtime_*` config fields, the `version.py` reporting, and the `runtime_admin_router.py` toggle line. Update tests that assert the toggle exists.
3. Mark `crates/a2a_runtime/` for removal in a follow-up release (out of scope for this plan to remove the crate code itself — but the workspace `Cargo.toml` entry stays harmless once nothing in Python imports it).

This is a **closed-scope, finite migration**, not an open-ended refactor.

### F8 — A2A 1.0.0 wire contract (spec-anchored details for C2 and C3)

All citations are to commit `69dd57cb7ec8f83b7d93855d166869a72f01a1eb` of `a2aproject/A2A` (the librarian's authoritative reference).

**Card endpoint (resolves Q8)**:
- Canonical well-known path is `/.well-known/agent-card.json` ([spec L1974-L1980](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L1974-L1980)). `agent-card.json` is registered in the IANA well-known URI registry ([spec L3326-L3345](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L3326-L3345)).
- Basic public card NOT inherently required to be authenticated; sensitive cards SHOULD be protected ([discovery guide L21-L39, L82-L92](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/topics/agent-discovery.md#L21-L39)).
- For a multi-agent gateway, the spec is non-prescriptive on per-agent paths. The natural extension is `/a2a/{agent_name}/.well-known/agent-card.json` per agent, and `/servers/{server_id}/a2a/{agent_name}/.well-known/agent-card.json` per virtual-server-scoped agent. This preserves the `agent-card.json` suffix convention.
- `GetExtendedAgentCard` (RPC method, see method catalog below) MUST authenticate; the extended card is a separate authenticated surface, not the public well-known.

**AgentCard required fields** ([proto L361-L398](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/specification/a2a.proto#L361-L398)):
`name`, `description`, `supportedInterfaces`, `version`, `capabilities`, `defaultInputModes`, `defaultOutputModes`, `skills`.
**Optional**: `provider`, `documentationUrl`, `securitySchemes`, `securityRequirements` (proto: `security_requirements`), `signatures`, `iconUrl`.

**Migration gotcha**: `protocolVersion` is NOT top-level in v1.0.0 — it moved INTO each `supportedInterfaces[]` entry ([what's new L123-L130](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/whats-new-v1.md#L123-L130)). This matches the wire-detail finding from earlier session work.

**Each `supportedInterfaces[]` entry required fields**: `url`, `protocolBinding`, `protocolVersion` ([proto L334-L355](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/specification/a2a.proto#L334-L355)).
**Optional**: `tenant` (opaque routing metadata).
**JSON field name is `protocolBinding`** (proto `protocol_binding`). NOT `transportProtocol` — that is wrong. Confirms the earlier wire-detail learning.

**Defined `protocolBinding` core values**: `JSONRPC`, `GRPC`, `HTTP+JSON` ([proto L340-L343](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/specification/a2a.proto#L340-L343)). Custom binding identifiers allowed as open-form strings.

**Dispatch URL (resolves Q9)**:
- Spec does NOT mandate a path suffix like `/rpc` or `/jsonrpc` for JSON-RPC dispatch ([JSON-RPC example L2249-L2266](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L2249-L2266); [SDK tutorial L27-L31](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/tutorials/python/5-start-server.md#L27-L31)).
- The dispatch endpoint is whatever `supportedInterfaces[].url` advertises. The card IS the contract.
- Natural choice for ContextForge: bare `POST /a2a/{agent_name}` (and `POST /servers/{server_id}/a2a/{agent_name}` for v-server scope). This is the URL the card's `url` field advertises. The existing legacy `/a2a/{name}/invoke` is a sibling, not a conflict (FastAPI matches the explicit `/invoke` suffix).
- PR #5313's `/a2a/{name}/jsonrpc` is NOT spec-mandated. Disposition options live in Q3.

**Method catalog** ([service + messages L19-L140](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/specification/a2a.proto#L19-L140), [request/response defs L650-L811](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/specification/a2a.proto#L650-L811)):
- `SendMessage` / `SendStreamingMessage` / `GetTask` / `ListTasks` / `CancelTask` / `SubscribeToTask`
- Push: `CreateTaskPushNotificationConfig` / `GetTaskPushNotificationConfig` / `ListTaskPushNotificationConfigs` / `DeleteTaskPushNotificationConfig`
- Card: `GetExtendedAgentCard`

**Response envelopes** ([proto L778-L802](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/specification/a2a.proto#L778-L802)):
- `SendMessageResponse.oneof payload`: `task | message`
- `StreamResponse.oneof payload`: `task | message | status_update | artifact_update`

**Legacy v0.3.0 method aliases** ([whats-new L115-L130, L884-L915](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/whats-new-v1.md#L115-L130)):
- `message/send` → `SendMessage`, `message/stream` → `SendStreamingMessage`
- `tasks/get` → `GetTask`, `tasks/cancel` → `CancelTask`, `tasks/resubscribe` → `SubscribeToTask`
- `tasks/pushNotificationConfig/{set,get,list,delete}` → `*TaskPushNotificationConfig`
- `agent/getAuthenticatedExtendedCard` → `GetExtendedAgentCard`
- **NOT a legacy alias**: `tasks/list` — this is NEW in v1.0.0 (no v0.3 equivalent).
- Back-compat posture per spec: servers MAY accept both legacy and current forms during transition; not mandated.

**Streaming semantics** ([JSON-RPC streaming L2316-L2330](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L2316-L2330)):
- JSON-RPC streaming = SSE (`text/event-stream`).
- Each SSE `data:` chunk = a complete JSON-RPC response object.
- Stream order: initial `Task` or `Message`, then zero-or-more status/artifact updates, then close on terminal/interrupted state.

**Push notifications** ([methods L2410-L2418](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L2410-L2418), [capability gating L569-L576](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L569-L576)):
- Optional, capability-gated via `AgentCard.capabilities.pushNotifications`.
- If absent/false, server MUST return `PushNotificationNotSupportedError`. Gateway pass-through respects this (the upstream returns the error; gateway forwards).

**Versioning** ([versioning L706-L724](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L706-L724)):
- Major.Minor protocol versions; patch versions don't affect compatibility.
- Clients MUST send `A2A-Version` header.
- A card can expose multiple `supportedInterfaces[]` entries with different `protocolVersion` values for mixed fleets.
- No transparent v1 ↔ v0.3 downgrade; interop only works if server/client intentionally support legacy surface.

**Federation patterns** ([multi-tenancy L1-L23, L58-L115](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/topics/multi-tenancy.md#L1-L23)):
- Spec is gateway-friendly and explicitly non-prescriptive.
- Allows multiple agents behind one endpoint; routing implementation is operator-defined.
- Supported patterns: URL-based routing (our primary), auth-header-based routing, `tenant`-field routing.
- No cross-gateway rewrite protocol — gateway just advertises correct per-interface URL/tenant.

**Implication for C1/C2/C3**: every wire detail above is now decided. C2 serves `/a2a/{agent_name}/.well-known/agent-card.json`. C3 serves `POST /a2a/{agent_name}` (bare). The card synthesizer in C1 emits `protocolBinding` (camelCase) not `transportProtocol`. JSON-RPC error envelopes use HTTP 200 + JSON-RPC error body per D6 (refined by D14 — see below). Streaming is SSE per A2A spec — C3's `SendStreamingMessage` and `SubscribeToTask` return `text/event-stream` with complete JSON-RPC responses per chunk.

### F9 — Visibility model: `token_teams=None` is admin bypass, not anonymous public-only

- `_check_agent_access()` at `mcpgateway/services/a2a_service.py:483-545` treats `token_teams is None AND user_email is None` as an admin-ish bypass — it shows public AND team-scoped agents (only private/owner-scoped are denied).
- **Anonymous public-only** must explicitly pass `token_teams=[]` (empty list, not None) to force public-only visibility. This is the canonical `normalize_token_teams()` behavior documented in AGENTS.md (PUBLIC-ONLY column).
- **Implication for C2 basic-card route**: T6 / synthesize must call `_check_agent_access(..., user_email=None, token_teams=[])` for the unauthenticated card path, NOT `principal=None`. Original plan's `synthesize_agent_card(..., principal=None)` would have leaked team-visible cards to anonymous callers. **Adversarial review #2 — verified, blocking.**

### F10 — Server CRUD schemas ALREADY accept `associated_a2a_agents` end-to-end

- `schemas.py:4261-4264` (ServerCreate), `:4429-4432` (ServerUpdate), `:4531-4535` (ServerRead) all declare `associated_a2a_agents: Optional[List[str]]`.
- Validator at `:4338` and `:4497` normalizes input across `associated_tools`, `associated_resources`, `associated_prompts`, `associated_a2a_agents` consistently.
- ServerRead has reflection at `:4592-4599` that extracts `.id` from passed model instances.
- **Implication**: API surface for "configure A2A upstreams and bundle into virtual servers" is ALREADY DELIVERED at the schema layer. The plan does NOT need new CRUD APIs. What it DOES need is verification that `ServerService.create_server` / `update_server` actually wires this through to populate `server_a2a_association`. If wired: zero new API code. If not wired: small service-layer fix.

### F11 — Admin UI has A2A templates; server-form integration TBD

- `mcpgateway/templates/` contains: `agents_partial.html`, `agents_selector_items.html`, `a2a_agent_plugin_bindings_partial.html`, `admin.html`.
- The presence of `agents_selector_items.html` suggests the UI already has a selector for A2A agents (analogous to tools/resources/prompts selectors).
- **Unverified**: whether the server-create / server-edit form actually USES `agents_selector_items.html` to bind A2A agents at server creation time.
- **Implication**: UI scope is "verify and patch", not "build from scratch". Likely 1-2 todos: confirm selector wires into server form, add A2A-card-URL display in agent detail view (new ops affordance).

### F12 — Existing `get_agent_card()` emits v0.3-shape; v1 card must be rebuilt fresh

- `mcpgateway/services/a2a_service.py:1379-1394` emits: top-level `url`, top-level `protocolVersion`, `supportsAuthenticatedExtendedCard`, NO `supportedInterfaces[]`. This is v0.3 (or pre-v1) wire shape.
- Strict v1 Pydantic model with `extra="forbid"` will REJECT this dict if passed through unchanged.
- **Implication**: T2 must NOT call `get_agent_card()` and feed its output into the v1 model. T2 builds the v1 `AgentCard` DTO directly from the `A2AAgent` row. The legacy `get_agent_card()` stays in place to serve the existing internal trusted-MCP-runtime endpoint (`main.py:9372-9405`) which is on its own deprecation path. **Adversarial review #16 — verified, blocking.**

### F13 — `crates/a2a_runtime/` is in workspace `members` AND `default-members`

- `Cargo.toml` (repo root) lines 4-15: `members = ["crates/*", ...]`, `default-members = ["crates/*", ...]`. So `crates/a2a_runtime/` participates in default `cargo build` / `cargo test` / `cargo check`.
- The earlier draft claimed the crate could be "left harmless". That is wrong. Leaving it in default-members keeps it in CI, keeps its dependencies pinned, and keeps it as maintained surface.
- **Implication for C5**: deprecation must either (a) remove `crates/a2a_runtime/` from `default-members` (still keep in `members` for opt-in), or (b) remove it from `members` entirely. Option (a) is the safer single-PR shape. **Adversarial review #18 — verified.**

### F14 — PR #5313 is NOT in the current checkout

- `mcpgateway/main.py:5237-5454` was cited as PR #5313's dispatch handler. In the current branch (`jps/compliance-tests`), that range is Tool API code, not A2A JSON-RPC dispatch.
- PR #5313 is open against `main` but has not been merged or rebased into this branch.
- **Implication**: every plan reference to "reuse PR #5313 dispatch core" is unverifiable until/unless that PR is merged. The plan must either (a) gate Wave 2 on merging PR #5313 first, or (b) build native dispatch from scratch and treat PR #5313 disposition as a separate post-landing question. **(b)** is the safer choice — adversarial review #12 endorses it.

### F15 — `PUBLIC_BASE_URL` does not exist as a generic setting; `app_domain` does

- `mcpgateway/config.py` grep for `public_base_url` returns only `sso_keycloak_public_base_url` (line 500) — Keycloak-specific, not the gateway's public URL.
- The actual gateway public-URL setting is `app_domain: HttpUrl = Field(default=HttpUrl("http://localhost:4444"))` at `config.py:1172`. Used at line 3502-3504 for allowed_origins construction.
- **Implication for D7 + A7**: card-URL rewriting must derive from `settings.app_domain` (with optional new `settings.a2a_public_base_url` override if the gateway is reverse-proxied at a different external base). Plan's earlier "PUBLIC_BASE_URL" reference is wrong. **Adversarial review #8 — verified.**

## Decisions (with rationale)

These follow from the architectural principles + findings; they are not contentious and the user will see them at the gate but they do not require approval forks.

- **D1 — Control-plane API is a Python module-level interface for phase 1.** Functions on `mcpgateway/services/a2a_service.py` (extended) with explicit signatures. NOT gRPC / NOT HTTP / NOT a separate process. P1 says "in-process is fine, but the surface must be definable so a later phase could split control plane out without rewriting handlers." Concretely: every function the data plane (C2/C3/C4) calls into the control plane (C1) MUST take only `(db: Session, ...explicit-params...)` and return plain dicts or DTOs — no shared global state, no FastAPI `Request` smuggling, no module-level caches keyed off live state. This makes a future RPC split mechanical.
- **D2 — AuthN/AuthZ use existing modules; zero new auth code in C2/C3/C4.** Routes use `Depends(get_current_user_with_permissions)` (AuthN entry, F5) and `@require_permission("a2a.invoke" or "a2a.read")` (AuthZ entry, F5). Visibility/ABAC filtering against `token_teams` is delegated to `a2a_service`'s existing helpers. Handler bodies never read JWT claims directly, never compare `token_teams` themselves, never set `request.state.user`. This is what P3 mandates.
- **D3 — Card synthesis is control-plane-owned; data plane renders only.** C2's handler calls a C1 function `synthesize_agent_card(db, agent_name, public_base_url, principal)` and returns the result verbatim. C2 does NOT decide what goes in the card. C2 does NOT decide whether to rewrite the `url` field. C1 does all of that.
- **D4 — Rust deprecation (C5) is sequenced strictly AFTER the Python data plane (C2/C3) lands.** A10 + safety. Callers in `tool_service.py` and `a2a_service.py` MUST have a working Python dispatcher to point at before their Rust branches are removed. No flag-day cutover; the `experimental_rust_a2a_runtime_enabled` flag stays settable through the transition, with the Python dispatcher as the unconditional default and the Rust branch retired in a single subsequent commit once the Python path has soak time.
- **D5 — Per-agent upstream auth is preserved unchanged from `/invoke`.** A8 + F3. `A2AAgent.auth_type/auth_value/oauth_config/passthrough_headers` continue to drive how the gateway authenticates to the upstream. The incoming caller's bearer token is only forwarded to the upstream when the UAID federation path is hit (existing semantic at `services/a2a_service.py:2672-2714`). The native dispatcher (C3) does not introduce a new "always-forward" mode.
- **D6 — Spec-compliant JSON-RPC error envelopes are mandatory in C3 for envelope/method/params errors.** A2A 1.0.0 dispatch errors for protocol-level concerns are JSON-RPC error responses (HTTP 200, body `{"jsonrpc":"2.0","error":{"code":-32xxx,"message":"...","data":...},"id":...}`). The set of JSON-RPC errors includes standard `-32700/-32600/-32601/-32602/-32603` AND A2A-specific `-32001..-32009` (per F8 spec section 5.4 — see D14 below for the disambiguation rule that resolves the original D6/T7 contradiction). HTTP error codes are reserved for transport-level failures only: 401 (no AuthN), 403 (no AuthZ), 404 (route does not exist OR agent unknown at this path BEFORE body parsing), 405 (wrong method), 5xx (gateway crash). **D14 below makes the agent-unknown vs method-unknown rule explicit.**
- **D7 — URL field on every served card is rewritten to gateway-public coordinates.** P1 + F6. The synthesizer (C1) NEVER passes through the upstream agent's `url` field. The rewritten URL points at the gateway's public dispatch endpoint for that agent (or for the agent within a virtual server, per A7).
- **D8 — Card JSON wire field is `protocolBinding`, not `transportProtocol`.** F8 + earlier session learning. The proto field is `protocol_binding` (snake_case); the JSON serialization is `protocolBinding` (camelCase). The SDK's `ClientFactory.create_from_url(...)` silently drops misnamed fields and raises `"no compatible transports found"` — this exact failure already cost time once in this branch. The synthesizer MUST emit `protocolBinding`. Encoded into a Pydantic model on the synthesizer side so the field name is structurally enforced, not just code-review-enforced.
- **D9 — `protocolVersion` is per-interface, NEVER top-level on the card.** F8 migration gotcha. The card synthesizer MUST place `protocolVersion` inside each `supportedInterfaces[]` entry. The v1.0.0 spec moved this field out of the card root. Same structural enforcement via Pydantic.
- **D10 — Streaming methods (`SendStreamingMessage`, `SubscribeToTask`) return SSE.** F8 streaming semantics. C3 returns `text/event-stream` for these two methods, with one complete JSON-RPC response per `data:` chunk. Non-streaming methods return a single JSON object. Dispatcher MUST inspect the method name (or the upstream response's `Content-Type`) to choose the response shape — it does NOT wrap streaming results in a single JSON envelope. **Refined by D15 below: streaming uses a SEPARATE dispatch path, not a flag on the unary `invoke_agent` codepath.**
- **D11 — Anonymous public card access uses `token_teams=[]`, NOT `token_teams=None`.** Derives from F9. `_check_agent_access(..., user_email=None, token_teams=None)` is an admin-ish bypass that leaks team-scoped agents to anonymous callers. For the unauthenticated basic-card route (T6), the synthesizer is called with `token_teams=[]` (empty list, the canonical public-only signal per `normalize_token_teams()`), which restricts visibility to `visibility == "public"` agents only. Authenticated extended-card paths derive `(user_email, token_teams, is_admin)` from `get_rpc_filter_context(request, user)` exactly as `/invoke` does today.
- **D12 — Native v1 card is built fresh from the `A2AAgent` DB row; do NOT feed `get_agent_card()` into the v1 model.** Derives from F12. The existing `get_agent_card()` at `a2a_service.py:1379-1395` emits v0.3/pre-v1 shape (top-level `url`, top-level `protocolVersion`, `supportsAuthenticatedExtendedCard`). With `extra="forbid"` on the v1 model, that dict would be REJECTED. The synthesizer (T2) reads the agent row directly and constructs a v1 `AgentCard` with one `SupportedInterface` entry. `get_agent_card()` stays unchanged for the existing internal-trusted endpoint at `main.py:9372-9405` until its own deprecation lands.
- **D13 — `A2A-Version` header validated inbound, set outbound based on the per-interface protocol version.** Spec F8 (versioning L706-L724). Inbound: C3 reads `A2A-Version` header on dispatch. Accepts `1.0` and `1.0.0` (Major.Minor compatibility per spec). Rejects unsupported with A2A-specific JSON-RPC `-32009 VersionNotSupportedError` (HTTP 200 + JSON-RPC error body per D6). Outbound: when forwarding to upstream, set `A2A-Version` to the value declared in the agent's registered `supportedInterfaces[].protocolVersion` (which the gateway emits in the card based on the `A2AAgent.protocol_version` column).
- **D14 — Agent-unknown vs method-unknown disambiguation rule** (resolves the D6/T7 contradiction Oracle #7 flagged). HTTP 404 is returned when the path resource doesn't exist — that is, when `resolve_agent_for_dispatch(db, agent_name, server_id=...)` raises `A2AAgentNotFoundError` (or its v-server cousin) BEFORE the request body is parsed. JSON-RPC `-32601 MethodNotFound` is returned (HTTP 200) ONLY when the agent exists and is visible AND the method name in the parsed body is not recognized by the upstream. The two errors mean different things to a JSON-RPC client and must be reported as different transport outcomes.
- **D15 — Streaming dispatch uses a SEPARATE `async with client.stream()` path; the existing buffered `invoke_agent()` codepath cannot be reused for streaming.** Derives from Oracle #10. The existing `_invoke_remote_agent` does `client.post(...)` then `.json()` / `.text` — buffers the entire response. SSE pass-through CANNOT be built on top of that. C3's dispatcher detects streaming methods (`SendStreamingMessage`, `SubscribeToTask`) BEFORE calling any helper, and routes through a dedicated streaming function that yields per upstream chunk. Cancellation: when the FastAPI response generator is GC'd or the client disconnects, the `async with client.stream(...)` context exits and the upstream connection is closed.
- **D16 — Rust deprecation requires workspace exclusion + one-release startup warning.** Derives from F13 + Oracle #18-19. Wave 4 work: (a) emit a startup warning when `EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED=true` is set BEFORE removing the flag (one-release deprecation gate); (b) remove `crates/a2a_runtime/` from `Cargo.toml`'s `default-members` so it stops shipping in default builds (keep in `members` for opt-in build during the transition); (c) only then delete the Python `rust_a2a_runtime.py` and config fields. This staged approach gives production users with the flag enabled time to migrate.
- **D17 — JSON-RPC body parsed manually in dispatch handler; NO FastAPI `Body(...)` dependency.** Derives from Oracle #5. FastAPI's `body: Dict[str, Any] = Body(...)` rejects malformed JSON with HTTP 422 BEFORE the handler runs, making JSON-RPC `-32700 ParseError` unreachable. The dispatch handler reads `raw = await request.body()`, attempts `json.loads(raw)`, catches `JSONDecodeError` → emits HTTP 200 + JSON-RPC `-32700` envelope. Only after successful parse does envelope-shape validation (D6) run.
- **D18 — `GetExtendedAgentCard` is an explicit method-branch in C3's dispatcher.** Derives from Oracle #4. The dispatcher inspects the parsed method name BEFORE forwarding. When method == `GetExtendedAgentCard` (or its legacy v0.3 alias `agent/getAuthenticatedExtendedCard`), the dispatcher: (a) requires `a2a.read` permission (not `a2a.invoke`); (b) calls the control-plane synthesizer (T2) with the authenticated principal's `(user_email, token_teams)` for full extended-card content; (c) NEVER forwards this method to the upstream. All other methods go through the standard pass-through dispatch (which still requires `a2a.invoke`).
- **D19 — Compliance coverage audit precedes implementation; gap-closure tests land BEFORE the code they verify.** P5 derivation. A new Wave 1.5 component performs an audit of `tests/live_gateway/a2a_compliance/` against A2A 1.0.0 protocol requirements (full method catalog, error codes including A2A-specific `-32001..-32009`, SSE shape, version negotiation, RBAC denial paths, v-server scoping). Gaps become compliance-test todos scheduled BEFORE the implementation todos that satisfy them. Implementation todos in Waves 2/3 explicitly cite the compliance assertion that verifies them.

## Scope IN

The plan delivers, end-to-end, with verification:

1. **C1 — Control-plane API extensions.** New/extended functions on `mcpgateway/services/a2a_service.py` and `services/server_service.py` for: (a) resolve agent by name within optional server context with visibility enforcement, (b) synthesize spec-compliant A2A 1.0.0 card with rewritten `url` + v-server membership check, (c) check server-membership via `server_a2a_association`, (d) validate inbound `A2A-Version` (method-aware) + set outbound header. All functions Python-callable, no HTTP. **NOTE (v4 polish)**: earlier draft included `(d) get upstream client config` here — removed per Momus v4 #3; existing `invoke_agent()` at `main.py:5125-5137` already handles upstream config so a dedicated helper is unnecessary.
2. **C2 — Native A2A card route(s).** Public endpoint(s) per A2A 1.0.0 (URL pending librarian, Q8). Basic card unauthenticated by default (A4); extended card behind `Depends(get_current_user_with_permissions)`. Calls C1 for content. URL field rewritten per D7.
3. **C3 — Native A2A JSON-RPC dispatch endpoint.** Single route accepting A2A 1.0.0 JSON-RPC method calls (URL pending librarian, Q9). Method pass-through (A6). Spec-compliant error envelopes per D6. SSE response shape for `message/stream` per A2A 1.0.0. Reuses PR #5313's dispatch core via an extracted helper.
4. **C4 — Virtual-server-scoped surface.** `/servers/{server_id}/a2a/{agent_name}*` path rewrite middleware + membership check via `server_a2a_association`. Mirrors `MCPPathRewriteMiddleware` (F2).
5. **C5 — Finish Rust A2A runtime deprecation.** Three concrete edits per F7. Python dispatcher becomes the only path. Config flags + sidecar reporting removed.
6. **C6 — Compliance harness completion.** URL update in `tests/live_gateway/a2a_compliance/targets/gateway_proxy.py` and `gateway_virtual.py`. Delete the GAP-001 xfail hook in `tests/live_gateway/a2a_compliance/conftest.py`. Update `tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md` (close GAP-001).
7. **Documentation**: A2A 1.0.0 wire-conformance note in `docs/docs/architecture/` (or equivalent) covering the new routes, virtual-server scoping, and migration from `/invoke`.

Each component is independently verifiable:
- C1 by unit tests calling its functions directly.
- C2/C3 by the compliance harness (which exists and currently x-fails on GAP-001).
- C4 by an integration test composing two agents into a virtual server and dispatching via both `/a2a/{name}` and `/servers/{id}/a2a/{name}`.
- C5 by `rg "rust_a2a_runtime"` returning zero matches in production code paths after the migration.
- C6 by the harness suite running clean (no GAP-001 xfails left).

## Scope OUT (Must NOT have)

- **Broader Rust deprecation beyond A2A runtime.** `crates/mcp_runtime/`, `plugins_rust/`, `tools_rust/` stay untouched (A1 default; user can expand at gate).
- **Refactoring existing `/a2a/{name}/invoke` to respect the new control-plane API.** Legacy envelope stays exactly as-is (A2). Future work, separate plan.
- **PR #5226 envelope-streaming integration into the native dispatcher.** Orthogonal (A5). Native `message/stream` is delivered by C3 per spec.
- **New AuthN mechanism.** No new JWT scheme, no new OAuth handler, no new session model. Existing modules are sufficient (F5).
- **New permission strings.** `a2a.invoke` and `a2a.read` (existing, F5) cover dispatch and card-read respectively.
- **Per-agent override of public base URL.** Single `PUBLIC_BASE_URL` setting (A7) — per-agent URL is over-engineering for phase 1.
- **Harness assertion extensions.** Test changes minimal per user explicit constraint (A9).
- **New schema / migration to `A2AAgent` or `Server` models.** Composition surface already exists (F1).
- **Method whitelist on dispatch.** Pass-through (A6); upstream is the truth source for capability advertisement.
- **Synchronous-mode fallback in C3.** Python dispatcher is async/`httpx`-based by default; no sync codepath.

## Open questions (surfaced at the approval gate)

Categorized by who owns the decision. Defaults are the values the plan adopts if the user does not override.

### Questions requiring user decision (real architectural forks)

- **Q1 — Rust deprecation scope.** Default per A1: NARROW (`rust_a2a_runtime.py` + `crates/a2a_runtime/` only). Alternatives: (a) BROAD — include `crates/mcp_runtime`, `plugins_rust/`, `tools_rust/` in this plan; (b) STRICT-A2A — include only `rust_a2a_runtime.py`, leave the crate to a follow-up. Why it matters: broad scope doubles or triples the plan size.
- **Q2 — Legacy `/a2a/{name}/invoke` deprecation timeline.** Default per A2: keep indefinitely with a "legacy envelope" doc note. Alternatives: (a) deprecate with 2-release removal timeline; (b) remove in this release. Why it matters: production callers may exist outside the project.
- **Q3 — PR #5313 disposition.** Default per A3: SUPERSEDE — extract dispatch core into a shared helper used by the new spec-correct route. Keep `/jsonrpc` as an internal alias if useful, but its error layer is replaced. Alternatives: (a) REUSE — accept PR #5313 as-is and add a separate spec-correct route alongside (two error models in the codebase); (b) REJECT — close PR #5313 and build native dispatch from scratch in C3. Why it matters: contributor relationship + code duplication.
- **Q4 — Card route auth posture.** Default per A4: BASIC card UNAUTHENTICATED at the well-known location, EXTENDED card AUTHENTICATED behind `a2a.read`. Alternatives: (a) ALL-AUTH — require AuthN on every card endpoint; (b) ALL-PUBLIC — basic and extended both unauthenticated. Why it matters: discoverability vs information disclosure trade-off.
- **Q5 — PR #5226 streaming disposition.** Default per A5: ORTHOGONAL — accept PR #5226 separately; native `message/stream` is delivered by C3 per A2A 1.0.0 spec; the two SSE surfaces co-exist (one envelope-shaped, one native). Alternatives: (a) INTEGRATE — fold PR #5226's SSE work into C3 with refactor; (b) REJECT — close PR #5226 in favor of C3 only. Why it matters: contributor relationship + how many SSE shapes the gateway exposes.
- **Q6 — Principles scope.** Raised in conversation. Default I am adopting: NARROW — P1/P2/P3 bind only the new A2A passthrough work; existing `/invoke` handler stays as-is. Alternative: BROAD — refactor `/invoke` (and PR #5226's `/stream`) to route through the same control-plane interface and AuthN/AuthZ modules. Why it matters: doubles plan scope.

### Questions resolved by F8 (A2A 1.0.0 spec)

- **Q8 — Native card URL location.** **RESOLVED**: per-agent well-known at `GET /a2a/{agent_name}/.well-known/agent-card.json` (and `GET /servers/{server_id}/a2a/{agent_name}/.well-known/agent-card.json` for virtual-server scope). The spec mandates the `agent-card.json` suffix (IANA-registered) but is non-prescriptive on the prefix; mounting it under each agent's existing namespace preserves convention AND aligns with the dispatch URL.
- **Q9 — Native dispatch URL.** **RESOLVED**: bare `POST /a2a/{agent_name}` (and `POST /servers/{server_id}/a2a/{agent_name}`). The A2A 1.0.0 spec does NOT mandate a `/rpc` or `/jsonrpc` suffix — `supportedInterfaces[].url` advertises whatever endpoint we serve. The card IS the contract. PR #5313's `/jsonrpc` route is therefore optional plumbing, not a spec requirement. Disposition lives in Q3 (default: keep `/jsonrpc` as a same-handler alias, native bare URL is the public-facing one).

### Questions where the default is likely fine (defaults adopted unless vetoed)

- **Q7 — Card `url` rewrite source.** Default per A7: `PUBLIC_BASE_URL` (or new `A2A_PUBLIC_BASE_URL` if naming clash). Veto at gate if you want per-agent or per-server overrides.
- **Q10 — Harness scope.** Default per A9: MINIMAL (user-stated constraint). Veto only if you want harness to also verify control-plane membership semantics.
- **Q11 — Bearer-token forwarding to upstream.** Default per A8: keep existing per-agent + UAID-federation pattern unchanged. Veto if you want a new global "forward incoming bearer to all upstreams" mode.
- **Q12 — Accept legacy v0.3 method aliases at the dispatcher?** Default: YES — the dispatcher maps `message/send` → `SendMessage`, `tasks/get` → `GetTask`, etc. before forwarding, per F8 ("servers MAY accept both legacy and current forms during transition"). This keeps existing v0.3 clients working without breaking changes. Veto for strict v1.0-only enforcement (the upstream is on the hook for v1.0 names then).
- **Q13 — Multiple `protocolBinding` values on the card?** Default: `JSONRPC` only for phase 1. The spec defines `JSONRPC`, `GRPC`, `HTTP+JSON` and allows custom. Phase 1 ships JSON-RPC because that matches PR #5313 and the existing harness compliance targets. Veto if you want gRPC and/or HTTP+JSON entries on the card from day one (this would expand C3 scope considerably).

## Approval gate
status: awaiting-approval

**Exploration complete.** All 4 grounding agents returned. Findings F1-F8 are cited. Architectural principles P1-P4 are locked. Components C1-C6, Decisions D1-D10, and Open questions Q1-Q13 are recorded.

**Six real forks need user decision before I write `.omo/plans/a2a-native-passthrough.md`:**

| # | Fork | Default I will use |
|---|------|--------------------|
| Q1 | Rust deprecation scope | NARROW (A2A runtime + crate only) |
| Q2 | Legacy `/invoke` timeline | KEEP indefinitely, document as legacy |
| Q3 | PR #5313 disposition | SUPERSEDE (extract dispatch core, keep `/jsonrpc` as same-handler alias, error layer replaced) |
| Q4 | Card auth posture | BASIC public, EXTENDED authenticated |
| Q5 | PR #5226 disposition | ORTHOGONAL (separate work) |
| Q6 | Principles scope | NARROW (bind new work only; don't refactor existing `/invoke` handler) |

**Defaults adopted unless explicitly vetoed (no decision required, but transparent):**
Q7 (PUBLIC_BASE_URL for url rewriting), Q10 (minimal harness changes per user constraint), Q11 (keep existing per-agent + UAID auth pattern), Q12 (accept v0.3 method aliases at dispatcher), Q13 (JSONRPC binding only for phase 1).

**On approval:** I will write `.omo/plans/a2a-native-passthrough.md` as a Codex-level execution plan with phased rollback points, decision-complete instructions, and no further interview needed during execution.
