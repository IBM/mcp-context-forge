# Review Feedback For `todo/code-review.md`

Scope: `git diff main`, with detailed validation focused on `tools_rust/mcp_runtime/` and `mcpgateway/transports/rust_mcp_runtime_proxy.py`.

## Current status on `modular-design`

This memo is now partly historical.

The original review was useful, but several of the highest-severity findings
have since been fixed on the branch:

- direct public Rust ingress no longer trusts client-supplied
  `x-contextforge-auth-context`
- direct public Rust ingress no longer trusts client-supplied
  `x-contextforge-server-id`
- the Rust -> Python auth seam now uses the actual peer address and no longer
  defaults a missing client IP to loopback
- the public Rust listener now serves a dedicated public router and no longer
  exposes the internal event-store endpoints
- the public Rust listener now serves a minimal health payload instead of the
  detailed internal runtime payload
- Redis session counting now uses `SCAN` instead of `KEYS`
- affinity Redis keys/channels now honor the configured cache prefix
- the upstream session cache no longer holds its mutex across HTTP I/O
- runtime/proxy transport errors are now redacted before they are returned to
  clients

The still-relevant follow-up items are:

- Rust runtime PostgreSQL TLS support now exists for
  `sslmode=disable|prefer|require` and optional `sslrootcert`, but client
  certificate auth via `sslcert` / `sslkey` is still unimplemented
- `session_id` query-parameter compatibility still exists in both Rust and
  Python and remains security-sensitive compatibility debt
- broader Python MCP handlers outside the runtime proxy still expose some
  exception text in client responses and need a separate repository-wide
  hardening pass if we want parity beyond the Rust runtime slice
- maintainability observations like the large `lib.rs` are still fair, but they
  are refactor opportunities rather than defect findings

## Historical verdict

`todo/code-review.md` is not complete.

The strongest missing findings are:

- Critical: direct public Rust ingress also trusts client-supplied `x-contextforge-server-id`, which can turn `/mcp` requests into server-scoped operations without the normal path-based per-server OAuth enforcement.
- Critical: the Rust -> Python auth seam derives `client_ip` from spoofable forwarding headers and defaults missing client IP to `127.0.0.1`, which breaks the token-scoping middleware's assumption that `request.client.host` is trustworthy.

Most of the existing concrete findings are real. The main corrections are:

- Finding 2 is real but should be framed as a health-path scalability issue, not a normal MCP hot-path issue.
- Finding 3 is better stated as "no PostgreSQL TLS support" rather than "guaranteed plaintext on every deployment".
- Finding 5 is incomplete because the Python proxy leaks backend exception text too.
- Finding 6 is existing compatibility/security debt, not a clean branch-specific regression.
- Findings 8 and 9 are maintainability observations, not defect findings.

## Missing Findings

### 1. Critical: Client-supplied `x-contextforge-server-id` is trusted on the direct public Rust listener

The reviewer caught the equivalent trust bug for `x-contextforge-auth-context`, but missed that the Rust public ingress also preserves and trusts `x-contextforge-server-id`.

Evidence:

- The Python proxy explicitly strips `x-contextforge-server-id` before forwarding requests to Rust in [mcpgateway/transports/rust_mcp_runtime_proxy.py:41-49](../mcpgateway/transports/rust_mcp_runtime_proxy.py).
- The Rust public auth probe does not strip that header in [tools_rust/mcp_runtime/src/lib.rs:2182-2204](../tools_rust/mcp_runtime/src/lib.rs).
- Rust treats any request carrying that header as server-scoped via [tools_rust/mcp_runtime/src/lib.rs:2146-2148](../tools_rust/mcp_runtime/src/lib.rs).
- Rust forwards that header downstream because `should_forward_header()` does not block it in [tools_rust/mcp_runtime/src/lib.rs:7393-7412](../tools_rust/mcp_runtime/src/lib.rs).
- Generic internal Rust-dispatched MCP RPC reads the header back into `params["server_id"]` in [mcpgateway/main.py:8748-8759](../mcpgateway/main.py).
- Rust direct DB/authz paths also consume it directly, for example [tools_rust/mcp_runtime/src/lib.rs:4397-4417](../tools_rust/mcp_runtime/src/lib.rs) and [mcpgateway/main.py:8074-8129](../mcpgateway/main.py).

Impact:

