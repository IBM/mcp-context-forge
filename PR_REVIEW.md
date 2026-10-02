# PR #6984: feat(loadtest): pin prod-up resources and add legacy/modern benchmark mode

**Author**: @Lang-Akshay | **Branch**: `py-performance-testing` → `main` | **State**: Open

## Summary

This PR adds a production Compose resource overlay and `prod-up`/`prod-down`, plus a fixed-tool Locust benchmark with legacy/modern routing and report summarization. The resource overlay renders successfully and the invalid-mode guard works, but the new production entrypoint inherits host-published development services and the benchmark's documented `PROD_BENCH_RUN_TIME` knob is ignored because the recipe uses `TIME`. The delegated security review returned `SECURITY_VERDICT=BLOCK`; merge readiness is therefore blocked.

## Findings (AGENTS.md format)

blocking | Makefile:5817-5827 | `prod-up` presents the base development Compose stack as production while retaining host-published HTTP, Fast Time, PostgreSQL, PgBouncer, and Redis endpoints; bearer traffic is also plain HTTP | Use a hardened production compose definition/override that keeps databases and caches internal, binds diagnostics deliberately, and requires TLS or explicitly documents and enforces a local-only benchmark target.

blocking | Makefile:2772,2914; tests/performance/performance.md:63 | The documented `make prod-benchmark-tools PROD_BENCH_RUN_TIME=10s` command does not change runtime: the target defines and consumes `TIME`, so it silently runs the 1800-second default | Replace `TIME` with the documented `PROD_BENCH_RUN_TIME` (or change the documentation and expose the required stable knob), then verify the command passes the requested duration to Locust.

functionally-impacting | Makefile:2872,2886-2922,5819 | Make variables are interpolated into shell source and command arguments without robust quoting; e.g. `REPLICA='3; echo INJECTED'` renders an injected command, and `PROD_BENCH_USER` is inserted into the Python command | Pass values through environment variables/positional parameters, quote every expansion, and validate numeric, URL, path, and mode inputs before invoking shell commands.

functionally-impacting | Makefile:2778,2883-2884,2908-2909 | The bearer token is expanded into the `bash -c` command text and the gateway signing secret is passed to Locust; an operator-supplied host can receive the token | Keep secrets out of command-line text, avoid passing the signing key unless required, and restrict benchmark hosts or require an explicit safe-host opt-in.

functionally-impacting | Makefile:2766-2772,2869-2924 | The linked #7003 contract asks for `USERS`, `SPAWN_RATE`, `RUN_TIME`, `WORKERS`, `FAST_TIME_IMAGE`, and `OUT_DIR` plus a third-party lane, but this target only supplies `PROD_BENCH_USERS`, `PROD_BENCH_SPAWN_RATE`, `TIME`, and legacy/modern modes | Either implement the remaining documented issue contract or explicitly split/defer those lanes and knobs in the PR/issue description.

suggestion | docker-compose.prod.yml:12-18,24-34; Makefile:5819 | `REPLICA` is unbounded while each gateway replica requests 4 CPU and 4 GiB, so an accidental large value can exhaust host capacity | Validate a positive bounded replica count and document the capacity budget.

## Blocking Changes

| # | Area | File | Line | Blocking reason | Required change |
| - | ---- | ---- | ---- | --------------- | --------------- |
| 1 | Security | Makefile | 5817-5827 | The delegated security review found that the new production start path exposes the base stack's HTTP, database, PgBouncer, Redis, and Fast Time host ports and bearer traffic remains HTTP. `SECURITY_VERDICT=BLOCK`. | Harden the production compose path (internalize database/cache/diagnostic ports and require TLS), or rename and enforce this as a local-only benchmark path rather than a production stack. |
| 2 | Quality / Breaking contract | Makefile; `tests/performance/performance.md` | 2772, 2914; 63 | The documented 10-second invocation uses `PROD_BENCH_RUN_TIME`, but the target only reads `TIME`; the documented command therefore uses the 30-minute default. This breaks the documented Make/environment contract and can unexpectedly run a benchmark for 30 minutes. | Add and consume `PROD_BENCH_RUN_TIME` (or change the published contract consistently) and verify the requested duration reaches Locust. |

## Unblocking Changes

