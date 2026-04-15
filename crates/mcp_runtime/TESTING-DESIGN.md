# Rust MCP Session/Auth Isolation Testing Design

Last updated: March 14, 2026

## Goal

Prove that Rust MCP session/auth reuse does not leak one caller's identity,
scope, server context, replay stream, or tool/resource/prompt visibility to
another caller.

This is stricter than "benchmark still works." Cross-user or cross-session
contamination is a release blocker for the fast Rust public path.

## Current implementation status

The first end-to-end implementation is already in place:

- `tests/e2e_rust/test_mcp_session_isolation.py`
- `make test-mcp-session-isolation`

Current compose-backed validation on this branch:

- `make test-mcp-session-isolation` -> `10 passed`
- `make test-mcp-cli` -> `23 passed`
- `make test-mcp-rbac` -> `40 passed`
- `cargo test --release --manifest-path crates/mcp_runtime/Cargo.toml`
  -> `48 passed`

The implemented suite currently proves:

- same-team peer session hijack denial
- same-email narrower-token session hijack denial
- cross-user live `GET /mcp` hijack denial
- cross-user replay/resume hijack denial
- cross-user `DELETE /mcp` denial with owner-session survival
- live tool-result freshness validation
- concurrent owner traffic plus peer hijack attempts without result leakage
- token revocation after `initialize` is denied within the documented bounded
  reuse TTL
- team membership removal after `initialize` is denied within the documented
  bounded reuse TTL
- team role revocation after `initialize` is denied within the documented
  bounded reuse TTL

Rust integration coverage also now proves:

- forced cross-worker affinity ownership preserves owner access
- peer reuse attempts are still denied when the request is forwarded across
  workers

This design therefore supplements existing coverage now; it is no longer purely
aspirational.

## Scope

This design covers:

- public MCP transport in `RUST_MCP_MODE=edge|full`
- runtime session metadata and session-auth reuse
- Redis-backed event-store and replay
- live-stream and affinity slices in `full`
- safe fallback behavior in `RUST_MCP_MODE=shadow`

It assumes the compose-backed environment from
[docker-compose.yml](../../docker-compose.yml),
which uses PostgreSQL and Redis.

## Why this matters

The current fast path binds authenticated context to MCP sessions inside Rust.
That is the right direction for performance, but it creates obvious security
questions:

- can caller B reuse caller A's `mcp-session-id`?
- can one token context silently leak into another token context?
- can replay/resume leak another caller's events?
- can affinity forwarding weaken ownership checks?
- can revocation or membership/role changes leave stale session auth usable for
  too long?

Those must be proven by tests, not inferred from implementation details.

## Security invariants

The following invariants should stay explicit and testable:

1. A session is owned by exactly one authenticated caller context.
2. A second caller must never gain access by reusing the same
   `mcp-session-id`.
3. Session-auth reuse must never widen visibility beyond the currently
   presented auth material and server scope.
4. Server-scoped MCP sessions must remain bound to the original `server_id`.
5. Replay/resume must never return another caller's events.
6. Affinity forwarding must preserve the same ownership checks as local
   handling.
7. Public/team/owner visibility must remain correct under reuse.
8. Revocation and membership/role changes must have a defined, bounded effect
   on existing sessions.
9. Safe fallback modes must not silently leave public MCP on an unsafe hybrid
   path.
10. Freshness checks must prove the fast path is returning live results, not
    stale or synthetic data.

## Current coverage

### Existing non-isolation suites

Useful existing coverage already lives in:

- [tests/e2e/test_mcp_rbac_transport.py](../../tests/e2e/test_mcp_rbac_transport.py)
- [tests/integration/test_streamable_http_redis.py](../../tests/integration/test_streamable_http_redis.py)
- [tests/e2e/test_session_pool_e2e.py](../../tests/e2e/test_session_pool_e2e.py)
- [tests/loadtest/locustfile_mcp_protocol.py](../../tests/loadtest/locustfile_mcp_protocol.py)

These are useful, but they are not enough on their own for Rust session-auth
reuse.

### Implemented isolation cases

The current compose-backed suite maps to the design like this:

- Session ownership: `POST`
  - same-team peer denied when reusing another caller's session
- Same email, different token
  - narrower/public-only token denied when reusing a team-scoped session
- Session ownership: live `GET /mcp`
  - cross-user attach denied
- Session ownership: replay/resume
  - cross-user replay denied
- Session ownership: `DELETE`
  - cross-user delete denied and owner session survives
- Freshness / no stale result reuse
  - live time/echo validation
- Concurrency
  - owner traffic plus hijack attempts do not leak results

## Current matrix

The core matrix should continue to be:

