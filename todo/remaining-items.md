# Remaining Rust MCP Items

This file tracks the remaining work after the current Rust MCP hardening pass.

## Implemented In This Branch

- [x] Add runtime observability for the session-auth fast path.
  - Rust `/health` now exposes `runtime_stats` with:
    - session-auth reuse hits and misses
    - miss reasons
    - backend Python auth round-trips
    - session access denial reasons
    - affinity forward attempts and forwarded requests
- [x] Extend the compose-backed Rust isolation suite with bounded-TTL revocation coverage.
- [x] Extend the compose-backed Rust isolation suite with bounded-TTL team membership removal coverage.
- [x] Extend the compose-backed Rust isolation suite with bounded-TTL team role revocation coverage.
- [x] Add forced cross-worker affinity ownership coverage in the Rust runtime integration tests.
- [x] Add a dedicated multi-user correctness load harness:
  - `tests/loadtest/locustfile_mcp_isolation.py`
  - `make test-mcp-session-isolation-load`
- [x] Keep `session_id` query-parameter support non-breaking in this PR and document it as compatibility debt instead of changing Python behavior.

## Still Open

- [ ] Re-run the new bounded-TTL compose-backed isolation checks on every release candidate:
  - `MCP_RUST_SESSION_AUTH_REUSE_TTL_SECONDS=2 MCP_RUST_SESSION_AUTH_REUSE_GRACE_SECONDS=1 make testing-rebuild-rust-full`
  - `make test-mcp-session-isolation`
  - `make test-mcp-session-isolation-load MCP_ISOLATION_LOAD_RUN_TIME=30s`
- [ ] Investigate the remaining low-rate failures in sustained `5m` tools-only runs.
- [ ] Decide whether to expose the new runtime stats beyond `/health` or export them into the broader metrics stack.
- [ ] Decide whether `session_id` query-parameter compatibility should be formally deprecated and later retired across both Python and Rust.
- [ ] Add client-certificate PostgreSQL TLS support for Rust (`sslcert` / `sslkey`) if that deployment mode is required.

## Deferred To Follow-Up

These remain intentionally outside this PR:

- broader Python-side MCP error redaction beyond the Rust runtime proxy path
- broader Playwright/admin login instability
- broader Python compatibility cleanup around query-parameter session identifiers
