HANDOFF CONTEXT
===============

USER REQUESTS (AS-IS)
---------------------
- Review the text, comments and diff of PR #5417.  It was decomposed into several containing PRs.  I'm interested in which of those PRs inherited the content of 'mcpgateway/services/reverse_proxy_service.py' so I can find the core function implementation.
- Create a new branch and worktree.  I want a working version of ContextForge with that file included (as per PR #5417).  Include other changes needed to support the execution of the service (feature flagged).  Use the PR as a baseline reference but also your expertise and researched best practices.  Note the client is available via https://github.com/contextforge-org/mcp-reverse-proxy .  The service should support connection.  Ask me any clarifying questions needed.
- Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.
- I'd like to change up agents.  Please record all progress and tell me where the fully documented plan is located.

GOAL
----
Deliver a feature-flagged reverse-proxy MCP service that the maintained client at contextforge-org/mcp-reverse-proxy can connect to: authenticated WebSocket admission, typed protocol and lifecycle management, stable catalog discovery, tool/resource/prompt execution, stored downstream authentication, heartbeat reachability, and Redis-backed multi-worker routing. Implementation, broad focused verification, docs/chart validation, package/security gates, real-client verification, and the T8 five-lane fixed-point review all pass; T8 is complete.

CURRENT STATE
-------------
- Active worktree: .worktrees/reverse-proxy-service. Branch: feat/reverse-proxy-service.
- Phase 3 is complete and previously Oracle-gated. All Phase 4/5 implementation tasks T1 through T8 in `.omo/plans/reverse-proxy-phase4.md` are complete; T8 closed on HEAD 8e51f3a98 with the five-lane/Oracle fixed-point review terminating at pass 4 APPROVE with zero blocking findings, high confidence.
- Live maintained-client harness: `RP_E2E_RUN_ID=final-review-20260815-r3 tests/live_gateway/reverse_proxy/run.sh` passes 12/12 in 51.74 seconds and writes each run beneath `artifacts/reverse-proxy-e2e/<run-slug>/`. The harness proves discovery/catalog visibility, tool/resource/prompt calls, typed text and binary resource payloads with runtime MIME, stored bearer forwarding, fresh-connection downstream restart recovery, graceful client-stop fail-closed behavior, 3-second heartbeat eviction, Redis wrong-worker relay/control operations, post-start Redis outage fail-closed behavior and recovery, unauthenticated/query-token 401, token-scope 403, server-owned authority, feature-off route absence, and credential absence from client/gateway logs.
- The harness runs one gateway container with two Gunicorn workers, Redis, the pinned fast-test server, the repository compliance server, and the maintained client from a local clone. Its trap removes child processes, containers, network, and database volume.
- Live verification found and fixed gateway defects including pre-accept WebSocket denial collapsing intended 401/403 statuses to ASGI's default 403, metadata-only PROXIED resources raising `Resource has no content` before downstream dispatch, Redis registration promotion passing Lua keys/arguments in the wrong order, and public resource serialization losing typed blob content/runtime MIME.
- Redis MONITOR captured signed `rp_request` envelopes from a non-owner worker to the owner worker; 20 echo calls completed successfully.
- Maintained-client dependency status (re-verified this pass): the local `mcp-reverse-proxy` clone is at `7498177fe5d0a765ac94ba4fbe234a9713e91328`, one commit ahead and seven commits behind `origin/main` (`05c1cb3`). The working tree base matches `origin/main` exactly (PR #5/#6 merged; `git diff origin/main -- src/` shows only the local security deltas on top), and the upstream `tests/integration/` suite is present byte-identical to `origin/main` (untracked, recoverable). Merged PR #5/#6 content plus local compatibility/security edits are materialized as preserved dirty changes; `stash@{0}: On main: t8-client-local-edits` remains retained and untracked `uv.lock` must not be included. Re-verified this pass: **client suite passes 144/144** (unit + 4 integration + 4 security tests), including the fresh-connection re-registration proof (`test_handle_gateway_request_stores_pending_and_reregisters_when_health_recovers` and the 9 sibling recovery tests), the raw-frame redaction test (`test_gateway_request_never_logs_authentication_material`), and the auth-clearing regressions; Ruff across all 12 source files passes.
- The branch tracks `origin/feat/reverse-proxy-service` and is pushed through 929bca847 (user pushed and set upstream on 2026-08-18). The five T8 fix commits (09897c527..8e51f3a98) are local and unpushed.

WORK COMPLETED
--------------
Investigation and setup
- Traced PR #5417 and established that no decomposed successor PR inherited mcpgateway/services/reverse_proxy_service.py; the implementation lineage is 8304cbba9 -> 67f99c7c6 -> PR #5417 head 96b1fcf95.
- Created .worktrees/reverse-proxy-service on feat/reverse-proxy-service from origin/main.
- Researched PR #5417, ContextForge runtime and security seams, official MCP lifecycle behavior, and the maintained client contextforge-org/mcp-reverse-proxy at de001b3bce56ba99f00f5502b2569925e6d0ccc7.

Phase 1 and 2 foundations (3 commits, then an origin/main merge)
- 0ce15f69c feat(reverse-proxy): authenticated WebSocket admission with layered authorization. Header-only Bearer auth, Layer 1 token-scope checks, Layer 2 RBAC checks, and shared non-permission restrictions evaluated before acceptance.
- 413fced98 feat(reverse-proxy): typed wire protocol and process-local session manager. Strict client/server wire models in reverse_proxy_protocol.py; correlation-before-send, send-inclusive timeouts, disconnect cancellation, connection-scoped responses, and notifications in reverse_proxy_sessions.py.
- a3a7c6eec feat(reverse-proxy): stable catalog registration and PROXIED persistence. Stable IDs derive from canonical owner, trusted scope, and normalized server name; internal PROXIED gateway persistence with caller-owned transactions, keeping PROXIED out of public GatewayCreate input.
- 00ab6fc75 merge: origin/main into feat/reverse-proxy-service, reconciling 8 upstream commits with both intents preserved.

Phase 3 features (4 commits)
- 73507e812 feat(reverse-proxy): map stable catalog IDs to process-local connections.
- 3b1385e8d feat(reverse-proxy): MCP discovery and catalog reconciliation over typed sessions.
- 34aac19db feat(reverse-proxy): wire authenticated WebSocket lifecycle to typed session manager.
- aaa2d88d2 feat(reverse-proxy): dispatch PROXIED gateway tools through reverse-proxy sessions.

Phase 4/5 completion (uncommitted working tree)
- Added PROXIED `resources/read` and `prompts/get`, strict stored-auth forwarding, heartbeat reachability, typed HTTP session unification, Redis relay authority, and relay-aware tool/resource/prompt dispatch.
- Added nginx WebSocket upgrade routing and host-port parameterization for isolated live stacks.
- Updated discovery initialization to MCP `2025-11-25` with a maintained client identity.
- Added explicit HTTP WebSocket denial responses so unauthenticated/query-token admission returns 401 and insufficient token scope returns 403 before acceptance.
- Added a PROXIED resource placeholder resolver so metadata-only discovered rows dispatch downstream rather than reading absent cached content.
- Added the repeatable real-client harness, auth probe, Compose override, JUnit artifact, credential scans, and teardown receipts under `tests/live_gateway/reverse_proxy/`.
- Split the live scenarios into shared typed helpers, distributed/security E2E coverage, and an isolated feature-off test; the current isolated two-worker harness passes 12/12.
- Hardened post-start Redis failure handling: the Pub/Sub listener reconnects across stream and factory failures, partial subscription failures close their resources, relay heartbeat retries while remaining fail closed, and re-registration replaces only stale same-worker owner generations without disturbing live local sessions.
- The final broad reverse-proxy selector wrote `artifacts/reverse-proxy-e2e/unit-junit.xml`: 1,450 tests, zero failures/errors, and one skip in 36.959 seconds. A refreshed affected gateway selector also passed with the same one pre-existing skip; the maintained client passes 140/140 after upstream integration coverage and local security regressions were combined.
- Gateway quality evidence is green for `make ruff interrogate pylint`, focused feature-owned `ty`, changed-production Bandit, detect-secrets (529 reviewed findings, zero live or unaudited secrets), and `make verify` (package rating 10/10). The canonical docs build and Helm `validate-all`/`test-template` also pass. Repository-wide Bandit still reports one unchanged migration-string false positive, which must remain an explicit pre-existing waiver rather than being hidden by a reverse-proxy change.
- A prior five-lane review was superseded when T8 was reopened for distributed lifecycle, SSE/RBAC, blob-resource, harness-isolation, client-provenance, and gate-evidence gaps. Those functional blockers have been fixed. This pass fixed two additional regressions: (1) `read_resource` direct_proxy path re-invoking already-resolved `ResourceContents` (AttributeError on `.id`), fixed by separating `ResourceContents` from the `ResourceContent`/`TextContent` invocation branch; (2) `auth_context.get_user_email` nested `user.email` taking precedence over top-level `email`/`sub`, violating the canonical email-over-sub order, fixed by checking top-level `email` then non-UUID `sub` before falling through to nested `user.email`. Refreshed runtime, gateway, client, Helm, lint, package, and secret gates are complete; the new five-lane fixed-point review has since terminated at pass 4 APPROVE (see the closeout section below).

Phase 3 hardening (14 fix commits from the first Oracle fixed-point loop, 35ffb9bff through 74599f806)
- Registration lifecycle redesign: quiesce-first / promote-last so the catalog and the routing table never split; per-stable-ID serialized promotion with rollback; retirement of a quiesced predecessor on post-commit cancellation; registration run as a sibling of the receive pump.
- Concurrency and correctness: fail-closed dispatch on a missing stable ID; rejection of malformed list entries and cursors during discovery; rejection of list results missing their member, with publication deferred until after promotion; revalidated token team membership and hardened connection lifecycle.
- Dispatch integration: PROXIED tools excluded from Rust direct execution, with validation before success telemetry; shared server service injected and catalog caches always invalidated.
- Telemetry: `mcp_call_failed` emitted for proxied dispatch failures, logging only the MCP error code and keeping peer error text out of exceptions and telemetry.
- Lint cleanup across the protocol and sessions modules.

Second Oracle cycle (this change set)
- reverse_proxy_discovery.py gained `PEER_AUTHORITY_FIELDS` and `_strip_peer_authority_fields()`, applied in `_build_tools()`, `_build_resources()` (direct resource dicts and resource-template dicts), and `_build_prompts()` before schema validation. Both snake_case and camelCase spellings are stripped, because PromptCreate inherits a camelCase alias generator.
- gateway_service.py DbResource and DbPrompt CREATE branches now set `team_id=gateway.team_id` and `owner_email=gateway.owner_email`, mirroring `_create_db_tool()`.
- test_reverse_proxy_discovery.py gained a `team_scoped_proxy_pair` fixture and three regression tests (resource, prompt, tool), each driving a peer payload claiming public visibility and attacker-controlled ownership, each asserting the persisted row lands on the gateway's scope. Red-first was verified in both directions.

Second Oracle fixed-point cycle closeout, T8 complete (5 DCO-signed fix commits, 09897c527 through 8e51f3a98)
- The five-lane/Oracle fixed-point review terminated across 4 Oracle passes: pass 1 found 2 blocking (reachability-write TOCTOU vs replacement registration; Redis-failure compensation abort) + 1 functional (missing /reverse-proxy token-scope patterns) + 1 suggestion (fixed harness image tag); pass 2 found 1 new blocking (denied guard + pre-commit failure = stale reachable=True); pass 3 refined it (quiesced-is-not-None does not prove predecessor restored); pass 4 APPROVE with zero blocking findings, high confidence.
- 09897c527 fix(reverse-proxy): close distributed lifecycle races in registration and reachability persistence. New unreachable_write_guard lease serialization (SET NX on mcpgw:rp_registration:{stable_id}, owner re-check inside, held through DB commit, fenced release) wired at router/reaper/authority-loss call sites via an authority_guard seam; compensate() restructured so local restore/demotion/retirement is guaranteed in try with every Redis cleanup independently best-effort in finally; WS teardown persistence moved to finally.
- 5a3bc92fb fix(auth): map reverse-proxy session endpoints in token scope patterns. Four exact mappings (GET /reverse-proxy/sessions and GET /reverse-proxy/sse/{id} -> gateways.read; DELETE /reverse-proxy/sessions/{id} -> gateways.delete; POST /reverse-proxy/sessions/{id}/request -> tools.execute); default-deny preserved for unmapped paths.
- b13c750f9 test(reverse-proxy): scope live harness image tag per run. Default IMAGE_LOCAL includes RUN_SLUG; cleanup reaps it unless RP_GATEWAY_IMAGE externally supplied; isolation test asserts per-run image names differ.
- 7755b2fae fix(reverse-proxy): re-persist reachability after failed replacement registration releases its lease. Pre-commit failure with no restored predecessor re-evaluates reachability through the guarded persistence path after lease release.
- 8e51f3a98 fix(reverse-proxy): verify predecessor restoration before skipping unreachable persistence. Restoration verified via resolve_connection_id; unconfirmed restoration compare-releases the stale predecessor owner generation (fenced Lua compare-delete) before the guarded synthetic eviction.
- Final gate evidence on 8e51f3a98: focused unit suite 26 modules, 2062 collected, 2059 passed, 3 pre-existing skips (test_session_registry_extended.py Redis-pubsub skips); make ruff / interrogate (100.0%) / pylint (10.00/10) all exit 0; uv run ty check on changed production files clean (branch-wide ty noise is pre-existing baseline, zero introduced); live isolated harness 12/12 (run final-20260818-r1, junit artifact artifacts/reverse-proxy-e2e/final-20260818-r1/junit.xml; run-scoped image reaped; docker containers/networks/volumes verified empty after); detect-secrets 530 reviewed, 0 live, 0 unaudited.

T8 re-verification pass (2026-08-15, continuation)
- Client reconciliation re-proven (MUST10): working tree base byte-matches `origin/main` for all `src/` files (PR #5/#6 merged); upstream `tests/integration/` present and identical to `origin/main`; local security deltas (raw-frame redaction, per-request auth clearing, recovery cleanup, pending-registration guard) intact. Full client suite re-run: **144 passed** (unit + 4 integration + 4 security). Fresh-connection re-registration proven via `test_handle_gateway_request_stores_pending_and_reregisters_when_health_recovers` + 9 sibling recovery tests (10 passed, 50 deselected on the -k filter).
- Gateway reconciliation analyzed (MUST13): 9 commits behind `origin/main`; `git merge-tree --write-tree HEAD origin/main` exit 0 (clean 3-way, no conflict); 10 overlapping files auto-merge. Commit boundary remains the parent's call.
- Gate evidence re-run (MUST14): focused reverse-proxy suite **285 passed** (exit 0) across 8 test modules; `ruff check` clean on all 14 changed gateway files; client `ruff`/tests clean.
- Coverage spot-check (MUST3/MUST6/MUST7): same-owner insufficient-role 403 proven by `test_http_routes_require_method_specific_rbac` (permission gate fires before any ownership/session lookup, `manager_factory.assert_not_awaited()`); SSE contract covered by `test_sse_endpoint_success`/`handles_cancelled_error`/`not_found`/`distributed_sse_uses_remote_session_directory` (stub delivery remains explicitly out of scope); ghost raw-frame/empty-catch items live in the client and are covered by the 4 security tests. All four HTTP endpoints invoke `_require_http_permission` with method-specific permissions (list/SSE `GATEWAYS_READ`, delete `GATEWAYS_DELETE`, request `TOOLS_EXECUTE`); WS admission performs layered token-scope + RBAC + non-permission checks before accept.
- Charts additions (MUST11) are intentional, not churn: `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED` and `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT` documented in values.yaml, values.schema.json, and README for the T4/T7 knobs.

PENDING TASKS
-------------
- DONE: five-lane fixed-point review completed across 4 Oracle passes, terminating at pass 4 APPROVE with zero blocking findings, high confidence; T8 checked. Repository-wide Bandit still exits 1 only for the explicit pre-existing low-confidence B608 migration-string finding in `7ab59991e017`; detect-secrets passes all 530 reviewed findings.
- Push decision for the 5 local fix commits (09897c527..8e51f3a98): pending user direction.
- Origin/main reconciliation: DEFERRED per explicit user instruction on 2026-08-18 (no changes to origin/main to be attempted). The branch is 12 commits behind `origin/main`; earlier `git merge-tree --write-tree HEAD origin/main` analysis verified a clean conflict-free 3-way merge (exit 0). Reconciliation to happen at PR time.
- Production-stack protocol/RBAC/compliance (`make test-mcp-protocol-e2e test-mcp-rbac test-protocol-compliance`): WAIVED — port 8080 is occupied by an SSH tunnel (PID 34769), preventing `make testing-up`. The live isolated harness proves the same coverage on ephemeral ports: protocol E2E (tool/resource/prompt calls), RBAC (unauthenticated 401, token-scope 403), and compliance (server-owned authority, feature-off route absence).
- Reconcile or remove the retained client stash only after confirming every client edit is preserved; never include `uv.lock`.
- A2A remains outside the reverse-proxy scope.

KEY FILES
---------
- mcpgateway/routers/reverse_proxy.py - Authenticated WebSocket endpoint wired to the typed session lifecycle.
- mcpgateway/middleware/token_scoping.py - Shared non-permission token restriction evaluator used during WebSocket admission.
- mcpgateway/services/reverse_proxy_protocol.py - Strict client/server wire models and envelope builders.
- mcpgateway/services/reverse_proxy_sessions.py - Process-local live sessions, correlation, timeout, notification, and disconnect behavior.
- mcpgateway/services/reverse_proxy_catalog.py - Stable authenticated gateway/server catalog registration, quiesce/promote/restore/retire lifecycle, and transaction locking.
- mcpgateway/services/reverse_proxy_discovery.py - MCP initialize/initialized/discovery, peer authority stripping, and catalog reconciliation.
- mcpgateway/services/gateway_service.py - Internal PROXIED persistence plus catalog sync/reconcile helpers.
- mcpgateway/services/server_service.py - Caller-owned transaction support and deferred side effects.
- mcpgateway/services/tool_service.py - PROXIED tool dispatch inside invoke_tool().
- mcpgateway/services/reverse_proxy_relay*.py - Redis ownership, signed relay envelopes, listener, heartbeat, and runtime lifecycle.
- mcpgateway/services/resource_service.py and prompt_service.py - PROXIED resource/prompt dispatch and downstream auth forwarding.
- tests/live_gateway/reverse_proxy/ - Repeatable two-worker maintained-client E2E/security harness.
- tests/unit/mcpgateway/routers/test_reverse_proxy.py and tests/unit/mcpgateway/services/test_reverse_proxy_*.py - Focused regression suites.

IMPORTANT DECISIONS
-------------------
- Follow the maintained client contract, not stale client documentation or PR #5417 defects.
- Use the legacy MCP initialize -> notifications/initialized -> capability-gated list flow, because the maintained client's downstream transport requires initialize to establish its MCP session. Modern 2026-07-28 stateless MCP support is not required for this compatibility phase.
- Maintained client registration is register {server{name, description, protocol:"mcp"}}, followed by register_ack(processing) and register_complete(success|error).
- Heartbeat responses are acknowledgements; the client does not require a pong or a tools/list health probe.
- Reject client-selected authority everywhere: owner, team, visibility, stable gateway/server ID, connection ID, and now every peer-advertised authority field on discovered tools, resources, and prompts.
- Preserve PR #5417 catalog scope semantics: trusted team state gives team visibility; otherwise platform-public visibility.
- Put proxied tool dispatch in ToolService.invoke_tool() so authorization, plugins, auth propagation, tracing, timeout accounting, metrics, and result normalization stay intact.
- Use persisted original_name for downstream tools/call, not the namespaced public tool name.
- Multi-worker routing uses Redis as the ownership authority and fails closed when Redis cannot establish the owner generation.
- Do not copy PR #5417 wholesale. It trusted client session IDs and installed response futures after sending, creating authority and race defects.

EXPLICIT CONSTRAINTS
--------------------
- Include other changes needed to support the execution of the service (feature flagged).
- Use the PR as a baseline reference but also expertise and researched best practices.
- Do not accept inbound client auth tokens via URL query parameters.
- Never trust client-provided ownership fields (`owner_email`, `team_id`, session owner); derive authorization from authenticated identity and server-side state.
- Security-sensitive changes must include deny-path regression tests (unauthenticated, wrong team, insufficient permissions, feature disabled).
- Don't push until asked.
- Never create files unless absolutely necessary; prefer editing existing files.

CONTEXT FOR CONTINUATION
------------------------
- The completion plan lives at `.omo/plans/reverse-proxy-phase4.md`. `.omo/` is gitignored, so the plan and notepads are worktree-local and are not carried by the branch.
- Review findings and their fixes are recorded in .omo/notepads/reverse-proxy-phase3/issues.md.
- Focused regression command:
  uv run pytest tests/unit/mcpgateway/services/test_reverse_proxy_protocol.py tests/unit/mcpgateway/services/test_reverse_proxy_sessions.py tests/unit/mcpgateway/services/test_reverse_proxy_catalog.py tests/unit/mcpgateway/services/test_reverse_proxy_catalog_identity_contracts.py tests/unit/mcpgateway/services/test_gateway_service_reverse_proxy.py tests/unit/mcpgateway/services/test_reverse_proxy_discovery.py tests/unit/mcpgateway/services/test_tool_service_reverse_proxy.py tests/unit/mcpgateway/routers/test_reverse_proxy.py -q
- Use uv-based project commands; this environment has no bare python command.
- Phase 3 research sessions: ses_00e5d17feffeT0vyeT1fDd0PwC, ses_00e5d1808ffeVEJ23kPFDooZxP, ses_00e5d1906ffeoL2tC4DtKR4cjV, ses_00e5d20f1ffe0E9vUHYb7hXbB1, ses_00e5d20f8ffeahyKNCFzsfKT3F.
- Phase 2 catalog implementer: ses_00e83e28affe9Ui8COYT2BS41M. Phase 2 Oracle reviewer: ses_00e778b88ffesZEC1A6Ha5m2xs.
