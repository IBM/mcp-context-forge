# E2E verification for issue #5247

Reproduces the reported bug and proves the fix against a real, isolated instance of the
gateway — real HTTP API, real SQLite database, real MCP server over SSE. No `gateway_service`
internals are mocked.

## What it proves

1. **The bug**: refreshing an unauthorized OAuth `authorization_code` gateway reports
   `success: false` with a message naming `/oauth/authorize/{id}` — not the silent
   `success: true` from the original report.
2. **The fix**: an authorized `authorization_code` gateway backed by a real token actually
   connects to a real MCP server (a `FastMCP` instance over SSE) and fetches tools.
3. A wrong bearer token is genuinely rejected by the upstream (proves the forwarded header
   is the real, live-resolved token, not a stub).
4. A non-OAuth gateway with wrong credentials still fails (no regression — this path was
   never broken).
5. The background health-check path for the same unauthorized gateway is unchanged: still
   reports `success: true` without attempting a connection.

## Running it

```bash
# 1. Start an isolated gateway instance (fresh SQLite DB, port 48444)
bash tests/e2e/issue_5247/manual/start_gateway.sh &

# 2. Wait for it to come up, then run the verification
curl -sf http://127.0.0.1:48444/health
./.venv/bin/python tests/e2e/issue_5247/manual/run_e2e.py

# 3. Stop the gateway
pkill -f "uvicorn mcpgateway.main:app"
```

Exit code is `0` when all scenarios pass, `1` otherwise. Full per-scenario detail is
also written to `manual/e2e_results.json` (git-ignored) next to the script.

Safe to run repeatedly against the same long-lived instance — every gateway it registers
carries a random per-run tag so re-runs never collide on name/URL uniqueness constraints.

## Why a local mock server, and why one script bypasses the registration API

The registration endpoint correctly enforces SSRF protection and rejects any
localhost/private-network URL — verified directly against
`SecurityValidator.validate_url`, not assumed. That's a real, working security control, not
something to route around in production. `register_local_gateway.py` calls the real
`GatewayService.register_gateway()` business logic directly with a `GatewayCreate` built via
`model_construct()`, which bypasses only that one Pydantic field validator — not any
encryption, discovery, or database logic — so the "authorized gateway actually connects"
scenario has a routable local target. The actual call this PR fixes,
`POST /gateways/{id}/tools/refresh`, always goes through the real, unmodified public
endpoint in every scenario.

## Files

| File | Purpose |
|---|---|
| `manual/start_gateway.sh` | Boots `mcpgateway.main:app` on an isolated SQLite DB and port 48444 |
| `manual/e2e.env.example` | Template env vars for the isolated instance (copied to `e2e.env` on first run) |
| `manual/run_e2e.py` | The verification script; prints PASS/FAIL per scenario and an overall summary |
| `manual/register_local_gateway.py` | Registration bypass for locally-hosted test targets (see above) |
| `manual/mock_upstream_mcp.py` | A real one-tool `FastMCP` server over SSE, gated on a bearer token, used as the "authorized upstream" |
