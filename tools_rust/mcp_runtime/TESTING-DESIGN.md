# Rust MCP Session/Auth Isolation Testing Design

Last updated: March 13, 2026

## Goal

Prove that Rust MCP session/auth reuse does not leak one caller's identity,
scope, server context, replay stream, or tool/resource/prompt visibility to any
other caller.

This design is intentionally stricter than "benchmark still works." It treats
cross-session or cross-user contamination as a release blocker for `edge` and
`full` modes.

## Implementation Status

The first end-to-end implementation of this design is now present in:

- [tests/e2e/test_mcp_session_isolation.py](/home/cmihai/agents2/pr/mcp-context-forge/tests/e2e/test_mcp_session_isolation.py)
- `make test-mcp-session-isolation`

Current compose-backed validation on the rebuilt `RUST_MCP_MODE=full` stack:

- `make test-mcp-session-isolation` -> `7 passed`
- `make test-mcp-cli` -> `23 passed`
- `make test-mcp-rbac` -> `40 passed`
- `cargo test --release --manifest-path tools_rust/mcp_runtime/Cargo.toml`
  -> `48 passed`

The implemented suite currently covers:

- same-team peer session hijack denial
- same-email narrower-token session hijack denial
- cross-user live `GET /mcp` hijack denial
- cross-user replay/resume hijack denial
- cross-user `DELETE /mcp` denial with owner-session survival
- live tool-result freshness validation
- concurrent owner traffic plus peer hijack attempts without result leakage

## Scope

This design covers:

- public MCP transport on `RUST_MCP_MODE=edge|full`
- Rust session metadata, event-store, resume, live-stream, and affinity cores
- Rust session-auth reuse after `initialize`
- direct public `/mcp` ingress to Rust
- safe fallback behavior in `RUST_MCP_MODE=shadow` and when public Rust session
  reuse is disabled

This design does not assume SQLite. The authoritative environment is the
compose-backed test stack in [docker-compose.yml](/home/cmihai/agents2/pr/mcp-context-forge/docker-compose.yml),
which uses PostgreSQL and Redis.

## Why This Matters

The current fast path reuses authenticated context per MCP session inside Rust.
That is the correct direction for performance, but it creates obvious security
questions:

- Can caller B reuse caller A's `mcp-session-id`?
- Can a session authenticated under one token be replayed with a different
  token or a narrower/wider scope?
- Can `GET /mcp` replay/resume leak events across users or workers?
- Can multi-worker affinity forwarding accidentally replay one user's session to
  another user?
- Can revocation, team membership changes, or role changes leave stale session
  auth usable for too long?

The answer must be proven by tests, not inferred from implementation details.

## Security Invariants

The following invariants should be explicitly tested and treated as required:

1. A session is owned by exactly one authenticated caller context.
2. A second caller must never gain access to that session by presenting the
   same `mcp-session-id`.
3. Session-bound auth reuse must never widen visibility beyond the presented
   auth material and server scope.
4. Server-scoped MCP sessions must remain bound to the original `server_id`.
5. Replay/resume must never return another caller's SSE events.
6. Affinity forwarding must preserve the same ownership checks as direct local
   handling.
7. Public, team, private, and owner visibility must remain correct under reuse.
8. Revocation and membership/role changes must have a defined, bounded effect on
   existing sessions.
9. Safe fallback modes must not silently leave public MCP on an unsafe hybrid
   path.
10. Tool results used for validation must be demonstrably fresh, not stale or
    cached.

## Current Coverage

There is already useful coverage in the repo:

- [tests/e2e/test_mcp_rbac_transport.py](/home/cmihai/agents2/pr/mcp-context-forge/tests/e2e/test_mcp_rbac_transport.py)
  covers multi-user RBAC, token scopes, team/public/private visibility, and
  revoked-token deny paths over real MCP transports.
- [tests/integration/test_streamable_http_redis.py](/home/cmihai/agents2/pr/mcp-context-forge/tests/integration/test_streamable_http_redis.py)
  covers multi-worker Redis event-store sharing and basic session isolation at
  the stream-id level.
- [tests/e2e/test_session_pool_e2e.py](/home/cmihai/agents2/pr/mcp-context-forge/tests/e2e/test_session_pool_e2e.py)
  covers session-pool identity extraction and transport isolation.
- [tests/loadtest/locustfile_mcp_protocol.py](/home/cmihai/agents2/pr/mcp-context-forge/tests/loadtest/locustfile_mcp_protocol.py)
  covers performance, but not cross-user correctness.

That is not enough for Rust session-auth reuse.

## Gaps

The important gaps are:

1. No E2E test where user A creates a session and user B attempts to use it.
2. No E2E test where the same email presents a different token after
   `initialize`, to prove scope/token changes do not reuse stale session auth.
3. No explicit replay/resume hijack test with `Last-Event-ID`.
4. No explicit session-delete hijack test.
5. No explicit cross-worker ownership test for Rust affinity forwarding.
6. No load test that validates correctness of returned data under mixed-user
   concurrency.
