# Reverse Proxy Service (Developer Guide)

This page is for developers working on the gateway-side reverse-proxy service. It covers how the service is put together and where the tests live.

For client usage and deployment, see the [MCP Reverse Proxy user guide](../using/reverse-proxy.md).

---

## What the service is

The reverse-proxy service lets an external, separately maintained client ([contextforge-org/mcp-reverse-proxy](https://github.com/contextforge-org/mcp-reverse-proxy)) connect a downstream MCP server to the gateway without inbound network access. The client dials out over an authenticated WebSocket to `mcpgateway/routers/reverse_proxy.py`, and registers its downstream server metadata on a typed, owner-bound session. HTTP endpoints list sessions, send a request to a session, stream a session over SSE, and disconnect a session.

Key pieces:

- **Typed wire protocol** (`mcpgateway/services/reverse_proxy_protocol.py`): the message contract between client and gateway. Registration, invocation, heartbeat, and teardown frames are validated against this protocol.
- **Session manager** (`mcpgateway/services/reverse_proxy_sessions.py`): process-local and the sole authority for session routing. It owns the mapping from session to client WebSocket inside one worker.
- **Connection lifecycle** (`mcpgateway/services/reverse_proxy_lifecycle.py`): the receive pump, register and heartbeat handling, and shielded teardown for one admitted connection.
- **Heartbeat freshness and reaper**: client heartbeats keep a session fresh. A reaper evicts sessions that go silent past `MCPGATEWAY_REVERSE_PROXY_HEARTBEAT_TIMEOUT`.

`MCPGATEWAY_REVERSE_PROXY_ENABLED` defaults to off.

### Security posture

- **Two layers, always.** Layer 1 is token scoping, driven by the exact `_PERMISSION_PATTERNS` mappings on the reverse-proxy routes. Layer 2 is RBAC. Neither substitutes for the other.
- **Server-owned identity.** The connection id and the session owner come from the server and the authenticated principal. The client cannot override them.
- **Owner-bound HTTP endpoints.** Each session endpoint enforces its RBAC permission and checks session ownership.

---

## Unit test surface

The reverse-proxy code is covered by focused unit tests:

| Path | Covers |
| ---- | ------ |
| `tests/unit/mcpgateway/routers/test_reverse_proxy.py` | WebSocket admission, connection lifecycle, and HTTP session endpoints |
| `tests/unit/mcpgateway/services/test_reverse_proxy_*.py` | Protocol and session services |
| `tests/unit/mcpgateway/middleware/test_token_scoping.py` | Layer-1 token scoping on the reverse-proxy routes |


---

## Related documentation

- [MCP Reverse Proxy user guide](../using/reverse-proxy.md) - client usage, deployment, and gateway-side configuration
- [Testing ContextForge](../testing/index.md) - the wider testing strategy