| # | Area | File | Line(s) | Non-blocking observation | Suggested improvement |
| - | ---- | ------- | ------- | ------------------------ | --------------------- |
| 1 | Security | Makefile | 2872, 2886-2922, 5819 | User-controlled Make variables are interpolated into shell source/arguments. A dry run with `REPLICA='3; echo INJECTED'` rendered the injected command; `PROD_BENCH_USER` was also rendered directly into the token-generation command. | Use environment variables or positional parameters, shell-quote all values, and validate numeric/path/URL inputs. |
| 2 | Security | Makefile | 2778, 2883-2884, 2908-2909 | The bearer token appears in the generated `bash -c` command text, the signing secret is passed to Locust, and an arbitrary benchmark host can receive the token. | Keep credentials out of process arguments, avoid exporting the signing key to Locust unless needed, and allowlist or explicitly gate non-local hosts. |
| 3 | Issue completion | Makefile; docker-compose.prod.yml | 2766-2924; 1-47 | #7003 remains only partially covered: the requested `WORKERS`, `FAST_TIME_IMAGE`, `OUT_DIR`, and third-party lane are absent, and the exact requested `MODE`/`RUN_TIME` interface differs from this PR's `PROD_BENCH_MODE`/`TIME` interface. | Clarify the split in the issue/PR or implement the remaining lanes and stable knobs. |
| 4 | Resource safety | docker-compose.prod.yml; Makefile | 12-18, 24-34; 5819 | The fixed 4 CPU/4 GiB reservation applies to six services (32 CPU/32 GiB at the default three replicas), while `REPLICA` has no bound. | Validate a bounded positive replica count and document minimum host capacity. |

## Issues

| Issue | Title | Status | Notes |
| ----- | ----- | ------ | ----- |
| #6983 | [CHORE]: Pin production compose resources for the Python control plane stack | ⚠️ Partial | The resource overlay and `prod-up`/`prod-down` are present and match the stated six-service 4 CPU/4 GiB table. The linked issue explicitly leaves benchmark rerun and `docker stats` capture for later; this PR also says those two items are not included. |
| #7003 | [CHORE]: Add make prod-benchmark-tools MODE=modern\|legacy to cf-integration | ⚠️ Partial | Legacy/modern target, defaults, mode-specific report names, preflight, and summary invocation are present. The linked acceptance list also asks for `RUN_TIME`/other knobs, workers, pinned Fast Time image handling, manifest details, and a third-party lane; those are not visible in the non-test diff, and test-file contents were excluded. |

## Reviewer Comments

No reviewer comments found (both pull-request review comments and issue-style comments were empty).

## Security

The delegated `security-reviewer` scanned the non-test Makefile and Compose overlay directly; test-file contents were not inspected. It reported one High, two Medium, and one Low finding and ended with `SECURITY_VERDICT=BLOCK`. The merged Compose configuration validated successfully, but confirmed inherited host-port exposure and the Make dry run confirmed command injection through unquoted variables.

| # | File | Line | Severity | CWE | Description | Fix |
| - | ---- | ---- | -------- | --- | ----------- | --- |
| 1 | Makefile | 5817-5827 | High | CWE-16/CWE-319 | `prod-up` starts the exposed base stack as a production stack: HTTP 8080, Fast Time 8888, PostgreSQL 5433, PgBouncer 6432, and Redis 6379 remain host-published; bearer traffic is HTTP. | Harden the production compose definition, internalize database/cache/diagnostic ports, and require TLS, or explicitly enforce local-only use. |
| 2 | Makefile | 2872, 2886-2922, 5819 | Medium | CWE-78 | Make variables are embedded in shell code without robust quoting; injected `REPLICA` and benchmark-user values alter the generated command. | Use environment/positional parameters, quote expansions, and validate mode, numbers, paths, URLs, and replica count. |
| 3 | Makefile | 2778, 2883-2884, 2908-2909 | Medium | CWE-200 | Bearer tokens are expanded in the `bash -c` text, the gateway signing key is passed to Locust, and the token can be sent to an operator-selected host. | Keep secrets out of process arguments, do not pass the signing key unless necessary, and restrict hosts. |
| 4 | docker-compose.prod.yml; Makefile | 12-18, 24-34; 5819 | Low | CWE-400 | Four CPU/four GiB reservations apply to every listed service and unbounded replicas can exhaust host capacity. | Bound `REPLICA` and document capacity requirements. |

No ContextForge token-scoping/RBAC implementation is changed. The preflight uses an Authorization header rather than a URL query parameter; no hardcoded credentials were added.

## Breaking Change

**Verdict**: `No`

No existing HTTP API, database schema, Helm value, or existing Make target is removed or renamed. The new `prod-up`, `prod-down`, `create-token`, `prod-benchmark-tools`, and `PROD_BENCH_*` variables are additive. The documented runtime mismatch is a new-target correctness/contract defect, not a breaking change to an existing consumer contract.

## Out of Scope Changes

| # | File | Line(s) | Out-of-scope change | Why not traceable to issue/PR intent |
| - | ------ | ------- | ------------------- | ------------------------------------ |

All changes trace to the linked issue(s) or PR intent. The `create-token` helper and preflight are incidental to making the benchmark target usable.