- A client that can reach `public_listen_http` directly can send `/mcp` with a forged `x-contextforge-server-id`.
- The internal auth check for direct public ingress uses the real request path (`/mcp`), not a server-scoped path, in [tools_rust/mcp_runtime/src/lib.rs:2360-2365](../tools_rust/mcp_runtime/src/lib.rs) and [mcpgateway/main.py:517-524](../mcpgateway/main.py).
- Per-server OAuth enforcement in the normal Streamable HTTP auth path only triggers when the path itself matches `/servers/{server_id}/mcp` in [mcpgateway/transports/streamablehttp_transport.py:3090-3103](../mcpgateway/transports/streamablehttp_transport.py).
- Internal Rust -> Python authorization assumes that per-server OAuth/path enforcement already happened before the internal hop, as documented in [mcpgateway/main.py:426-454](../mcpgateway/main.py).

Why this matters:

- This is not the same bug as forged `x-contextforge-auth-context`.
- A caller does not need to forge an auth context to exploit it.
- The bug can bypass the path-based "server requires OAuth" check for unauthenticated/public-only requests by smuggling server scope through a trusted internal header.

Recommended fix:

- Strip `x-contextforge-server-id` from direct public client requests before auth.
- Treat it like other internal-only headers in the public listener path.
- Only inject it from trusted routing state, not from client headers.

### 2. Critical: Direct public Rust ingress allows spoofed or loopback-default client IP in token scoping

The Rust public auth handoff breaks the token-scoping middleware's trust model for client IP.

Evidence:

- Rust derives `client_ip` from `X-Real-IP` or `X-Forwarded-For` in [tools_rust/mcp_runtime/src/lib.rs:2207-2223](../tools_rust/mcp_runtime/src/lib.rs).
- Rust forwards that value into Python auth in [tools_rust/mcp_runtime/src/lib.rs:2360-2365](../tools_rust/mcp_runtime/src/lib.rs).
- Python internal auth builds a synthetic ASGI scope with `client=(client_ip or "127.0.0.1", 0)` in [mcpgateway/main.py:463-490](../mcpgateway/main.py).
- Token scoping intentionally trusts only `request.client.host`, not raw forwarding headers, in [mcpgateway/middleware/token_scoping.py:408-426](../mcpgateway/middleware/token_scoping.py) and enforces IP restrictions from that value in [mcpgateway/middleware/token_scoping.py:1304-1309](../mcpgateway/middleware/token_scoping.py).

Impact:

- A direct public client can spoof IP-based token restrictions by setting `X-Real-IP` or `X-Forwarded-For`.
- If those headers are absent, the request is treated as coming from `127.0.0.1`.
- Any token with loopback/internal-only IP restrictions can therefore be incorrectly accepted when the Rust public listener is reachable directly.

Recommended fix:

- Do not derive `client_ip` from client-controlled forwarding headers on the direct public listener.
- Use the real socket peer address, or only trust forwarding headers after an actual trusted proxy layer has rewritten the peer IP.
- Do not default missing `client_ip` to loopback in the internal auth scope.

### 3. Medium: Public health endpoints leak internal runtime details

The public Rust router exposes unauthenticated health endpoints that reveal internal configuration and topology.

Evidence:

- `/health` and `/healthz` are mounted on the same router as the public ingress in [tools_rust/mcp_runtime/src/lib.rs:897-929](../tools_rust/mcp_runtime/src/lib.rs) and served on both listeners in [tools_rust/mcp_runtime/src/lib.rs:937-964](../tools_rust/mcp_runtime/src/lib.rs).
- The response includes `backend_rpc_url`, feature flags, protocol metadata, and active session counts via [tools_rust/mcp_runtime/src/lib.rs:180-192](../tools_rust/mcp_runtime/src/lib.rs) and [tools_rust/mcp_runtime/src/lib.rs:1010-1024](../tools_rust/mcp_runtime/src/lib.rs).

Impact:

- Anyone who can reach the public listener can enumerate backend topology and enabled runtime capabilities.
- This is lower severity than the auth issues above, but still unnecessary information exposure.

Recommended fix:

- Serve a minimal external health payload on the public listener, or bind the detailed health endpoint to the private listener only.

### 4. Missing extension to finding 5: the Python proxy also leaks detailed transport errors

The current review only calls out the Rust runtime's client-visible error leakage. The Python proxy has the same issue.

Evidence:

- On `httpx.HTTPError`, the proxy returns `str(exc)` to the client in [mcpgateway/transports/rust_mcp_runtime_proxy.py:110-124](../mcpgateway/transports/rust_mcp_runtime_proxy.py).

Impact:

