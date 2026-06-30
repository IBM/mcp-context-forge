# Session-affinity end-to-end reproducers

Multi-worker (Docker stack) e2e checks for the session-affinity forward-dispatch work
(#4557 / #4205). These are **not** pytest tests — they run against a live, multi-replica
gateway so they exercise the real cross-worker forwarding that an in-process test cannot.
The in-process complement lives at
`tests/integration/test_internal_mcp_dispatch_auth.py`.

## Scripts

| Script | What it validates |
|--------|-------------------|
| `counter_server.py` | A minimal stateful MCP counter (per-session state keyed by the upstream `ServerSession`). Run on the host; `COUNTER_PORT` selects the port (`9400` default, `9401` for the multi-upstream test). |
| `run_reproducers.py` | **Tests 1–5** (admin token): single session ×25; 3 concurrent sessions; two tokens; one session across two counters; owner-worker `kill -9` failover. Proves upstream-session reuse, per-session/token/upstream isolation, and the failover contract. |
| `run_public_only.py` | **Public-only** session (no token) is served, not RBAC-denied — the multi-worker proof of the trusted-internal public-only dispatch fix. Requires `MCP_REQUIRE_AUTH=false`. |
| `run_gating.py` | **Kill-switch (flag-off)**: with the stack started `MCPGATEWAY_SESSION_AFFINITY_ENABLED=false`, asserts affinity is dormant — the gateway still serves, no `worker_heartbeat`/`pool_owner` keys are created, and a cross-worker stateful session is not forwarded (reverts to the pre-affinity baseline). The flag-off A/B companion to `run_reproducers.py` (which covers flag-on). |

## Prerequisites

1. Build + start the testing stack from the branch under test:
   ```bash
   make docker-prod          # build mcpgateway/mcpgateway:latest from the working tree
   make testing-up           # 3 gateway replicas behind nginx + Redis + Postgres
   ```
2. Start the counter server(s) on the host (reachable from gateway containers via
   `host.docker.internal`, which compose maps with `extra_hosts`):
   ```bash
   .venv/bin/python tests/e2e/session_affinity/counter_server.py &                 # :9400
   COUNTER_PORT=9401 .venv/bin/python tests/e2e/session_affinity/counter_server.py &  # :9401 (Test 4)
   ```
3. Export the stack's JWT secret (used to mint tokens):
   ```bash
   export JWT_SECRET_KEY=$(grep -E '^JWT_SECRET_KEY=' .env | cut -d= -f2-)
   ```

## Running

```bash
# Tests 1–5 (admin token)
export MCPGATEWAY_BEARER_TOKEN=$(.venv/bin/python -m mcpgateway.utils.create_jwt_token \
    --username admin@example.com --admin --exp 10080 --secret "$JWT_SECRET_KEY" --algo HS256)
.venv/bin/python tests/e2e/session_affinity/run_reproducers.py

# Public-only (requires the gateway started with MCP_REQUIRE_AUTH=false)
.venv/bin/python tests/e2e/session_affinity/run_public_only.py

# Kill-switch (requires the gateway started with MCPGATEWAY_SESSION_AFFINITY_ENABLED=false)
.venv/bin/python tests/e2e/session_affinity/run_gating.py
```

Each script prints a per-test `PASS/FAIL` summary and exits non-zero on failure.

## Notes

- These run against `http://localhost:8080` (nginx) by default; override with `GW_BASE`.
- `run_public_only.py` registers the counter as a **public** gateway/virtual server so the
  tools are visible to public-only callers, then drives the session with no `Authorization`
  header. It needs `MCP_REQUIRE_AUTH=false`; otherwise the unauthenticated `initialize`
  returns 401.
- The benchmark (`make benchmark-mcp-tools`) is the throughput companion to these
  correctness reproducers.