## Quality

| Check | Status | Notes |
| ----- | ------ | ----- |
| Tests added/updated | ⚠️ | Test paths are listed in metadata, but test contents were not loaded, diffed, or assessed. |
| No hardcoded secrets | ✅ | No new literal password, token, or signing secret was found in the reviewed non-test diff. |
| No debug code | ✅ | No commented-out debug code was observed in the reviewed non-test diff. |
| Docs updated | ✅ | `tests/performance/performance.md` documents resource pins, modes, reports, and invocation; its runtime knob is incorrect as noted above. |
| Migration (if needed) | N/A | No database schema change. |
| Migration linearity | N/A | No migration changed; `alembic heads` not applicable. |
| Coding standards | ⚠️ | `git diff --check` passed. Python linter/vulture tools were unavailable, and changed Python test contents were excluded by review policy. |

## Redundant Code

| # | File | Line(s) | Type | Description | Suggestion |
| - | ---- | ------- | ---- | ----------- | ---------- |

No tool-anchored redundant-code finding. `ruff` and `vulture` were unavailable; test-file contents were excluded.

## Test Context

Test files are listed by path only. Their contents were not loaded, diffed, or assessed.

## Files Changed

| File | Status | Summary |
| ---- | ------ | ------- |
| Makefile | Modified | Adds benchmark variables/recipe, token helper, and production start/stop targets. |
| docker-compose.prod.yml | Added | Adds fixed resource limits/reservations and three default gateway replicas. |
| tests/loadtest/locustfile_mcp_protocol.py | Modified — Test — context excluded | Contents not loaded, diffed, or assessed. |
| tests/loadtest/summarize_prod_benchmark.py | Added — Test — context excluded | Contents not loaded, diffed, or assessed. |
| tests/loadtest/test_summarize_prod_benchmark.py | Added — Test — context excluded | Contents not loaded, diffed, or assessed. |
| tests/performance/performance.md | Modified | Performance documentation; documentation was reviewed, not test assertions. |

## Verification

- `docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet` — passed.
- Merged Compose inspection confirmed the six services receive 4 CPU/4 GiB limits and reservations; host-published ports remain inherited from the base stack.
- `make -f <(git show HEAD:Makefile) PROD_BENCH_MODE=invalid prod-benchmark-tools` — rejected invalid mode with exit status 2.
- `make -f <(git show HEAD:Makefile) -n REPLICA='3; echo INJECTED' prod-up` — reproduced command injection in the rendered recipe.
- `make -f <(git show HEAD:Makefile) -n PROD_BENCH_USER='x; echo INJECTED' prod-benchmark-tools` — reproduced direct insertion into the token-generation command.
- `git diff --check origin/main...HEAD -- Makefile docker-compose.prod.yml tests/performance/performance.md` — passed.
- `ruff`, `vulture`, and `alembic` executables were unavailable; no migration was changed.

## Verdict

| Dimension | Rating |
| --------- | ------ |
| Blocking Changes | 2 |
| Breaking Change | No |
| Issue Completion | 🟡 |
| Security Risk | ⚫ |
| PR Quality | 🟡 |
| Redundant Code | 🟡 |
| Scope | 🟢 In scope |
| Test Context | Excluded |

**Final verdict**: `REQUEST_CHANGES`
> The security handoff is blocking, and the documented runtime environment variable is ignored by the target. Fix the production exposure and benchmark contract before merge; harden shell/secret handling and clarify the remaining #7003 scope.

---

## Concise PR Comment

❌ **REQUEST_CHANGES** — The resource overlay and mode validation are present, but the delegated security review returned `SECURITY_VERDICT=BLOCK`, and `PROD_BENCH_RUN_TIME=10s` is ignored because the recipe uses `TIME` (1800s default).

### Required Changes
- [ ] Makefile:5817-5827 — harden or explicitly enforce local-only `prod-up`; do not expose production DB/cache/HTTP bearer traffic.
- [ ] Makefile:2772,2914; performance.md:63 — implement the documented runtime knob and verify it reaches Locust.

| Area | Rating | Key Issue |
| ---- | ------ | --------- |
| Blocking Changes | 2 | Production exposure and ignored documented runtime knob. |
| Security | 🔴 | Security handoff is `SECURITY_VERDICT=BLOCK`; shell injection and secret exposure also need fixes. |
| Issue Coverage | 🟡 | #6983 resource work is present; #7003 is partial. |
| Code Quality | 🟡 | Shell interpolation is unsafe; diff whitespace check passed. |
| Breaking Change | No | No existing consumer contract is removed; new documented contract is incorrect. |
| Scope | 🟢 | Changes trace to #6983/#7003 and PR intent. |
| Test Context | Excluded | Test contents were not loaded. |
