# F1 Plan Compliance Audit — A2A Native Passthrough

**Verdict**: APPROVE
**Auditor**: Oracle (read-only)
**Branch**: wxo-2026-06 @ 22a70fe12
**Plan**: .omo/plans/a2a-native-passthrough.md

## Must-have coverage (C1-C8)

1. **C1 — PRESENT**: Control-plane helpers exist in `mcpgateway/services/a2a_service.py`: `validate_a2a_version` at `:593` (`44a7038cb`), `check_server_a2a_membership` at `:930` (`61c8fbaee`), `resolve_agent_for_dispatch` at `:982` (`61c8fbaee`), `synthesize_agent_card` at `:1116` (`f7413b82f`), `dispatch_a2a_jsonrpc_unary` at `:1290` (`bc2a495ce`), and `dispatch_a2a_jsonrpc_streaming` at `:1389` (`1e456b43`). Server-side A2A association authorization is wired through `mcpgateway/services/server_service.py:211-263` (`2727d6015`, hardened by `bd551b215`, snapshot-updated by `84d6ffed8`).

2. **C2 — PRESENT**: Per-agent card endpoint exists at `mcpgateway/main.py:5195` (`00e6fc9f`), is public/no `require_permission` per `:5203-5207`, resolves public base via `settings.app_domain`/`a2a_public_base_url` at `:5241`, and calls synthesizer with `token_teams=[]` at `:5264-5270`. Dispatch endpoint exists at `mcpgateway/main.py:5419` (`e0a61d75b`) with raw body parsing at `:5520-5529`, method-aware version validation at `:5534-5542`, `a2a.read` for extended cards at `:5548-5558`, `a2a.invoke` for other methods at `:5629-5639`, DB-synthesized extended card at `:5600-5609`, and SSE streaming at `:5641-5703`.

3. **C3 — PRESENT**: `A2APathRewriteMiddleware` exists in `mcpgateway/middleware/a2a_path_rewrite.py:56` (`eda88d88a`), uses regex `^/servers/([^/]+)/a2a/([^/]+)(/.*)?$` at `:53`, rewrites to `/a2a/{agent_name}{suffix}` at `:119-124`, and stores `scope["a2a_server_id"]`. Card/dispatch handlers consume that scope at `mcpgateway/main.py:5268` and `:5497`.

4. **C4 — PRESENT**: Compliance audit evidence exists at `.omo/evidence/c4-audit-checklist.md:1-17` (`cbd583a87`, re-pass `d1c2544fb`). Gap-closure tests landed under `tests/live_gateway/a2a_compliance/v1_0_0/*_extra.py` via `fd03f8f05` and `d219df7e9`, with RBAC fixture closeout in `22a70fe12`.

5. **C5 — PRESENT**: Server CRUD A2A association auth/wiring exists in `mcpgateway/services/server_service.py:211-263` and response round-trip includes `associated_a2a_agents` at `:550`. Admin UI POST handling reads `associatedA2aAgents` in `mcpgateway/admin.py:3044` and `:3212`, JS submit wiring is in `mcpgateway/admin_ui/formSubmitHandlers.js:445-455`, selectors are in `mcpgateway/templates/admin.html:2949-2966` and `:11494-11512`, card URL affordance is in `mcpgateway/admin_ui/a2aAgents.js:76-90`, and end-to-end form persistence is tested in `tests/integration/test_admin_server_a2a_flow.py:16-31`.

6. **C6 — PRESENT**: Rust runtime deprecation is staged, not physically deleted. Startup warning exists in `mcpgateway/main.py:1318-1330` (`dd2ff02a3`), `Cargo.toml:11-20` excludes `contextforge_a2a_runtime` from default members while preserving workspace membership (`5259def29`), Rust call-site branches were removed by `248b6faa2`, and config fields remain with deprecation comments at `mcpgateway/config.py:336-360` (`f2c47bb8`).

7. **C7 — PRESENT**: Compliance harness now has live gateway targets in `tests/live_gateway/a2a_compliance/conftest.py:13-21` and matrix cases at `:47-50` (`24a6f9aa3`). Gateway target clients use real `ClientFactory(config=...)` in `targets/gateway_proxy.py:49-59` and `targets/gateway_virtual.py:45-55` (`bb4132fd9`). The blanket GAP-001 xfail hook is removed; only targeted fixture/environment skips remain.

