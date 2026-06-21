# a2a-native-passthrough - Work Plan

> **Pre-execution checklist — resolution log**
>
> The plan converged through 5 adversarial review cycles (CRITICAL count 5→5→2→0→0). Final-round polish applied 3 fixes (T12 step 9 `await` removed, pytest selectors lowercase, UAID wording clarified) plus the 6 documented MEDIUMs from this checklist (all resolved before execution began):
>
> 1. ✅ **Error mapping table `Test` column** — added in T6 table; each gateway-owned trigger row maps to a concrete `pytest tests/...` reference.
> 2. ✅ **`-32007` trigger condition concrete** — defined as "agent's `capabilities.extendedAgentCard` is False or absent"; T12 step 8 GetExtendedAgentCard branch now checks `agent.capabilities.get("extendedAgentCard", False)` before synthesizing.
> 3. ✅ **Dependency matrix T28 split refs** — T27 row no longer claims to block T28A continuation; T29 row depends on T28B+T15+T19; Wave 1+2 summary text updated.
> 4. ✅ **Cargo verification structural** — T27 step 5 replaced grep-on-output with `cargo metadata --format-version=1 --no-deps | jq '.workspace_default_members[]'` structural check, immune to cache state.
> 5. ✅ **Error table line ref** — "T12 step 6" → "T7 + T12 step 7" (matches polish-pass reordering).
> 6. ✅ **Draft staleness scrub** — `get_upstream_client_config` mentions in draft C1-CP row + Scope IN section now annotated as superseded with rationale.
>
> Plan is **APPROVED FOR EXECUTION**.



## TL;DR (For humans)

**What you'll get:** Native A2A 1.0.0 protocol support in the gateway. Any A2A SDK client can register, discover, and talk to agents through the gateway exactly the way it would talk to a direct A2A agent — including streaming. Agents can be addressed individually or bundled into named virtual servers and addressed via the virtual-server URL.

**Why this approach:** A layered architecture (control plane separate from data plane) lets the gateway reuse every authentication, registration, and authorization surface that already exists in ContextForge instead of inventing parallel auth code. The data plane is pure Python, and the existing experimental Rust A2A runtime — which is already disabled by default and emitting deprecation warnings — is fully retired as part of the work, simplifying the codebase by one whole sidecar.

**What it will NOT do:**
- Will not change the existing legacy `/invoke` REST envelope. Production callers stay safe.
- Will not expand into broader Rust deprecation work. Other Rust components are out of scope.
- Will not fold in PR #5226's separate streaming work. Those PRs stay independent.

**Effort:** Medium
**Risk:** Low — the database composition table already exists, the authentication and authorization modules already exist, and the compliance harness is already built and waiting for exactly this wire surface to land. There is no schema migration, no new auth model, no new permission strings.
**Decisions to sanity-check:** Card discovery is public, the authenticated extended card is gated. The contributor PR that added a `/jsonrpc` URL gets folded in as a same-handler alias rather than rejected or accepted as-is.

Your next move: approve for execution, or hand to an executor agent with this file as the brief. Full execution detail follows below.

---

> TL;DR (machine): Medium effort, Low risk, 6 components (control-plane API, per-agent card + dispatch, virtual-server scoping, Rust A2A runtime retirement, harness completion, docs) closing A2A-GAP-001 with full A2A 1.0.0 wire conformance across both per-agent and virtual-server-scoped URLs.

## Scope (REVISED post-adversarial-review)

### Must have

