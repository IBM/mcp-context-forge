# ADR-049: Multi-Protocol Virtual Servers

## Status
Accepted

## Context
Virtual servers may need to expose multiple protocol interfaces simultaneously to serve diverse clients and use cases:

- **MCP (SSE/WebSocket)** for standard tool access and server-to-agent communication
- **A2A (JSON-RPC)** for agent-to-agent communication with structured task workflows
- **REST/gRPC** for integration with external systems

A single virtual server instance should be able to host multiple protocol bindings without duplication. Currently, server configuration is tightly coupled to a single protocol, limiting flexibility.

## Decision
Introduce a `ServerInterface` model (`server_interfaces` table) that stores per-protocol configuration with a unique constraint on `(server_id, protocol, binding)`. Each interface has its own version, tenant scope, and enabled flag.

```sql
CREATE TABLE server_interfaces (
  id VARCHAR(36) PRIMARY KEY,
  server_id VARCHAR(36) NOT NULL,
  protocol VARCHAR(50) NOT NULL,        -- e.g., 'a2a-jsonrpc', 'mcp-sse', 'mcp-ws', 'rest'
  binding VARCHAR(255),                  -- e.g., '/a2a', '/mcp', '/rest'
  version VARCHAR(50),                   -- Protocol-specific version
  tenant_id VARCHAR(36),                 -- Inherited or overridden
  enabled BOOLEAN DEFAULT TRUE,
  config_json TEXT,                      -- Protocol-specific config
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  UNIQUE KEY unique_server_protocol_binding (server_id, protocol, binding),
  FOREIGN KEY (server_id) REFERENCES servers(id)
);
```

Additionally, introduce an `A2AAgentAuth` model (`a2a_agent_auth` table) that extracts agent authentication configuration into a dedicated 1:1 table for cleaner schema evolution.

```sql
CREATE TABLE a2a_agent_auth (
  id VARCHAR(36) PRIMARY KEY,
  server_interface_id VARCHAR(36) NOT NULL UNIQUE,
  auth_type VARCHAR(50),                 -- 'api_key', 'jwt', 'oauth2'
  api_key_hash VARCHAR(255),             -- For API key auth
  jwt_issuer VARCHAR(255),               -- For JWT auth
  oauth2_provider VARCHAR(255),          -- For OAuth2 auth
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  FOREIGN KEY (server_interface_id) REFERENCES server_interfaces(id)
);
```

## Consequences

### Positive
- **Flexibility**: A single server can have both `a2a-jsonrpc` and `mcp-sse` interfaces simultaneously
- **Clean separation**: Protocol-specific configuration is isolated from the main server record
- **Extensibility**: New protocols can be added without schema migration sprawl
- **Agent card generation**: Derives supported interfaces from interface records, enabling discovery
- **Protocol routing**: Uses interface binding URLs to dispatch requests to the correct handler
- **Auth isolation**: `A2AAgentAuth` extracts auth configuration for independent management

### Negative
- **Schema complexity**: Additional tables and relationships increase the model surface area
- **Query complexity**: Multi-protocol lookups require joins across interface records
- **Migration burden**: Existing single-protocol servers must be migrated to the new model
- **Testing scope**: Multi-protocol scenarios require comprehensive integration testing

## Implementation Notes

- Backward compatibility: Single-protocol servers continue to function; gradual migration to multi-protocol is optional
- Agent card generation discovers all enabled interfaces on a server and reports them in the agent card
- Protocol routing uses the binding path to select the appropriate handler
- The `A2AAgentAuth` model is optional; servers without A2A interfaces do not require auth records
- Interface versioning allows independent version bumps for different protocols on the same server

## References
- `mcpgateway/db.py` - ORM models for `ServerInterface` and `A2AAgentAuth`
- `mcpgateway/services/` - Protocol-specific routing logic
- `docs/docs/architecture/multitenancy.md` - Multi-tenancy model