8. **C8 — PRESENT**: Architecture documentation exists at `docs/docs/architecture/a2a-native.md:1-19` (`4c3504b46`), includes URL families, path rewrite, synthesizer, RBAC, versioning, streaming, hooks, Rust deprecation, and harness sections. It is linked from `docs/docs/architecture/index.md:109`.

## Must-NOT compliance (1-20)

1. **PASS**: New native handlers use `Depends(get_current_user_with_permissions)` and `get_rpc_filter_context`; no JWT claim parsing in handlers. Evidence: `mcpgateway/main.py:5420-5425`, `:5484-5490`.

2. **PASS**: JSON-RPC envelope errors return HTTP 200 JSON bodies; transport errors remain HTTP statuses. Evidence: parse error and invalid body at `mcpgateway/main.py:5520-5529`, version error at `:5537-5542`, RBAC 403 at `:5557-5558` and `:5638-5639`, path 404 at `:5501-5506`.

3. **PASS**: Native card models reject top-level `protocolVersion`; `protocolVersion` lives on `SupportedInterface`. Evidence: `mcpgateway/schemas_a2a_native.py:118-126`, tests at `tests/unit/mcpgateway/test_a2a_native_schemas.py:97-102`.

4. **PASS**: Native card uses `protocolBinding`, not `transportProtocol`. Evidence: `mcpgateway/schemas_a2a_native.py:124-126`, compliance assertion `tests/live_gateway/a2a_compliance/v1_0_0/test_agent_card_extra.py:44-65`.

5. **PASS**: Legacy `POST /a2a/{agent_name}/invoke` predates this branch and is not mutated by scoped diff; blame shows old commits at `mcpgateway/main.py:5092-5112`.

6. **PASS**: No new Rust code was added; Rust work is deprecation/config only. Evidence: `Cargo.toml:11-20`; no `crates/a2a_runtime/` source diff in scoped check.

7. **PASS**: No DB model/schema/migration changes for this plan. Evidence: scoped diff over `mcpgateway/alembic`, `mcpgateway/db.py`, `mcpgateway/schemas.py` returned no plan changes.

8. **PASS**: No new permission strings; native dispatch uses existing `a2a.read` and `a2a.invoke`. Evidence: `mcpgateway/db.py:1357-1361`; handler checks at `mcpgateway/main.py:5551` and `:5632`.

9. **PASS**: Card synthesis rewrites URL to gateway coordinates and does not pass upstream URL. Evidence: `mcpgateway/services/a2a_service.py:1234-1239`.

10. **PASS**: No global mutable state in handlers for per-request A2A dispatch; request-scoped values flow via args/scope. Evidence: `mcpgateway/main.py:5484-5518`, `:5601-5609`, `:5672-5679`.

11. **PASS**: Compliance matrix shape remains target/transport based; target constructors are still simple classes in `targets/gateway_proxy.py:38-58` and `targets/gateway_virtual.py:33-54`.

12. **PASS**: `crates/a2a_runtime/` is not deleted; only default-members exclusion landed. Evidence: `Cargo.toml:5-20`.

13. **PASS**: No general method whitelist was introduced; gateway special-cases only extended-card and streaming handling, while other methods go through unary dispatch. Evidence: `mcpgateway/main.py:5548-5627`, `:5641-5705`, `mcpgateway/services/a2a_service.py:1350-1353`.

14. **PASS**: Phase-1 card advertises JSON-RPC only. Evidence: `mcpgateway/schemas_a2a_native.py:124-126`; compliance test expects `JSONRPC` at `test_agent_card_extra.py:68-87`.

15. **PASS**: Bearer forwarding and UAID plumbing reuse existing `invoke_agent` path. Evidence: native route extracts bearer/hop like legacy path at `mcpgateway/main.py:5508-5518`, unary dispatch calls `invoke_agent` with `bearer_token`, `hop_count`, and headers at `mcpgateway/services/a2a_service.py:1368-1379`.

16. **PASS**: Native synthesis does not reuse legacy `get_agent_card()`. Evidence: synthesizer doc/code at `mcpgateway/services/a2a_service.py:1125-1132`; it builds fresh interface URL at `:1234-1239`.

17. **PASS**: Native JSON-RPC route has no `Body(...)`; manual parse is used. Evidence: function signature `mcpgateway/main.py:5419-5426`; body read/parse at `:5520-5529`.

