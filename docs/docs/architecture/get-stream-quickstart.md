# GET /mcp Stream — Quickstart

Hands-on guide for exercising the server-to-client SSE stream introduced in
[ADR-052](adr/052-get-stream-and-server-initiated-requests.md). Three
deployment shapes, in increasing complexity:

1. Bare `make dev` (single process, no Redis)
2. `make compose-up` (single-replica container, no Redis)
3. `make testing-up` (3-replica multi-node, Redis-backed)

Pick the lowest tier that exercises what you're trying to verify. The wire
protocol is identical in all three; only the cross-process / cross-node
fanout differs.

## Prerequisite (all tiers)

The GET stream requires stateful sessions. Without them you'll keep getting
405. Add this to `.env`:

```bash
USE_STATEFUL_SESSIONS=true
```

`MCP_GET_STREAM_ENABLED=true` is the default; you only need to set it
explicitly if you want to flip the kill switch off.

## Tier 1 — Bare `make dev`

```bash
make dev
```

Backend selection: `cache_type` defaults to `database`, so the bus binds
`InMemoryServerEventBus` and the listener claim uses an in-process dict +
`asyncio.Lock`. Single process, no Redis required.

What works: GET stream, `Last-Event-Id` resume, single-listener 409,
server-initiated request correlation. Everything that doesn't depend on
fanout across processes.

What doesn't work in this tier: cross-worker delivery (there's only one
worker). If you start `gunicorn -w 4` against this config, each worker has
its own event-bus state — clients hitting different workers won't see each
other's events. That's by design (see ADR-052 § "Single-node vs. multi-node
fallback contract") and is why we ship `cache_type=redis` for multi-worker.

## Tier 2 — `make compose-up` (single replica, no Redis enforcement)

For containerized testing without spinning up the full Redis-backed stack:

```bash
make compose-up           # docker-compose.yml + override.lite.yml; 2 replicas
```

To collapse to single replica without Redis affinity:

```bash
GATEWAY_REPLICAS=1 make compose-up
```

The default `make compose-up` runs 2 replicas, which means you'd need
`MCPGATEWAY_SESSION_AFFINITY_ENABLED=true` and Redis in the picture (see
Tier 3) — otherwise POSTs may land on a different replica than holds the
upstream session, and request correlation will fail. Stick to single
replica here unless you're ready for the multi-node setup.

## Tier 3 — `make testing-up` (multi-node, Redis-backed)

This is the right tier for verifying ADR-052 multi-node behavior — Pub/Sub
fanout, listener-claim race resolution, POST affinity routing.

### What you get out of the box

`make testing-up` brings up the testing profile with:

- 3 gateway replicas (`GATEWAY_REPLICAS=3`)
- 24 gunicorn workers per replica (`GUNICORN_WORKERS=24`) — 72 worker
  processes total
- nginx on `:8080` fronting them
- PostgreSQL, Redis, Locust, fast_test_server, A2A echo agent, MCP Inspector
- `CACHE_TYPE=redis` already set in `docker-compose.yml`

### The two flags you need to enable

Edit `docker-compose.yml` and uncomment:

```yaml
- USE_STATEFUL_SESSIONS=true                        # line ~444
- MCPGATEWAY_SESSION_AFFINITY_ENABLED=true          # line ~447
```

`USE_STATEFUL_SESSIONS` is the GET-stream prerequisite (Tier 1's flag, same
meaning). `MCPGATEWAY_SESSION_AFFINITY_ENABLED` is what makes POST routing
land on the worker holding the upstream session — without it, server-
initiated request correlation will fail because the response POST won't
reach the worker holding the `RequestResponder`.

Then:

```bash
make testing-down              # if already running
make testing-up                # rebuilds against your edits
```

### Verifying it works end-to-end

Open the MCP Inspector at `http://localhost:6274`. Connect to the gateway
via `http://nginx:80/mcp` (or the gateway URL surfaced in the testing-up
output). Run `initialize` — you'll get an `Mcp-Session-Id` back.

Then in a separate terminal:

```bash
TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
        --username admin@example.com --exp 60 --secret KEY)
SID=<paste-the-mcp-session-id-from-inspector>

# 1. Open the GET stream — holds open with text/event-stream
curl -N \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SID" \
  -H "Accept: text/event-stream" \
  http://localhost:8080/mcp

# 2. From a third terminal, trigger an upstream notification (e.g., reload
#    a tool on fast_test_server). The notification should appear in the
#    GET stream from step 1.

# 3. Single-listener invariant: open a second GET on the same SID → 409
curl -i -H "Authorization: Bearer $TOKEN" \
       -H "Mcp-Session-Id: $SID" \
       -H "Accept: text/event-stream" \
       http://localhost:8080/mcp
# expect: HTTP/1.1 409 Conflict, Retry-After: 1
```

### Watching the cross-node fanout

Tail the gateway logs while a GET is held open and a notification fires:

```bash
docker compose logs -f gateway | grep -E "ServerEventBus|listener|publish"
```

You should see the bus pick `Redis backend` at startup, the listener-claim
on whichever worker accepts the GET, and the publish from whichever worker
holds the upstream session — and they may be different workers. That's the
point of ADR-052: GET is node-agnostic.

To force the cross-node case deterministically, scale to many replicas and
hit the gateway with parallel sessions. nginx round-robins, so within a
few requests you'll have a session whose GET and POST land on different
workers.

### Tearing down

```bash
make testing-down
```

## Common gotchas

- **No upstream MCP server registered = no notifications to fan out.** The
  GET stream stays open with keepalives but won't carry payloads. Register
  an MCP server (the `fast_test_server` is auto-registered by
  `make testing-up`) and exercise something that emits notifications.
- **`USE_STATEFUL_SESSIONS=false` (the default) → 405.** This is by design
  per spec — the GET stream needs an event store.
- **Session id from the wrong `initialize`.** A `Mcp-Session-Id` issued
  yesterday won't match anything today; re-run `initialize`.
- **`Accept` header missing.** GET /mcp requires `Accept: text/event-stream`
  (or `*/*`); other Accept values get 406.
- **Multi-replica without `MCPGATEWAY_SESSION_AFFINITY_ENABLED`.** GET still
  works (Pub/Sub doesn't need affinity), but POSTs may land on the wrong
  worker — server-initiated request correlation breaks because the
  `RequestResponder` lives in one worker's memory.

## Where to look in code

- `mcpgateway/transports/server_event_bus.py` — bus implementations and
  factory
- `mcpgateway/transports/streamablehttp_transport.py` —
  `_handle_get_stream`, `_maybe_intercept_response_post`
- `mcpgateway/services/session_affinity.py` — `claim_listener` /
  `heartbeat_listener` / `release_listener`
- `mcpgateway/services/notification_service.py` —
  `_forward_notification_to_stream`, `_forward_request_to_stream`,
  `complete_request`

## Related

- [ADR-052: GET /mcp Stream and Server-Initiated Request Correlation](adr/052-get-stream-and-server-initiated-requests.md)
- [ADR-038: Multi-Worker Session Affinity](adr/038-multi-worker-session-affinity.md)
- [Rust MCP Runtime — DEVELOPING § GET /mcp Stream Relay](../../crates/mcp_runtime/DEVELOPING.md)
- [MCP Streamable HTTP — Listening for messages from the server](https://modelcontextprotocol.io/specification/draft/basic/transports#listening-for-messages-from-the-server)