7. No explicit release gate for revocation or membership-change semantics after
   session initialization.

## Recommended Test Strategy

Use four layers:

1. Rust unit tests
2. Python unit and integration tests
3. Compose-backed E2E tests with real users/teams/tokens
4. Multi-user performance-safety tests that validate correctness while loading
   the fast path

## Test Matrix

Run the core matrix in these modes:

- `RUST_MCP_MODE=shadow`
- `RUST_MCP_MODE=edge`
- `RUST_MCP_MODE=full`

For `edge|full`, run with:

- `RUST_MCP_SESSION_AUTH_REUSE=true`
- `RUST_MCP_SESSION_AUTH_REUSE=false`

That gives two distinct guarantees:

- fast path is correct
- safe fallback is correct

## Test Actors

Create the following callers dynamically through the real REST API, not through
static fixtures in compose:

1. `admin_unrestricted`
   - `is_admin=true`
   - `teams=null`
   - used for setup and privileged verification
2. `team_a_dev`
   - non-admin
   - member of team A
3. `team_a_viewer`
   - non-admin
   - member of team A
4. `team_b_dev`
   - non-admin
   - member of team B
5. `public_only_user`
   - non-admin
   - public-only token
6. `same_email_alt_scope`
   - same email as `team_a_dev`, but different token scope / different token JTI
   - used to prove token changes do not silently reuse old session auth

## Test Data

Create one dedicated virtual server for the isolation suite. Keep the dataset
small and deterministic.

For that server, create:

- tools
  - `iso-public-tool`
  - `iso-team-a-tool`
  - `iso-team-b-tool`
  - `iso-owner-a-tool`
- resources
  - `resource://iso/public`
  - `resource://iso/team-a`
  - `resource://iso/team-b`
  - `resource://iso/owner-a`
- prompts
  - `iso-public-prompt`
  - `iso-team-a-prompt`
  - `iso-team-b-prompt`
  - `iso-owner-a-prompt`

The visibility and owner/team assignments should make it impossible for the
wrong caller to "accidentally" see the right result.

Also use freshness tools on the same server:

- `fast-time-get-system-time`
- `fast-test-echo`

Those prove that responses are live and not stale/cached.

## End-to-End Cases

### 1. Session Ownership: POST

Scenario:

1. user A initializes a session on server S
2. user A performs `tools/list`, `resources/list`, `prompts/list`
3. user B reuses A's `mcp-session-id` on the same server

Expected:

- user B does not receive A's auth context
- user B does not see A-only or team-A-only objects unless B is independently
  allowed to see them
- preferred transport contract:
  - deny with `403`, or
  - hide existence with `404`
- whichever contract is chosen, it must be stable and explicit

### 2. Session Ownership: GET Replay/Resume

Scenario:

1. user A initializes a session
2. user A generates replayable traffic
3. user B calls public `GET /mcp` with:
   - A's `mcp-session-id`
   - a valid `Last-Event-ID`

Expected:

- user B receives no replay stream from A's session
- if denied, there must be no partial event leakage before close

### 3. Session Ownership: DELETE

Scenario:

1. user A initializes a session
2. user B issues `DELETE /mcp` for A's session
3. user A attempts another valid call with the same session

Expected:

- B cannot tear down A's session
- A's session remains usable, unless the implementation deliberately hides
  existence and still preserves ownership

### 4. Same Email, Different Token

Scenario:

1. user A initializes with token T1
2. user A reuses the same session with token T2 for the same email but a
   different JTI and different team scope

Expected:

- Rust must not blindly reuse the old auth context if the presented auth
  material changed
- effective visibility must match T2, not stale state from T1

This is the most important direct test for auth-binding fingerprint logic.

### 5. Server Scope Pinning

Scenario:

1. user A initializes on `/servers/S1/mcp`
2. user A or user B attempts to use the same session on `/servers/S2/mcp`

Expected:

- session reuse across server IDs is denied
- no stale data from S1 appears on S2

### 6. Public/Team/Owner Visibility Under Reuse

For each actor, run:

- `tools/list`
- `resources/list`
- `prompts/list`
- `resources/read`
- `prompts/get`

Expected set:

- `public_only_user` sees only public items
- `team_a_*` sees public + team A + own private
- `team_b_*` sees public + team B + own private
- `admin_unrestricted` sees all

The same assertions must pass:

- before session reuse
- after repeated in-session requests
- after affinity forwarding across workers

### 7. Revocation After Initialize

Scenario:

1. user A initializes a session
2. revoke A's token
3. continue MCP traffic on the existing session

This test must force a product decision. Two acceptable contracts are possible:

- strict contract:
  - session becomes unusable immediately after revocation
- bounded-lag contract:
  - session may continue for at most `RUST_MCP_SESSION_AUTH_REUSE_TTL_SECONDS`

Recommendation:

- before enabling Rust session-auth reuse as a default fast path, move to the
  strict contract by invalidating bound session auth on revocation events
- if bounded lag is retained, document it clearly and test the exact bound

### 8. Team Membership / Role Change After Initialize

Scenario:

