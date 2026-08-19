# Reverse Proxy Service (Developer Guide)

This page is for developers working on the gateway-side reverse-proxy service. It covers how the service is put together, where the tests live, and how to run the live end-to-end harness that exercises the full path against real infrastructure.

For client usage and deployment, see the [MCP Reverse Proxy user guide](../using/reverse-proxy.md).

---

## What the service is

The reverse-proxy service lets an external, separately maintained client ([contextforge-org/mcp-reverse-proxy](https://github.com/contextforge-org/mcp-reverse-proxy)) connect a downstream MCP server to the gateway without inbound network access. The client dials out over an authenticated WebSocket to `mcpgateway/routers/reverse_proxy.py`, registers its downstream server, and the gateway persists that registration as an internal `PROXIED` gateway with a stable identity derived from owner, scope, and the normalized server name.

Key pieces:

- **Typed wire protocol** (`mcpgateway/services/reverse_proxy_protocol.py`): the message contract between client and gateway. Registration, invocation, heartbeat, and teardown frames are validated against this protocol.
- **Session manager** (`mcpgateway/services/reverse_proxy_sessions.py`): process-local and the sole authority for the four HTTP session endpoints. It owns the mapping from session to client WebSocket inside one worker.
- **PROXIED dispatch**: `tools/call`, `resources/read`, and `prompts/get` against a reverse-proxied server are dispatched over the owning WebSocket rather than an outbound HTTP connection. Stored downstream credentials are decrypted at dispatch time and forwarded to the downstream server; they are never logged.
- **Heartbeat freshness and reaper**: client heartbeats keep a session fresh. A reaper evicts sessions that go silent past `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT`, which drives the reachability state of the catalog gateway.
- **Distributed relay** (`mcpgateway/services/reverse_proxy_relay*.py`): optional Redis-backed relay for multi-worker deployments. When `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED=true`, a call landing on a non-owner worker is routed to the worker that owns the client WebSocket. Redis holds short-lived owner generations, worker heartbeats, and signed request/response envelopes; the WebSocket itself stays local to its owner worker.

Both `MCPGATEWAY_REVERSE_PROXY_ENABLED` and `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED` default to off.

### Security posture

- **Two layers, always.** Layer 1 is token scoping, driven by the exact `_PERMISSION_PATTERNS` mappings on the reverse-proxy routes. Layer 2 is RBAC. Neither substitutes for the other.
- **Fail-closed dispatch.** If ownership is not authoritative (for example, Redis is unavailable in distributed mode), dispatch fails closed instead of guessing.
- **Server-owned identity.** The `PROXIED` gateway identity (owner, scope, normalized name) is derived server-side and cannot be overridden by the client.

---

## Unit test surface

The reverse-proxy code is covered by focused unit tests:

| Path | Covers |
| ---- | ------ |
| `tests/unit/mcpgateway/routers/test_reverse_proxy.py` | WebSocket endpoint and the four HTTP session endpoints |
| `tests/unit/mcpgateway/services/test_reverse_proxy_*.py` | Protocol, sessions, catalog, discovery, and relay services |
| `tests/unit/mcpgateway/services/test_{tool,resource,prompt}_service_reverse_proxy.py` | PROXIED dispatch from the tool, resource, and prompt services |
| `tests/unit/mcpgateway/middleware/test_token_scoping.py` | Layer-1 token scoping on the reverse-proxy routes |
| `tests/unit/mcpgateway/test_reverse_proxy_live_harness.py` | Harness invariants, including that parallel runs from different worktrees stay isolated |

The distributed lifecycle also has deterministic race and compensation regression tests, so ordering-sensitive bugs (concurrent registration, relay failover, eviction) are pinned without needing live infrastructure.

---

## Live end-to-end harness

The harness in `tests/live_gateway/reverse_proxy/` runs the real maintained client against a containerized multi-worker gateway and executes 12 live scenarios. It is **not** part of `make test` or CI. It is a manually invoked live verification for when you change the reverse-proxy service, the protocol, or the dispatch path.

### Prerequisites

- Docker with compose v2
- `uv`
- A local clone of the maintained client ([contextforge-org/mcp-reverse-proxy](https://github.com/contextforge-org/mcp-reverse-proxy))

The client clone is located via `MCP_REVERSE_PROXY_CLIENT_ROOT`, which defaults to `../../../mcp-reverse-proxy` relative to the repo root (the fleet-worktree layout). Most developers need to set it explicitly:

```bash
export MCP_REVERSE_PROXY_CLIENT_ROOT=/path/to/mcp-reverse-proxy
```

The script exits with status 2 and a clear message if `pyproject.toml` is missing at that path.

### Invocation

```bash
RP_E2E_RUN_ID=my-run tests/live_gateway/reverse_proxy/run.sh
```

Any working directory works; the script resolves the repo root via `git rev-parse`. If `RP_E2E_RUN_ID` is unset, the run id defaults to a pid/random slug.

### What it runs

The script brings up the repo's `docker-compose.yml` stack plus the `tests/live_gateway/reverse_proxy/docker-compose.reverse-proxy.yml` override:

- One gateway container with **2 Gunicorn workers**, `MCPGATEWAY_REVERSE_PROXY_ENABLED=true` and `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED=true`
- Redis, Postgres, pgbouncer, and nginx
- The pinned fast-test downstream server, the repo compliance server, and auth/authority probe servers
- The real maintained client, as three separate client processes

It then runs two pytest modules:

- `test_reverse_proxy_e2e.py` (11 scenarios)
- `test_reverse_proxy_feature_flag_e2e.py` (1 scenario)

The scenarios cover:

1. Auth-denial status preservation
2. Token-scope 403 on a restricted token
3. Authority non-override (client cannot claim server-owned identity)
4. Resource and prompt round-trips, including typed blobs
5. Cross-worker relay invocation
6. Server-owned authority on discovered catalog rows
7. Stored bearer token forwarding without exposure in logs
8. Downstream-restart re-registration recovery
9. Redis-outage fail-closed behavior plus recovery
10. Client-stop unreachable state plus fail-closed dispatch
11. Heartbeat-timeout eviction
12. Feature-flag-off route absence

### Isolation

All host ports are picked dynamically, so there are no fixed-port conflicts. Every compose resource, container name, and the gateway image tag is namespaced by the run slug, which means parallel runs from different worktrees are isolated. A unit test (`tests/unit/mcpgateway/test_reverse_proxy_live_harness.py`) asserts this.

### Artifacts

Each run writes to `artifacts/reverse-proxy-e2e/<run-slug>/`:

- `junit.xml` for the pytest results
- `gateway.log` plus per-process logs for each client and probe server

After the pytest run, the harness also greps the logs for bearer tokens and the forwarded downstream token, and fails if any credential leaked into a log.

### Cleanup

An `EXIT` trap kills the client and server processes, tears down containers, the network, and volumes, and removes the run-scoped gateway image unless `RP_GATEWAY_IMAGE` was supplied externally. If any Docker resources survive cleanup, the script reports it and exits non-zero.

### Environment overrides

| Variable | Purpose |
| -------- | ------- |
| `RP_E2E_RUN_ID` | Stable run name; also the artifact directory slug |
| `MCP_REVERSE_PROXY_CLIENT_ROOT` | Path to the maintained client clone |
| `RP_GATEWAY_IMAGE` | Use a prebuilt gateway image instead of building one |
| `RP_HEARTBEAT_TIMEOUT` | Heartbeat eviction timeout in seconds (default 3) |
| `FAST_TEST_PORT`, `NGINX_PORT`, `REDIS_HOST_PORT`, `POSTGRES_HOST_PORT`, `PGBOUNCER_HOST_PORT`, `RP_COMPLIANCE_PORT`, `RP_AUTH_PORT`, `RP_FEATURE_OFF_PORT` | Pin a host port instead of picking a random one |
| `RP_JWT_SECRET_KEY`, `RP_AUTH_ENCRYPTION_SECRET` | Override the generated per-run secrets |

---

## Related documentation

- [MCP Reverse Proxy user guide](../using/reverse-proxy.md) - client usage, deployment, and gateway-side configuration
- [Testing ContextForge](../testing/index.md) - the wider testing strategy