- `RUST_MCP_MODE=shadow`
- `RUST_MCP_MODE=edge`
- `RUST_MCP_MODE=full`

Important nuance:

- `edge` and `full` currently default to session-auth reuse through the mode
  presets
- `RUST_MCP_SESSION_AUTH_REUSE=false` should still be exercised as an advanced
  override case, but it is no longer the primary UX

That means there are two guarantees to keep proving:

- the fast public Rust path is correct
- the safe fallback path is correct

## Test actors

The design still assumes dynamically created callers through the real REST API:

1. `admin_unrestricted`
   - `is_admin=true`
   - `teams=null`
2. `team_a_dev`
3. `team_a_viewer`
4. `team_b_dev`
5. `public_only_user`
6. `same_email_alt_scope`

The implemented compose-backed suite already uses real REST setup and minted
tokens; additional scenarios should keep following that pattern.

## Test data

Continue to prefer dynamic API-created fixtures over long-lived compose state.

Recommended server content:

- public, team-scoped, and owner-scoped objects
- at least one live time/echo tool for freshness validation

The current isolation suite prefers a compose-backed time-capable streamable
HTTP gateway:

- canonical preference: `fast_time`
- fallback: `fast_test`

That fallback is acceptable because the suite is proving session/auth binding,
not benchmarking a specific upstream server.

## Implemented hardening additions

The following design items are now implemented:

1. Revocation after initialize
2. Team membership / role change after initialize
3. Forced cross-worker affinity ownership scenarios
4. Multi-user correctness load harness
5. Explicit reuse/fallback observability counters

### 1. Revocation after initialize

Scenario:

1. user A initializes a session
2. revoke A's token
3. continue MCP traffic on the same session

Required outcome:

- either strict invalidation, or
- a clearly documented and explicitly tested bounded TTL contract

Current status:

- implemented as a bounded TTL contract in
  `tests/e2e_rust/test_mcp_session_isolation.py`

### 2. Team membership / role change after initialize

Scenario:

1. user A initializes while in team A
2. remove A from team A or downgrade A's role
3. repeat discovery and action calls on the same session

Required outcome:

- same explicit contract as revocation

Current status:

- implemented for both membership removal and role revocation in
  `tests/e2e_rust/test_mcp_session_isolation.py`

### 3. Forced cross-worker affinity ownership

Scenario:

1. user A initializes on worker 1
2. subsequent traffic lands on another worker
3. user B attempts the same hijack from a different worker

Required outcome:

- owner succeeds across workers
- non-owner is denied across workers
- forwarded and local handling enforce the same ownership rule

Current status:

- implemented in `crates/mcp_runtime/tests/runtime.rs`

### 4. Multi-user load correctness harness

Add a dedicated load harness that validates:

- expected allowlist per user
- denylist never appears
- hijack attempts fail correctly
- time/echo results remain live and per-user

This should be a separate correctness harness, not a replacement for the
throughput benchmarks.

Current status:

- implemented in `tests/loadtest/locustfile_mcp_isolation.py`
- exposed as `make test-mcp-session-isolation-load`

## Observability now available

Rust `/health` now exposes `runtime_stats` for:

- session-auth reuse hits
- session-auth reuse misses
- miss reasons
- backend Python auth round-trips
- session-owner and auth-binding denials
- server-scope mismatch denials
- affinity forward attempts and forwarded requests

## Remaining gaps

The main remaining gaps are now narrower:

1. Routine release validation of the bounded TTL contract under a short test TTL
2. Broader correctness-load validation as part of release-style testing, not
   just availability of the harness
3. Longer-term architectural work if the project wants revocation-aware
   invalidation instead of a bounded TTL contract

## Rollout gate

Because `edge` and `full` now default to the fast path in local mode presets,
the right question is no longer "can we ever enable this?" It is:

"What must stay green before we trust it more broadly and rely less on the safe
fallback?"

Recommended gate:

1. Keep `test-mcp-session-isolation` green
2. Keep the short-TTL revocation/membership/role-change cases green
3. Keep forced cross-worker affinity ownership coverage green
4. Run the multi-user load/correctness harness
5. Review `runtime_stats` to confirm the fast path is being exercised and that
   denial/fallback behavior looks sane

## Short version

We now have an initial proof that the Rust fast path preserves session
ownership for the main hijack and freshness cases.

What is now implemented covers the main deny path plus the bounded-TTL drift
cases around:

- revocation
- membership/role drift
- forced cross-worker ownership
- correctness under concurrent multi-user load

What remains is mostly operational rigor:

- re-running the short-TTL correctness suite before release
- using the new stats to understand reuse/fallback behavior in real runs
- deciding whether bounded TTL reuse is acceptable long-term or should be
  replaced with revocation-aware invalidation
