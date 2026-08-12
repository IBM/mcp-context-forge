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
Deliver a feature-flagged reverse-proxy MCP service that the maintained client at contextforge-org/mcp-reverse-proxy can connect to: authenticated WebSocket admission, a typed wire protocol, stable catalog registration, MCP discovery/reconciliation, and proxied tool execution. Phases 1 through 3 are now complete. Distributed affinity and real-client E2E remain as Phase 4 and Phase 5.

CURRENT STATE
-------------
- Active worktree: .worktrees/reverse-proxy-service. Branch: feat/reverse-proxy-service.
- Phase 3 is COMPLETE and Oracle-gated. All Phase 3 implementation tasks (0 through 5) in .omo/plans/reverse-proxy-phase3.md are done and their acceptance criteria are met.
- Tests: 260 focused reverse-proxy tests pass, plus the broader tests/unit/mcpgateway/services/test_gateway_service.py suite at 362 passed / 1 skipped.
- Lint and docs gates: `make ruff interrogate pylint` clean.
- Review: two full Oracle fixed-point review cycles ran. Cycle 1 raised two blocking findings, both fixed:
  1. A stale design-doc lifecycle description (plan sections D2/D4 still described the pre-redesign single-shot `attach_stable_id()` API instead of the current quiesce / promote / restore / retire lifecycle).
  2. A peer-controlled visibility and ownership leak in discovered resources and prompts. A team-scoped peer could advertise `visibility: "public"` (plus `team_id`, `owner_email`, `gateway_id`) in its `resources/list` and `prompts/list` responses and widen the resulting catalog row past its own authenticated scope; the CREATE branches in gateway_service.py also left those rows team-orphaned. Detail is recorded in .omo/notepads/reverse-proxy-phase3/issues.md.
  Cycle 2 confirmed zero remaining blocking findings.
- Nothing has been pushed. The branch is local-only, per the standing instruction.

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

PENDING TASKS (out of scope for Phase 3)
----------------------------------------
Both items below are listed as explicit follow-ons in .omo/plans/reverse-proxy-phase3.md and are deliberately not part of this branch's Phase 3 delivery.

- Phase 4: distributed affinity and lifecycle. Multi-worker routing, health, unregister semantics, and startup/shutdown; reachable-status lifecycle; legacy manager unification.
  Multi-worker limitation (honest note): the stable-ID to connection-ID mapping is process-local. In a multi-worker deployment, a tool invoke routed to a worker that does not own the WebSocket fails closed with "no active reverse-proxy connection" until Phase 4 lands distributed routing.
- Phase 5: real maintained-client E2E and security verification.

Also explicitly out of scope: resource and prompt read dispatch through the proxy (Phase 3 covers discovery plus `tools/call` only), and A2A.

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
- tests/unit/mcpgateway/routers/test_reverse_proxy.py and tests/unit/mcpgateway/services/test_reverse_proxy_*.py - Focused suite (260 tests).

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
- Keep process-local socket lookup fail-closed in Phase 3 and state the multi-worker limitation honestly; distributed routing belongs to Phase 4.
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
- The Phase 3 plan lives at .omo/plans/reverse-proxy-phase3.md. Note that .omo/ is gitignored, so the plan and notepads are worktree-local and are not carried by the branch.
- Review findings and their fixes are recorded in .omo/notepads/reverse-proxy-phase3/issues.md.
- Focused regression command:
  uv run pytest tests/unit/mcpgateway/services/test_reverse_proxy_protocol.py tests/unit/mcpgateway/services/test_reverse_proxy_sessions.py tests/unit/mcpgateway/services/test_reverse_proxy_catalog.py tests/unit/mcpgateway/services/test_reverse_proxy_catalog_identity_contracts.py tests/unit/mcpgateway/services/test_gateway_service_reverse_proxy.py tests/unit/mcpgateway/services/test_reverse_proxy_discovery.py tests/unit/mcpgateway/services/test_tool_service_reverse_proxy.py tests/unit/mcpgateway/routers/test_reverse_proxy.py -q
- Use uv-based project commands; this environment has no bare python command.
- Phase 3 research sessions: ses_00e5d17feffeT0vyeT1fDd0PwC, ses_00e5d1808ffeVEJ23kPFDooZxP, ses_00e5d1906ffeoL2tC4DtKR4cjV, ses_00e5d20f1ffe0E9vUHYb7hXbB1, ses_00e5d20f8ffeahyKNCFzsfKT3F.
- Phase 2 catalog implementer: ses_00e83e28affe9Ui8COYT2BS41M. Phase 2 Oracle reviewer: ses_00e778b88ffesZEC1A6Ha5m2xs.