1. user A initializes while in team A
2. remove A from team A or downgrade A's role
3. repeat discovery and action calls on the same session

Expected:

- same decision needed as revocation:
  - strict invalidation preferred
  - bounded lag only if explicitly documented and accepted

### 9. Affinity / Multi-Worker Ownership

Scenario:

1. user A initializes on worker 1
2. subsequent `POST`, `GET`, and `DELETE` traffic lands on worker 2 or 3
3. user B attempts the same hijack from another worker

Expected:

- user A succeeds across workers
- user B is denied across workers
- ownership checks behave the same whether the request is handled locally or
  forwarded through the Redis owner-worker channel

### 10. Freshness / No Stale Result Reuse

Scenario:

1. user A calls `fast-test-echo` with unique nonce N1
2. user B calls `fast-test-echo` with unique nonce N2
3. user A calls `fast-time-get-system-time`
4. repeat after a known delay

Expected:

- echo returns the exact caller-provided nonce, not another user's value
- time changes monotonically and tracks the upstream server

This does not prove auth isolation by itself, but it proves the fast path is not
returning stale or synthetic data.

## Recommended New Test Files

### E2E correctness

- `tests/e2e/test_mcp_session_isolation.py`

Primary responsibilities:

- create users/teams/roles/tokens through the real REST API
- create a dedicated isolation virtual server and scoped objects
- exercise `POST`, `GET`, and `DELETE /mcp`
- assert deny paths for hijack attempts
- assert no visibility leakage

### Integration for Rust session auth reuse semantics

- `tests/integration/test_rust_mcp_session_auth_reuse.py`

Primary responsibilities:

- fingerprint mismatch
- TTL expiry
- server-id mismatch
- owner-email mismatch
- explicit fallback reasons

### Load/perf safety harness

- `tests/loadtest/locustfile_mcp_isolation.py`

Primary responsibilities:

- multiple independent users and tokens
- each user owns its own expected allowlist and denylist
- each task validates returned payloads, not just latency and status codes
- periodic hijack attempts must count as success only when they are denied

## Load Test Design

Performance testing should not only measure RPS. It should verify correctness
under concurrency.

### User groups

At minimum:

- team A user
- team B user
- public-only user
- admin user

### Per-user validation

Each user maintains:

- its own bearer token
- its own MCP session id
- its own expected visible tools/resources/prompts
- a denylist of objects that must never appear

Each task validates:

- the result contains all required allowed objects
- the result contains none of the forbidden objects
- the session id used belongs to the same logical user

### Active hijack probes

During the load run, a small percentage of tasks should intentionally:

- reuse another user's session id
- switch the token while reusing a session
- attempt replay/resume on another user's session
- attempt delete on another user's session

These tasks should be counted as failures unless they are denied correctly.

### Freshness probes

During the same run:

- `fast-test-echo` sends per-user unique nonces
- `fast-time-get-system-time` verifies time drift and monotonicity

This catches stale/cached response pollution while the system is under load.

## Data Setup Strategy

Prefer runtime setup through pytest/API helpers over static compose fixtures.

Why:

- avoids long-lived state pollution in the compose stack
- keeps tests isolated and repeatable
- makes it easy to vary users/teams/scopes per scenario

Recommended helpers:

- `tests/e2e/mcp_isolation_helpers.py`
  - create team
  - create user
  - assign RBAC role
  - mint scoped token
  - create isolation server objects
  - cleanup

If a dedicated upstream MCP server becomes necessary, add it explicitly to
compose only after the API-driven fixture route is exhausted.

## Observability Needed

Before or while implementing the tests, add counters/logs for:

- session-auth reuse hits
- session-auth reuse misses
- fallback-to-Python-auth reason
- session-owner mismatch denials
- server-id mismatch denials
- replay/resume ownership denials
- delete ownership denials

These are useful both for debugging and for proving that the denial paths are
actually exercised under load.

## Release Gates

Do not treat Rust session-auth reuse as ready for default fast-path use until
all of the following are green:

1. E2E session hijack tests for `POST`, `GET`, and `DELETE`
2. same-email/different-token scope-change test
3. cross-worker affinity ownership test
4. freshness tests with echo/time tools
5. load/perf isolation test with zero cross-user leakage
6. explicit documented behavior for revocation and membership/role changes

## Recommended Implementation Order

1. Add `tests/e2e/test_mcp_session_isolation.py`
2. Add integration coverage for Rust auth-binding reuse edge cases
3. Add observability counters for reuse/fallback/denial reasons
4. Add the multi-user Locust isolation harness
5. Decide and document the revocation/team-change contract
6. Only then consider making the fast reuse path a less experimental default

## Short Version

To be confident that Rust session-auth reuse is safe, we need to prove:

- one session cannot be reused by another user
- one token context cannot silently leak into another token context
- one server scope cannot leak into another server scope
- replay/resume and delete honor the same ownership rules as normal calls
- multi-worker affinity does not weaken ownership
- load tests validate data correctness, not only throughput

That proof does not exist yet. This design defines how to build it.