18. **PASS with caveat**: No generic `PUBLIC_BASE_URL` config/reference is used for native A2A. UI uses scoped `window.A2A_PUBLIC_BASE_URL`, populated from compliant server-side `a2a_public_base_url`/`settings.app_domain` at `mcpgateway/admin.py:4113` and `mcpgateway/templates/admin.html:12270`; route logic uses the same source at `mcpgateway/main.py:5241` and `:5601`.

19. **PASS**: C4 audit/gap tests landed before C2/C3 implementation commits: `cbd583a87`, `fd03f8f05`, `d219df7e9`, `d1c2544fb` precede `00e6fc9f`, `e0a61d75b`, and `eda88d88a` in chronological log.

20. **PASS**: CRUD/UI verification was not deferred; T20/T21/T22 landed via `2727d6015`, `7b965a962`, `81820b68a`, and `77b73562d`, with integration evidence in `tests/integration/test_admin_server_a2a_flow.py:16-31`.

## Amendment status verification (A-I)

- **A — DOCS_MATCH_CODE**: Policy module exists and is the central decision point. Evidence: `mcpgateway/services/a2a_access_policy.py:68`, `:130`, `:195`; service delegates at `mcpgateway/services/a2a_service.py:1211-1229`.
- **B — DOCS_MATCH_CODE**: Three-level v-server access is encoded in policy docs/body. Evidence: `mcpgateway/services/a2a_access_policy.py:139-153`; card/dispatch collapse denials to 404 at `mcpgateway/main.py:5501-5506`.
- **C — DOCS_MATCH_CODE**: `CallerContext` sentinel exists and bypass is explicit. Evidence: `mcpgateway/services/caller_context.py:65-81`; server service bypass checks `caller_context.is_system` at `mcpgateway/services/server_service.py:243`.
- **D — DOCS_MATCH_CODE**: T21A/T21B split is implemented and T22 verifies POST persistence. Evidence: `formSubmitHandlers.js:445-455`, `admin.html:2949-2966`, `a2aAgents.js:76-90`, `test_admin_server_a2a_flow.py:16-31`.
- **E — DOCS_MATCH_CODE**: Future policy-engine migration is documented as out-of-scope/provisional. Evidence: `mcpgateway/services/a2a_access_policy.py:16-23` and `:116-122`.
- **F — DOCS_MATCH_CODE**: Stage (a) helper extraction/placeholders is done; stage (b) real cpex hook bodies remain deferred. Evidence: `mcpgateway/services/a2a_hooks.py:358-384`, call sites in `mcpgateway/main.py:5243-5278`, `:5560-5580`, `:5641-5703`, proposal doc `docs/docs/architecture/a2a-cpex-hook-proposal.md`.
- **G — DRIFT**: Plan text still says `Status: PROPOSED` at `.omo/plans/a2a-native-passthrough.md:984`, but code implemented all three parts in `d52d23854`, `9c57030b1`, and `84d6ffed8`. Evidence: `A2AAgentSnapshot` at `mcpgateway/services/a2a_hooks.py:55`, policy consuming snapshot at `mcpgateway/services/a2a_access_policy.py:71` and `:127`.
- **H — DOCS_MATCH_CODE**: Case-sensitive lookup accepted by plan and code. Evidence: exact-name query in `mcpgateway/services/a2a_service.py:1188-1190`; legacy route also pre-existing/case-sensitive by blame.
- **I — DRIFT, non-blocking**: I.1 and I.2 plan entries still say deferred at `.omo/plans/a2a-native-passthrough.md:1022` and `:1039`, but both have since landed (`4c3504b46` for docs, `22a70fe12` for fixtures). I.3 remains correctly deferred as a program-level 250 LOC concern.

## Commit-to-todo mapping

