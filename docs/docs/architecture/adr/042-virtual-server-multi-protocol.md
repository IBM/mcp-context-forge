# ADR-0042: Virtual Servers as Multi-Protocol Endpoints

## Context

Virtual servers currently expose only MCP protocol endpoints (SSE, WebSocket, streamable HTTP). A2A agents are standalone resources served at `/a2a/{agent_name}/*`. The association between a virtual server and its A2A agents is metadata-only -- a virtual server does not expose A2A protocol endpoints for agents associated with it. There is no mechanism for a virtual server to present itself as an A2A agent to external callers.

The A2A v1.0 specification introduces `AgentCard.supported_interfaces`, which explicitly models multiple protocol bindings per agent (JSON-RPC, REST, gRPC, etc.). This aligns with ContextForge's position as a multi-protocol federation layer that should be able to expose a single logical server over multiple transports.

Two design options were evaluated:

- **Option A**: Extend the existing `Server` model so a single virtual server can serve both MCP and A2A interfaces.
- **Option B**: Create a separate `A2AServer` model with its own lifecycle, duplicating management and configuration surfaces.

## Decision

Adopt **Option A** -- extend the existing `Server` model to support multi-protocol endpoints.

A single virtual server can expose both MCP and A2A interfaces. The implementation introduces:

- **New Server model fields**: `a2a_enabled` (boolean, default `false`), `a2a_tenant` (optional string), `a2a_agent_card_override` (optional JSON for customizing the generated AgentCard), `a2a_protocol_version` (default `v1.0`).
- **New service**: `A2AServerService` handles A2A protocol serving for virtual servers, including task federation to associated agents.
- **New router**: `a2a_server_router` mounts A2A endpoints at `/servers/{server_id}/a2a/*`, handling JSON-RPC dispatch, AgentCard serving, and task lifecycle.
- **AgentCard auto-generation**: The server's AgentCard is automatically generated from server metadata (name, description, URL) combined with capabilities declared by its associated agents. The `a2a_agent_card_override` field allows operators to customize specific fields.
- **Task federation**: A `ServerTaskMapping` table tracks which server-level tasks map to which downstream agent tasks, enabling the server to federate task execution across its associated agents.

## Consequences

### Positive
- No model duplication: a single `Server` entity manages both MCP and A2A protocol exposure.
- Single management point for operators: one server configuration controls all protocol interfaces.
- Natural mapping to the v1.0 `AgentCard.supported_interfaces` model.
- Existing server association with agents (`server_agents` join table) is reused for A2A task routing.
- Admin UI can present protocol capabilities as a unified view per server.

### Negative
- The `Server` model grows in scope with A2A-specific fields (mitigated by keeping A2A fields optional and defaulting to disabled).
- Service layer complexity increases with a new `A2AServerService` (mitigated by clear separation from existing `ServerService`).
- Migration required to add new columns to the `servers` table.

### Risks / Mitigations
- Feature creep in the Server model -- mitigate by keeping A2A fields behind `a2a_enabled` and validating that A2A-specific fields are only set when enabled.
- AgentCard auto-generation may not cover all use cases -- mitigate with the `a2a_agent_card_override` escape hatch for operator customization.
- Task federation adds distributed state -- mitigate with the `ServerTaskMapping` table providing explicit tracking and cleanup semantics.

## Alternatives Considered

- **Option B: Separate A2AServer model**: Rejected. Duplicates the management surface (separate CRUD, separate UI, separate RBAC entries). Complicates the association between servers and agents since agents would need to be linked to both model types. Does not align with the v1.0 specification's multi-interface model where a single agent identity exposes multiple protocol bindings.
- **A2A-only servers (no MCP)**: Not rejected but not required as a separate concept. Setting `a2a_enabled=true` on a server that has no MCP gateways associated achieves this naturally.

## Related
- ADR-0041: A2A Protocol v1.0 RC1 Migration Strategy
- ADR-0043: Tenant vs Team Separation
- A2A v1.0 `AgentCard.supported_interfaces` specification
- Existing virtual server implementation: `mcpgateway/services/server_service.py`, `mcpgateway/routers/server_router.py`