1. **C1 — Control-plane API extensions** in `mcpgateway/services/a2a_service.py` and `mcpgateway/services/server_service.py`:
   - `resolve_agent_for_dispatch(db, agent_name, server_id=None, user_email=None, token_teams=None) -> A2AAgent` — agent lookup WITH explicit Layer-1 visibility enforcement via `_check_agent_access` (raises `A2AAgentNotFoundError` on visibility miss, NOT a separate permission error).
   - `check_server_a2a_membership(db, server_id, agent_id) -> bool` — query against existing `server_a2a_association`.
   - `synthesize_agent_card(db, agent_name, public_base_url, server_id=None, user_email=None, token_teams=None) -> AgentCard` — builds v1 `AgentCard` **FRESH from the `A2AAgent` row, NOT via legacy `get_agent_card()`** (D12). Anonymous public-card path passes `token_teams=[]` (D11). Also enforces v-server membership when `server_id` provided (Oracle v3 #2). v-server membership check happens via internal call to `check_server_a2a_membership`.
   - ~~`get_upstream_client_config(db, agent)`~~ — **REMOVED from must-have** (Momus v4 #3 — no todo implements it). The T4/T5 unary + streaming dispatchers reuse existing `a2a_service.invoke_agent(...)` infrastructure (verified at `main.py:5125-5137`), which already resolves per-agent upstream URL + auth + OAuth headers internally per D5. A dedicated helper is unnecessary.
   - `validate_a2a_version(header_value, method=None) -> str` — accepts `1.0` / `1.0.0`; missing/empty + legacy-alias method → `"1.0"` with deprecation log (Q12 transition); missing/empty + v1 method → `VersionNotSupportedError` (D13 + v4 MEDIUM #9).
   - `dispatch_a2a_jsonrpc_unary(db, agent, body, bearer_token) -> dict` — non-streaming dispatch helper (D15).
   - `dispatch_a2a_jsonrpc_streaming(db, agent, body, bearer_token) -> AsyncIterator[dict]` — streaming dispatch using `async with client.stream(...)` (D15).

2. **C2 — Per-agent data plane** (`/a2a/{agent_name}/*`):
   - `GET /a2a/{agent_name}/.well-known/agent-card.json` — basic card UNAUTHENTICATED, calls synthesizer with `token_teams=[]` (D11). NO `@require_permission` decorator.
   - `POST /a2a/{agent_name}` — dispatch route with:
     - Manual JSON parsing from `await request.body()` (D17 — enables `-32700 ParseError`).
     - Visibility derivation via `get_rpc_filter_context(request, user)` before resolve (Oracle #3).
     - Explicit `GetExtendedAgentCard` method branch using `a2a.read` permission, calls control-plane synthesizer, NEVER forwards upstream (D18).
     - All other methods require `a2a.invoke` and pass through (with v0.3 alias mapping per F8 but EXCLUDING `tasks/list` — Oracle #22).
     - HTTP 404 when path resource (agent) doesn't exist BEFORE body parse (D14); `-32601` only when method unknown on known agent (D14).
     - SSE via separate streaming path (D15) for `SendStreamingMessage` and `SubscribeToTask`.
     - `A2A-Version` header validated inbound, set outbound (D13).
   - Route registration order: static suffix routes (`/invoke`, `/state`, `/jsonrpc`-if-applicable) BEFORE bare `/{agent_name}` (Oracle #15).

3. **C3 — Virtual-server-scoped data plane** (`/servers/{server_id}/a2a/{agent_name}/*`):
   - `A2APathRewriteMiddleware` matching regex `^/servers/([^/]+)/a2a/([^/]+)(/.*)?$` — base form AND suffix form (Oracle #14).
   - Rewrites to `/a2a/{agent_name}{suffix or ""}` with `server_id` injected into `request.scope["a2a_server_id"]`.
   - Handlers from C2 read `server_id` from scope and call `check_server_a2a_membership(...)` before synthesis or dispatch.

4. **C4 — Compliance coverage audit + gap closure (NEW per P5)**:
   - Enumerate every assertion in `tests/live_gateway/a2a_compliance/` and map to A2A 1.0.0 protocol requirements (method catalog, error codes incl. `-32001..-32009`, SSE shape, A2A-Version handling, RBAC denial, v-server scoping).
   - Identify gaps; write gap-closure compliance tests BEFORE corresponding implementation lands in C2/C3.
   - Each implementation todo in C2/C3 cites the compliance assertion that verifies it.

5. **C5 — Server CRUD + Admin UI verification and patches (NEW addressing user goal #1+#2)**:
   - Verify `ServerService.create_server` / `update_server` populates `server_a2a_association` from `schemas.ServerCreate.associated_a2a_agents` (F10). If wired: write a regression test that proves it. If not wired: fix the service-layer wiring + write the regression test.
   - Verify admin server-create / server-edit form templates use `agents_selector_items.html` for A2A binding (F11). If wired: write a UI regression test. If not wired: add the selector + write the test.
   - Add card-endpoint-URL display affordance in agent detail view (new ops surface).

6. **C6 — Rust A2A runtime deprecation (REVISED v3 — staged across THIS release N and follow-up N+1)**:
   - **Release N (this plan)**:
     - T23: Add startup warning when `EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED=true` is set, telling users the flag is now a no-op and physical removal is in N+1.
     - T24: Remove `crates/a2a_runtime/` (package `contextforge_a2a_runtime`) from `Cargo.toml` `default-members` (keep in `members` for cargo workspace continuity during transition).
     - T25: Remove `experimental_rust_a2a_runtime_*` execution branches in `tool_service.py` and `a2a_service.py` so the Python dispatcher is the only path. **NOTE (Oracle v3 #5 honesty)**: this is a removal of behavior, not a deprecation-cycle wait — users with the flag set lose Rust dispatch in this release. T23's warning is INFORMATIONAL so operators can scrape logs and update their configs. The "one warned release before physical deletion" gate applies to the MODULE FILE + CONFIG FIELDS only (T26), not the execution behavior.
     - T26: Mark module + config + reporting DEPRECATED with `DeprecationWarning` on import, `# DEPRECATED` comments on config fields, `_rust_a2a_runtime_managed()` returning False, `.env.example` comment prefix. **NO physical deletion** of the Python module, the 6 config fields, the `_rust_a2a_runtime_managed` symbol, or the runtime_admin_router toggle line. Operators relying on those imports/symbols stay safe.
   - **Release N+1 (out of scope for this plan, tracked in `.omo/followups/` or repo issue)**:
     - Delete `mcpgateway/services/rust_a2a_runtime.py` (the now-DeprecationWarning-emitting module).
     - Delete the 6 config fields in `mcpgateway/config.py:331-351` + validator at `:2883`.
     - Delete status-reporting helpers in `mcpgateway/version.py:140-567`.
     - Delete `runtime_admin_router.py:92` toggle.
     - Remove `crates/a2a_runtime/` from `Cargo.toml` `members` entirely (after which the crate directory itself can be physically removed in a subsequent commit).

7. **C7 — Compliance harness completion (revised per Oracle #11)**:
   - Wire fixture plumbing in `tests/live_gateway/a2a_compliance/conftest.py`: gateway base URL, auth token, registered agent name, server_id — currently placeholders.
   - Update `A2AGatewayProxyTarget._open_client` and `A2AGatewayVirtualServerTarget._open_client` to use real `ClientFactory(config=...)` shape mirroring `targets/reference.py`.
   - Delete the GAP-001 xfail hook.
   - Mark GAP-001 closed in `COMPLIANCE_GAPS.md` with closing commit reference.

8. **C8 — Documentation**: A2A 1.0.0 wire-conformance + migration note at `docs/docs/architecture/a2a-native.md`.

### Must NOT have (guardrails — REVISED)

1. **No new auth code in handlers.** AuthN: `Depends(get_current_user_with_permissions)` exclusively — no JWT claim reading, no `auth_middleware` direct calls. AuthZ: EITHER `@require_permission("a2a.invoke")` decorator (for single-permission routes matching existing `/invoke` pattern) OR per-method `permission_service.check_permission(user_email=..., permission=..., token_teams=..., resource_type="a2a_agent", resource_id=str(agent.id), team_id=agent.team_id)` calls INSIDE the handler (for routes where the required permission depends on the parsed body, like T12's `GetExtendedAgentCard` branch). Both are valid AuthZ patterns; the route picks ONE based on whether the permission is body-dependent. **Visibility derivation goes through `get_rpc_filter_context(request, user)` — same as existing `/invoke` at `main.py:5074`.** Per Oracle re-review v3 #8: Must-NOT cannot say "@require_permission exclusively" because T12's body-dependent RBAC requires per-method check.
2. **No `HTTPException` for JSON-RPC ENVELOPE errors.** D6 + D14. HTTPException is reserved for transport-level failures: 401, 403, 404 for path-resource-not-found (agent unknown BEFORE body parse), 405, 5xx. JSON-RPC errors (`-32700..-32603` + A2A-specific `-32001..-32009`) are HTTP 200 + JSON-RPC error body.
3. **No top-level `protocolVersion` on the card.** Per-interface only (D9).
4. **No `transportProtocol` field name.** Always `protocolBinding` in JSON (D8). SDK silently drops misnamed fields.
5. **No mutation of existing `POST /a2a/{name}/invoke`.** Legacy envelope stays as-is per A2.
6. **No new Rust code.** Pure Python (P4).
7. **No new join tables or schema migrations.** `server_a2a_association` already exists (F1); `associated_a2a_agents` already in `ServerCreate`/`ServerUpdate` (F10).
8. **No new permission strings.** `a2a.invoke` for dispatch, `a2a.read` for `GetExtendedAgentCard` (F5).
9. **No upstream-card passthrough.** Synthesizer ALWAYS rewrites `url`; NEVER serves upstream's URL directly (D7).
10. **No global mutable state in handlers.** Per-request data flows via function args from control plane (P1+P2).
11. **No matrix/fixture/conftest restructuring beyond what P5 audit requires.** A9 still binds the parts of the harness unrelated to coverage gaps; coverage-gap tests get written, but matrix layout and target-class CONSTRUCTOR shapes stay untouched.
12. **No deletion of `crates/a2a_runtime/`** in this plan. Removed from `default-members` only (D16); deletion from `members` is a follow-up release. **The earlier "harmless" framing was wrong (F13).**
13. **No method whitelist** in C2 dispatcher EXCEPT `GetExtendedAgentCard` (D18 — gateway-handled). All other methods pass through. `tasks/list` is NOT mapped as a legacy alias (Oracle #22).
14. **No gRPC or HTTP+JSON `protocolBinding` on phase-1 cards.** JSONRPC only.
15. **No bearer-forwarding behavior change.** Existing per-agent + UAID federation pattern unchanged. **UAID handling reuses the EXISTING `a2a_service.invoke_agent()` path** (verified at `main.py:5125-5137`) — that helper already detects whether the `agent_name` input is a UAID and routes through federation before falling through to local resolution. T12's call to `resolve_agent_for_dispatch(db, agent_name, ...)` for the path-resource check + T4's call to `invoke_agent(db, agent_name, ...)` together preserve the existing UAID-aware behavior. The previous wording "UAID dispatch runs BEFORE local resolution" was misleading — both happen inside the service layer in the order the existing code chooses. Momus v5 #2 clarification.
16. **No reuse of `get_agent_card()` for v1 synthesis.** Fresh build from `A2AAgent` row (D12). Legacy `get_agent_card()` stays for the existing internal trusted endpoint.
17. **No FastAPI `body: Dict[str, Any] = Body(...)` for the JSON-RPC route.** Manual parsing required (D17) — otherwise `-32700 ParseError` is unreachable.
18. **No `PUBLIC_BASE_URL` references.** Use `settings.app_domain` + optional `settings.a2a_public_base_url` override (F15 + A7).
19. **No implementation in C2/C3 before C4 audit + gap-closure tests land.** P5 ordering is binding (D19).
20. **No deferred CRUD/UI verification.** C5 lands in the same plan; the user's goals #1 and #2 are first-class deliverables.

## Verification strategy (REVISED)

> Zero human intervention — all verification is agent-executed.

### P5 compliance-test-first overrides default TDD posture

Per P5, compliance test coverage is the verification floor for protocol behavior. The audit in C4 produces the slate of gap-closure compliance tests that land BEFORE C2/C3 implementation. Implementation todos cite the compliance assertion that verifies them.

### Test layout (verified against tree)

- **Unit tests**: `tests/unit/mcpgateway/services/test_a2a_service.py` (existing), new `tests/unit/mcpgateway/services/test_a2a_service_native.py` for C1 control-plane functions.
- **Pydantic models**: new `tests/unit/mcpgateway/test_a2a_native_schemas.py` for the v1 `AgentCard` / `SupportedInterface` model assertions (D8/D9 enforcement).
- **Integration tests**: new `tests/integration/test_a2a_native_routes.py` for C2 in-process route exercises (httpx AsyncClient against FastAPI app).
- **Compliance harness**: `tests/live_gateway/a2a_compliance/` (existing); C4 ADDS missing assertions, C7 wires fixtures + closes GAP-001.
- **Server CRUD wiring**: existing tests in `tests/unit/mcpgateway/services/test_server_service.py` (verify) + new test asserting `associated_a2a_agents` round-trips through create → DB → read.
- **Admin UI**: existing template tests under `tests/unit/mcpgateway/templates/` if present, otherwise small render tests exercising `agents_selector_items.html` in the server-form context.

### Test decision per component

- **C1 (control plane)**: TDD. Tests written first (`test_a2a_service_native.py`), implementation lands to make them pass.
- **C2 (per-agent data plane)**: COMPLIANCE-FIRST per P5. The compliance test (written in C4) is the acceptance criterion. Implementation lands to flip the assertion from RED to GREEN. Supplementary in-process integration tests for non-protocol behavior (auth derivation, route ordering).
- **C3 (v-server data plane)**: Same as C2 — compliance harness for protocol behavior, integration tests for v-server-specific behavior (membership miss returns JSON-RPC `-32601` per D14 — wait, actually D14 says agent-unknown-at-path is HTTP 404, including v-server membership miss since the path resource doesn't exist for that caller).
- **C4 (compliance audit + gap closure)**: produces compliance tests as deliverables. The audit ITSELF is verified by a checklist artifact `.omo/evidence/c4-audit-checklist.md` mapping every A2A 1.0.0 requirement → assertion location.
- **C5 (CRUD + UI)**: integration tests proving end-to-end binding (server create with A2A agents → DB row in `server_a2a_association`) + UI render test.
- **C6 (Rust deprecation)**: existing tests in `tests/unit/mcpgateway/services/test_tool_service.py` and `test_a2a_service.py` must stay green. Add deprecation-warning test (asserts warning emitted when flag set).
- **C7 (harness completion)**: harness suite IS the test. Verification = 0 GAP-001 xfails + all compliance assertions green for both targets.
- **C8 (docs)**: `mkdocs build` clean.

### Framework

`pytest` (existing repo convention), `httpx.AsyncClient` for in-process route exercises, `pytest tests/live_gateway/a2a_compliance/...` for compliance harness, `make test-protocol-compliance-a2a-gateway` for the live-stack runner (Makefile target Oracle #25 mentioned).

### Evidence

`.omo/evidence/task-<N>-a2a-native-passthrough.<ext>` — `.txt` for plain pytest logs, `.json` for structured assertion dumps, `.md` for the C4 audit checklist. Each todo writes its evidence file. Wave 1 creates `.omo/evidence/` if not present.

### Per-component verification commands (test paths VERIFIED against tree)

| Component | Verification command | Pass criterion |
|-----------|---------------------|----------------|
| C1 | `pytest tests/unit/mcpgateway/services/test_a2a_service_native.py tests/unit/mcpgateway/test_a2a_native_schemas.py -v` | All new tests pass; `pytest tests/unit/mcpgateway/services/test_a2a_service.py` regressions = 0 |
| C2 | `pytest tests/integration/test_a2a_native_routes.py -v` AND `pytest tests/live_gateway/a2a_compliance/ -k 'gateway_proxy' -v` (lowercase matches actual parametrize IDs `gateway_proxy-jsonrpc` per conftest `_CASES`; Momus v5 #1 fix) | All integration tests green; compliance suite green for proxy target |
| C3 | `pytest tests/integration/test_a2a_native_routes.py::test_vserver_* -v` AND `pytest tests/live_gateway/a2a_compliance/ -k 'gateway_virtual' -v` (lowercase parametrize-ID convention; Momus v5 #1 fix) | All v-server tests green; compliance suite green for v-server target |
| C4 | `cat .omo/evidence/c4-audit-checklist.md` shows every spec requirement mapped to an assertion location | Checklist complete; new compliance tests committed before C2/C3 work begins |
| C5 | `pytest tests/unit/mcpgateway/services/test_server_service.py::test_a2a_association_create -v` + UI render test | end-to-end binding round-trips through DB; UI selector renders within server form |
| C6 | `rg "rust_a2a_runtime\|experimental_rust_a2a_runtime" mcpgateway/services/{tool_service,a2a_service}.py` returns 0 lines (T25 — call sites removed; module + config retained per T26 split per Oracle v3 #5); `pytest tests/unit/mcpgateway/services/` green; startup-warning test asserts warning emitted; `pytest tests/unit/mcpgateway/services/test_rust_a2a_runtime_deprecation.py` passes (DeprecationWarning on import) | Migration complete with no regressions; deprecation cycle verified |
| C7 | `pytest tests/live_gateway/a2a_compliance/ -v` reports 0 GAP-001 xfails AND all 28 previously-x-failed cells now pass | Harness end-to-end green |
| C8 | `mkdocs build` from repo root with `docs/docs/architecture/a2a-native.md` present | Build clean |

### Cross-cutting verification (run at the end of every wave)

- `make lint` — black, isort, ruff, pylint pass on changed files.
- `make test` — full test suite green (or only pre-existing unrelated failures noted).
- **Per-wave compliance gate** (NEW per Oracle #25): for Waves 3+ (data plane on), explicitly run `make test-protocol-compliance-a2a-gateway` OR `pytest tests/live_gateway/a2a_compliance/...` against a running stack. `make test` alone ignores `tests/live_gateway/` per Makefile config.
- `lsp_diagnostics` clean on changed files.
- For C2/C3: live smoke against `a2a_echo_agent` (`docker-compose.yml` ports 9100/9101). Real `ClientFactory.create_from_url(...)` from a Python driver proves end-to-end behavior.

### Final verification (after all waves)

The Final verification wave below is non-negotiable. All sub-tasks must APPROVE before declaring complete.

## Execution strategy (REVISED — 8 waves)

### Parallel execution waves

> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split. P5 binds wave ordering: compliance gap closure precedes implementation.

- **Wave 1 (Foundation)** — 7 todos — Pydantic models + control-plane API (synthesize_agent_card with v-server membership, resolve_agent_for_dispatch with visibility, check_server_a2a_membership) + dispatch helpers (unary + streaming) + error mapper + version validator. Setup `.omo/evidence/` directory inline. (`get_upstream_client_config` removed from must-have per Momus v4 #3 — T4/T5 reuse existing `invoke_agent()` per D5.)
- **Wave 2 (Compliance harness fixture wiring + audit + gap closure)** — 4 todos — T28A fixture plumbing PRECEDES T8 audit + T9/T10 gap-closure tests (D19 / P5). MUST land BEFORE Wave 3 implementation. Without T28A target-aware URL fixtures, gap-closure tests cannot exercise gateway targets.
- **Wave 3 (Per-agent data plane)** — 5 todos — card route, dispatch route, route-ordering regression, SSE wiring, proxy compliance smoke. Implementation lands to flip C4's gap-closure assertions GREEN.
- **Wave 4 (Virtual-server data plane)** — 4 todos — middleware (with corrected regex per Oracle #14), v-server card + dispatch routes, integration test + v-server compliance smoke.
- **Wave 5 (Server CRUD + Admin UI verify/patch)** — 3 todos — `ServerService.create_server` wiring verification, admin UI server-form selector verification, card-endpoint-URL ops affordance. Parallelizable with Wave 3+4.
- **Wave 6 (Rust A2A runtime deprecation — STAGED across releases per C6/Oracle v3 #5)** — 5 todos in THIS release N: startup warning (T23), workspace `default-members` exclusion (T24), call-site removal making Python unconditional (T25), file/config DEPRECATION MARKING but NOT physical deletion (T26), full-system smoke verifying the deprecation cycle is live (T27). **Physical deletion of the deprecated module/config/version-reporting is OUT OF SCOPE for this plan** — it lands in release N+1 after operators have one release of warned-but-still-importable code to migrate. Depends on Wave 3 (Python target must exist).
- **Wave 7 (Compliance harness completion)** — 3 todos — fixture plumbing (NOT just `_open_client`), target-class updates, xfail removal + GAPS.md close. Depends on Waves 3+4+5.
- **Wave 8 (Documentation)** — 1 todo — wire-conformance + migration docs.

Within a wave, todos can run in parallel unless flagged in the per-todo header.

### Dependency matrix

| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| T1 (Pydantic models — `mcpgateway/schemas_a2a_native.py`) | — | T2, T11 | T3, T4, T5, T6, T7 |
| T2 (synthesize_agent_card; fresh build from A2AAgent row) | T1 | T11, T16 | T3, T4, T5, T6, T7 |
| T3 (resolve_agent + visibility via `_check_agent_access`) | — | T11, T12, T15 | T1, T2, T4, T5, T6, T7 |
| T4 (dispatch_a2a_jsonrpc_unary helper; no Body() — manual parse) | — | T12 | T1, T2, T3, T5, T6, T7 |
| T5 (dispatch_a2a_jsonrpc_streaming via `async with client.stream`) | — | T14 | T1, T2, T3, T4, T6, T7 |
| T6 (A2A error mapper incl. `-32001..-32009`) | — | T12 | T1, T2, T3, T4, T5, T7 |
| T7 (validate_a2a_version + outbound header set) | — | T12 | T1, T2, T3, T4, T5, T6 |
| T8 (C4 audit: enumerate existing assertions, map to spec catalog) | — | T9, T10 | — |
| T9 (gap-closure tests: card discovery + field names) | T8 | T11 | T10 |
| T10 (gap-closure tests: JSON-RPC method coverage + error codes + SSE + A2A-Version) | T8 | T12, T14 | T9 |
| T11 (per-agent card route `GET /a2a/{name}/.well-known/agent-card.json`) | T1, T2, T3, T9 | T13 | T12, T14 |
| T12 (per-agent dispatch route `POST /a2a/{name}`; manual parse; GetExtendedAgentCard branch) | T3, T4, T6, T7, T10 | T13, T15 | T11, T14 |
| T13 (route-ordering regression test) | T11, T12 | T15 | T14 |
| T14 (SSE wiring for streaming methods) | T5, T10 | T15 | T11, T12 |
| T15 (compliance smoke: proxy target) | T11, T12, T13, T14 | T16, T26 | — |
| T16 (A2APathRewriteMiddleware with regex for base+suffix forms) | T3 | T17, T18 | T19, T20, T21 |
| T17 (v-server card route — same handler with server_id from scope) | T16, T11 | T19 | T18 |
| T18 (v-server dispatch route — same handler with server_id) | T16, T12, T14 | T19 | T17 |
| T19 (v-server integration + compliance smoke) | T17, T18 | T22, T26 | — |
| T20 (verify/patch `ServerService.create_server` for A2A association) | — | T22 | T15, T16-T19, T21 |
| T21 (verify/patch admin UI server-form A2A selector + add card-URL affordance) | — | T22 | T15, T16-T19, T20 |
| T22 (integration test: server create with A2A agents → DB binding + UI render) | T20, T21 | T26 | — |
| T23 (Rust runtime startup warning when flag set) | T15 | T24, T25, T26 | T20-T22 |
| T24 (remove crates/a2a_runtime from default-members) | T15 | T26 | T23, T25 |
| T25 (remove rust branches in tool_service.py + a2a_service.py) | T15 | T26 | T23, T24 |
| T26 (mark Rust module/config DEPRECATED; physical deletion → release N+1) | T23, T24, T25 | T27 | — |
| T27 (full-system smoke after deprecation marking; correct crate name verification) | T26 | — (terminal in Wave 6; does NOT block T28A which is a Wave 2 prerequisite already in flight) | — |
| T28A (Wave 2 prerequisite: minimal fixtures — gateway_base_url, auth_token via tests/helpers/auth.py, registered_agent_id, raw_card_url/raw_dispatch_url over {reference, gateway_proxy}) | none (executes FIRST in Wave 2) | T8, T9, T10, T15 | — |
| T28B (Wave 7: server creation with associated_a2a_agents=[agent_id, ...], `test_fixture_sanity.py` new file, gateway_virtual parameterization) | T19, T20, T22 | T29, T30 | — |
| T29 (update both target classes' _open_client with real ClientFactory(config=...)) | T28B, T15, T19 | T30 | — |
| T30 (delete GAP-001 xfail hook + close GAPS.md) | T29 | T31 | — |
| T31 (architecture docs) | T30 | — | — |

## Todos (REVISED — 31 todos across 8 waves)

> Implementation + Test = ONE todo. Never separate. P5 compliance-test-first binds wave ordering.

### Wave 1 — Foundation (control-plane API + reusable helpers, NO HTTP yet)

- [ ] 1. Pydantic models at `mcpgateway/schemas_a2a_native.py` (top-level file, NOT under `schemas/`)
  What to do: Create `mcpgateway/schemas_a2a_native.py` (verified: `mcpgateway/schemas.py` is a file, NOT a package — placing models under `schemas/` would collide per Momus #1 / Oracle #1). Pydantic v2 models `AgentCard`, `AgentProvider`, `AgentCapabilities`, `AgentSkill`, `SupportedInterface`, `SecurityRequirement`. `Field(alias="protocolBinding")` for snake→camel. `protocolVersion` on `SupportedInterface`, NEVER on `AgentCard` (D9). `ConfigDict(populate_by_name=True, extra="forbid")`. Required fields per F8. Also create `tests/unit/mcpgateway/test_a2a_native_schemas.py` with a LOCAL fixture (not the undefined `minimal_valid_card` from the original plan — Momus #2 fix).
  Must NOT do: do NOT use path `mcpgateway/schemas/a2a_native.py`. Do NOT add `transportProtocol` alias. Do NOT use `extra="allow"`. Do NOT put `protocolVersion` on AgentCard root.
  Parallelization: Wave 1 | Blocked by: none | Blocks: T2, T11
  References: D8, D9, F8 ([proto L361-L398](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/specification/a2a.proto#L361-L398), [proto L334-L355](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/specification/a2a.proto#L334-L355)); `mcpgateway/schemas.py` for repo Pydantic v2 conventions; do NOT mirror legacy `a2a_service.py:1332-1395` (Oracle #16 — wrong shape).
  Acceptance: `pytest tests/unit/mcpgateway/test_a2a_native_schemas.py -v` passes; ValidationError on `transportProtocol`; ValidationError on top-level `protocolVersion`; round-trip `model_dump(by_alias=True)` emits `protocolBinding`.
  QA: happy=local fixture parses to AgentCard. failure=dict with `transportProtocol` raises ValidationError. Evidence: .omo/evidence/task-1-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): add A2A 1.0.0 Pydantic models with strict field-name enforcement

- [ ] 2. Card synthesizer `synthesize_agent_card(...)` — FRESH from row (D12) + v-server membership enforcement (Oracle re-review #2)
  What to do: Add `synthesize_agent_card(db, agent_name, public_base_url, server_id=None, user_email=None, token_teams=None) -> Optional[AgentCard]` in `mcpgateway/services/a2a_service.py`. Resolve agent. If `server_id` is provided AND `check_server_a2a_membership(db, server_id, agent.id)` returns False → **return None** (forged-card prevention). Then check visibility via `_check_agent_access(db, agent, user_email, token_teams)`; return None on deny. Then build the v1 `AgentCard` (T1 model) DIRECTLY from `A2AAgent` row fields. ONE `SupportedInterface` entry: `url = f"{public_base_url}/servers/{server_id}/a2a/{agent_name}"` or `f"{public_base_url}/a2a/{agent_name}"`, `protocolBinding="JSONRPC"`, `protocolVersion=agent.protocol_version` (NOT hardcoded). Caller resolves `public_base_url = getattr(settings, "a2a_public_base_url", None) or str(settings.app_domain).rstrip('/')` (Oracle re-review #4 — defensive getattr because `a2a_public_base_url` is a SOFT addition, not a hard new config field).
  Must NOT do: do NOT call `get_agent_card()` and pass output through (Oracle #16 — wire shape mismatch). Do NOT hardcode `protocolVersion="1.0"`. Do NOT serve a card when `server_id` is provided but membership fails (Oracle re-review #2 — security hole). Do NOT raise inside the helper — return None on every deny path.
  Parallelization: Wave 1 | Blocked by: T1 | Blocks: T11, T17
  References: D11, D12, F9, F12 (`a2a_service.py:1379-1395` legacy NOT to reuse); F5 (`a2a_service.py:483-545` `_check_agent_access`); F1 (`db.py:2490-2495` `server_a2a_association`); F15 (`config.py:1172` `app_domain`); Oracle re-review #2 + #4.
  Acceptance: `pytest tests/unit/mcpgateway/services/test_a2a_service_native.py::test_synthesize -v` covers 8 cases (URL absent server, URL with server, `protocolBinding="JSONRPC"`, per-interface `protocolVersion`, public visibility `token_teams=[]` hides team-only agent, model validates clean, **v-server membership miss returns None**, **agent in different server returns None**).
  QA: happy=public agent + `token_teams=[]` → card. failure 1=team-only agent + `token_teams=[]` → None. failure 2=foreign agent at `/servers/{X}/a2a/foreign` → None. Evidence: .omo/evidence/task-2-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): synthesize v1 AgentCard with visibility + v-server membership

- [ ] 3. Agent resolution + membership — with visibility derivation
  What to do: Add `resolve_agent_for_dispatch(db, agent_name, server_id=None, user_email=None, token_teams=None) -> A2AAgent` and `check_server_a2a_membership(db, server_id, agent_id) -> bool` to `mcpgateway/services/a2a_service.py`. Case-insensitive name match. AFTER finding agent, call `_check_agent_access(db, agent, user_email, token_teams)`; on deny raise `A2AAgentNotFoundError` (Oracle #3 — visibility miss looks like not-found). If `server_id` provided AND membership check fails, raise `AgentNotInServerError`. Membership: direct join query on `server_a2a_association` (NOT relationship traversal).
  Must NOT do: do NOT skip visibility. Do NOT raise HTTPException. Do NOT use `Server.a2a_agents` ORM traversal.
  Parallelization: Wave 1 | Blocked by: none | Blocks: T11, T12, T15
  References: D11 + Oracle #3; F1 (`db.py:2490-2495`); F5 (`a2a_service.py:483-545`); F3 (`main.py:5041-5137` /invoke pattern).
  Acceptance: `pytest tests/unit/mcpgateway/services/test_a2a_service_native.py::test_resolve_and_membership -v` covers 6 cases (bare lookup, valid membership, invalid membership, missing agent, visibility deny non-admin/wrong-team, admin bypass `token_teams=None`).
  QA: happy=admin bypass returns agent. failure=team-only agent + `token_teams=[]` → A2AAgentNotFoundError. Evidence: .omo/evidence/task-3-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): agent resolution + membership with explicit visibility

- [ ] 4. Unary dispatch helper `dispatch_a2a_jsonrpc_unary(...)` (signature aligned with T12 — CRITICAL v3 #2)
  What to do: Add `async def dispatch_a2a_jsonrpc_unary(db, agent, body, *, bearer_token=None, hop_count=0, request_headers=None) -> dict | tuple[int, str, Any]` to `mcpgateway/services/a2a_service.py`. **Signature matches the exact kwargs T12 passes** (Oracle v3 #2 fix). Validate envelope (`jsonrpc=="2.0"`, `method` non-empty str, `params` dict-or-null, `id` optional). Map legacy v0.3 aliases per F8 EXCLUDING `tasks/list` (Oracle #22). Calls existing `a2a_service.invoke_agent(...)` (verified at `main.py:5125-5137`) passing through `bearer_token`, `hop_count`, `content_type=request_headers.get("content-type")`, `request_headers` to preserve per-agent auth + UAID federation + plugin context (D5). **UAID-first**: if `agent.uaid` is set AND format suggests cross-gateway, the existing `invoke_agent` already routes via federation path. Return either the successful dict OR a `(code, message, data)` tuple for error cases that T12 maps to `make_jsonrpc_error`.
  Must NOT do: do NOT include `tasks/list` in alias map. Do NOT handle `GetExtendedAgentCard` here (T12 route-layer branch). Do NOT raise HTTPException. Do NOT touch FastAPI objects. Do NOT drop the `hop_count` / `request_headers` kwargs — they are part of the verified `/invoke` contract.
  Parallelization: Wave 1 | Blocked by: none | Blocks: T12
  References: F4, F8 alias table (minus `tasks/list`), verified `main.py:5125-5137` invoke_agent call shape, D5, Oracle v3 #2 (signature alignment).
  Acceptance: `pytest tests/unit/mcpgateway/services/test_a2a_service_native.py::test_dispatch_unary -v` covers (a) all correct legacy aliases mapped, (b) happy + error paths, (c) UAID-first routing through existing federation, (d) `tasks/list` NOT mapped, (e) `hop_count` propagates to upstream, (f) function accepts T12's exact kwargs without TypeError.
  QA: happy=`SendMessage` → dict. failure 1=`tasks/list` reaches upstream unchanged. failure 2=missing `hop_count` kwarg → TypeError caught at unit-test level. Evidence: .omo/evidence/task-4-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): unary JSON-RPC dispatch (kwargs aligned with verified /invoke)

- [ ] 5. Streaming dispatch `dispatch_a2a_jsonrpc_streaming(...)` — REAL SSE parser + aligned signature (v3 CRITICAL #5 + #2)
  What to do: Add `async def dispatch_a2a_jsonrpc_streaming(db, agent, body, *, bearer_token=None, hop_count=0, request_headers=None) -> AsyncIterator[dict]` to `mcpgateway/services/a2a_service.py`. **Signature matches T12's exact kwargs** (Oracle v3 #2 fix — paired with T4). Use `async with client.stream("POST", upstream_url, headers={"Accept": "text/event-stream", "A2A-Version": agent.protocol_version, **(request_headers or {}), "Authorization": f"Bearer {bearer_token}" if bearer_token else None})` (build headers dict carefully — drop None values). **Iterate as a real SSE parser, NOT `aiter_lines() + json.loads`** (Oracle v2 #5): maintain a `data_buffer: list[str] = []`; for each line from `response.aiter_lines()`: if line starts with `data: ` → append `line[6:]` to buffer; if line is empty (blank line, SSE event delimiter) AND buffer is non-empty → `payload = "\n".join(data_buffer); buffer.clear(); try: yield json.loads(payload) except json.JSONDecodeError: yield make_jsonrpc_error(INVALID_AGENT_RESPONSE, "Upstream sent malformed SSE payload", body.get("id"))`. Ignore `id:`, `event:`, `retry:` SSE field lines. On generator cancellation (downstream consumer disconnects), the `async with client.stream(...)` context exits and closes the upstream connection. On upstream HTTP error before stream starts → yield ONE `make_jsonrpc_error(...)` then exit.
  Must NOT do: do NOT call T4 for streaming methods. Do NOT use `client.post(...).json()` — buffers (Oracle #10). Do NOT json.loads each line — A2A SSE framing is `data: {...}\n\n` not line-delimited JSON (Oracle re-review #5). Do NOT prepend `data:` in the yielded dict — caller (T14) re-wraps for the downstream SSE response.
  Parallelization: Wave 1 | Blocked by: none | Blocks: T14
  References: D15, Oracle #10 + re-review #5; F8 ([JSON-RPC streaming L2316-L2330](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L2316-L2330)) — confirms `data:` SSE framing.
  Acceptance: `pytest tests/unit/mcpgateway/services/test_a2a_service_native.py::test_dispatch_streaming -v` covers (a) mock upstream emits 3 SSE events → generator yields 3 dicts; (b) multi-line `data:` accumulation works (`data: {"a":1,\ndata: "b":2}\n\n` yields one dict); (c) blank-line-only frames are ignored; (d) cancellation closes upstream within ~100ms; (e) upstream HTTP error before stream → yield 1 error chunk + exit; (f) malformed JSON inside a `data:` payload → yield `INVALID_AGENT_RESPONSE` and continue (or exit, choose at impl time and document).
  QA: happy=mock SSE → 3 dicts. failure=`data: not-json\n\n` → INVALID_AGENT_RESPONSE chunk. Evidence: .omo/evidence/task-5-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): streaming JSON-RPC dispatch with real SSE parser

- [ ] 6. A2A error envelope helpers + trigger table (Oracle re-review #14)
  What to do: Add to `mcpgateway/services/a2a_service.py` constants `PARSE_ERROR=-32700`, `INVALID_REQUEST=-32600`, `METHOD_NOT_FOUND=-32601`, `INVALID_PARAMS=-32602`, `INTERNAL_ERROR=-32603`, plus A2A-specific `TASK_NOT_FOUND=-32001`, `TASK_NOT_CANCELABLE=-32002`, `PUSH_NOT_SUPPORTED=-32003`, `UNSUPPORTED_OPERATION=-32004`, `CONTENT_TYPE_NOT_SUPPORTED=-32005`, `INVALID_AGENT_RESPONSE=-32006`, `AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED=-32007`, `MULTIPLE_PUSH_NOT_SUPPORTED=-32008`, `VERSION_NOT_SUPPORTED=-32009`. Add `make_jsonrpc_error(code, message, request_id, data=None) -> dict` returning `{"jsonrpc":"2.0","error":{"code":code,"message":message,"data":data},"id":request_id}` with `data` omitted when None.

  Also produce `.omo/evidence/task-6-error-mapping-table.md` (committed as part of this todo) with the mapping table:

  | Trigger | Owner | Code | Wire location | Test |
  |---------|-------|------|---------------|------|
  | JSON syntax error in body | Gateway | `-32700` | T12 manual parse | `tests/integration/test_a2a_native_routes.py::test_dispatch_parse_error` |
  | Body not a JSON object (`[]`, `123`, `"x"`) | Gateway | `-32600` | T12 isinstance(dict) guard | `tests/integration/test_a2a_native_routes.py::test_dispatch_invalid_request_shape` |
  | Method field missing or non-string | Gateway | `-32600` | T4 envelope validation | `tests/unit/mcpgateway/services/test_a2a_service_native.py::test_dispatch_unary_envelope_validation` |
  | `A2A-Version` missing OR unsupported (and method is not a legacy v0.3 alias) | Gateway | `-32009` | T7 + T12 step 7 | `tests/unit/mcpgateway/services/test_a2a_version_negotiation.py::test_missing_header_v1_method_rejected` + `tests/integration/test_a2a_native_routes.py::test_dispatch_version_unsupported` |
  | Unknown method on a known agent | Upstream | `-32601` | upstream agent (gateway pass-through) | upstream test (out of scope) |
  | Invalid params on a known method | Upstream | `-32602` | upstream agent | upstream test (out of scope) |
  | Task ID not found (`GetTask`, `CancelTask`) | Upstream | `-32001` | upstream agent | upstream test (out of scope) |
  | Task in terminal state (`CancelTask`) | Upstream | `-32002` | upstream agent | upstream test (out of scope) |
  | Push config method on agent without `pushNotifications` capability | Upstream | `-32003` | upstream agent (gateway pass-through; no gateway-side fast-fail in phase 1) | upstream test (out of scope) |
  | Upstream returns malformed JSON in SSE chunk | Gateway | `-32006` | T5 SSE parser | `tests/unit/mcpgateway/services/test_a2a_service_native.py::test_dispatch_streaming_malformed_chunk` |
  | `GetExtendedAgentCard` invoked when agent's `capabilities.extendedAgentCard` is False or absent | Gateway | `-32007` | T12 `GetExtendedAgentCard` branch | `tests/integration/test_a2a_native_routes.py::test_get_extended_card_not_configured` |
  | Upstream HTTP 5xx or transport error | Gateway | `-32603` | T4/T5 catch + map | `tests/unit/mcpgateway/services/test_a2a_service_native.py::test_dispatch_unary_upstream_5xx` |
  | Unauthorized caller per `a2a.invoke` or `a2a.read` | Gateway HTTP | HTTP 403 (NOT JSON-RPC) | T12 permission check |
  | Unknown agent at path | Gateway HTTP | HTTP 404 (NOT JSON-RPC, per D14) | T12 resolve_agent_for_dispatch |
  | Malformed/missing auth | Gateway HTTP | HTTP 401 | middleware |

  The table is referenced from T12 implementation to confirm every error path has a designated code, owner, and wire location (Oracle re-review #14: constants alone do not imply behavior).
  Must NOT do: do NOT include HTTP status logic in the helper. Do NOT silently coerce A2A codes to `-32603`. Do NOT skip the trigger table.
  Parallelization: Wave 1 | Blocked by: none | Blocks: T12
  References: D6, D14, Oracle re-review #14; F8 ([error code mappings](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#54-error-code-mappings)).
  Acceptance: `pytest tests/unit/mcpgateway/services/test_a2a_jsonrpc_errors.py -v` passes ALL 14 constants + id passthrough; `.omo/evidence/task-6-error-mapping-table.md` exists with the table above; T12's test suite asserts each gateway-owned row in the table triggers the right code.
  QA: happy=`make_jsonrpc_error(VERSION_NOT_SUPPORTED,"...",1)` → exact wire dict with `-32009`. failure=missing positional → TypeError. Evidence: .omo/evidence/task-6-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): JSON-RPC error helpers + error-mapping trigger table

- [ ] 7. `validate_a2a_version` — method-aware (legacy aliases tolerate missing header) (v4 MEDIUM #9)
  What to do: Add `validate_a2a_version(header_value: Optional[str], method: Optional[str] = None) -> str` to `mcpgateway/services/a2a_service.py`. Behavior:
  - If `header_value` is `"1.0"` or `"1.0.0"` → return it verbatim (preserve what client sent).
  - If `header_value` is missing/empty/None AND `method` is one of the legacy v0.3 aliases (`message/send`, `message/stream`, `tasks/get`, `tasks/cancel`, `tasks/resubscribe`, `tasks/pushNotificationConfig/*`, `agent/getAuthenticatedExtendedCard`) → return `"1.0"` AND log `logger.info("Accepting legacy v0.3 client without A2A-Version header for method %s; v0.3 alias transition support", method)`. This preserves transitional v0.3 client compatibility per Q12 / Oracle v3 #9.
  - If `header_value` is missing/empty/None AND `method` is a v1.0-native method (or None — method unknown yet) → raise `VersionNotSupportedError("A2A-Version header is required for v1 native dispatch")`.
  - Anything else (`"2.0"`, `"0.3"`, `"abc"`, etc.) → raise `VersionNotSupportedError`.
  T12 catches and translates to JSON-RPC `-32009`. Also add `outbound_a2a_version(agent: A2AAgent) -> str` returning `agent.protocol_version` for upstream `A2A-Version` header.

  **Update T12 step 7** to pass the method into `validate_a2a_version(header_value=..., method=body.get("method"))`. This requires reordering T12's flow: body parse + isinstance(dict) guard come BEFORE A2A-Version validation, which is already the order in the current T12.
  Must NOT do: do NOT default missing/empty to `"1.0"` UNCONDITIONALLY — that silently accepts non-compliant v1 clients. Do NOT accept `"0.3"` as a header value (legacy support is method-alias level, not header level, per Q12). Do NOT silently rewrite `1.0` to `1.0.0` — preserve what client sent.
  Parallelization: Wave 1 | Blocked by: none | Blocks: T12
  References: D13 + Oracle v3 #9 (legacy compat fix); F8 ([versioning L706-L724](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L706-L724)); Q12 legacy alias transition support.
  Acceptance: `pytest tests/unit/mcpgateway/services/test_a2a_version_negotiation.py -v` covers (a) `"1.0"` + any method → returns `"1.0"`; (b) `"1.0.0"` + any method → returns `"1.0.0"`; (c) missing/empty + `"SendMessage"` (v1 method) → VersionNotSupportedError; (d) missing/empty + `"message/send"` (legacy alias) → returns `"1.0"` + info-log fires; (e) missing/empty + method=None → VersionNotSupportedError; (f) `"2.0"` + any method → VersionNotSupportedError; (g) `"0.3"` + any method → VersionNotSupportedError; (h) outbound uses `agent.protocol_version`.
  QA: happy 1=`validate_a2a_version("1.0", "SendMessage")` → `"1.0"`. happy 2=`validate_a2a_version(None, "message/send")` → `"1.0"` + log. failure 1=`validate_a2a_version(None, "SendMessage")` → VersionNotSupportedError. failure 2=`validate_a2a_version("2.0", None)` → VersionNotSupportedError. Evidence: `.omo/evidence/task-7-a2a-native-passthrough.txt`
  Commit: Y | feat(a2a): A2A-Version validation with legacy-alias header tolerance

### Wave 2 — Compliance harness fixture wiring + coverage audit + gap closure (NEW per P5; precedes implementation)

**Ordering note (REVISED v4 — T28 split per Oracle v3 #6)**: T28 has been split into Part A (Wave 2 prerequisite) and Part B (Wave 7 finalization). **Wave 2 sequence**: [**T28 Part A** (minimal fixtures: `gateway_base_url`, `auth_token` via `tests/helpers/auth.py:make_test_jwt`, `registered_agent_id`, target-aware `raw_card_url`/`raw_dispatch_url` parameterized over `{reference, gateway_proxy}`) → **T8** (audit) → **T9** (card-discovery gap-closure tests) → **T10** (dispatch/streaming/error-code gap-closure tests, parameterized over `{reference, gateway_proxy}` with `xfail_on(gateway_proxy, reason="A2A-GAP-001-PRE-IMPL")`)].

Part B of T28 (server creation with `associated_a2a_agents=[agent_id, ...]` + `test_fixture_sanity.py` + `gateway_virtual` parameterization) stays in Wave 7 because it depends on T20's service-layer verification. T29 (target-class `_open_client` wiring) and T30 (xfail removal) also stay in Wave 7 because they depend on Wave 3+4 implementation landing first.

Without Part A executing first, Wave 2 gap-closure tests could only exercise the `reference` target — P5 compliance-test-first principle would be unrealized for the gateway surface.

- [ ] 8. C4 audit: enumerate existing compliance assertions and map to A2A 1.0.0 protocol catalog
  What to do: Read every test in `tests/live_gateway/a2a_compliance/` and produce `.omo/evidence/c4-audit-checklist.md` with sections: (1) Card discovery — every required field name + URL-rewrite assertion; (2) JSON-RPC envelope validation; (3) Method catalog — every method from F8 (`SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`, push-config CRUD, `GetExtendedAgentCard`); (4) Error codes — standard `-32700..-32603` AND A2A-specific `-32001..-32009`; (5) SSE shape — `text/event-stream` MIME, `data:` chunk shape, terminal state handling; (6) `A2A-Version` header — inbound validation, outbound set; (7) v0.3 alias acceptance (EXCLUDING `tasks/list`); (8) RBAC / visibility denial paths; (9) v-server scoping behavior. For each row: which test file/function asserts it, OR "GAP" with severity (BLOCK vs nice-to-have).
  Must NOT do: do NOT write new tests in this todo — only document gaps. Do NOT extend matrix / fixture / target-class CONSTRUCTOR shapes (A9 still binds).
  Parallelization: Wave 2 | Blocked by: none | Blocks: T9, T10
  References: P5, F8 method catalog; `tests/live_gateway/a2a_compliance/` (entire tree); `tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md` for the existing gap convention to mirror.
  Acceptance: `.omo/evidence/c4-audit-checklist.md` exists with 9 sections, every spec requirement either CITES an existing assertion or is marked GAP-BLOCK/GAP-NICE.
  QA: happy=checklist is comprehensive (every F8 method appears, every error code appears). failure=any spec requirement missing from the doc. Evidence: .omo/evidence/task-8-a2a-native-passthrough.md (the checklist)
  Commit: Y | docs(a2a): compliance coverage audit checklist for A2A-1.0.0 surface

- [ ] 9. Gap-closure compliance tests — card discovery + field-name assertions
  What to do: Implement every BLOCK-severity GAP from T8's audit section (1) Card discovery. Per gap: add or extend assertion in `tests/live_gateway/a2a_compliance/test_*.py` (or new file `tests/live_gateway/a2a_compliance/test_card_discovery_extra.py` if no existing home fits). Assertions to cover: `supportedInterfaces[0].protocolBinding == "JSONRPC"` (NOT `transportProtocol`), `protocolVersion` is per-interface (NEVER top-level), `supportedInterfaces[0].url` rewritten to gateway-public URL (matches `{public_base}/a2a/{name}`), required fields present per F8, `extra="forbid"` on the model — unknown card fields rejected at parse time.
  Must NOT do: do NOT change matrix/fixture/target constructors. Do NOT add NICE-severity gaps in this todo (defer to follow-up). Do NOT add assertions for fields the spec marks optional unless the GAP-BLOCK list says so.
  Parallelization: Wave 2 | Blocked by: T8 | Blocks: T11
  References: T8 checklist; D8, D9, D12, F8.
  Acceptance: `pytest tests/live_gateway/a2a_compliance/ -k 'card' -v` reports all card-discovery assertions present; current xfail state shows the new assertions in collected list (they will FAIL until Wave 3 lands — that is intentional per P5).
  QA: happy=new assertions present and run. failure=spec field missed → re-open T8 checklist. Evidence: .omo/evidence/task-9-a2a-native-passthrough.txt
  Commit: Y | test(a2a-compliance): add gap-closure card-discovery assertions

- [ ] 10. Gap-closure compliance tests — JSON-RPC methods + error codes + SSE + A2A-Version + RBAC denial
  What to do: Implement every BLOCK-severity GAP from T8's sections 2-9. Specifically: assertions for each method in the catalog (Send/Stream/Get/List/Cancel/Subscribe/push-config-CRUD/GetExtendedAgentCard) returning the correct response envelope shape; assertions for each error code (standard `-32700..-32603` + A2A `-32001..-32009`) being emitted under the right trigger condition; SSE assertion that each `data:` chunk parses as complete JSON-RPC response; `A2A-Version` inbound rejection of unsupported (HTTP 200 + `-32009`); v0.3 alias acceptance for `message/send` → `SendMessage` etc. (EXCLUDING `tasks/list` per Oracle #22); RBAC denial paths — auth missing → 401, wrong team token → 404 (visibility deny looks like not-found per D11/Oracle #3), wrong scope → 403; v-server scoping — agent-not-in-server returns 404 at path (D14).
  Must NOT do: do NOT include `tasks/list` in alias-test expectations. Do NOT change matrix. Do NOT touch reference-target tests beyond what gap closure requires.
  Parallelization: Wave 2 | Blocked by: T8 | Blocks: T12, T14
  References: T8 checklist; D6, D11, D13, D14, F8 method catalog + error codes; Oracle #6, #20, #22.
  Acceptance: `pytest tests/live_gateway/a2a_compliance/ -v` shows all new assertions collected; gateway-target cells will FAIL until Waves 3+4 implementation lands (intentional per P5).
  QA: happy=all sections covered. failure=any BLOCK gap not covered. Evidence: .omo/evidence/task-10-a2a-native-passthrough.txt
  Commit: Y | test(a2a-compliance): add gap-closure dispatch/streaming/auth assertions

### Wave 3 — Per-agent data plane (`/a2a/{name}/*` routes) — implementation flips Wave 2 assertions GREEN

- [ ] 11. Per-agent card route `GET /a2a/{agent_name}/.well-known/agent-card.json` (public; D11)
  What to do: Add to `mcpgateway/main.py` under `a2a_router`. Signature: `async def get_a2a_agent_card(agent_name: str, request: Request, db: Session = Depends(get_db)) -> Response`. Resolve `public_base = getattr(settings, "a2a_public_base_url", None) or str(settings.app_domain).rstrip('/')` (Oracle re-review #4 — defensive getattr because `a2a_public_base_url` is a SOFT addition, not a hard new config field that this plan adds). Call `synthesize_agent_card(db, agent_name, public_base, server_id=request.scope.get("a2a_server_id"), user_email=None, token_teams=[])` (PUBLIC path passes `token_teams=[]` per D11; v-server membership enforced inside T2). None return → HTTP 404 (covers: unknown agent, visibility deny, v-server membership miss — all collapse to one transport-level outcome per D14). AgentCard return → `Response(content=card.model_dump_json(by_alias=True, exclude_none=True), media_type="application/json")`. NO `@require_permission`. Same handler serves v-server path post-middleware-rewrite (W4).
  Must NOT do: do NOT use `response_model=AgentCard` (FastAPI serializes by python name, not alias). Do NOT pass `token_teams=None` (admin bypass leaks). Do NOT assume `settings.a2a_public_base_url` is defined (Oracle re-review #4 — use getattr).
  Parallelization: Wave 3 | Blocked by: T1, T2, T3, T9 | Blocks: T13, T15
  References: D11, F6, F15, F8 ([spec L1974-L1980](https://github.com/a2aproject/A2A/blob/69dd57cb7ec8f83b7d93855d166869a72f01a1eb/docs/specification.md#L1974-L1980)); Oracle re-review #4.
  Acceptance: `pytest tests/integration/test_a2a_native_routes.py::test_card_endpoint -v` passes; live curl returns `protocolBinding=JSONRPC` (camelCase); flips T9's gap-closure card assertions GREEN.
  QA: happy=public agent → 200 + valid card. failure 1=unknown → 404. failure 2=team-only for anonymous → 404. failure 3=foreign agent at `/servers/{X}/a2a/foreign-agent/.well-known/agent-card.json` → 404 (membership). Evidence: .omo/evidence/task-11-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): public well-known A2A card endpoint with v-server safety

- [ ] 12. Per-agent dispatch route `POST /a2a/{agent_name}` — method-aware RBAC + verified `/invoke` plumbing (v3 REGRESSION CRITICAL #1 + HIGH #3 + #8)
  What to do: Route handler in `mcpgateway/main.py` under `a2a_router`. **Signature: `async def dispatch_a2a_agent(agent_name: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user_with_permissions), permission_service: PermissionService = Depends(get_permission_service)) -> Response`. NO `@require_permission(...)` decorator on the route** (Oracle v2 #1 — body-dependent RBAC requires per-method check). **NO `Body(...)` parameter** (D17 — enables `-32700 ParseError`).

  Handler flow (strict order — matches verified `/invoke` at `main.py:5040-5137`):
  1. Derive `(user_email, token_teams, is_admin) = get_rpc_filter_context(request, user)` (VERIFIED at `main.py:5074`).
  2. Apply the same admin/public-only token reshaping as `/invoke` at `main.py:5076-5080`:
     ```python
     if is_admin and token_teams is None:
         token_teams = None  # admin unrestricted
     elif token_teams is None:
         token_teams = []  # non-admin without teams = public-only
     ```
  3. Resolve agent via `resolve_agent_for_dispatch(db, agent_name, server_id=request.scope.get("a2a_server_id"), user_email=user_email, token_teams=token_teams)`; on `A2AAgentNotFoundError` → `return Response(status_code=404)` (D14 — visibility miss also surfaces as `A2AAgentNotFoundError` per T3).
  4. **VERIFIED `/invoke` extraction pattern** (verbatim from `main.py:5094-5123`):
     ```python
     hop_count = uaid_utils.read_hop_count(request.headers)
     bearer_token = getattr(request.state, "bearer_token", None)
     if not bearer_token:
         auth_header = request.headers.get("authorization", "")
         if auth_header.lower().startswith("bearer "):
             bearer_token = auth_header[7:]
     if bearer_token and not _is_jwt_token(bearer_token):
         bearer_token = None  # do not forward opaque tokens
     content_type = request.headers.get("content-type")
     request_headers = _filter_sensitive_headers({k.lower(): v for k, v in request.headers.items()})
     ```
     `uaid_utils.read_hop_count` is verified at `main.py:5094, 5196`. `_is_jwt_token` and `_filter_sensitive_headers` are existing module-level helpers in `main.py`. (Oracle v3 #3 correction — the previous plan made up `X-Forwarded-A2A-Hop` and `ALLOWED_FORWARD_HEADERS`; real code uses `uaid_utils.read_hop_count` reading whatever header convention that helper defines.)
  5. `raw = await request.body()`; `try: body = json.loads(raw) except json.JSONDecodeError: return JSONResponse(make_jsonrpc_error(PARSE_ERROR, "Parse error", None), status_code=200)`.
  6. **`if not isinstance(body, dict): return JSONResponse(make_jsonrpc_error(INVALID_REQUEST, "Request body must be a JSON object", None), status_code=200)`** (Oracle v2 #7 — `[]`/`"x"`/`123` are valid JSON but invalid JSON-RPC).
  7. Extract method early so version validation can be method-aware (T7 v4 signature requires this): `method = body.get("method")`. Then validate `A2A-Version` via `validate_a2a_version(header_value=request.headers.get("A2A-Version"), method=method)` — T7 accepts missing header for legacy v0.3 aliases AND rejects missing header for v1 methods. On `VersionNotSupportedError` → HTTP 200 + `make_jsonrpc_error(VERSION_NOT_SUPPORTED, ..., body.get("id"))`.
  8. **VERIFIED RBAC signature** (`permission_service.py:70-82`): the method is `check_permission(user_email: str, permission: str, resource_type=..., resource_id=..., team_id=..., token_teams=..., ...)`. Per Oracle v3 #1 the previous plan called `check_permission(user=user, ...)` — wrong kwarg. Method-dependent RBAC:
     ```python
     method = body.get("method")
     if method in {"GetExtendedAgentCard", "agent/getAuthenticatedExtendedCard"}:
         granted = await permission_service.check_permission(
             user_email=user_email,
             permission="a2a.read",
             resource_type="a2a_agent",
             resource_id=str(agent.id),
             team_id=agent.team_id,
             token_teams=token_teams,
         )
         if not granted:
             return Response(status_code=403)
         # Concrete -32007 trigger (v4 MEDIUM #2 + error-table fix): the
         # gateway can only synthesize the extended card if the agent's
         # capabilities explicitly advertise extendedAgentCard support.
         capabilities = agent.capabilities or {}
         if not capabilities.get("extendedAgentCard", False):
             return JSONResponse(
                 make_jsonrpc_error(AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED, "Agent does not support authenticated extended card", body.get("id")),
                 status_code=200,
             )
         card = await synthesize_agent_card(
             db, agent_name, public_base_url,
             server_id=request.scope.get("a2a_server_id"),
             user_email=user_email, token_teams=token_teams,
         )
         return JSONResponse({"jsonrpc": "2.0", "result": card.model_dump(by_alias=True, exclude_none=True), "id": body.get("id")}, status_code=200)
     else:
         granted = await permission_service.check_permission(
             user_email=user_email,
             permission="a2a.invoke",
             resource_type="a2a_agent",
             resource_id=str(agent.id),
             team_id=agent.team_id,
             token_teams=token_teams,
         )
         if not granted:
             return Response(status_code=403)
     ```
     **NEVER forward `GetExtendedAgentCard` upstream** (D18). Passing `token_teams` is security-significant: `check_permission` at lines 126-130 suppresses admin bypass when `token_teams == []` (public-only tokens cannot satisfy ANY permission via admin bypass).
  9. Detect streaming: `method in {"SendStreamingMessage", "SubscribeToTask", "message/stream", "tasks/resubscribe"}` → `gen = dispatch_a2a_jsonrpc_streaming(db, agent, body, bearer_token=bearer_token, hop_count=hop_count, request_headers=request_headers)` (NO `await` — T5 returns an async generator; `await`ing it would raise `TypeError: object async_generator can't be used in 'await' expression`. Oracle v5 HIGH fix) → T14's `StreamingResponse(_sse_format(gen), media_type="text/event-stream")`.
  10. Else → `result = await dispatch_a2a_jsonrpc_unary(db, agent, body, bearer_token=bearer_token, hop_count=hop_count, request_headers=request_headers)`; success → JSONResponse({"jsonrpc": "2.0", "result": result, "id": body.get("id")}, 200); error tuple `(code, msg, data)` → JSONResponse(make_jsonrpc_error(code, msg, body.get("id"), data), 200) per D6.

  Must NOT do: do NOT use `body: Dict = Body(...)`. Do NOT put `@require_permission` on the route (body-dependent permission requires per-method check). Do NOT call `check_permission(user=...)` (Oracle v3 #1 — wrong kwarg; verified API is `user_email=`). Do NOT skip `token_teams` in `check_permission` calls (security-significant per lines 126-130). Do NOT invent `X-Forwarded-A2A-Hop` (Oracle v3 #3 — use `uaid_utils.read_hop_count` per verified `/invoke`). Do NOT skip the `isinstance(body, dict)` guard. Do NOT forward `GetExtendedAgentCard` upstream.
  Parallelization: Wave 3 | Blocked by: T3, T4, T5, T6, T7, T10 | Blocks: T13, T14, T15
  References: D6, D11, D13, D14, D17, D18; verified `mcpgateway/services/permission_service.py:70-82` for `check_permission` signature; verified `mcpgateway/main.py:5040-5137` for `/invoke` extraction pattern; F5 (`get_rpc_filter_context`); Oracle v3 #1, #3, #8 corrections.
  Acceptance: `pytest tests/integration/test_a2a_native_routes.py -v` passes; compliance gates from T10 GREEN; live behavior matches the 9 scenarios in QA.
  QA: (a) malformed JSON → HTTP 200 + `-32700`; (b) `body=[]` → HTTP 200 + `-32600`; (c) missing agent → HTTP 404; (d) wrong-team token (`token_teams=[]`) for team-only agent → HTTP 404; (e) `A2A-Version: 2.0` → HTTP 200 + `-32009`; (f) `GetExtendedAgentCard` with `a2a.read` only (NO `a2a.invoke`) → 200 + synthesized card (proves route-level decorator is gone); (g) `SendMessage` with `a2a.invoke` only → 200 + result; (h) `SendMessage` with `a2a.read` only → 403; (i) public-only token (`token_teams=[]`) for ADMIN user calling private agent → 403 (proves admin bypass suppression at lines 126-130 fires). Evidence: .omo/evidence/task-12-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): A2A 1.0.0 dispatch with method-aware RBAC + verified plumbing

- [ ] 13. Route ordering regression test (Oracle #15)
  What to do: pytest `tests/integration/test_a2a_route_ordering.py`. Assert: (a) `POST /a2a/invoke` still resolves to LEGACY `/invoke` handler (NOT captured by `/{agent_name}`); (b) static suffix routes register BEFORE catch-all `/{agent_name}` in FastAPI route table; (c) `POST /a2a/foo/invoke` does NOT match the catch-all `POST /{agent_name}`. Use `app.routes` introspection. If PR #5313 lands later, extend to assert `/a2a/foo/jsonrpc` also keeps its semantics.
  Must NOT do: do NOT mutate any route registration.
  Parallelization: Wave 3 | Blocked by: T11, T12 | Blocks: T15
  References: Oracle #15.
  Acceptance: pytest passes; introspection confirms order.
  QA: happy=`POST /a2a/invoke` hits legacy. failure=catch-all wins → regression. Evidence: .omo/evidence/task-13-a2a-native-passthrough.txt
  Commit: Y | test(a2a): route-ordering regression for catch-all dispatch

- [ ] 14. SSE response wiring for streaming methods (D10/D15) — single re-wrap, no double-encoding
  What to do: In T12 handler when streaming method detected: `from fastapi.responses import StreamingResponse; gen = dispatch_a2a_jsonrpc_streaming(db, agent, body, bearer_token=bearer_token, hop_count=hop_count, request_headers=request_headers); return StreamingResponse(_sse_format(gen), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})` — `request_headers` matches T5's verified kwarg name (Oracle v4 #4 regression fix). **Helper `_sse_format(gen) -> AsyncIterator[str]`: for each dict yielded by T5, emit EXACTLY `f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"`** — one SSE event per parsed upstream event (Oracle re-review #5 pairing fix: T5 yields parsed dicts, T14 re-wraps as SSE for downstream; the upstream `data:` framing has already been STRIPPED by T5's SSE parser, so T14's re-wrap does NOT double-encode). Use `separators=(',', ':')` compact form to minimize bytes on the wire.
  Must NOT do: do NOT use T4 for streaming methods. Do NOT batch chunks into one envelope. Do NOT add SSE retry headers. Do NOT emit a downstream `data:` prefix if the upstream chunk text already had one — T5's parser has stripped the `data:` framing; the dict yielded is the PARSED JSON object, not the SSE-framed text.
  Parallelization: Wave 3 | Blocked by: T5, T10 | Blocks: T15
  References: D10, D15, F8 SSE shape; Oracle re-review #5 (paired with T5 SSE parser fix).
  Acceptance: pytest streaming integration tests + manual `curl -N` shows multiple `data: {jsonrpc...}\n\n` events EACH parsing as ONE complete JSON-RPC response (no double-encoded `data:` inside the body); cancel test shows upstream connection closes within ~100ms.
  QA: happy=stream emits Task → status_update → final → close with N upstream events == N downstream SSE events. failure=double-encoded `data:` inside body or fewer/more downstream events than upstream → fix T5 or T14. Evidence: .omo/evidence/task-14-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): SSE streaming response wiring (single re-wrap, spec-correct framing)

- [ ] 15. Proxy compliance smoke: verify T9+T10 assertions now GREEN
  What to do: After T11+T12+T13+T14, run `pytest tests/live_gateway/a2a_compliance/ -k 'A2AGatewayProxyTarget' -v` against running gateway with echo agent (docker-compose ports 9100/9101). The gap-closure assertions written in T9+T10 should now PASS. NOTE: harness target class `_open_client` still raises NotImplementedError (T29 fixes that); for this todo, use a temporary smoke script `scripts/qa/a2a_proxy_smoke.py` that opens `ClientFactory(config=...).create_from_url(f"{gw}/a2a/echo")` directly and exercises the gap-closure assertions. Delete the smoke script in T30 once harness is wired.
  Must NOT do: do NOT update harness target classes yet (Wave 7). Do NOT skip on failure — failure means C2 impl bug.
  Parallelization: Wave 3 | Blocked by: T11, T12, T13, T14 | Blocks: T16, T29
  References: T9, T10, T11-T14.
  Acceptance: `python scripts/qa/a2a_proxy_smoke.py` exits 0; every BLOCK-severity gap from T8 audit now PASSES.
  QA: happy=all gap assertions pass. failure=any fails → fix C2/C3 code in Wave 3 BEFORE Wave 4. Evidence: .omo/evidence/task-15-a2a-native-passthrough.txt
  Commit: Y | test(a2a): per-agent compliance smoke verifies Wave 3 implementation

### Wave 4 — Virtual-server-scoped data plane (`/servers/{id}/a2a/{name}/*`)

- [ ] 16. `A2APathRewriteMiddleware` — regex matches base AND suffix forms (Oracle #14 fix)
  What to do: New `mcpgateway/middleware/a2a_path_rewrite.py`. Mirror `MCPPathRewriteMiddleware` shape from `main.py:3000-3041`. Regex: `^/servers/([^/]+)/a2a/([^/]+)(/.*)?$` — captures `server_id`, `agent_name`, optional `suffix`. On match: rewrite `request.scope["path"]` to `/a2a/{agent_name}{suffix or ""}`, inject `request.scope["a2a_server_id"] = server_id`. Preserve `request.scope["modified_path"]` for downstream. Wire into middleware chain at `main.py:3197-3220` mirroring MCP middleware position.
  Must NOT do: do NOT enforce membership in middleware (handler's job per T3+T11+T12 split). Do NOT match outside `/servers/{id}/a2a/...`. Do NOT use a regex that requires a trailing `/*` — Oracle #14 — the BASE dispatch URL `/servers/X/a2a/Y` would otherwise be missed.
  Parallelization: Wave 4 | Blocked by: T3 | Blocks: T17, T18
  References: F2 (`main.py:3000-3041` MCPPathRewriteMiddleware), Oracle #14.
  Acceptance: pytest `tests/middleware/test_a2a_path_rewrite.py` covers (a) `/servers/X/a2a/Y` rewrites + scope set; (b) `/servers/X/a2a/Y/.well-known/agent-card.json` rewrites; (c) `/a2a/Y` untouched; (d) `/servers/X/mcp` untouched.
  QA: happy=both base + suffix URL forms route. failure=base URL misses → regex bug. Evidence: .omo/evidence/task-16-a2a-native-passthrough.txt
  Commit: Y | feat(a2a): v-server path rewrite middleware (base + suffix forms)

- [ ] 17. V-server card route (same handler as T11 via middleware-set scope)
  What to do: T11 handler ALREADY reads `request.scope.get("a2a_server_id")` and passes to `synthesize_agent_card(..., server_id=...)`. So this todo is a verification + integration test, not new code. Add `tests/integration/test_a2a_native_routes.py::test_vserver_card` asserting (a) card URL contains `/servers/{id}/` prefix, (b) membership-miss returns HTTP 404, (c) anonymous request to team-only agent in server returns 404 (visibility hides).
  Must NOT do: do NOT add a duplicate route decorator.
  Parallelization: Wave 4 | Blocked by: T11, T16 | Blocks: T19
  References: T11, T16, D7, D11, D14, F1.
  Acceptance: pytest test_vserver_card passes 3 scenarios.
  QA: happy=v-server card returns with prefixed URL. failure=URL missing prefix → T2 synthesize ignored server_id. Evidence: .omo/evidence/task-17-a2a-native-passthrough.txt
  Commit: Y | test(a2a): v-server card endpoint integration

- [ ] 18. V-server dispatch route (same handler as T12 via middleware-set scope)
  What to do: T12 handler ALREADY reads server_id from scope. Verification + integration test. Add `tests/integration/test_a2a_native_routes.py::test_vserver_dispatch` covering (a) happy SendMessage via v-server URL, (b) agent-not-in-server returns HTTP 404 (D14 — path resource doesn't exist), (c) streaming `SendStreamingMessage` via v-server URL still SSEs, (d) GetExtendedAgentCard via v-server URL respects `a2a.read`.
  Must NOT do: do NOT introduce a separate v-server handler.
  Parallelization: Wave 4 | Blocked by: T12, T14, T16 | Blocks: T19
  References: T12, T14, T16, D14, D18.
  Acceptance: pytest test_vserver_dispatch passes 4 scenarios.
  QA: happy=v-server dispatch round-trips through both URL families identically. failure=membership-miss → wrong code → D14 not enforced. Evidence: .omo/evidence/task-18-a2a-native-passthrough.txt
  Commit: Y | test(a2a): v-server dispatch endpoint integration

- [ ] 19. V-server composition integration test + compliance smoke (IDs not names — Momus v3 #3)
  What to do: pytest `tests/integration/test_a2a_vserver_composition.py`. Fixture flow (VERIFIED against `server_service.py:210-241` which queries `at.model.id.in_(ids)`):
  ```python
  # register two echo agents, capture their IDs
  resp1 = client.post("/a2a", json={"name": "echo", "endpoint_url": "http://127.0.0.1:9100", ...})
  agent1_id = resp1.json()["id"]  # UUID
  resp2 = client.post("/a2a", json={"name": "echo2", "endpoint_url": "http://127.0.0.1:9101", ...})
  agent2_id = resp2.json()["id"]  # UUID
  # create Server with the IDs (NOT names)
  server_resp = client.post("/servers", json={"server": {"name": "echo_bundle", "associated_a2a_agents": [agent1_id, agent2_id], ...}})
  server_id = server_resp.json()["id"]
  ```
  Then exercise: (a) `GET /a2a/echo/.well-known/agent-card.json` works (per-agent URL uses NAME); (b) `GET /servers/{server_id}/a2a/echo/.well-known/agent-card.json` works (v-server URL also uses NAME in path); (c) `POST /servers/{server_id}/a2a/echo` dispatches; (d) `POST /servers/{server_id}/a2a/foreign-agent` (an agent NOT in `associated_a2a_agents`) returns HTTP 404 per D14. Plus `scripts/qa/a2a_vserver_smoke.py` driving `ClientFactory.create_from_url(f"{gw}/servers/{server_id}/a2a/echo")` and exercising T9+T10 gap-closure assertions against gateway_virtual target.
  Must NOT do: do NOT mock upstream. Do NOT pass agent NAMES into `associated_a2a_agents` (Momus v3 #3: verified service-layer queries by ID — would 404 at create time with "A2A agent with id 'echo' does not exist"). Do NOT update harness target classes yet (T29 in Wave 7).
  Parallelization: Wave 4 | Blocked by: T17, T18 | Blocks: T22, T29
  References: T9, T10, T17, T18; verified `mcpgateway/services/server_service.py:210-241` (IDs); `docker-compose.yml` echo agents at ports 9100 + 9101.
  Acceptance: pytest + smoke script exit 0; all v-server gap-closure assertions GREEN; `server_service.py` does NOT raise `ServerError("A2A agent with id 'echo' does not exist")`.
  QA: happy=both URL families work; v-server membership hides foreign agents. failure 1=any compliance assertion fails → fix Wave 3/4 code. failure 2=`ServerError` at fixture-setup → using names instead of IDs. Evidence: .omo/evidence/task-19-a2a-native-passthrough.txt
  Commit: Y | test(a2a): v-server composition (IDs in association, names in URL path)

### Wave 5 — Server CRUD service + Admin UI verify/patch (NEW — addresses user goals #1+#2)

- [ ] 20. Verify/patch `ServerService` populates `server_a2a_association` from `associated_a2a_agents` (F10)
  What to do: Read `mcpgateway/services/server_service.py::create_server` and `update_server`. Trace whether `schemas.ServerCreate.associated_a2a_agents` (F10 verified: schemas.py:4264 declares it) actually propagates to rows in `server_a2a_association`. If wired: write regression test `tests/unit/mcpgateway/services/test_server_service.py::test_a2a_association_roundtrip` covering create → DB → read shows the binding. If NOT wired: add the missing service-layer code (mirror the `associated_tools` pattern that DOES work) + write the test.
  Must NOT do: do NOT change the schema (F10 confirms it's already correct). Do NOT skip the test even if wired — regression coverage is the deliverable.
  Parallelization: Wave 5 | Blocked by: none | Blocks: T22
  References: F10 (schemas:4261-4264, 4429-4432, 4531-4535); F1 (`db.py:2490-2495` association); existing `associated_tools` wiring pattern in `server_service.py`.
  Acceptance: pytest test_a2a_association_roundtrip passes; `db.session.query(server_a2a_association).filter_by(server_id=X).count() == len(associated_a2a_agents_passed)`.
  QA: happy=create server with `associated_a2a_agents=["a1","a2"]` → both rows in DB. failure=count mismatch → wiring missing/broken. Evidence: .omo/evidence/task-20-a2a-native-passthrough.txt
  Commit: Y | feat(servers)/test(servers): verify/wire A2A agent association on server CRUD

- [ ] 21. Admin UI: server-form A2A selector + JS submit-handler wiring + card-URL affordance (Oracle re-review #10)
  What to do: **Full UI binding flow**, NOT just template inclusion (Oracle re-review #10: rendering the selector ≠ actually submitting selected agents). Three parts:

  (a) **Template**: in `mcpgateway/templates/admin.html`, locate server-create and server-edit form sections. If `agents_selector_items.html` (F11 confirmed exists) is NOT already `{% include %}`-d for A2A binding, add it mirroring the existing `associatedTools` / `associatedResources` selector pattern. Match the input `name="associatedA2aAgents"` (camelCase to match the existing convention for other selectors in the form).

  (b) **JS submit handler**: in `mcpgateway/admin_ui/formSubmitHandlers.js` (verified at lines 399-425 for `associatedTools` + `associatedResources` patterns), add an analogous block:
  ```javascript
  const a2aContainer = document.getElementById("associatedA2aAgents");
  if (a2aContainer) {
    const a2aSel = getEditSelections("associatedA2aAgents");
    const checked = Array.from(
      document.querySelectorAll('input[name="associatedA2aAgents"]:checked'),
    ).map((el) => el.value);
    const combined = Array.from(new Set([...a2aSel, ...checked]));
    formData.delete("associatedA2aAgents");
    combined.forEach((id) => formData.append("associatedA2aAgents", id));
  }
  ```
  This mirrors the tools/resources pattern EXACTLY, including dedup via Set, merging edit-mode selections with checked inputs. Edit-modal prepopulation: in `mcpgateway/admin_ui/a2aAgents.js` (already exists) or `admin.js`, ensure server-edit modal populates the selector from `server.associated_a2a_agents` field returned by `GET /servers/{id}`. Rebuild the UI bundle via `npm run build-ui` (or `make build-ui`).

  (c) **Card-URL ops affordance**: in agent detail view (in `a2aAgents.js` or appropriate template), add a "Card endpoint URL" display showing `{public_base}/a2a/{name}/.well-known/agent-card.json` with a `<button onclick="navigator.clipboard.writeText(...)">Copy</button>` affordance.

  Must NOT do: do NOT redesign existing form layout. Do NOT skip the JS submit handler (Oracle re-review #10 — that was the root cause of the UI gap). Do NOT introduce a different camelCase convention — match `associatedTools` / `associatedResources` so the backend `associated_a2a_agents` payload mapping (snake_case Python ↔ camelCase form data) keeps working via existing FastAPI body-form conversion.
  Parallelization: Wave 5 | Blocked by: none | Blocks: T22
  References: F11 (templates exist); Oracle re-review #10; `mcpgateway/admin_ui/formSubmitHandlers.js:399-425` (verified pattern to mirror); `mcpgateway/admin_ui/a2aAgents.js` (exists with editA2AAgent/testA2AAgent); existing tool/resource selector logic in `admin.html`.
  Acceptance:
  - Manual: server-edit form shows an A2A agent multi-select alongside tools/resources/prompts; selecting agents and saving the form persists them to `server.associated_a2a_agents` in the API response.
  - Manual: agent detail view shows the rewritten card URL + working copy button.
  - Test: `pytest tests/integration/test_admin_server_a2a_flow.py::test_form_submits_a2a_agents` simulates form POST with `associatedA2aAgents=["a1","a2"]` and asserts the resulting server row has both IDs in `server_a2a_association` (overlap with T22 integration test — explicit form-data submission, not bare JSON API).
  QA: happy=full UI flow round-trips A2A agent IDs. failure=selector renders but server has empty `associated_a2a_agents` after save → JS submit handler missing or template input name mismatch. Evidence: .omo/evidence/task-21-a2a-native-passthrough.txt
  Commit: Y | feat(admin-ui): server-form A2A selector + JS submit handler + card-URL affordance

- [ ] 22. Integration test: server-create-with-A2A-agents end-to-end through admin API
  What to do: pytest `tests/integration/test_admin_server_a2a_flow.py`: POST to `/admin/servers` (or equivalent admin endpoint) with body containing `associated_a2a_agents=["agent-1", "agent-2"]`; assert HTTP 201; assert `GET /servers/{id}` returns both in `associated_a2a_agents`; assert `GET /servers/{id}/a2a/agent-1/.well-known/agent-card.json` returns the v-server-scoped card; assert `GET /servers/{id}/a2a/foreign-agent/.well-known/agent-card.json` returns 404 (foreign agent NOT in server).
  Must NOT do: do NOT mock the admin service.
  Parallelization: Wave 5 | Blocked by: T19, T20, T21 | Blocks: T28
  References: T19, T20, T21; F10.
  Acceptance: pytest passes 4 assertions.
  QA: happy=server-with-A2A-agents goes through API and exercises v-server URLs. failure=any assertion fails → fix upstream code. Evidence: .omo/evidence/task-22-a2a-native-passthrough.txt
  Commit: Y | test(integration): admin server-with-A2A-agents end-to-end

### Wave 6 — Rust A2A runtime deprecation (depends on Wave 3: Python target must exist)

- [ ] 23. Startup deprecation warning when `EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED=true` (D16 / Oracle #19)
  What to do: In `mcpgateway/main.py` startup hook (or wherever startup-time settings are validated), if `settings.experimental_rust_a2a_runtime_enabled is True`, emit `logger.warning("EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED=true is DEPRECATED. The Rust A2A runtime is removed in the next release; Python dispatcher is the only path. This flag is now ignored.")`. Add pytest deprecation-warning test that sets the env var and asserts the warning is logged at startup.
  Must NOT do: do NOT delete the flag yet (T26). Do NOT suppress the warning behind a separate flag.
  Parallelization: Wave 6 | Blocked by: T15 | Blocks: T24, T25, T26
  References: D16, Oracle #19; `mcpgateway/main.py` startup hooks.
  Acceptance: pytest deprecation warning test passes; manual: set env var, restart gateway, observe warning in logs.
  QA: happy=flag set → warning. failure=warning missing → fix logger call. Evidence: .omo/evidence/task-23-a2a-native-passthrough.txt
  Commit: Y | refactor(a2a): deprecation warning for experimental Rust A2A runtime flag

- [ ] 24. Remove `crates/a2a_runtime/` from Cargo workspace `default-members` (F13 / D16) — using verified crate name
  What to do: Edit root `Cargo.toml`. In `default-members`, replace the `crates/*` glob with an explicit list that EXCLUDES `crates/a2a_runtime`. Keep `crates/a2a_runtime` in `members` for the transition release (Scope OUT: removing from members is a follow-up release). Add a comment in `Cargo.toml` explaining the policy and pointing at this todo: `# default-members intentionally excludes crates/a2a_runtime (contextforge_a2a_runtime) which is deprecated. See plans/a2a-native-passthrough.md T24.` (Oracle re-review #17 — comment requirement). Note the actual crate package name is `contextforge_a2a_runtime` (verified from `crates/a2a_runtime/Cargo.toml:package.name`).
  Must NOT do: do NOT remove from `members`. Do NOT use the wrong package name in verification commands (Momus #3 — `a2a_runtime` is the DIRECTORY; `contextforge_a2a_runtime` is the package NAME).
  Parallelization: Wave 6 | Blocked by: T23 | Blocks: T26
  References: F13, D16; `Cargo.toml:5-14` (current workspace config); `crates/a2a_runtime/Cargo.toml` (verified `name = "contextforge_a2a_runtime"`); Momus re-review #3 + Oracle re-review #17.
  Acceptance:
  - `cargo check --workspace` passes (validates all members including a2a_runtime still compile).
  - `cargo build` (NO `--workspace` flag, NO `--package` flag — pure default-members build) does NOT compile `contextforge_a2a_runtime`. Verify via `cargo build 2>&1 | rg -c contextforge_a2a_runtime` returning `0`.
  - `rg "contextforge_a2a_runtime" Cargo.toml` shows the package name in the policy comment but NOT in the default-members list itself.
  QA: happy=default build skips contextforge_a2a_runtime. failure=`cargo check --workspace` fails → fix Cargo.toml syntax; failure=`cargo build` still compiles contextforge_a2a_runtime → check default-members glob/list was actually replaced. Evidence: .omo/evidence/task-24-a2a-native-passthrough.txt
  Commit: Y | refactor(a2a): exclude contextforge_a2a_runtime from Cargo default-members

- [ ] 25. Remove `rust_a2a_runtime` branches in `tool_service.py` + `a2a_service.py`
  What to do: Per F7 caller inventory: in `mcpgateway/services/tool_service.py` delete import at line 89, remove `if settings.experimental_rust_a2a_runtime_enabled:` branches around lines 5873 + 7130, delete `except RustA2ARuntimeError as e:` at 5910. In `mcpgateway/services/a2a_service.py` delete import at line 45, remove `if settings.experimental_rust_a2a_runtime_enabled:` branch around 2306, remove delegate-mode branch 2395-2436 and its `except RustA2ARuntimeError` handler. Delete `_should_delegate_a2a_to_rust()` if unused elsewhere. Python dispatcher (T4+T5) becomes unconditional.
  Must NOT do: do NOT change `invoke_agent()` public signature. Do NOT alter per-agent auth handling (D5). Do NOT touch `/invoke` route semantics.
  Parallelization: Wave 6 | Blocked by: T23 | Blocks: T26
  References: F7; D5.
  Acceptance: `rg "rust_a2a_runtime" mcpgateway/services/{tool_service,a2a_service}.py` returns 0 lines; `pytest tests/unit/mcpgateway/services/test_{tool_service,a2a_service}.py -v` green.
  QA: happy=service tests + /invoke smoke unchanged. failure=behavior change → revert + investigate. Evidence: .omo/evidence/task-25-a2a-native-passthrough.txt
  Commit: Y | refactor(a2a): drop Rust runtime branches from tool_service + a2a_service

- [ ] 26. Mark `rust_a2a_runtime.py` + config + reporting as DEPRECATED (NO physical deletion — Oracle re-review #8 split)
  What to do: This todo finalizes deprecation marking WITHOUT physically deleting code/config — physical deletion moves to a follow-up release after this plan's warning cycle ships (Oracle re-review #8: T23 warning + T25/T26 same-release deletion would mean users never see a warned version).
  - In `mcpgateway/services/rust_a2a_runtime.py`: add module-level docstring `"""DEPRECATED in release N. Removal scheduled for release N+1. Migrated to Python dispatcher in mcpgateway/services/a2a_service.py. See plans/a2a-native-passthrough.md."""` and emit `warnings.warn("rust_a2a_runtime module is deprecated; use Python dispatcher", DeprecationWarning, stacklevel=2)` at module import time.
  - In `mcpgateway/config.py:331-351`: keep the 6 fields BUT add a `# DEPRECATED: removed in release N+1 (see plans/a2a-native-passthrough.md)` comment per field. They remain settable so callers with the env var don't crash; T23 startup warning surfaces the deprecation; T25 already made Python the only execution path.
  - In `mcpgateway/version.py:140-567`: change the `_rust_a2a_runtime_managed()` body to ALWAYS return False (Python is the only path now); leave the symbol so external `/version` consumers don't break; add a `# DEPRECATED` comment with removal release tag.
  - In `mcpgateway/routers/runtime_admin_router.py:92`: leave the toggle line BUT add a 410-Gone-style response for any POST that tries to enable a2a Rust runtime (cannot enable a path that is no longer wired). MCP side untouched.
  - Update `.env.example`: prefix the `EXPERIMENTAL_RUST_A2A_RUNTIME_*` lines with `# DEPRECATED — removed in release N+1`. Don't delete them.
  - Add follow-up scope notes to `docs/docs/architecture/a2a-native.md` (T31): "Release N+1 removes `rust_a2a_runtime.py`, the 6 config fields, the version reporting helper, the admin toggle, and tests asserting them." Create a tracking issue or todo entry in `.omo/followups/` if that convention exists.
  Must NOT do: do NOT physically delete `rust_a2a_runtime.py` in THIS release (Oracle re-review #8 — would skip the warning cycle). Do NOT remove config fields from `config.py`. Do NOT remove `_rust_a2a_runtime_managed` symbol. Do NOT touch MCP runtime code in `version.py`.
  Parallelization: Wave 6 | Blocked by: T24, T25 | Blocks: T27
  References: F7 (config + version inventory); F13; D16 (refined with split); Oracle re-review #8 (split deprecation cycle).
  Acceptance:
  - `python -c "import mcpgateway.services.rust_a2a_runtime"` emits DeprecationWarning (verified via `pytest -W error::DeprecationWarning ...` on a marker test).
  - `rg "DEPRECATED" mcpgateway/config.py mcpgateway/version.py mcpgateway/services/rust_a2a_runtime.py .env.example` shows deprecation markers added.
  - `rg "rust_a2a_runtime|experimental_rust_a2a_runtime" mcpgateway/services/{tool_service,a2a_service}.py` returns 0 lines (T25 already removed call-sites).
  - `make test` green; existing tests still pass.
  QA: happy=import emits DeprecationWarning; config field still settable but no longer affects dispatch. failure=physical deletion happened → undo, follow split. Evidence: .omo/evidence/task-26-a2a-native-passthrough.txt
  Commit: Y | refactor(a2a): mark Rust runtime module/config/reporting deprecated (deletion in N+1)

- [ ] 27. Rust deprecation full-system smoke — using verified crate name + correct flags
  What to do: After T23-T26 all land, run and capture:
  1. `make lint` — exits 0.
  2. `make test` — exits 0 with no new regressions; existing tests asserting the flag setting still pass (since fields remain per T26 split).
  3. `make test-protocol-compliance-a2a-gateway` — exits 0 (live harness against running gateway).
  4. `cargo check --workspace` — exits 0 (validates all members including `contextforge_a2a_runtime` still compile in members list).
  5. **Structural default-members verification** (v4 MEDIUM #4 / v5 MEDIUM fix — grep on `cargo build --verbose` can false-pass when cargo prints `Fresh` instead of `Compiling` from cache): `cargo metadata --format-version=1 --no-deps | jq -r '.workspace_default_members[]' | rg -v contextforge_a2a_runtime | wc -l` returns the number of crates remaining in default-members AND `cargo metadata --format-version=1 --no-deps | jq -r '.workspace_default_members[]' | rg -c contextforge_a2a_runtime` returns `0`. This inspects the resolved workspace metadata directly, immune to cache state.
  6. `cargo test --workspace --exclude contextforge_a2a_runtime` — exits 0 (uses verified crate package name from Momus re-review #3, NOT directory name `a2a_runtime`).
  7. New test: `pytest tests/unit/mcpgateway/services/test_rust_a2a_runtime_deprecation.py` asserting `import mcpgateway.services.rust_a2a_runtime` emits `DeprecationWarning` at module-load time.
  Must NOT do: do NOT use `--exclude a2a_runtime` (wrong name — directory not package, Momus #3). Do NOT skip the deprecation-warning test (proves T23+T26 deprecation cycle is real).
  Parallelization: Wave 6 | Blocked by: T26 | Blocks: T28 (Wave 2 prerequisite already landed before this)
  References: T23-T26; Momus re-review #3 (crate package name `contextforge_a2a_runtime`).
  Acceptance: all 7 commands/tests exit 0; capture output to `.omo/evidence/task-27-a2a-native-passthrough.txt`.
  QA: happy=full-system green AND deprecation warning fires on import. failure=any command fails → investigate before moving on. Evidence: .omo/evidence/task-27-a2a-native-passthrough.txt
  Commit: Y | test(a2a): full-system smoke after Rust deprecation (verified crate name)

### Wave 7 — Compliance harness completion

- [ ] 28. Wire real fixtures into compliance-harness `conftest.py` — **SPLIT into Wave-2 minimal vs Wave-7 server-creation** (v3 HIGH #6)

  **Split rationale** (Oracle v3 #6 fix): the previous "T28 executes first in Wave 2" was internally inconsistent because T28 also created a server using `associated_a2a_agents` which depends on T20's service-layer verification. Resolution: split T28 into two operationally-distinct pieces, both still tracked under todo #28 to preserve numbering:

  **Part A (Wave 2 prerequisite — runs BEFORE T8)**: wire the minimal fixtures needed for Wave 2 gap-closure tests to RUN against gateway targets:
  - `gateway_base_url` — read `A2A_COMPLIANCE_GATEWAY_URL` env, default `http://localhost:4444`.
  - `auth_token` — generated via the verified helper `tests.helpers.auth.make_test_jwt(...)` (per `tests/AGENTS.md`) with admin claims signed by `JWT_SECRET_KEY` from env. NOT `mcpgateway.utils.create_jwt_token.create_jwt_token` — that was an invention; the real test helper is `tests/helpers/auth.py:make_test_jwt`.
  - `registered_agent_id` — register echo via `POST /a2a` admin API in session-scoped setup, capture the returned `id` (a UUID). **IDs, not names** (Momus v3 #3 + verified `server_service.py:226` which queries `at.model.id.in_(ids)`).
  - `registered_agent_name` — `echo` (used only in URL path construction, NOT in association lists).
  - `raw_card_url` and `raw_dispatch_url` target-aware fixture pair so Wave 2 gap-closure tests in T9/T10 can parameterize over `target ∈ {reference, gateway_proxy}` (NOT `gateway_virtual` yet — that needs Part B's server). Tests should `xfail_on(request, "gateway_proxy", reason="A2A-GAP-001-PRE-IMPL")` until Wave 3 lands, so the assertions COLLECT and FAIL-CLEANLY against gateway_proxy.

  **Part B (Wave 7 — runs as part of harness completion AFTER T20 verifies server CRUD wiring)**: extend the fixtures with `server_id`:
  - Create a Server via `POST /servers` with `associated_a2a_agents=[registered_agent_id]` (IDs, plural-form list of UUIDs from Part A — verified pattern from `server_service.py:210-241`). Return the created server's `id`.
  - Update `raw_card_url` and `raw_dispatch_url` to also parameterize over `gateway_virtual`.
  - Add a sanity test at `tests/live_gateway/a2a_compliance/test_fixture_sanity.py` (NEW FILE — Oracle v3 #11 fix: `conftest.py` is for fixtures/hooks, test functions there are not collected as tests) that exercises all fixtures and asserts they resolve to real values, hits `GET /version` with auth, validates `server_id` is a UUID.

  Must NOT do: do NOT hardcode tokens. Do NOT pass agent NAMES into `associated_a2a_agents` (Momus v3 #3 — verified service-layer queries by ID at `server_service.py:226`). Do NOT put the sanity test in `conftest.py` (won't be collected). Do NOT modify the test matrix layout. Do NOT use `--collect-only` for acceptance (does NOT exercise fixtures, Oracle v2 #9). Do NOT call `mcpgateway.utils.create_jwt_token.create_jwt_token(--admin=True, teams=None)` — the `--admin` and `teams=None` are CLI flags; in test code, use `tests/helpers/auth.py:make_test_jwt` which takes Python args.
  Parallelization: Part A in Wave 2 (executes BEFORE T8) | Blocked by: none for Part A; T20+T22 for Part B | Blocks: T9, T10, T15 (Part A); T29, T30 (Part B)
  References: Oracle v3 #6, #11; Momus v3 #3 (IDs not names); verified `tests/helpers/auth.py:make_test_jwt` (per tests/AGENTS.md); verified `mcpgateway/services/server_service.py:210-241` (associate by IDs); verified `mcpgateway/services/permission_service.py:70-82` for token shape; `tests/live_gateway/a2a_compliance/conftest.py` (current placeholders).
  Acceptance:
  - Part A acceptance: `pytest tests/live_gateway/a2a_compliance/v1_0_0/test_agent_card.py -k gateway_proxy -v` shows COLLECTED tests with xfail_on markers using the existing `_CASES` parametrize matrix (Momus v4 #2 + Oracle v4 #5: the harness does NOT define a `--target` CLI option; target selection happens via fixture IDs filtered with `-k`). Tests use the raw URL fixtures, not `_open_client` (which still raises until T29).
  - Part B acceptance: `pytest tests/live_gateway/a2a_compliance/test_fixture_sanity.py -v` passes — proves `server_id` is UUID, auth token works, gateway agent registered.
  QA:
  - Part A happy: Wave 2 gap-closure tests collect + fail against gateway_proxy (proving P5 ordering). Part A failure: tests collect but DON'T fail against gateway_proxy → gap-closure assertions are bad.
  - Part B happy: full fixture sanity test passes. Failure: server creation fails → check IDs vs names in association list.
  Evidence: `.omo/evidence/task-28-a-a2a-native-passthrough.txt` (Part A), `.omo/evidence/task-28-b-a2a-native-passthrough.txt` (Part B).
  Commit: Y (TWO commits): `test(a2a-compliance): Part A minimal fixtures for Wave 2 gap closure` + `test(a2a-compliance): Part B server fixture + sanity test for Wave 7`

- [ ] 29. Update both target classes' `_open_client` — `@asynccontextmanager` shape with VERIFIED attribute names (v3 HIGH #7)
  What to do: In `tests/live_gateway/a2a_compliance/targets/gateway_proxy.py::_open_client` (VERIFIED current attributes at `gateway_proxy.py:44-47` are `self._base_url`, `self._auth_token`, `self._agent_name` — Oracle v3 #7 caught the previous plan's nonexistent `self.gateway_base_url` etc):
  ```python
  from contextlib import asynccontextmanager
  import httpx
  from a2a.client.client import Client, ClientConfig
  from a2a.client.client_factory import ClientFactory

  @asynccontextmanager
  async def _open_client(self, transport: Transport, **client_kwargs: object) -> AsyncIterator[Client]:
      async with httpx.AsyncClient(
          base_url=self._base_url,
          headers={"Authorization": f"Bearer {self._auth_token}"},
      ) as httpx_client:
          config = ClientConfig(httpx_client=httpx_client)
          factory = ClientFactory(config=config)
          client = await factory.create_from_url(f"{self._base_url}/a2a/{self._agent_name}")
          async with client as connected:
              yield connected
  ```
  Mirrors `targets/reference.py:58-64` EXACTLY. Same shape in `targets/gateway_virtual.py::_open_client` — VERIFY the v-server target's constructor at `gateway_virtual.py:__init__` to confirm its server_id attribute name (likely `self._server_id` matching the convention) before writing the code; URL becomes `f"{self._base_url}/servers/{self._server_id}/a2a/{self._agent_name}"`.
  Must NOT do: do NOT use bare `return await ...`. Do NOT skip the `async with client as connected` block. Do NOT change target-class CONSTRUCTOR signatures (A9). Do NOT verify acceptance with `--collect-only` (does NOT exercise the asynccontextmanager).
  Parallelization: Wave 7 | Blocked by: T28, T15, T19 | Blocks: T30
  References: T28; Oracle re-review #9 (asynccontextmanager + yield-inside pattern); `tests/live_gateway/a2a_compliance/targets/reference.py:58-64` (verified canonical shape); `tests/live_gateway/a2a_compliance/targets/gateway_proxy.py`; `tests/live_gateway/a2a_compliance/targets/gateway_virtual.py`.
  Acceptance: `pytest tests/live_gateway/a2a_compliance/ -k 'A2AGatewayProxyTarget or A2AGatewayVirtualServerTarget' -v` — **runs actual tests** (NOT `--collect-only`), exercises `_open_client`, raises 0 `NotImplementedError`s, conformance assertions PASS against running gateway with echo agent.
  QA: happy=both targets execute the asynccontextmanager and successfully exchange JSON-RPC with the gateway. failure=NotImplementedError → wrong line edited; missing yield → asynccontextmanager raises. Evidence: .omo/evidence/task-29-a2a-native-passthrough.txt
  Commit: Y | test(a2a-compliance): target classes use asynccontextmanager + ClientConfig

- [ ] 30. Delete GAP-001 xfail hook + close in `COMPLIANCE_GAPS.md`
  What to do: Delete the `pytest_collection_modifyitems` hook in `tests/live_gateway/a2a_compliance/conftest.py` that blanket-x-fails gateway-target cells under GAP-001. Edit `tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md`: mark GAP-001 as **CLOSED** with a one-line reference to the closing commit. The 28 previously-x-failed cells (14 gateway × 2 protocol-version columns) become live conformance assertions. ALSO: delete the temporary `scripts/qa/a2a_proxy_smoke.py` and `scripts/qa/a2a_vserver_smoke.py` created in T15 and T19 — the harness is now the canonical verification surface (Oracle #24 — prefer pytest over ad-hoc scripts).
  Must NOT do: do NOT delete any OTHER xfail hooks. Do NOT remove the GAP-001 entry from `COMPLIANCE_GAPS.md` — mark it CLOSED for the audit trail.
  Parallelization: Wave 7 | Blocked by: T29 | Blocks: T31
  References: `tests/live_gateway/a2a_compliance/conftest.py` (GAP-001 hook); `tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md` (gap inventory); Oracle #24 (smoke scripts cleanup).
  Acceptance: `pytest tests/live_gateway/a2a_compliance/ -v` reports 0 xfails for GAP-001; all 28 previously-x-failed cells PASS; `grep -A2 "GAP-001" COMPLIANCE_GAPS.md` shows CLOSED; `ls scripts/qa/a2a_*` returns nothing.
  QA: happy=harness fully green for gateway targets. failure=any cell still fails → real gateway bug surfaced — fix upstream Wave 3/4 code BEFORE merging this todo. Evidence: .omo/evidence/task-30-a2a-native-passthrough.txt
  Commit: Y | test(a2a-compliance): close A2A-GAP-001 — gateway compliance assertions live

### Wave 8 — Documentation

- [ ] 31. A2A 1.0.0 wire-conformance + migration documentation
  What to do: Create `docs/docs/architecture/a2a-native.md` covering: (a) route inventory (per-agent `/a2a/{name}/.well-known/agent-card.json` + `POST /a2a/{name}`, v-server variants `/servers/{id}/a2a/{name}/...`); (b) control-plane / data-plane split with the interaction contract (P1); (c) AuthN/AuthZ posture (P3) — `Depends(get_current_user_with_permissions)` + `@require_permission(...)` + visibility derivation via `get_rpc_filter_context`; (d) card synthesis + URL rewrite + `protocolBinding`/`protocolVersion` field-name gotchas (D8/D9); (e) JSON-RPC error model with full code table — standard `-32700..-32603` + A2A-specific `-32001..-32009` (D6); (f) `A2A-Version` negotiation (D13); (g) v0.3 method-alias support timeline — accepted during transition with documented end-of-support policy (Q12 default + Oracle #26); (h) Rust A2A runtime retirement history; (i) migration guide for callers moving from `/a2a/{name}/invoke` (legacy) to native `POST /a2a/{name}`. Cross-link from `docs/docs/manage/` index. Add the legacy-alias deprecation warning header / log behavior to the "Future work" section (Oracle #26 fix).
  Must NOT do: do NOT document gRPC or HTTP+JSON bindings (Q13 default — JSONRPC-only for phase 1). Do NOT document push-notification methods as gateway features beyond spec pass-through.
  Parallelization: Wave 8 | Blocked by: T30 | Blocks: none
  References: docs/AGENTS.md; the draft at `.omo/drafts/a2a-native-passthrough.md` for technical content; F8 wire details; D6-D19 decisions; Oracle #26.
  Acceptance: `mkdocs build` runs clean from repo root with `docs/docs/architecture/a2a-native.md` present; a future contributor can implement an A2A client against the gateway using only this doc + the A2A spec.
  QA: happy=mkdocs build no warnings; doc readable end-to-end. failure=warnings on cross-links → fix until clean. Evidence: .omo/evidence/task-31-a2a-native-passthrough.txt
  Commit: Y | docs(a2a): native A2A 1.0.0 passthrough + migration + deprecation policy

## Session amendments (post-Wave 1 execution, ratified via Metis + Momus reviews)

> These amendments document architectural decisions that arose DURING execution of the canonical waves above and were promoted to plan-level after Metis (architectural review) and Momus (plan critique) passes converged on the same fault lines. Each amendment is written with the same shape as the canonical task entries (What to do, Must NOT do, Acceptance, References, Status, Commit) so it can be audited as a first-class plan item rather than as an ad-hoc patch in commit messages. They DO NOT replace the canonical tasks T1-T31; they extend the contract for items that were under-specified or out-of-scope when the plan was first drafted.

### Amendment A — Centralized A2A access-decision policy module

  What was done: Created `mcpgateway/services/a2a_access_policy.py` exposing three async module-level functions that hold ALL visibility and authorization decisions for A2A agents:

    - `can_view_a2a_agent_directly(...)` — single-level: agent visibility primitive only. Used by the per-agent `/a2a/{name}` URL family.
    - `can_view_a2a_agent_in_server_context(...)` — three-level conjunctive (see Amendment B). Used by the v-server-scoped `/servers/{id}/a2a/{name}` URL family.
    - `can_associate_a2a_agent_with_server(...)` — CRUD authorization. Used by `ServerService.register_server` / `update_server` to gate the creation of `server_a2a_association` rows.

  Each function takes the existing primitives' instance (`A2AAgentService`) as a delegation-shim parameter so the existing `_check_agent_access` and `check_server_a2a_membership` methods can be called without circular imports.

  Must NOT do: do NOT inline visibility logic in any new A2A code path. All decisions go through the policy module. Do NOT call the underlying primitives directly from outside the policy module; the policy functions are the single source of truth.

  Acceptance: `pytest tests/unit/mcpgateway/services/test_a2a_access_policy.py` passes 11 tests pinning the three functions' contracts (TestCanViewAgentDirectly + TestCanViewAgentInServerContext + TestCanAssociateAgentWithServer). The refactored Wave 1 `synthesize_agent_card` and `resolve_agent_for_dispatch` in `a2a_service.py` delegate to the policy functions; the inline visibility logic is gone.

  References: Metis review (background task `bg_84ec601d`); Momus critique (background task `bg_ab1b9fd3`); D11; D14; F1; F5.

  Status: DONE.

  Commit: ef3edb6b0 | feat(a2a): centralized A2A access-decision policy module (Phase A)

### Amendment B — Three-level conjunctive access in v-server context (clarifies D11)

  What was done: Codified the v-server visibility contract as a THREE-level conjunctive check inside `can_view_a2a_agent_in_server_context`:

    1. **Server-level visibility** — caller can see the virtual server itself (sync, no DB).
    2. **Agent-in-server membership** — the binding has been explicitly configured on this server via `server_a2a_association` (single SELECT).
    3. **Agent-level visibility** — caller can see the agent itself; its Layer-1 scope still applies in v-server context (async, may query team membership).

  ALL three checks must pass; NONE substitute for the others. Server membership does NOT bypass agent visibility, agent visibility does NOT bypass server visibility, and public visibility on either side does NOT bypass the binding check. All denial paths return the same `False`; the route layer collapses to HTTP 404 per D14 so the caller cannot distinguish WHICH layer denied.

  This amendment SUPERSEDES an in-session interpretation where server membership was to be the source of truth and agent visibility was to be bypassed in v-server context. That interpretation conflicted with the user-stated requirement ("Visibility of an agent in a virtual server is two-level: does the user have access to the virtual server? Do they access to the agent? Finally, do they have access to the agent-server combination?") and was reversed before any code shipped under it.

  Check ordering is CHEAPEST-FIRST for performance and DB-work reduction, NOT for constant-time evaluation. Denials at the three layers are distinguishable by latency in milliseconds (sync < SELECT < team-query SELECT). Deployments with a stronger threat model can run all three unconditionally and combine the booleans — the policy function is the single edit point.

  Must NOT do: do NOT bypass any of the three checks via per-deployment configuration in the policy module; threat-model-driven changes should be a forked policy module.

  Acceptance: `pytest tests/unit/mcpgateway/services/test_a2a_access_policy.py::TestCanViewAgentInServerContext` passes 5 tests pinning the conjunctive contract: all-three-pass returns True; each individual denial short-circuits subsequent checks; all three denial paths collapse to the same False (no leak about which layer denied).

  References: User architectural clarification this session (two-tier statement); Metis H3; D11 (extended); D14.

  Status: DONE.

  Commit: ef3edb6b0 (initial) + bd551b215 (timing-side-channel docstring honesty fix).

### Amendment C — CallerContext sentinel for CRUD authorization (closes Momus Block 2)

  What was done: Created `mcpgateway/services/caller_context.py` exposing a frozen `CallerContext` dataclass with two factory methods:

    - `CallerContext.system()` — explicit opt-in bypass for internal pathways (bootstrap, seed, import after admin-only verification, tests that opt out).
    - `CallerContext.for_user(user_email, token_teams)` — real authenticated caller from a route handler.

  The `CallerContext.is_system` attribute is the ONLY condition that bypasses the CRUD authorization check in `_authorize_a2a_associations`. The pre-amendment pattern (`caller_user_email is None AND caller_token_teams is None` → system context) was magic-by-omission: any caller that forgot to thread auth context would silently hit the bypass. Momus correctly flagged this as a CRITICAL under-specification. `CallerContext.for_user(None, [])` — an anonymous public-only caller — is NOT a system context; the policy check runs and denies non-public access correctly.

  Refactored signatures: `ServerService.register_server`, `ServerService.update_server`, `_authorize_a2a_associations`, `_associate_server_entities`, `_update_server_associations` all take `caller_context: Optional[CallerContext]` instead of the prior `(caller_user_email, caller_token_teams)` pair. `None` defaults to `CallerContext.system()` for backward compatibility with the 100+ pre-existing tests that don't thread auth context; new user-facing callers MUST pass `CallerContext.for_user(...)`.

  Threaded through 4 user-facing route handlers (`main.py` create_server + update_server, `admin.py` register_server + update_server) and 3 internal call sites (`import_service.py`, all with explicit `CallerContext.system()` + load-bearing SECURITY comment naming the admin-only route precondition).

  Must NOT do: do NOT add a third factory method that constructs a non-system context with arbitrary defaults. Do NOT remove the `is_system` flag — it is the load-bearing distinction between explicit bypass and "real caller with no teams". Do NOT call the policy function `can_associate_a2a_agent_with_server` from new code WITHOUT routing through `_authorize_a2a_associations` (which holds the bypass logic).

  Acceptance: `pytest tests/unit/mcpgateway/services/test_server_service_a2a_auth.py` passes 12 tests across 4 classes:

    - `TestAuthorizeA2AAssociationsSystemContext` (3): bypass fires ONLY for `.system()`; does NOT fire for `for_user(None, [])` (anonymous public-only) or `for_user("admin", None)` (authenticated-admin shape) — closes Metis M4 boundary tests.
    - `TestAuthorizeA2AAssociationsAllowPath` (2): for_user grants → silent return + correct kwargs forwarded.
    - `TestAuthorizeA2AAssociationsDenyPath` (3): denial raises ServerError, generic message (no agent/server name leak), short-circuits on first.
    - `TestCallerContextFactories` (4): factory shapes; frozen invariant; anonymous != system.

  References: Metis C2 (import bypass); Momus Block 2 (under-specified escape hatch); D11; F10.

  Status: DONE.

  Commit: bd551b215 | refactor(a2a)/feat(servers): close Metis C1/C2/C3/H3/H4 + Momus Block 2 via CallerContext sentinel.

### Amendment D — T21 split into T21A (DONE) + T21B (DONE)

  Original T21 (line 551 of this plan) bundled three deliverables into one task: template selector + JS submit-handler wiring + card-URL ops affordance + bundle rebuild + Vitest tests. Momus correctly flagged that an in-session commit landed only the JS submit handler (T21A) with the other deliverables deferred, contradicting the plan's "no deferred CRUD/UI verification" stance. This amendment makes the split canonical.

#### T21A — JS submit handler (DONE)

  What was done: Added the A2A agent submit-handler block to `mcpgateway/admin_ui/formSubmitHandlers.js`, mirroring the existing `associatedTools` / `associatedResources` / `associatedPrompts` pattern. The handler reads the persistent edit-selection store for `associatedA2aAgents`, flushes currently-checked checkboxes from the live DOM into the store, and replaces the FormData entries with the union. Defensive `if (a2aContainer)` guard means the handler is a no-op until T21B lands the template selector.

  Acceptance: `node --check mcpgateway/admin_ui/formSubmitHandlers.js` passes (syntactic). The handler runs in two places: the server-create flow (after the prompts block, before the fetch to `/admin/servers`) and the server-edit flow (inside the existing `forEach` over the selectors array). Field name is camelCase `associatedA2aAgents` because the FastAPI endpoints already accept this camelCase form-data key (Pydantic alias for the snake-case `associated_a2a_agents`).

  Status: DONE.

  Commit: 7b965a962 | feat(admin-ui): server-form A2A agent submit handler (T21 phase 1).

#### T21B — Template selector + init helper + card-URL affordance + bundle rebuild + Vitest (DONE)

  What to do: Five sub-deliverables, all required for T21 to be considered complete per the original plan acceptance:

    a. **Template selector** in `mcpgateway/templates/admin.html`: add an A2A agent multi-select to BOTH the server-CREATE and server-EDIT forms, mirroring the existing `associatedTools` / `associatedResources` / `associatedPrompts` selector blocks. Match the input `name="associatedA2aAgents"` (the JS handler from T21A already expects this). HTMX endpoint `/admin/a2a/partial` already exists at `mcpgateway/admin.py:10963` — no new endpoint needed. For the server-EDIT form, the container id must be `edit-server-a2a-agents` so the T21A handler's array-driven sync block matches.

    b. **Init helper** in `mcpgateway/admin_ui/admin.js`: add `initA2aAgentSelect(...)` mirroring `initToolSelect` / `initResourceSelect`. The template's `hx-on:htmx:after-swap` handler invokes it once the partial loads. Pin the helper signature with the same first-load arg names the existing helpers use so any future refactor can replace all three with a single generic helper without breaking call sites.

    c. **Card-URL ops affordance** in `mcpgateway/admin_ui/a2aAgents.js`: in the agent-detail view, add a "Card endpoint URL" display showing `{public_base}/a2a/{name}/.well-known/agent-card.json` plus a Copy button using `navigator.clipboard.writeText(url)`. The `public_base` is the same value `get_a2a_agent_card` reads via `getattr(settings, "a2a_public_base_url", None) or str(settings.app_domain).rstrip("/")` — expose it on the agent-detail page via the existing template variable injection or a small HTMX call.

    d. **UI bundle rebuild**: `make build-ui` (requires `npm install` in the dev environment). The Vitest tests in (e) and the existing Vitest suite verify the bundle.

    e. **Vitest tests** for T21A handler + T21B init helper: `tests/unit/js/serverForms.test.js` (NEW) exercising the persistent-selection store sync logic + the init helper's interaction with the HTMX-loaded partial. Mirrors the shape of existing Vitest tests under `tests/unit/js/`.

  Must NOT do: do NOT introduce a different camelCase convention than `associatedA2aAgents` (the JS handler from T21A and the FastAPI body-form key are both already on this name). Do NOT skip the bundle rebuild — without it the template selector renders but the handler doesn't run. Do NOT add server-edit form changes that break the existing `getEditSelections("...")` contract.

  Parallelization: Wave 5+ | Blocked by: T20, T21A | Blocks: T22

  References: original T21 (line 551), Oracle re-review #10 (the JS submit handler being the load-bearing piece, not just template inclusion).

  Acceptance:
    - Manual: server-edit form shows an A2A agent multi-select alongside tools/resources/prompts; selecting agents and saving the form persists them to `server.associated_a2a_agents` in the API response.
    - Manual: agent-detail view shows the rewritten card URL + working Copy button.
    - Automated: `pytest tests/integration/test_admin_server_a2a_flow.py::test_form_submits_a2a_agents` (referenced in T21 original, T22 makes this real) simulates form POST with `associatedA2aAgents=["a1","a2"]` and asserts the resulting server row has both IDs in `server_a2a_association`.
    - Automated: `npx vitest run tests/unit/js/serverForms.test.js` passes.
    - Build: `make build-ui` succeeds; the produced bundle includes the new init helper and submit-handler blocks.

  QA: happy=full UI flow round-trips A2A agent IDs end-to-end. failure=selector renders but server has empty `associated_a2a_agents` after save → JS submit handler missing or template input name mismatch (most likely cause: stale bundle, run `make build-ui`). Evidence: `.omo/evidence/task-21B-a2a-native-passthrough.txt`.

  Commit: 81820b68a | feat(admin-ui)/feat(servers): server-form A2A selector + card-URL affordance (T21B)

  Status: DONE. Landed in commit ``81820b68a`` (also closes T22 via commit ``77b73562d``). Oracle F1 caught the stale "OPEN" text in a follow-up review and this commit flipped it to match the shipped state.

### Amendment E — Future policy-engine migration is out of scope (closes Momus Block 3)

  Original Phase A messaging asserted that the `a2a_access_policy.py` module is "rules-engine-ready" with stable signatures. Momus correctly flagged that this overcommitted: the same evidence file stated the `a2a_service` delegation-shim parameter "will drop" once primitives migrate into the policy layer. Both stability and parameter-drop cannot be true.

  Adopted scope:

  - **Today's call sites are STABLE** through any implementation refactor of the three policy functions that keeps the same kwargs and the same boolean return contract.
  - **Function signatures are STABLE for today's callers ONLY.** The `a2a_service` delegation-shim parameter exists to avoid circular imports today and has no semantic role in the policy decision — it is provisional and may be dropped in a future refactor when the primitives' return values are pre-fetched at the call site instead.
  - **No specific policy-engine vendor or migration is committed.** Any future move to an external policy engine is a separate plan with its own scope, acceptance criteria, and breaking-change disclosure. The current policy-module shape is chosen for clarity TODAY, not as a no-op migration target for any specific engine.

  Must NOT do: do NOT advertise the policy module as a no-op migration target for any external rules engine. Do NOT promise stable signatures forever; the `a2a_service` parameter is provisional.

  Acceptance: the `can_view_a2a_agent_directly` docstring now contains both the stability claim ("treat the signature as STABLE for today's callers") and a breaking-change disclaimer naming the `a2a_service` parameter as provisional.

  References: Momus Block 3 (internal contradiction in original "rules-engine-ready" claim); Phase A evidence at `.omo/evidence/phase-a-a2a-access-policy.txt`.

  Status: DONE (clarification only, no further code change required).

  Commit: bd551b215 (docstring update in `a2a_access_policy.py`).

### Amendment F — Phase C: Plugin wiring gaps on T11 card, T12 GetExtendedAgentCard, and T5 streaming (DEFERRED — scope clarified)

  What to do: Plugin-context preservation in the original plan (D5) was scoped only to the unary dispatch path that reuses `invoke_agent`. Three new code paths landed during Wave 3 + Wave 4 that DO NOT reuse `invoke_agent` and therefore do NOT fire A2A-specific pre/post hooks (only the global `HttpAuthMiddleware → run_pre_request_hooks` HTTP-level hook fires, which is necessary but not sufficient for plugins that enforce per-method policy):

    - **T11 card route** (`get_a2a_agent_card` in `main.py`): calls `synthesize_agent_card` which reads the DB directly. No A2A-specific hook fires.
    - **T12 GetExtendedAgentCard branch**: D18 explicitly forbids forwarding upstream; the gateway synthesizes the extended card via T2 and returns it directly. No A2A-specific hook fires.
    - **T5 streaming dispatch** (`dispatch_a2a_jsonrpc_streaming`): uses `client.stream()` directly per Oracle v2 #5 + v3 #5 SEPARATE-codepath decision. Bypasses `invoke_agent` entirely. No A2A-specific hook fires.

  Worst case impact:

    - **Audit gap**: A2A-specific plugins that audit per-method invocations miss all card discoveries, all extended card synthesis events, and all streaming dispatches.
    - **Policy bypass**: A2A-specific plugins that enforce per-method rate-limiting, content filtering, or DLP miss the same three paths. A streaming method that should be rate-limited via an A2A plugin is unbounded.

  Three sub-tasks:

#### T-Phase-C-1 — A2A pre/post hooks on T11 card route

  What to do: In `main.py::get_a2a_agent_card`, before calling `a2a_service.synthesize_agent_card` and after receiving the result (or on the None-return path), fire the A2A-specific pre/post hooks. Hook event names: `a2a.card.pre` and `a2a.card.post`. Hook context: agent name, server id (if v-server), public base URL, caller (None for anonymous). Mirror the existing hook-firing pattern in `invoke_agent`.

  Acceptance: pytest `tests/unit/mcpgateway/test_main_a2a_hooks.py::test_card_route_fires_pre_post_hooks` passes; a registered plugin that hooks `a2a.card.pre` and `a2a.card.post` observes both events for every card request including v-server URL form.

  Status: OPEN.

  Commit: Y | feat(a2a): A2A pre/post hooks on T11 card route (Phase C #1)

#### T-Phase-C-2 — A2A pre/post hooks on T12 GetExtendedAgentCard branch

  What to do: In `main.py::dispatch_a2a_agent`, inside the `GetExtendedAgentCard` / `agent/getAuthenticatedExtendedCard` short-circuit (before synthesize_agent_card and after the result), fire the A2A-specific pre/post hooks. Hook event names: `a2a.extended_card.pre` and `a2a.extended_card.post`. Hook context: agent name, server id, caller identity, capabilities flag, agent.id. Must remain CONSISTENT with D18 — hooks observe the request; they do NOT enable a plugin to forward upstream.

  Acceptance: pytest `tests/unit/mcpgateway/test_main_a2a_hooks.py::test_extended_card_fires_pre_post_hooks` passes; D18 (NEVER forward upstream) is still enforced via the existing assert_not_called check on dispatch_a2a_jsonrpc_unary.

  Status: OPEN.

  Commit: Y | feat(a2a): A2A pre/post hooks on T12 GetExtendedAgentCard branch (Phase C #2)

#### T-Phase-C-3 — A2A pre/post hooks on T5 streaming dispatch

  What to do: In `mcpgateway/services/a2a_service.py::dispatch_a2a_jsonrpc_streaming`, fire the A2A-specific pre hook BEFORE the upstream `client.stream()` call and the post hook AFTER the stream closes (in the finally block or stream-end branch). Hook event names: `a2a.dispatch.pre` (matches the unary path's pre-hook) and `a2a.dispatch.post.streaming` (distinguishes from unary post-hook so plugins can distinguish if needed). Hook context: agent name, server id (if v-server), method (SendStreamingMessage / SubscribeToTask / v0.3 alias), caller identity, hop count, bearer-token presence (not value).

  Acceptance: pytest `tests/unit/mcpgateway/services/test_a2a_streaming_hooks.py::test_streaming_fires_pre_post_hooks` passes; a registered plugin sees one pre-hook event before the SSE stream starts and one post-hook event after it ends, even on early disconnect. Integration test extends `tests/integration/test_a2a_native_routes.py::TestPerAgentDispatchEndpoint::test_streaming_method_returns_sse_response` to verify hook firing through the route.

  Must NOT do: do NOT fire the post-hook from inside the async-generator yield loop — it must fire OUTSIDE so plugins see one event per request, not one per chunk.

  Status: OPEN.

  Commit: Y | feat(a2a): A2A pre/post hooks on T5 streaming dispatch (Phase C #3)

  References: Metis H1 (plugin wiring gap as the user's first-raised concern); D5 (original plugin context decision, now extended); D18 (GetExtendedAgentCard NEVER forwards upstream, still enforced).

#### Phase C deferral note (added post-Wave 7 closeout)

  Background: the cpex framework that owns ``AgentHookType`` is an external dependency and exposes only ``AGENT_PRE_INVOKE`` / ``AGENT_POST_INVOKE`` for A2A. Adding the granular event names this amendment originally specified (``a2a.card.pre``, ``a2a.extended_card.pre``, ``a2a.dispatch.post.streaming``) would require either (a) modifying cpex to introduce new hook types, or (b) reusing ``AGENT_PRE_INVOKE`` / ``AGENT_POST_INVOKE`` for all three paths — which conflates metadata reads (card discovery) with actual invocations from a plugin's perspective, breaking semantic expectations for rate-limiters and content filters.

  Scope reduction adopted: Phase C ships in two stages. Stage (a) — helper extraction + placeholder wiring at T11/T12/T5 — landed in commit ``676130982`` and is documented in detail below; stage (b) — cpex fork decision + placeholder body swap — remains as the gating future commit. The HTTP-level ``HttpAuthMiddleware → run_pre_request_hooks`` already fires for ``/a2a/*`` URLs per the global registration at ``main.py``, so plugins that gate at the HTTP layer continue to work today on the native paths.

  Plan task entries for the three sub-tasks (T-Phase-C-1, T-Phase-C-2, T-Phase-C-3) remain valid as the acceptance contract for stage (b). The placeholder helpers in ``mcpgateway/services/a2a_hooks.py`` (commit ``676130982``) have stable signatures matching what each event will need at firing time; the stage (b) commit becomes a body swap, not a re-wiring.

#### Phase C stage (a) closeout — helper extraction + placeholder wiring (DONE, commit 676130982)

  What landed:

  - ``mcpgateway/services/a2a_hooks.py`` NEW. Three live helpers — ``build_a2a_hook_context``, ``fire_a2a_pre_invoke_hook``, ``fire_a2a_post_invoke_hook`` — wrap the existing cpex ``AGENT_PRE_INVOKE`` / ``AGENT_POST_INVOKE`` types and consolidate the GlobalContext + PydanticA2AAgent + invoke_hook setup that previously lived inline. Six placeholder helpers (``fire_a2a_card_pre_hook`` / ``fire_a2a_card_post_hook`` / ``fire_a2a_extended_card_pre_hook`` / ``fire_a2a_extended_card_post_hook`` / ``fire_a2a_streaming_dispatch_pre_hook`` / ``fire_a2a_streaming_dispatch_post_hook``) document the integration points for the deferred Phase C events. They are no-ops today that log at DEBUG so the audit trail still reflects WHERE the firing would happen.
  - ``mcpgateway/services/a2a_service.py``. ``invoke_agent`` now uses the three live helpers. Behavior is byte-identical to the prior inline form — the existing ``test_a2a_agent_invoke_hooks.py`` suite (16 tests) passes unchanged. Agent fields are snapshot into a ``SimpleNamespace`` so the helper call happens AFTER ``db.commit() + db.close()``, preserving the release-DB-before-HTTP timing contract.
  - ``mcpgateway/main.py``. ``get_a2a_agent_card`` (T11) fires ``fire_a2a_card_pre_hook`` before ``synthesize_agent_card`` and ``fire_a2a_card_post_hook`` after, with ``card_resolved=True/False`` distinguishing real discovery from 404 outcomes. ``dispatch_a2a_agent`` extended-card branch (T12) builds an ``A2AHookContext`` from the resolved agent, fires the pre-hook before the capability check, then fires the post-hook before either the ``-32007`` return or the success return. ``dispatch_a2a_agent`` streaming branch (T5) wraps the SSE generator with a ``try/finally`` that fires ``fire_a2a_streaming_dispatch_post_hook`` OUTSIDE the yield loop — one event per request, not per chunk, per the Amendment F constraint.
  - ``docs/docs/architecture/a2a-cpex-hook-proposal.md`` NEW. Documents the six proposed cpex ``AgentHookType`` values + payload classes (Path A) vs the ``AGENT_PRE_INVOKE`` / ``AGENT_POST_INVOKE`` reuse path with method discriminator (Path B). Recommendation is Path A. Records open questions (card-route denial semantics, per-chunk hook, potential MCP overlap).
  - ``tests/unit/mcpgateway/services/test_a2a_hooks.py`` NEW. 14 tests across 4 classes covering the live helpers and the six placeholder no-ops. The full regression set (66 tests across hooks, invoke hooks, T11/T12/T5 native-route integration, and route ordering) passes.

  What still needs the stage (b) commit:

  - Decide Path A or Path B with the cpex maintainers. The markdown proposal recommends Path A (clean enum separation) but accepts Path B as a transitional shape if cpex changes are blocked.
  - Swap the six placeholder helper bodies for real ``invoke_hook`` calls against the chosen path. The call sites at T11 / T12 / T5 do NOT change — helper signatures are stable across both paths.
  - Land the cpex enum / payload additions (Path A) OR the payload schema extension (Path B) in the cpex repository.
  - Add per-event "fired" tests asserting the plugin chain receives the expected payload. The existing placeholder tests pin the no-op contract; the stage (b) tests will pin the real-firing contract.

### Amendment G — ``A2AAgentSnapshot`` frozen dataclass for shared hook + policy consumption (PROPOSED)

  Background: the helper extraction in commit ``676130982`` introduced a ``SimpleNamespace``-based "agent snapshot" pattern in ``invoke_agent`` — a detached projection of the ``DbA2AAgent`` ORM row that ``build_a2a_hook_context`` consumes. The pattern works (it satisfies the helper's duck-typed ``agent`` parameter) but the ``SimpleNamespace`` shape is loose; a future maintainer can drift the field set without anything failing fast. The user-raised observation that the same shape is naturally consumable by the ``a2a_access_policy.py`` functions (Amendment A) suggests formalizing it as a proper frozen dataclass. That formalization:

  - Locks the field set so any new policy or hook concern adds fields explicitly rather than reaching for ORM attributes ad-hoc.
  - Decouples every downstream consumer from the DB session lifecycle (already true for the hook path, would become true for the policy path too).
  - Pairs with ``CallerContext`` (Amendment C) as the AGENT side of every policy input — together they are the canonical ``(caller, target)`` tuple every policy + hook decision needs.
  - Matches Amendment E's restatement that the future policy-engine migration needs pre-fetched primitives passed as entity attributes. The snapshot is the bridge to that migration.

  What to do (split into three commits for clean bisectability):

  1. Define ``A2AAgentSnapshot`` as a frozen dataclass in ``mcpgateway/services/a2a_hooks.py`` (or a new ``a2a_agent_snapshot.py`` if ``a2a_hooks.py`` grows past 250 LOC). Add a ``from_orm(agent: DbA2AAgent) -> A2AAgentSnapshot`` classmethod that extracts all fields once. Fields: ``id``, ``name``, ``team_id``, ``visibility``, ``enabled``, ``tags``, ``owner_email``, ``oauth_config``, ``oauth_enabled``, ``passthrough_headers``, ``auth_type``. Audit ``_check_agent_access`` and the three ``a2a_access_policy.py`` functions to confirm field coverage before locking the set.
  2. Refactor the ``invoke_agent`` caller to pass ``A2AAgentSnapshot.from_orm(agent)`` instead of the inline ``SimpleNamespace`` construction. Keep ``build_a2a_hook_context``'s ``getattr`` fallback for backward compatibility during transition.
  3. Refactor ``can_view_a2a_agent_directly``, ``can_view_a2a_agent_in_server_context``, and ``can_associate_a2a_agent_with_server`` in ``a2a_access_policy.py`` to accept ``agent_snapshot: A2AAgentSnapshot``. Update the underlying ``_check_agent_access`` primitive to take the snapshot too. Update callers (``synthesize_agent_card``, ``resolve_agent_for_dispatch``, server_service hooks) to build the snapshot once after the lookup and pass it through.

  Must NOT do:

  - Do NOT remove the duck-typed ``getattr`` fallback in ``build_a2a_hook_context`` without first migrating ALL hook callers to pass ``A2AAgentSnapshot`` — partial migration creates a confusing dual-mode helper.
  - Do NOT add wire-level secrets (``endpoint_url``, ``auth_value``, ``auth_query_params``) to the snapshot. Those stay on the ORM row and flow through ``prepare_a2a_invocation`` separately. The snapshot is for AUTHORIZATION + OBSERVABILITY identity, not for invocation wire shape.
  - Do NOT change the policy function signatures in the same commit as the snapshot introduction. Split into (1) introduce snapshot, (2) refactor ``invoke_agent`` caller, (3) refactor policy callers. Each commit independently bisectable.

  Acceptance criteria:

  - ``pytest tests/unit/mcpgateway/services/test_a2a_hooks.py`` continues to pass after stage (1) and (2).
  - ``pytest tests/unit/mcpgateway/services/test_a2a_access_policy.py`` is updated in stage (3) to construct ``A2AAgentSnapshot`` via ``from_orm``; all 11 tests still pass.
  - ``_check_agent_access`` accepts both the snapshot AND the legacy ORM row during transition (overload or duck-typing); a follow-up commit can drop the ORM signature once all callers migrate.
  - Pre-commit hooks pass; LSP clean on changed files; behavior unchanged for unauthenticated card-route callers (Amendment B three-level conjunctive deny still collapses to ``False``).

  References: user-raised design question in the helper-extraction session ("Could the SimpleNamespace object also be used by the AuthN/AuthZ/RBAC/ABAC policy module?"); Amendment A (centralized policy module — the consumer that benefits); Amendment C (``CallerContext`` sentinel — the caller-side pair to this agent-side snapshot); Amendment E (future policy-engine migration restatement — explains why pre-fetched primitives matter); commit ``676130982`` (where the ``SimpleNamespace`` pattern was introduced and is now ready for formalization).

  Status: PROPOSED.

  Commit (when implemented, split into three): ``refactor(a2a): introduce A2AAgentSnapshot frozen dataclass for hook + policy reuse (Amendment G part 1)``; ``refactor(a2a): invoke_agent uses A2AAgentSnapshot (Amendment G part 2)``; ``refactor(a2a): a2a_access_policy + _check_agent_access accept A2AAgentSnapshot (Amendment G part 3)``.

### Amendment H — T3 agent-name lookup is case-sensitive (closes Oracle F1 #3)

  Background: Oracle F1 (background task ``bg_6cd20eb9``) flagged that the T3 plan-task entry specified case-INSENSITIVE name matching for ``A2AAgentService.resolve_agent_for_dispatch`` but the shipped code at ``a2a_service.py:995-998`` documents and ``a2a_service.py:1050`` implements case-SENSITIVE matching (``DbA2AAgent.name == agent_name`` exact). Oracle marked this MAJOR with the recommendation to either implement case-insensitive lookup or amend the plan to explicitly accept case-sensitive parity with the existing ``/invoke`` route.

  Decision (Path b): the plan is amended to explicitly accept case-sensitive matching. Rationale:

  - The existing ``/invoke`` route is case-sensitive. Switching to case-insensitive for the new native-passthrough routes would create a SURPRISING inconsistency where the same agent name resolves differently depending on which transport the caller chose.
  - Case-insensitive matching introduces a name-collision policy decision (what if both ``"Foo"`` and ``"foo"`` register? which wins on lookup?) that the plan never resolved. Path-a would force that resolution as a side-effect.
  - The T3 original text was written before the ``/invoke`` parity constraint was fully appreciated. The plan amendment realigns the contract with the shipped behaviour rather than introducing a behaviour change post-Wave 7.

  What to do: nothing in code. This amendment closes Oracle F1 #3 by adjusting the plan acceptance criterion.

  Must NOT do: do NOT add a case-insensitive lookup primitive without a parallel decision about name-collision precedence, name-canonicalisation at registration, and migration handling for existing case-variant names in production datastores. That is a separate scoped change with its own design review.

  Acceptance criteria: ``a2a_service.py::resolve_agent_for_dispatch`` and the underlying ``DbA2AAgent.name == agent_name`` filter remain case-sensitive. ``/a2a/{name}`` per-agent dispatch, ``/servers/{id}/a2a/{name}`` v-server dispatch, and the legacy ``/invoke`` route all behave identically with respect to case. Existing tests at ``tests/integration/test_a2a_native_routes.py`` (case-sensitive resolution) and ``tests/integration/test_a2a_vserver_composition.py`` (case-sensitive v-server lookup) continue to pass without modification.

  References: Oracle F1 #3 ``bg_6cd20eb9``; original T3 plan entry; ``mcpgateway/services/a2a_service.py:995-998`` (case-sensitivity documentation); ``mcpgateway/services/a2a_service.py:1050`` (case-sensitive name filter); existing ``/invoke`` route case-sensitive behaviour.

  Status: DONE (docs-only amendment).

  Commit: this commit | docs(plan): Amendment H + Amendment D status flip + deferred follow-up work (Oracle F1+F2 plan-side closeout).

### Amendment I — Deferred follow-up work (Oracle F1+F2 + 250 LOC ceiling)

  Captures the items Oracle F1 ``bg_6cd20eb9`` and Oracle F2 ``bg_dc735107`` surfaced that cannot land as ad-hoc fixes in the current commit cycle and need their own focused commits or program-level attention. The Oracle critical fixes (D14 double-wrap, streaming auth refactor, stale docstrings + P5 TODO honesty) landed in commit ``059a376e7``; what is left here is the work that requires a meaningful chunk of new code, new fixtures, or cross-codebase refactoring beyond this plan's scope.

#### I.1 — T31 architecture documentation (Wave 8, BLOCKING per F1)

  What to do: write ``docs/docs/architecture/a2a-native.md`` per the original T31 entry. Covers: native passthrough architecture (per-agent + v-server URL families), the synthesizer, the path-rewrite middleware, method-aware RBAC, A2A-Version negotiation, the streaming dispatch wrapper, the helper-extraction + placeholder hook wiring (Amendment F stage a), the Rust runtime deprecation cycle (Wave 6), and the compliance harness layout. Cross-link from ``docs/docs/index.md`` plus the relevant existing docs (manage/rbac.md, architecture/multitenancy.md). Run ``mkdocs build`` clean.

  Must NOT do: do NOT skip the deprecation-cycle section (T23–T27) or the Amendment-F-deferral framing — both are operator-visible and shape the migration story.

  Acceptance: doc exists; ``mkdocs build`` succeeds; doc is reachable from the mkdocs nav; references commit ``676130982`` (Amendment F stage a) and commit ``059a376e7`` (Oracle F1+F2 critical fixes) as part of the implementation trail.

  Status: DEFERRED to a focused Wave 8 commit (no work in this commit).

  Commit (when implemented): Y | docs(a2a): T31 native passthrough architecture doc (Wave 8)

#### I.2 — P5 compliance fixture work (BLOCKING per F2)

  What to do: add two fixtures to ``tests/live_gateway/a2a_compliance/`` that the existing P5 placeholder skips at ``v1_0_0/test_rbac_extra.py:143-151`` and ``:166-172`` reference:

  - A team-scoped A2A agent registered to ``team-a`` (mirrors ``registered_agent_id`` but scoped) + a JWT token with ``teams=["team-b"]``. Lets the wrong-team-visibility-404 assertion fire (D11: visibility hides rather than 403).
  - A non-admin JWT token granted ``a2a.read`` ONLY (not ``a2a.invoke``). Lets the ``GetExtendedAgentCard`` permission test fire (T12 step 8: per-method RBAC).

  Both fixtures live in ``conftest.py`` alongside the existing ``registered_agent_id`` + ``server_id`` fixtures (commits ``2bc20d26d``, ``fd03f8f05``, etc.). Once the fixtures land, remove the two TODO ``pytest.skip`` lines and let the existing assertion bodies run.

  Must NOT do: do NOT inline the fixture work into ``v1_0_0/test_rbac_extra.py`` — keep the conftest fixture / test split so other compliance tests can reuse the team-scoped + per-permission tokens.

  Acceptance: ``pytest tests/live_gateway/a2a_compliance/v1_0_0/test_rbac_extra.py -v`` runs the previously-skipped assertions; both pass against a live gateway with the matching agent + token registered.

  Status: DEFERRED to a focused fixture-work commit (no work in this commit; the TODO comments now honestly point at this addendum rather than the stale "Wave 7 T28 Part B" reference).

  Commit (when implemented): Y | test(a2a-compliance): team-scoped agent + per-permission token fixtures (F2 P5 closeout)

#### I.3 — 250 LOC ceiling violations (program-level, not this plan)

  What was found: F2 ``bg_dc735107`` cross-cutting note flagged ``mcpgateway/main.py`` (13,166 LOC), ``mcpgateway/services/a2a_service.py`` (4,528 LOC), ``mcpgateway/services/server_service.py`` (2,147 LOC), and ``tests/live_gateway/a2a_compliance/conftest.py`` (410 LOC) all violate the 250 LOC ceiling. These files PRE-DATE this plan and accumulated their bulk over the project lifetime; this plan's contribution to the line count is bounded (helper extraction + placeholder wiring + plan amendments).

  What to do: a separate program-level refactor that splits these files along genuine seam lines (transport vs admin vs RBAC vs service vs middleware for main.py; per-domain helper modules for a2a_service.py + server_service.py; fixture modules for the harness conftest.py). NOT an ad-hoc edit attached to this plan.

  Must NOT do: do NOT attempt a single-commit "split the file" mass refactor without a comprehensive test plan — these are the busiest hot paths in the gateway and a botched seam means weeks of regressions. The current bulk is acceptable cost relative to that risk profile until a real decomposition design lands.

  Acceptance: out of scope for this plan. Captured here for traceability — Oracle F2 saw it; the project owner decides when to spin it up as its own initiative.

  Status: DEFERRED (program-level concern, NOT a follow-up commit to this plan).

  Commit (when undertaken): owned by a separate refactor initiative.

## Final verification wave (REVISED)

> Runs in parallel after ALL 31 todos T1-T31. ALL four must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.

- [ ] F1. **Plan compliance audit** — Oracle (read-only) review of the implemented diff against this plan's Must have (8 components) and Must NOT have (20 items). Auditor reads each commit in order, maps it to a todo number (T1-T31), and asserts the todo's acceptance criteria were actually met. APPROVE = zero Must-NOT violations + every Must-have deliverable present.
  References: `.omo/plans/a2a-native-passthrough.md` (this file); `.omo/drafts/a2a-native-passthrough.md` (full reasoning + findings F1-F15 + decisions D1-D19 + principles P1-P5).
  Acceptance: Oracle returns "APPROVE" with no Must-NOT violations and every Must-have item evidenced. Evidence: `.omo/evidence/final-1-a2a-native-passthrough.md`

- [ ] F2. **Code quality review** — Oracle (read-only) review on the most load-bearing files:
  - `mcpgateway/schemas_a2a_native.py` (D8/D9 strict field-name enforcement; `extra="forbid"`)
  - `mcpgateway/services/a2a_service.py` (new synthesizer NOT reusing `get_agent_card`, D12; unary+streaming dispatch separation, D15; visibility via `_check_agent_access`, D11; A2A error helpers including `-32001..-32009`, D6)
  - The new card+dispatch route handlers in `mcpgateway/main.py` (D2 no inline auth; D17 manual JSON parse, no `Body()`; D18 `GetExtendedAgentCard` branch; D14 HTTP 404 vs `-32601` disambiguation; D13 `A2A-Version` validation)
  - `mcpgateway/middleware/a2a_path_rewrite.py` (regex matches base+suffix forms per Oracle #14; no membership enforcement in middleware per P1)
  - `mcpgateway/services/server_service.py` (T20 verify/patch — `associated_a2a_agents` round-trips through `server_a2a_association`)
  - Compliance fixtures in `tests/live_gateway/a2a_compliance/conftest.py` (real plumbing per Oracle #11, no placeholders)

  APPROVE = principles upheld in code structure across all named files.
  References: P1, P2, P3, P4, P5; D2, D6, D8, D9, D11, D12, D13, D14, D15, D17, D18.
  Acceptance: Oracle returns "APPROVE" with no principle violations. Evidence: `.omo/evidence/final-2-a2a-native-passthrough.md`

- [ ] F3. **Real manual QA against a live A2A SDK client** — drive the gateway end-to-end via `interactive_bash` + a Python driver script using `ClientFactory(config=...).create_from_url(...)` (real shape per Oracle #11). Scenarios:
  (a) Per-agent card discovery → `protocolBinding=JSONRPC` (camelCase), per-interface `protocolVersion`, URL rewritten to gateway.
  (b) Per-agent `SendMessage` dispatch → JSON-RPC result.
  (c) Per-agent `SendStreamingMessage` → multiple SSE `data:` chunks each parsing as complete JSON-RPC.
  (d) V-server-scoped card + dispatch via `/servers/{id}/a2a/{name}` work identically to per-agent paths.
  (e) V-server membership miss → HTTP 404 (D14 — path resource doesn't exist).
  (f) Malformed JSON body → HTTP 200 + `-32700 ParseError` (D17 — manual parse).
  (g) `A2A-Version: 2.0` header → HTTP 200 + `-32009 VersionNotSupported` (D13).
  (h) Legacy `message/send` alias → forwarded as `SendMessage` (Q12); `tasks/list` is NOT mapped (Oracle #22).
  (i) `GetExtendedAgentCard` with `a2a.read` permission → gateway-synthesized extended card (NOT forwarded upstream per D18); without permission → HTTP 403.
  (j) Auth deny paths: missing token → 401; token without `a2a.invoke` → 403; team-only agent accessed by wrong-team token → HTTP 404 (visibility hides per D11/Oracle #3).
  (k) UAID cross-gateway dispatch → routes through existing federation path (Oracle #13).
  (l) Concurrent SSE streams → cancellation closes upstream connection within ~100ms (D15).
  (m) Host-header spoofing attempt with `app_domain` configured → card `url` uses configured value, NOT spoofed Host (F15).

  APPROVE = all 13 scenarios observed live with expected wire output.
  References: F8 wire shape; D6, D11, D13, D14, D15, D17, D18; Oracle #2, #3, #5, #11, #13, #20, #22.
  Acceptance: All 13 scenarios produce expected output. Evidence: `.omo/evidence/final-3-a2a-native-passthrough.md` (transcript + tcpdump for streaming + curl output per scenario).

- [ ] F4. **Scope fidelity** — verify nothing in Scope OUT was touched:
  (a) `git diff main...HEAD -- mcpgateway/main.py | rg "^[+-].*async def invoke_a2a_agent[^_]"` returns 0 lines (legacy `/invoke` handler at `main.py:5041-5137` untouched per A2).
  (b) `git diff main...HEAD -- mcpgateway/db.py | rg "^[+].*Permissions\."` returns 0 lines (no new permission strings — `a2a.invoke` + `a2a.read` cover all per F5).
  (c) `git diff main...HEAD -- mcpgateway/alembic/` shows no new migration (no schema changes — `server_a2a_association` already exists per F1).
  (d) `git diff main...HEAD -- crates/` shows ONLY `Cargo.toml` `default-members` edit + tests; `crates/a2a_runtime/` source code untouched per Scope OUT.
  (e) Existing `mcpgateway/services/a2a_service.py::get_agent_card` (line 1379-1395) untouched per D12 (legacy v0.3-shape stays for internal endpoint).
  (f) `git log --oneline main...HEAD | wc -l` ≈ 31 commits (one per todo per atomic-commit strategy).

  References: Scope OUT items (20 enumerated in Must NOT section above — REVISED from 15 in original plan).
  Acceptance: All six checks return as expected. Evidence: `.omo/evidence/final-4-a2a-native-passthrough.md`

  Additional check (g) per Oracle re-review #8: `mcpgateway/services/rust_a2a_runtime.py` STILL EXISTS post-merge (deprecation cycle requires one warned release before physical deletion); `rg "DeprecationWarning" mcpgateway/services/rust_a2a_runtime.py` returns ≥1.

## Commit strategy (REVISED)

- **Atomic commits**: one commit per todo (T1-T31). Each todo's "Commit:" line specifies the conventional-commits message.
- **Conventional Commits**: `feat(a2a):`, `refactor(a2a):`, `test(a2a):`, `test(a2a-compliance):`, `docs(a2a):`, `feat(servers):`, `feat(admin-ui):` prefixes. Match the prefix to the todo's primary effect.
- **DCO**: every commit signed with `-s` (`git commit -s`). Non-negotiable per AGENTS.md.
- **Branch**: continue on `jps/compliance-tests` (the harness branch this plan unblocks). Do NOT create a new branch — harness + native A2A passthrough land together.
- **Push timing**: do NOT push until the user explicitly asks. Final verification wave runs locally first.
- **Per-wave QA gate (REVISED — softened per user direction)**:
  - **Lint is NOT a gate.** Pre-commit hooks handle linting at commit time (ruff, black, IBM Detect Secrets, etc.); a wave is not blocked on whole-repo markdown/yamllint hygiene.
  - **All waves: `make test` passes AND ≥90% test coverage on production code added/changed in this wave.** Existing code paths the wave touched are also expected to retain their prior coverage level (no regression). Test-only files do not count toward the coverage measurement (they ARE the coverage).
  - **Waves 3-7: also `make test-protocol-compliance-a2a-gateway` passes** against a running gateway (Oracle #25 — `make test` alone ignores `tests/live_gateway/`).
  - **Wave 8: also `mkdocs build` clean** with the new architecture doc rendered.
  Wave N+1 does not start until Wave N is green. If a Wave N todo's acceptance criterion fails, fix THAT todo in a follow-up commit on the same wave — do NOT carry failures into Wave N+1.
- **Rollback strategy per wave**:
  - **Wave 1** (T1-T7, Foundation): no behavior change; revert = `git revert` of 7 commits. Safe.
  - **Wave 2** (T8-T10, Compliance audit + gap closure): test-only; revert removes the new assertions. Compliance baseline regresses to pre-audit state. Safe.
  - **Wave 3** (T11-T15, Per-agent data plane): routes are new; revert removes them. Legacy `/invoke` untouched. Safe.
  - **Wave 4** (T16-T19, V-server data plane): middleware + v-server-specific test fixtures; revert removes them. Per-agent routes from Wave 3 remain. Safe.
  - **Wave 5** (T20-T22, CRUD + UI verify/patch): service-layer + template changes; revert restores prior behavior. **Caution**: if T20 added new service-layer wiring (because pre-existing was broken), revert ALSO removes the fix — verify carefully before reverting.
  - **Wave 6** (T23-T27, Rust deprecation — STAGED per C6 across release N and N+1): T23 deprecation warning is harmless to revert. T24 Cargo.toml exclusion → revert restores `contextforge_a2a_runtime` to default build. T25 call-site removal → revert restores Rust execution path, but it was experimental-default-off so impact is nil for users with default settings. Production users with `EXPERIMENTAL_RUST_A2A_RUNTIME_ENABLED=true` lose Rust dispatch on T25 land; they were warned in T23. T26 deprecation marking (NO physical deletion in this release) → revert removes the DeprecationWarnings; module + config fields remain intact either way. T27 smoke verification → revert is a no-op (tests only). Physical module/config/version-reporting deletion is OUT OF SCOPE for this plan — happens in release N+1, so there's no "code/config deletion" to roll back in this release.
  - **Wave 7** (T28-T30, Harness completion): test-only; revert restores `NotImplementedError` + xfail hook. GAP-001 reopens. Safe.
  - **Wave 8** (T31, Docs): docs-only; revert removes the new file. No behavior impact. Safe.
- **No squash on merge**: each todo is independently bisectable. Preserve the atomic 31-commit history.

## Success criteria (REVISED — third pass)

The plan is complete when ALL of the following hold simultaneously:

1. **All 31 todos checked off** in this file (T1-T31).
2. **Final verification wave F1-F4 all APPROVE** with evidence files written under `.omo/evidence/`.
3. **`make lint && make test && make test-protocol-compliance-a2a-gateway`** all run green on the branch (no new regressions; pre-existing unrelated failures noted but not introduced).
4. **`pytest tests/live_gateway/a2a_compliance/ -v`** reports 0 xfails for GAP-001 AND all 28 previously-x-failed cells (14 gateway × 2 protocol-version columns) pass AND every gap-closure assertion written in T9+T10 passes against BOTH `gateway_proxy` and `gateway_virtual` targets (P5 realization, Oracle re-review #3).
5. **`tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md`** shows GAP-001 as **CLOSED** with the closing commit referenced.
6. **Rust deprecation cycle is real** (Oracle re-review #8 split):
   a. `rg "rust_a2a_runtime|experimental_rust_a2a_runtime" mcpgateway/services/{tool_service,a2a_service}.py` returns 0 lines (T25 — call sites removed, Python dispatcher unconditional).
   b. `mcpgateway/services/rust_a2a_runtime.py` STILL EXISTS but emits `DeprecationWarning` at module import (T26 — physical deletion deferred to release N+1 so users get one warned release cycle).
   c. The 6 `experimental_rust_a2a_runtime_*` config fields STILL EXIST in `mcpgateway/config.py` with `# DEPRECATED` comments (T26).
   d. `pytest tests/unit/mcpgateway/services/test_rust_a2a_runtime_deprecation.py` proves import emits the warning.
   e. A follow-up release tracking entry exists for physical removal in release N+1 (location TBD — `.omo/followups/` or repo issue).
7. **Cargo workspace** (using verified crate package name `contextforge_a2a_runtime`):
   a. `cargo check --workspace` passes.
   b. `cargo build` (NO `--workspace`) does NOT compile `contextforge_a2a_runtime` — `cargo build --verbose 2>&1 | rg -c "Compiling contextforge_a2a_runtime"` returns 0.
   c. `cargo test --workspace --exclude contextforge_a2a_runtime` passes.
8. **`.omo/evidence/c4-audit-checklist.md`** exists and shows every A2A 1.0.0 spec requirement either cited to an existing assertion or covered by a Wave 2 gap-closure test.
9. **`.omo/evidence/task-6-error-mapping-table.md`** exists with every gateway-owned error trigger mapped to a wire location and a test (Oracle re-review #14).
10. **Live smoke (F3)** passes all 13 manual QA scenarios against running gateway with both echo agents (ports 9100 + 9101).
11. **`mkdocs build`** runs clean with `docs/docs/architecture/a2a-native.md` present, including a section that explicitly documents (i) the legacy v0.3 alias support timeline and end-of-support policy (Oracle #26) and (ii) the Rust runtime deprecation cycle naming release N (warning) and N+1 (removal).
12. **End-to-end CRUD/UI flow**: admin can create a server with `associated_a2a_agents=[echo_agent_id]` (the UUID returned from `POST /a2a`, NOT the name `"echo"` — verified `server_service.py:226` queries `at.model.id.in_(ids)`) through the BROWSER UI (form submit, not just API); the v-server URL `/servers/{server_id}/a2a/echo` then serves a card and dispatches (the URL path uses `echo` as the agent NAME — name vs ID distinction is consistent across the plan).
13. **No security regression in v-server cards**: `pytest tests/integration/test_a2a_native_routes.py::test_vserver_card_membership` proves a foreign-agent card request at `/servers/{X}/a2a/foreign/.well-known/agent-card.json` returns 404, NOT a forged card (Oracle re-review #2).
14. **User explicit go-ahead** to push the branch (this plan does NOT auto-push).

Anything less than ALL of these = not done. No "ship it with a follow-up TODO" carve-outs.