- Backend host/port and transport details can leak to clients even before a request reaches the Rust runtime.

Recommended fix:

- Keep detailed exception text in logs only.
- Return a generic 502 payload to clients.

## Validation Of Existing Findings In `todo/code-review.md`

### 1. Client-supplied `x-contextforge-auth-context` header bypasses authentication

Status: correct.

Notes:

- This is real on the direct public Rust listener in [tools_rust/mcp_runtime/src/lib.rs:2317-2357](../tools_rust/mcp_runtime/src/lib.rs).
- The Python proxy strips the header before forwarding in [mcpgateway/transports/rust_mcp_runtime_proxy.py:41-49](../mcpgateway/transports/rust_mcp_runtime_proxy.py).
- The review should be expanded to also cover the parallel `x-contextforge-server-id` trust issue above.

### 2. Redis `KEYS` command in production path

Status: partly correct.

What is correct:

- The code really uses `redis.keys()` in [tools_rust/mcp_runtime/src/lib.rs:2790-2798](../tools_rust/mcp_runtime/src/lib.rs).
- `KEYS` is a scalability/latency risk on large Redis keyspaces.

What should be corrected:

- This is not on the normal MCP request hot path.
- It is only used through the health endpoint path: [tools_rust/mcp_runtime/src/lib.rs:1010-1024](../tools_rust/mcp_runtime/src/lib.rs) -> [tools_rust/mcp_runtime/src/lib.rs:2726-2737](../tools_rust/mcp_runtime/src/lib.rs) -> [tools_rust/mcp_runtime/src/lib.rs:2790-2798](../tools_rust/mcp_runtime/src/lib.rs).

Recommended wording:

- Reframe as "health endpoint uses Redis `KEYS`, creating a potential Redis DoS/scalability problem under large keyspaces or frequent health polling."

### 3. No TLS for PostgreSQL connections

Status: partly correct.

What is correct:

- The runtime hardwires PostgreSQL to `NoTls` in [tools_rust/mcp_runtime/src/lib.rs:2118-2127](../tools_rust/mcp_runtime/src/lib.rs).
- `tokio-postgres` is built without TLS support in [tools_rust/mcp_runtime/Cargo.toml:20-30](../tools_rust/mcp_runtime/Cargo.toml).

What should be corrected:

- "Credentials and query data are sent in plaintext" is too absolute.
- If the database server requires TLS, the connection will fail rather than silently downgrading.

Recommended wording:

- Reframe as "the runtime has no PostgreSQL TLS support, so it cannot safely connect to deployments that require encrypted DB transport."

### 4. Internal endpoints exposed without authentication

Status: correct.

Notes:

- The shared router mounts the event-store endpoints in [tools_rust/mcp_runtime/src/lib.rs:897-905](../tools_rust/mcp_runtime/src/lib.rs).
- The same router is used for both public and private listeners in [tools_rust/mcp_runtime/src/lib.rs:937-964](../tools_rust/mcp_runtime/src/lib.rs).
- The handlers only check `event_store_enabled`, not caller identity, in [tools_rust/mcp_runtime/src/lib.rs:1105-1151](../tools_rust/mcp_runtime/src/lib.rs).

### 5. Error detail leakage to clients

Status: correct, but incomplete.

What is correct:

- The Rust runtime returns `err.to_string()` / `data: err.to_string()` in many client-visible errors.

What is missing:

- The Python proxy leaks `str(exc)` to clients too in [mcpgateway/transports/rust_mcp_runtime_proxy.py:110-124](../mcpgateway/transports/rust_mcp_runtime_proxy.py).

### 6. `session_id` accepted from query parameters

Status: partly correct.

What is correct:

- Rust accepts `session_id` from the query string in [tools_rust/mcp_runtime/src/lib.rs:3445-3454](../tools_rust/mcp_runtime/src/lib.rs).
- This is security-sensitive because session IDs are effectively bearer-style session selectors.

What should be corrected:

- This is not a clean new regression introduced only by the Rust runtime.
- The existing Python initialize path also accepts `request.query_params.get("session_id")` in [mcpgateway/main.py:8321-8332](../mcpgateway/main.py).
- The Rust behavior is intentionally exercised in tests, for example [tools_rust/mcp_runtime/src/lib.rs:8487-8515](../tools_rust/mcp_runtime/src/lib.rs).

Important nuance:

- The risk is amplified because ownerless sessions are explicitly accepted in [tools_rust/mcp_runtime/src/lib.rs:9016-9052](../tools_rust/mcp_runtime/src/lib.rs).