| Commit | T-number or Amendment | Brief description |
|---|---|---|
| c5a39bd3a | Planning precheck | Resolve 6 pre-execution checklist items |
| 87c59ba3f | T1 | A2A 1.0.0 Pydantic models |
| 61c8fbaee | T3 | Agent resolution + v-server membership helpers |
| f7413b82f | T2 | Fresh A2A card synthesis |
| e3e13768d | T6 | JSON-RPC error helpers + mapping table |
| 44a7038cb | T7 | A2A-Version validation |
| bc2a495ce | T4 | Unary JSON-RPC dispatch |
| 1e456b43e | T5 | Streaming JSON-RPC dispatch |
| 58a6cf6f4 | Planning/T1 QA | Per-wave gate update + Wave 1 coverage |
| d6f0247d7 | T28-A | Gateway fixture plumbing, part A |
| cbd583a87 | T8 | C4 coverage audit checklist |
| fd03f8f05 | T9 | Card-discovery gap-closure tests |
| d219df7e9 | T10 | Dispatch/error/SSE/version/RBAC tests |
| d1c2544fb | T8 | Audit re-pass after gap closure |
| 00e6fc9f5 | T11 | Public well-known A2A card endpoint |
| e0a61d75b | T12/T14 | Native dispatch + SSE response wrapper |
| 1b8014898 | T13 | Route ordering regression |
| b775a513f | T15 | Proxy compliance smoke |
| eda88d88a | T16 | V-server path rewrite middleware |
| ef3edb6b0 | Amendment A/B | Centralized A2A access policy |
| a80e640d9 | T17/T18 | V-server card + dispatch integration |
| 2727d6015 | T20 | CRUD authorization for A2A associations |
| b6e45561d | T19 | V-server composition E2E |
| 7b965a962 | T21A | JS submit handler |
| bd551b215 | Amendment B/C/E | CallerContext hardening and policy doc fixes |
| 8b65a22d5 | Amendments A-F | Insert session amendments |
| 81820b68a | T21B | Selector + card URL affordance |
| 77b73562d | T22 | Admin form POST persistence test |
| dd2ff02a3 | T23 | Rust runtime flag warning |
| 5259def29 | T24 | Exclude Rust A2A crate from default members |
| 248b6faa2 | T25 | Drop Rust runtime branches |
| f2c47bb8d | T26 | Deprecate runtime module/config/reporting |
| 1bf117b52 | T27 | Full-system smoke after Rust deprecation |
| 2bc20d26d | T28-B | Server fixture and sanity test |
| bb4132fd9 | T29 | Target classes use real ClientFactory |
| 24a6f9aa3 | T30 | Close A2A-GAP-001 |
| 64664ca7f | Amendment F | Phase C deferral decision |
| 676130982 | Amendment F stage (a) | Hook helpers + placeholder wiring |
| 723d6951b | Amendment G plan | Snapshot proposal and Phase C closeout docs |
| 3c63dbb10 | Unmapped hygiene | `.gitignore` consolidation |
| 059a376e7 | F1/F2 fixes | Double-wrap, streaming auth, stale docs |
| 268b33ef1 | Amendment H/I + hygiene | Case-sensitive plan closeout + `.omo` allowlist |
| c900cf652 | Unmapped hygiene | Pre-commit restage reformats |
| d52d23854 | Amendment G part 1 | Introduce `A2AAgentSnapshot` |
| 9c57030b1 | Amendment G part 2 | `invoke_agent` consumes snapshot |
| 84d6ffed8 | Amendment G part 3 | Policy + `_check_agent_access` consume snapshot |
| 4c3504b46 | T31 / I.1 | Architecture doc |
| 22a70fe12 | I.2 | Team-scoped + per-permission compliance fixtures |

## Unmapped commits (red flag)

- `3c63dbb10` — `.gitignore` consolidation; workflow hygiene, not a plan deliverable.
- `c900cf652` — pre-commit restage reformats touching `mcpgateway/schemas_a2a_native.py`, `mcpgateway/services/metrics.py`, and `mcpgateway/tools/builder/build_hooks.py`; not traceable to a specific T-number or amendment.
- `268b33ef1` is mostly mapped to Amendment H/I, but its `.gitignore` allowlist portion is workflow hygiene.

## Findings

### Blocking (would block APPROVE)

none

### Non-blocking observations

- Amendment G and Amendment I.1/I.2 status text in the plan is stale relative to code reality; the code is ahead of the documented status, not behind it.
- Two hygiene commits are not plan-scoped. They do not appear to violate Must-NOT guardrails, but they should be called out if this branch is reviewed for strict atomic plan history.
- `A2A_PUBLIC_BASE_URL` is a scoped UI variable backed by the approved `a2a_public_base_url`/`settings.app_domain` source. I do not treat it as the forbidden generic `PUBLIC_BASE_URL` pattern, but reviewers may want to rename it if they interpret the guardrail literally.

## Final verdict

APPROVE — every Must-have deliverable is present, no Must-NOT guardrail violation was found, and the remaining issues are documentation/status drift or hygiene-history concerns rather than plan-compliance blockers.
