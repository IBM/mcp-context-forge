# Reverse Proxy Service (Developer Guide)

This page is for developers working on the gateway-side reverse-proxy service. It covers how the service is put together and where the tests live.

For client usage and deployment, see the [MCP Reverse Proxy user guide](../using/reverse-proxy.md).

---

## What the service is

The reverse-proxy service lets an external, separately maintained client ([contextforge-org/mcp-reverse-proxy](https://github.com/contextforge-org/mcp-reverse-proxy)) connect a downstream MCP server to the gateway without inbound network access. The client dials out over an authenticated WebSocket to `mcpgateway/routers/reverse_proxy.py`, registers its downstream server, and the gateway persists that registration as an internal `PROXIED` gateway with a stable identity derived from owner, scope, and the normalized server name.

Key pieces:

- **Typed wire protocol** (`mcpgateway/services/reverse_proxy_protocol.py`): the message contract between client and gateway. Registration, invocation, heartbeat, and teardown frames are validated against this protocol.
- **Session manager** (`mcpgateway/services/reverse_proxy_sessions.py`): process-local and the sole authority for session routing. It owns the mapping from session to client WebSocket inside one worker.
- **PROXIED dispatch**: `tools/call`, `resources/read`, and `prompts/get` against a reverse-proxied server are dispatched over the owning WebSocket rather than an outbound HTTP connection. Stored downstream credentials are decrypted at dispatch time and forwarded to the downstream server; they are never logged.
- **Heartbeat freshness and reaper**: client heartbeats keep a session fresh. A reaper evicts sessions that go silent past `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT`, which drives the reachability state of the catalog gateway.

`MCPGATEWAY_REVERSE_PROXY_ENABLED` defaults to off.

### Security posture

- **Two layers, always.** Layer 1 is token scoping, driven by the exact `_PERMISSION_PATTERNS` mappings on the reverse-proxy routes. Layer 2 is RBAC. Neither substitutes for the other.
- **Fail-closed dispatch.** If no live connection exists for the gateway (for example, the client disconnected or was evicted), dispatch fails closed instead of guessing.
- **Server-owned identity.** The `PROXIED` gateway identity (owner, scope, normalized name) is derived server-side and cannot be overridden by the client.

---

## Unit test surface

The reverse-proxy code is covered by focused unit tests:

| Path | Covers |
| ---- | ------ |
| `tests/unit/mcpgateway/routers/test_reverse_proxy.py` | WebSocket endpoint admission and lifecycle |
| `tests/unit/mcpgateway/services/test_reverse_proxy_*.py` | Protocol, sessions, catalog, and discovery services |
| `tests/unit/mcpgateway/services/test_{tool,resource,prompt}_service_reverse_proxy.py` | PROXIED dispatch from the tool, resource, and prompt services |
| `tests/unit/mcpgateway/middleware/test_token_scoping.py` | Layer-1 token scoping on the reverse-proxy routes |

The registration lifecycle also has deterministic race and compensation regression tests, so ordering-sensitive bugs (concurrent registration, eviction) are pinned without needing live infrastructure.

---

## Related documentation

- [MCP Reverse Proxy user guide](../using/reverse-proxy.md) - client usage, deployment, and gateway-side configuration
- [Testing ContextForge](../testing/index.md) - the wider testing strategy