Recommended wording:

- Reframe as "existing compatibility behavior that remains unsafe and should be retired," not as an accidental branch-specific regression.

### 7. `ensure_upstream_session` holds mutex across HTTP I/O

Status: correct.

Notes:

- The lock is held across `initialize_upstream_session().await` in [tools_rust/mcp_runtime/src/lib.rs:6791-6817](../tools_rust/mcp_runtime/src/lib.rs).
- The contrast with the better RMCP pattern in [tools_rust/mcp_runtime/src/lib.rs:6991-7006](../tools_rust/mcp_runtime/src/lib.rs) is fair.

### 8. Monolithic 9167-line `lib.rs`

Status: accurate observation, but not a defect finding.

Notes:

- This is maintainability/refactor feedback, not a correctness or security bug.
- I would not send it as a finding if the goal is a defect-focused review.

### 9. URL derivation boilerplate

Status: accurate observation, but not a defect finding.

Notes:

- Same as finding 8: valid cleanup suggestion, not a concrete bug/regression.

### 10. Unbounded in-memory session caches

Status: mostly correct.

What is correct:

- The caches are unbounded for unique cold keys.
- There is no periodic background sweeper.
- `resolved_tool_call_plans` keeps expired entries until overwritten in [tools_rust/mcp_runtime/src/lib.rs:6569-6592](../tools_rust/mcp_runtime/src/lib.rs).
- `upstream_tool_sessions` only drop entries on explicit error/removal paths.

What should be softened:

- The current review table slightly overstates some behaviors.
- `runtime_sessions` are lazily swept on access and health checks in [tools_rust/mcp_runtime/src/lib.rs:2726-2750](../tools_rust/mcp_runtime/src/lib.rs).
- Reused keys overwrite prior entries rather than growing without bound for that key.

Recommended wording:

- "Cold unique sessions/plans can accumulate without a periodic sweeper or global size bound."

### 11. Hardcoded Redis key prefixes for affinity

Status: correct.

Notes:

- Runtime session keys use `cache_prefix`, but affinity keys hardcode `mcpgw:` in [tools_rust/mcp_runtime/src/lib.rs:2867-2869](../tools_rust/mcp_runtime/src/lib.rs) and [tools_rust/mcp_runtime/src/lib.rs:2918](../tools_rust/mcp_runtime/src/lib.rs).
- Python uses the same hardcoded affinity key pattern, so the collision concern is real anywhere multiple deployments share a Redis instance.

## Issues I Re-Checked And Am Not Promoting To Findings

### 1. "Rust proxy should fall back to Python when the sidecar is unavailable"

I am not treating this as a defect.

Reason:

- The current behavior looks intentional and is test-covered.
- The proxy returns a JSON-RPC 502 instead of falling back in [mcpgateway/transports/rust_mcp_runtime_proxy.py:110-124](../mcpgateway/transports/rust_mcp_runtime_proxy.py).
- That behavior is explicitly asserted in [tests/unit/mcpgateway/transports/test_rust_mcp_runtime_proxy.py:603-636](../tests/unit/mcpgateway/transports/test_rust_mcp_runtime_proxy.py).

### 2. "Initialize can rebind a session to a different server"

I am not treating this as a clean branch-specific finding.

Reason:

- The Rust initialize path does overwrite stored `server_id` on success in [tools_rust/mcp_runtime/src/lib.rs:2604-2672](../tools_rust/mcp_runtime/src/lib.rs).
- But the existing Python initialize/session flow also does not maintain a server-bound session identity in [mcpgateway/main.py:8321-8332](../mcpgateway/main.py) and [mcpgateway/cache/session_registry.py:2086-2149](../mcpgateway/cache/session_registry.py).
- That makes it existing system behavior, not a clearly introduced regression in this branch.

## Bottom Line

If this feedback is being sent back to the reviewer, the most important corrections are:

- Add the missing `x-contextforge-server-id` trust bug on direct public Rust ingress.
- Add the missing spoofable/default-loopback `client_ip` bug in the Rust -> Python auth seam.
- Reframe finding 2 as a health-path `KEYS` issue.
- Reframe finding 3 as missing PostgreSQL TLS support, not guaranteed plaintext in every deployment.
- Extend finding 5 to include the Python proxy's client-visible exception text.
- Reframe finding 6 as existing compatibility/security debt rather than a new accidental regression.
- Drop or demote findings 8 and 9 if the goal is a bug-focused review.
