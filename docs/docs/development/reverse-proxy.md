# Reverse Proxy Service (Developer Guide)

This page is for developers working on the gateway-side reverse-proxy service. It covers how the service is put together and where the tests live.

For client usage and deployment, see the [MCP Reverse Proxy user guide](../using/reverse-proxy.md).

---

## What the service is

The reverse-proxy service lets an external, separately maintained client ([contextforge-org/mcp-reverse-proxy](https://github.com/contextforge-org/mcp-reverse-proxy)) connect a downstream MCP server to the gateway without inbound network access. The client opens an outbound, authenticated WebSocket to `mcpgateway/routers/reverse_proxy.py`. The client registers its downstream server. The gateway persists the registration as an internal `PROXIED` gateway. The gateway derives a stable identity from owner, scope, and the normalized server name.

Key pieces:

- **Typed wire protocol** (`mcpgateway/services/reverse_proxy_protocol.py`): the message contract between client and gateway. The gateway validates registration, invocation, heartbeat, and teardown frames against this protocol.
- **Session manager** (`mcpgateway/services/reverse_proxy_sessions.py`): process-local and the sole authority for the four HTTP session endpoints. It owns the mapping from session to client WebSocket inside one worker.
- **PROXIED dispatch**: `tools/call`, `resources/read`, and `prompts/get` against a reverse-proxied server run over the owning WebSocket, not over an outbound HTTP connection. Dispatch decrypts stored downstream credentials and forwards them to the downstream server. The gateway never logs these credentials.
- **Heartbeat freshness and reaper**: client heartbeats keep a session fresh. A reaper evicts sessions that stop sending heartbeats past `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT`. Eviction drives the reachability state of the catalog gateway.
- **Distributed relay** (`mcpgateway/services/reverse_proxy_relay*.py`): optional Redis-backed relay for multi-worker deployments. When `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED=true`, a call can land on a non-owner worker. The relay routes the call to the worker that owns the client WebSocket. Redis holds short-lived owner generations, worker heartbeats, and signed request/response envelopes. The WebSocket stays local to its owner worker.

Both `MCPGATEWAY_REVERSE_PROXY_ENABLED` and `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED` default to off. The distributed flag is strict in both directions. With the flag off, `get_reverse_proxy_relay()` in `mcpgateway/services/reverse_proxy_relay_runtime.py` returns the local-only wrapper, and the factory creates no Redis client. With the flag on, the factory fails fast when the canonical Redis connection is unavailable. A misconfigured worker therefore never starts half-distributed.

### Security posture

- **Two layers, always.** Layer 1 is token scoping, driven by the exact `_PERMISSION_PATTERNS` mappings on the reverse-proxy routes. Layer 2 is RBAC. Neither substitutes for the other.
- **Fail-closed dispatch.** When ownership is not authoritative, dispatch fails closed. Examples: the client disconnects, the reaper evicts the session, or Redis is unavailable in distributed mode.
- **Server-owned identity.** The `PROXIED` gateway identity (owner, scope, normalized name) is derived server-side and cannot be overridden by the client.

---

## Distributed routing and the Redis lease

The distributed relay is split across three modules:

- `mcpgateway/services/reverse_proxy_relay.py`: the relay state machine. The `_RedisLease` helper parameterizes the registration and owner leases over key, holder value, and TTL. Generation-fenced Lua scripts implement acquire, refresh, promote, and release. A stale generation can never overwrite or delete a newer owner.
- `mcpgateway/services/reverse_proxy_relay_runtime.py`: `reverse_proxy_relay_lifespan()` supervises the signed-envelope listener and the worker-heartbeat refresh with readiness and deterministic cleanup. The runtime regenerates worker identity after a process fork.
- `mcpgateway/services/reverse_proxy_lifecycle.py`: the lease seams. Registration claims, maintains, and promotes the registration lease around the catalog commits. Teardown and registration compensation release exact owner generations best-effort through fenced compare-delete. A Redis cleanup failure therefore never strands routing state.
- `mcpgateway/services/reverse_proxy_relay_io.py` and `reverse_proxy_relay_models.py`: the signed HMAC envelopes and the typed Redis models behind them.

One registration walks the lease lifecycle in order: `claim_registration` (single-writer claim) → a `maintain_registration` heartbeat task → `heartbeat_registration` as the commit gate → `promote_registration` (only the claim holder can promote to owner) → `release_registration`. Eviction of a dead worker reclaims the owner generation by compare-delete. The reclaimer first confirms that the worker heartbeat is absent. An unreachable-write guard prevents eviction persistence from racing a live owner or an in-flight replacement registration.

---

## Unit test surface

Focused unit tests cover the reverse-proxy code:

| Path | Covers |
| ---- | ------ |
| `tests/unit/mcpgateway/routers/test_reverse_proxy.py` | WebSocket endpoint and the four HTTP session endpoints |
| `tests/unit/mcpgateway/services/test_reverse_proxy_*.py` | Protocol, sessions, catalog, discovery, and relay services (`test_reverse_proxy_relay.py` pins the Redis lease fencing, owner claims, and signed-envelope relay) |
| `tests/unit/mcpgateway/services/test_{tool,resource,prompt}_service_reverse_proxy.py` | PROXIED dispatch from the tool, resource, and prompt services |
| `tests/unit/mcpgateway/middleware/test_token_scoping.py` | Layer-1 token scoping on the reverse-proxy routes |

The distributed lifecycle adds deterministic race and compensation regression tests. These tests pin ordering-sensitive bugs (concurrent registration, relay failover, dead-owner reclaim, eviction) without live infrastructure.

---

## Live end-to-end harness

The harness in `tests/live_gateway/reverse_proxy/` runs the real maintained client against a containerized multi-worker gateway. It executes 12 live scenarios. It is **not** part of `make test` or CI. Run it manually when you change the reverse-proxy service, the protocol, or the dispatch path.

### Prerequisites

- Docker with compose v2
- `uv`
- A local clone of the maintained client ([contextforge-org/mcp-reverse-proxy](https://github.com/contextforge-org/mcp-reverse-proxy)) - only when you run the client from source. You do not need it when `RP_CLIENT_IMAGE` is set.

The script locates the client clone via `MCP_REVERSE_PROXY_CLIENT_ROOT`. The variable defaults to `../../../mcp-reverse-proxy` relative to the repo root (the fleet-worktree layout). Most developers need to set it explicitly:

```bash
export MCP_REVERSE_PROXY_CLIENT_ROOT=/path/to/mcp-reverse-proxy
```

When `RP_CLIENT_IMAGE` is unset, the script validates the clone. It exits with status 2 and a clear message when `pyproject.toml` is missing at that path.

### Invocation

```bash
RP_E2E_RUN_ID=my-run tests/live_gateway/reverse_proxy/run.sh
```

Any working directory works. The script resolves the repo root via `git rev-parse`. If `RP_E2E_RUN_ID` is unset, the run id defaults to a pid/random slug.

Set `RP_CLIENT_IMAGE` to run the client from the published container image instead of a local clone. Each client then runs as a container on the compose network. No client clone is required:

```bash
RP_CLIENT_IMAGE=ghcr.io/contextforge-org/mcp-reverse-proxy:latest RP_E2E_RUN_ID=my-run tests/live_gateway/reverse_proxy/run.sh
```

### What it runs

The script brings up the repo's `docker-compose.yml` stack plus the `tests/live_gateway/reverse_proxy/docker-compose.reverse-proxy.yml` override:

- One gateway container with **2 Gunicorn workers**, `MCPGATEWAY_REVERSE_PROXY_ENABLED=true` and `MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED=true`
- Redis, Postgres, pgbouncer, and nginx
- The real maintained client, as three separate client processes (or three containers on the compose network with `RP_CLIENT_IMAGE`)

It then runs two pytest modules:

- `test_reverse_proxy_e2e.py` (11 scenarios)
- `test_reverse_proxy_feature_flag_e2e.py` (1 scenario)

The scenarios cover:

1. Auth-denial status preservation
2. Token-scope 403 on a restricted token
3. Authority non-override (the client cannot claim server-owned identity)
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

The script picks all host ports dynamically. Fixed-port conflicts cannot occur. Every compose resource, container name, and the gateway image tag is namespaced by the run slug. Parallel runs from different worktrees stay isolated. A unit test (`tests/unit/mcpgateway/services/test_reverse_proxy_live_harness.py`) asserts this.

### Artifacts

Each run writes to `artifacts/reverse-proxy-e2e/<run-slug>/`:

- `junit.xml` for the pytest results
- `gateway.log` plus per-process logs for each client and probe server

After the pytest run, the harness greps the logs for bearer tokens and the forwarded downstream token. The harness fails the run when a credential appears in any log.

### Cleanup

An `EXIT` trap kills the client and server processes. With `RP_CLIENT_IMAGE`, it captures the client container logs and removes the containers instead. It tears down containers, the network, and volumes. It removes the run-scoped gateway image unless `RP_GATEWAY_IMAGE` is supplied externally. If any Docker resource survives cleanup, the script reports it and exits non-zero.

### Environment overrides

| Variable | Purpose |
| -------- | ------- |
| `RP_E2E_RUN_ID` | Run identifier. The script derives the run slug and the artifact directory from it. |
| `MCP_REVERSE_PROXY_CLIENT_ROOT` | Path to the maintained client clone (not used when `RP_CLIENT_IMAGE` is set) |
| `RP_CLIENT_IMAGE` | Run the three clients from this container image (for example `ghcr.io/contextforge-org/mcp-reverse-proxy:latest`) instead of `uv run` from a local clone |
| `RP_GATEWAY_IMAGE` | Use a prebuilt gateway image instead of building one |
| `FAST_TIME_IMAGE` | Override the pinned fast-test downstream server image |
| `FAST_TEST_PORT`, `NGINX_PORT`, `REDIS_HOST_PORT`, `POSTGRES_HOST_PORT`, `PGBOUNCER_HOST_PORT`, `RP_COMPLIANCE_PORT`, `RP_AUTH_PORT`, `RP_FEATURE_OFF_PORT` | Pin a host port instead of picking a random one |
| `RP_HEARTBEAT_TIMEOUT` | Heartbeat eviction timeout in seconds (default 3) |
| `RP_JWT_SECRET_KEY`, `RP_AUTH_ENCRYPTION_SECRET` | Override the generated per-run secrets |
| `RP_PLATFORM_ADMIN_PASSWORD`, `RP_DEFAULT_USER_PASSWORD` | Override the generated per-run credentials |

---

## Related documentation

- [MCP Reverse Proxy user guide](../using/reverse-proxy.md) - client usage, deployment, and gateway-side configuration
- [Testing ContextForge](../testing/index.md) - the wider testing strategy
